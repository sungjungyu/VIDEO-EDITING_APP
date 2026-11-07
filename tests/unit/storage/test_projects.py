"""프로젝트 저장소 테스트: 저장·다시 열기·삭제, 분석 결과 읽기 캐시, 클립 삭제 시 활성 작업 검사."""

from __future__ import annotations

import os
import threading
import time

import pytest

from vibecut.domain.models import Analysis, ClipInfo, EditPlan, Line
from vibecut.errors import Conflict, NotFound
from vibecut.services import projects as project_service
from vibecut.services.jobs import JobManager
from vibecut.storage.projects import ProjectStore


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


def test_analysis_cache_follows_file_changes(tmp_path):
    store = ProjectStore(tmp_path)
    pid = store.create("캐시").project_id
    assert store.load_analysis(pid) is None
    first = Analysis(lines=[Line(seg_id="t1", clip_id="c01", start=0, end=1, text="하나")])
    store.save_analysis(pid, first)
    assert store.load_analysis(pid) is store.load_analysis(pid)          # 파일이 그대로면 다시 읽지 않는다
    other = ProjectStore(tmp_path)                                         # 다른 프로세스가 바꾼 경우
    other.save_analysis(pid, Analysis(lines=[Line(seg_id="t2", clip_id="c01", start=0, end=1, text="둘둘")]))
    path = store.project_dir(pid) / "analysis.json"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert [line.text for line in store.load_analysis(pid).lines] == ["둘둘"]


def test_delete_clip_blocked_during_render_and_delete_project_waits_for_job(tmp_path):
    store = ProjectStore(tmp_path)
    jobs = JobManager(tmp_path)
    started = threading.Event()
    try:
        p = store.create("삭제 테스트")
        pid = p.project_id

        def add_clip(proj):
            proj.clips.append(ClipInfo(clip_id="c01", filename="a.mp4", stored_name="c01.mp4", duration=5.0))
            proj.timeline.append("c01")

        store.update(pid, add_clip)

        def running_render(ctx):
            started.set()
            while not ctx.cancel.is_set():
                time.sleep(0.02)
            ctx.check()

        job = jobs.submit("render", pid, running_render)
        started.wait(5)
        with pytest.raises(Conflict):
            project_service.delete_clip(store, jobs, pid, "c01")
        project_service.delete_project(store, jobs, pid)
        assert jobs.get(job.job_id).status == "canceled"
    finally:
        jobs.shutdown()


def test_preview_renders_do_not_evict_final_renders(tmp_path, monkeypatch):
    from vibecut.domain.models import KeepRange
    from vibecut.services import rendering

    store = ProjectStore(tmp_path)
    p = store.create("렌더 한도")
    pid = p.project_id
    clip_file = store.clip_path(pid, "c01.mp4")
    clip_file.write_bytes(b"fake")

    def setup(proj):
        proj.clips.append(ClipInfo(clip_id="c01", filename="a.mp4", stored_name="c01.mp4", duration=5.0, fps=30))
        proj.timeline.append("c01")

    store.update(pid, setup)
    plan = store.load_plan(pid)
    plan.keep = [KeepRange(clip_id="c01", start=0.0, end=2.0, out_start=0.0)]
    plan.duration = 2.0
    store.save_plan(pid, plan)

    def fake_render(plan, clips, files, quality, out, workdir, on_progress=None, cancel=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return {"width": 960, "height": 540, "duration": 2.0, "plan_duration": 2.0, "error_ms": 0.0,
                "elapsed_sec": 0.1, "size_bytes": 3}

    monkeypatch.setattr(rendering, "render_plan", fake_render)
    from vibecut.services.context import RunContext
    final_res = rendering.run_render(RunContext(), store, pid, "final")["render"]
    for _ in range(5):
        rendering.run_render(RunContext(), store, pid, "preview")

    proj = store.get(pid)
    finals = [r for r in proj.renders if r.quality == "final"]
    previews = [r for r in proj.renders if r.quality == "preview"]
    assert len(finals) == 1 and finals[0].render_id == final_res["render_id"]
    assert store.render_path(pid, final_res["file"]).exists()
    assert len(previews) == rendering.MAX_PREVIEW_RENDERS


def test_wipe_media_removes_videos_and_audio_but_keeps_text_caches(tmp_path):
    store = ProjectStore(tmp_path)
    pid = store.create("지울 프로젝트").project_id
    store.clip_path(pid, "c01.mp4").write_bytes(b"video")
    store.audio_dir.mkdir(parents=True)
    (store.audio_dir / "abc.wav").write_bytes(b"wav")
    (store.cache_dir / "stt").mkdir()
    (store.cache_dir / "stt" / "abc.json").write_text("{}", encoding="utf-8")

    assert store.wipe_media() == 1
    assert not any(store.projects_dir.iterdir()) and not store.audio_dir.exists()
    assert (store.cache_dir / "stt" / "abc.json").exists()           # 받아쓰기 글자 캐시는 남긴다
    with pytest.raises(NotFound):
        store.get(pid)
