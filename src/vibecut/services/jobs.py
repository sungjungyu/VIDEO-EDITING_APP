"""디스크에 기록되는 작업 큐.

- 종류마다 동시에 도는 개수를 제한한다 (렌더 1개, 분석 1개, 프록시 2개 — CPU를 나눠 쓰기 때문)
- 상태·진행률·결과를 data/jobs/{id}.json에 남기고, 작업 로그는 {id}.log에 남긴다
- 서버를 다시 켜면 '도는 중'이던 작업은 '중단됨'으로 표시한다 (몰래 다시 돌려 API 한도를 쓰지 않게)
- 보관 기간(retention_days)이 지난 끝난 작업 기록은 서버를 켤 때 지운다 (기록이 끝없이 쌓이지 않게)
- 취소: 이벤트를 세우면 단계 사이와 ffmpeg 실행 중에 멈춘다
"""

from __future__ import annotations

import concurrent.futures.thread as _thread_pool
import logging
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from ..domain.models import Job, now_iso
from ..errors import Canceled
from ..log import close_job_logger, job_logger
from ..media.ffmpeg import kill_active_processes
from ..storage.files import read_json, write_json
from .context import RunContext

log = logging.getLogger("vibecut.jobs")


class JobContext(RunContext):
    """작업 큐에서 도는 작업의 맥락: 진행률을 작업 기록에 남긴다."""

    def __init__(self, manager: JobManager, job_id: str, cancel: threading.Event, logger: logging.Logger):
        super().__init__(job_id, cancel, logger)
        self._manager = manager

    def progress(self, percent: float, stage: str | None = None, message: str | None = None) -> None:
        changes: dict = {"progress": round(max(0.0, min(100.0, percent)), 1)}
        if stage is not None:
            changes["stage"] = stage
        if message is not None:
            changes["message"] = message
        self._manager.update(self.job_id, **changes)


class JobManager:
    def __init__(self, data_dir: Path, workers: dict[str, int] | None = None, retention_days: int | None = None):
        self.dir = Path(data_dir) / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        workers = {"analyze": 1, "render": 1, "proxy": 2, **(workers or {})}
        self._executors = {kind: ThreadPoolExecutor(max_workers=max(1, n), thread_name_prefix=f"job-{kind}")
                           for kind, n in workers.items()}
        self._jobs: dict[str, Job] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._last_write: dict[str, float] = {}
        self._lock = threading.RLock()
        self._recover(retention_days)

    def _recover(self, retention_days: int | None) -> None:
        limit = time.time() - retention_days * 86400 if retention_days else None
        for path in self.dir.glob("*.json"):
            try:
                job = Job.model_validate(read_json(path))
            except (OSError, ValueError):
                continue
            if limit is not None and job.finished and _timestamp(job.finished_at or job.created_at) < limit:
                path.unlink(missing_ok=True)
                path.with_suffix(".log").unlink(missing_ok=True)
                continue
            if not job.finished:
                job.status, job.finished_at = "failed", now_iso()
                job.error = "서버가 다시 시작되어 작업이 중단되었습니다. 다시 실행해 주세요."
                write_json(path, job.model_dump())
            self._jobs[job.job_id] = job

    def _save(self, job: Job, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write.get(job.job_id, 0) < 0.5:
            return
        self._last_write[job.job_id] = now
        write_json(self.dir / f"{job.job_id}.json", job.model_dump())

    def update(self, job_id: str, **changes) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            important = any(k in changes for k in ("status", "stage", "error", "result"))
            for key, value in changes.items():
                setattr(job, key, value)
            self._save(job, force=important)
            return job.model_copy()

    def submit(self, kind: str, project_id: str | None, fn: Callable, *args, **kwargs) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind, project_id=project_id, stage="대기 중")
        with self._lock:
            self._jobs[job.job_id] = job
            self._cancel[job.job_id] = threading.Event()
            self._save(job, force=True)
        self._executors[kind].submit(self._run, job.job_id, fn, args, kwargs)
        return job.model_copy()

    def _run(self, job_id: str, fn: Callable, args: tuple, kwargs: dict) -> None:
        cancel = self._cancel.get(job_id)
        if cancel is None or cancel.is_set():
            return
        logger = job_logger(job_id, self.dir / f"{job_id}.log")
        ctx = JobContext(self, job_id, cancel, logger)
        self.update(job_id, status="running", started_at=now_iso(), stage="시작")
        started = time.time()
        try:
            result = fn(ctx, *args, **kwargs) or {}
            ctx.metrics["elapsed_sec"] = round(time.time() - started, 2)
            ctx.metrics["ai_usage"] = ctx.usage.to_dict()
            self.update(job_id, status="done", progress=100.0, stage="완료", result=result, metrics=ctx.metrics,
                        finished_at=now_iso())
        except Canceled:
            self.update(job_id, status="canceled", stage="취소됨", finished_at=now_iso(), metrics=ctx.metrics)
        except Exception as error:
            logger.error("작업 실패: %s\n%s", error, traceback.format_exc())
            self.update(job_id, status="failed", stage="실패", error=str(error)[:800], finished_at=now_iso(),
                        metrics=ctx.metrics)
        finally:
            close_job_logger(logger)
            with self._lock:
                self._cancel.pop(job_id, None)
                self._last_write.pop(job_id, None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy() if job else None

    def list(self, project_id: str | None = None, kind: str | None = None) -> list[Job]:
        with self._lock:
            jobs = [j.model_copy() for j in self._jobs.values()
                    if (project_id is None or j.project_id == project_id) and (kind is None or j.kind == kind)]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def active(self, project_id: str, kind: str) -> Job | None:
        return next((j for j in self.list(project_id, kind) if not j.finished), None)

    def cancel(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if ev := self._cancel.get(job_id):
                ev.set()
            if job.status == "queued":
                self._cancel.pop(job_id, None)
                self._last_write.pop(job_id, None)
                return self.update(job_id, status="canceled", stage="취소됨", finished_at=now_iso())
            return job.model_copy()

    def cancel_project(self, project_id: str, kind: str | None = None, timeout: float = 5.0) -> None:
        """프로젝트의 활성 작업을 취소하고 끝날 때까지 기다린다 (파일 삭제 전 ffmpeg가 파일을 놓게)."""
        active_ids = [j.job_id for j in self.list(project_id, kind) if not j.finished]
        for jid in active_ids:
            self.cancel(jid)
        deadline = time.time() + timeout
        for jid in active_ids:
            while time.time() < deadline:
                job = self.get(jid)
                if job is None or job.finished:
                    break
                time.sleep(0.05)

    def wait(self, job_id: str, timeout: float = 600.0) -> Job:
        """테스트·명령줄용: 작업이 끝날 때까지 기다린다."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.get(job_id)
            if job is not None and job.finished:
                return job
            time.sleep(0.1)
        raise TimeoutError(f"작업 {job_id}이 {timeout}초 안에 끝나지 않았습니다.")

    def shutdown(self) -> None:
        with self._lock:
            events = list(self._cancel.values())
        for event in events:
            event.set()
        kill_active_processes()
        for executor in self._executors.values():
            executor.shutdown(wait=False, cancel_futures=True)
            for t in getattr(executor, "_threads", ()):
                _thread_pool._threads_queues.pop(t, None)


def _timestamp(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return time.time()
