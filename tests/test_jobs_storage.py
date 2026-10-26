"""프로젝트 저장소와 작업 큐 테스트."""

from __future__ import annotations

import threading
import time

import pytest

from vibecut.media.ffmpeg import Canceled
from vibecut.models import EditPlan, Job
from vibecut.server.jobs import JobManager
from vibecut.server.storage import NotFound, ProjectStore, write_json


def test_project_crud_and_persistence(tmp_path):
    store = ProjectStore(tmp_path)
    p = store.create("여행 브이로그")
    assert store.get(p.project_id).name == "여행 브이로그"
    store.update(p.project_id, lambda x: setattr(x, "timeline", []))
    plan = store.load_plan(p.project_id)
    assert isinstance(plan, EditPlan) and plan.keep == []
    plan.options.max_pause = 1.2
    store.save_plan(p.project_id, plan)
    again = ProjectStore(tmp_path)                       # 서버를 다시 켠 것처럼
    assert again.load_plan(p.project_id).options.max_pause == 1.2
    assert [x.project_id for x in again.list()] == [p.project_id]
    again.delete(p.project_id)
    with pytest.raises(NotFound):
        again.get(p.project_id)
    with pytest.raises(NotFound):
        again.get("../../etc")


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
