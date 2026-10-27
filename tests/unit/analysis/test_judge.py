"""문장별 컷 판단 테스트: 자체 규칙, Gemini 판단 병합, 안전장치(과도한 컷·실패 시 규칙)."""

from __future__ import annotations

from vibecut.analysis import judge as judge_mod
from vibecut.domain.models import Line
from vibecut.errors import AIError


def L(seg_id, text, start, end, clip_id="c01"):
    return Line(seg_id=seg_id, clip_id=clip_id, start=start, end=end, text=text)


LINES = [L("t0001", "안녕하세요 오늘은 성수동 카페에 왔습니다", 0, 3), L("t0002", "음", 3.2, 3.6),
         L("t0003", "여기 라떼가 유명하다고", 4, 6), L("t0004", "아 다시 할게", 6.2, 7),
         L("t0005", "여기 라떼가 정말 유명하다고 해서 와봤어요", 7.5, 10), L("t0006", "와 진짜 대박!", 10.5, 12)]


def test_rule_decisions():
    rules = judge_mod.rule_decisions(LINES, {})
    assert (rules["t0002"].keep, rules["t0002"].reason) == (False, "군더더기")
    assert (rules["t0003"].keep, rules["t0003"].reason) == (False, "NG")           # 바로 뒤에서 다시 말함
    assert (rules["t0004"].keep, rules["t0004"].reason) == (False, "지시어")
    assert rules["t0005"].keep and rules["t0001"].keep
    assert rules["t0006"].keep and rules["t0006"].emphasis
    weak = judge_mod.rule_decisions([L("t1", "그니까", 0, 1)], {"filler_removal": "약 (크게 거슬리는 것만)"})
    assert weak["t1"].keep


class ScriptedAI:
    available = True

    def __init__(self, data):
        self.data = data

    def generate_json(self, prompt, schema=None, **kw):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def test_judge_merges_ai_items_with_hard_rules():
    ai = ScriptedAI({"decisions": [
        {"id": "t0001", "keep": False, "reason": "반복", "confidence": 0.6, "emphasis": False, "note": "x"},
        {"id": "t0003", "keep": True, "reason": "일반", "confidence": 0.7, "emphasis": False, "note": "살림"},
        {"id": "t9999", "keep": False, "reason": "NG", "confidence": 1, "emphasis": False, "note": "없는 id"},
    ]})
    decisions, engine, warnings = judge_mod.judge_lines(LINES, [], {}, ai)
    assert engine == "ai" and not warnings
    assert decisions["t0001"].keep is False and decisions["t0001"].source == "ai"
    assert decisions["t0003"].keep is True                             # AI가 규칙(NG)을 뒤집음
    assert decisions["t0002"].keep is False and decisions["t0002"].source == "rule"   # 확실한 규칙 컷 유지
    assert decisions["t0005"].keep and decisions["t0005"].source == "ai"
    assert "t9999" not in decisions


def test_judge_guard_and_failure_fall_back_to_rules():
    all_cut = ScriptedAI({"decisions": [{"id": line.seg_id, "keep": False, "reason": "NG", "confidence": 0.9,
                                         "emphasis": False, "note": ""} for line in LINES]})
    decisions, engine, warnings = judge_mod.judge_lines(LINES, [], {}, all_cut)
    assert decisions["t0001"].keep and warnings
    decisions, engine, warnings = judge_mod.judge_lines(LINES, [], {}, ScriptedAI(AIError("503")))
    assert engine == "rule" and decisions["t0001"].keep and warnings
