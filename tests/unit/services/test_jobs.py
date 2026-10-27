"""작업 큐 테스트: 진행·실패 기록, 취소, 재시작 시 중단 표시, 오래된 기록 정리."""

from __future__ import annotations

import threading
import time

from vibecut.domain.models import Job
from vibecut.errors import Canceled
from vibecut.services.jobs import JobManager
from vibecut.storage.files import write_json


def test_job_lifecycle(tmp_path):
    jobs = JobManager(tmp_path)
    try:
        def ok(ctx, value):
            ctx.progress(50, "절반")
            with ctx.stage("일"):
                pass
            return {"value": value}

        def boom(ctx):
            raise ValueError("일부러 실패")

        done = jobs.wait(jobs.submit("analyze", "p1", ok, 3).job_id)
        assert done.status == "done" and done.result == {"value": 3} and "일" in done.metrics["stages"]
        failed = jobs.wait(jobs.submit("analyze", "p1", boom).job_id)
        assert failed.status == "failed" and "일부러 실패" in failed.error
        assert (tmp_path / "jobs" / f"{failed.job_id}.log").read_text(encoding="utf-8").count("일부러 실패") >= 1
    finally:
        jobs.shutdown()


def test_cancel_running_and_queued(tmp_path):
    jobs = JobManager(tmp_path, {"render": 1})
    started = threading.Event()
    try:
        def slow(ctx):
            started.set()
            for _ in range(200):
                ctx.check()
                time.sleep(0.02)
            return {}

        running = jobs.submit("render", "p1", slow)
        queued = jobs.submit("render", "p1", slow)
        started.wait(5)
        jobs.cancel(queued.job_id)
        jobs.cancel(running.job_id)
        assert jobs.wait(running.job_id).status == "canceled"
        assert jobs.get(queued.job_id).status == "canceled"
    finally:
        jobs.shutdown()
    assert isinstance(Canceled("x"), Exception)


def test_restart_marks_unfinished_jobs(tmp_path):
    (tmp_path / "jobs").mkdir()
    write_json(tmp_path / "jobs" / "abc.json", Job(job_id="abc", kind="render", status="running").model_dump())
    jobs = JobManager(tmp_path)
    try:
        job = jobs.get("abc")
        assert job.status == "failed" and "다시 시작" in job.error
    finally:
        jobs.shutdown()


def test_old_finished_jobs_are_removed_on_start(tmp_path):
    (tmp_path / "jobs").mkdir()
    old = Job(job_id="old", kind="render", status="done", created_at="2020-01-01T00:00:00+00:00",
              finished_at="2020-01-01T00:01:00+00:00")
    write_json(tmp_path / "jobs" / "old.json", old.model_dump())
    (tmp_path / "jobs" / "old.log").write_text("로그", encoding="utf-8")
    write_json(tmp_path / "jobs" / "new.json", Job(job_id="new", kind="render", status="done").model_dump())
    jobs = JobManager(tmp_path, retention_days=14)
    try:
        assert jobs.get("old") is None and not (tmp_path / "jobs" / "old.log").exists()
        assert jobs.get("new") is not None
    finally:
        jobs.shutdown()
