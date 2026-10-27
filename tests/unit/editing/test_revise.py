"""자연어 수정 요청 테스트 (오프라인 규칙 명령)."""

from __future__ import annotations

from vibecut.analysis import judge as judge_mod
from vibecut.domain.models import Analysis, EditPlan, Line, LineDecision
from vibecut.editing.planner import effective_decisions
from vibecut.editing.revise import revise


def L(seg_id, text, start, end, clip_id="c01"):
    return Line(seg_id=seg_id, clip_id=clip_id, start=start, end=end, text=text)


LINES = [L("t0001", "안녕하세요 오늘은 성수동 카페에 왔습니다", 0, 3), L("t0002", "음", 3.2, 3.6),
         L("t0003", "여기 라떼가 유명하다고", 4, 6), L("t0004", "아 다시 할게", 6.2, 7),
         L("t0005", "여기 라떼가 정말 유명하다고 해서 와봤어요", 7.5, 10), L("t0006", "와 진짜 대박!", 10.5, 12)]


def test_revise_offline_commands():
    decisions = effective_decisions(EditPlan(), Analysis(lines=LINES, judgments=judge_mod.rule_decisions(LINES)))
    changes, message, engine = revise("전체 살려줘", LINES, decisions, {}, None)
    assert engine == "rule" and all(c == {"keep": True} for c in changes.values()) and len(changes) == 3
    keep_all = {line.seg_id: LineDecision(seg_id=line.seg_id) for line in LINES}
    changes, message, engine = revise("말더듬이랑 군더더기 잘라줘", LINES, keep_all, {}, None)
    assert {"t0002", "t0004"} <= set(changes)
