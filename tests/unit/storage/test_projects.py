"""프로젝트 저장소 테스트: 저장·다시 열기·삭제, 분석 결과 읽기 캐시."""

from __future__ import annotations

import os

import pytest

from vibecut.domain.models import Analysis, EditPlan, Line
from vibecut.errors import NotFound
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
