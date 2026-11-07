"""편집 계획 서비스: AI를 기다리는 동안 사용자가 고친 내용이 사라지지 않는다."""

from __future__ import annotations

from tests.unit.editing.test_select import tree_analysis
from vibecut.domain.models import ClipInfo
from vibecut.services import editing as editing_service
from vibecut.storage.projects import ProjectStore


def project_with_analysis(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("테스트")
    analysis, clip = tree_analysis()

    def add(p):
        p.clips.append(ClipInfo(**clip.model_dump()))
        p.timeline.append(clip.clip_id)

    store.update(project.project_id, add)
    store.save_analysis(project.project_id, analysis)
    return store, project.project_id


class EditsWhileScoring:
    """장면 점수를 매기는 사이에 사용자가 문장 하나를 자른다 (AI 응답을 기다리는 몇 초를 흉내)."""

    def __init__(self, store, project_id):
        self.store, self.project_id = store, project_id

    def generate_json(self, *args, **kwargs):
        editing_service.patch_lines(self.store, self.project_id,
                                    [editing_service.LineChange(seg_id="t0001", keep=False)])
        return {"scores": []}


def test_select_keeps_edits_made_while_ai_is_scoring(tmp_path):
    store, pid = project_with_analysis(tmp_path)
    _, plan, engine, _ = editing_service.select(store, EditsWhileScoring(store, pid), pid, "auto", target_sec=90)
    assert engine == "ai" and plan.selection.mode == "auto"
    assert plan.lines["t0001"].keep is False                       # 기다리는 동안 고친 문장이 남아 있다
    assert store.load_plan(pid).lines["t0001"].keep is False
