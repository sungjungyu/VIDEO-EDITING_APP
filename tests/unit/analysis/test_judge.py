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


def test_judge_preserves_retake_cut_when_ai_omits_it():
    """AI가 응답에서 생략한 다시 찍기(NG, 확신도 0.7) 문장도 규칙대로 잘린다."""
    ai = ScriptedAI({"decisions": []})
    decisions, engine, warnings = judge_mod.judge_lines(LINES, [], {}, ai)
    assert engine == "ai" and not warnings
    assert decisions["t0003"].keep is False and decisions["t0003"].reason == "NG"
    assert decisions["t0004"].keep is False and decisions["t0004"].reason == "지시어"


def test_judge_guard_and_failure_fall_back_to_rules():
    all_cut = ScriptedAI({"decisions": [{"id": line.seg_id, "keep": False, "reason": "NG", "confidence": 0.9,
                                         "emphasis": False, "note": ""} for line in LINES]})
    decisions, engine, warnings = judge_mod.judge_lines(LINES, [], {}, all_cut)
    assert decisions["t0001"].keep and warnings
    decisions, engine, warnings = judge_mod.judge_lines(LINES, [], {}, ScriptedAI(AIError("503")))
    assert engine == "rule" and decisions["t0001"].keep and warnings


# ---------------------------------------------------------------- 확신도·하이브리드 (v4 T2)

def test_cut_confidence_grows_with_distance_from_threshold_and_stays_hard():
    """지금 자르는 규칙은 모두 HARD_RULE 이상 (judge_lines 동작이 예전과 같다), 확실할수록 높다."""
    exact = [L("a", "여기 라떼가 정말 유명해요", 0, 2), L("b", "여기 라떼가 정말 유명해요", 2.5, 4.5)]
    close = LINES
    exact_ng = judge_mod.rule_decisions(exact, {})["a"]
    close_ng = judge_mod.rule_decisions(close, {})["t0003"]
    assert exact_ng.reason == close_ng.reason == "NG"
    assert exact_ng.confidence > close_ng.confidence >= judge_mod.HARD_RULE
    cue_alone = judge_mod.rule_decisions([L("c", "아 다시 할게", 0, 1)], {})["c"]
    cue_inside = judge_mod.rule_decisions([L("d", "오늘은 처음부터 순서대로 하나씩 설명해 드릴게요", 0, 3)], {})["d"]
    assert cue_alone.confidence > cue_inside.confidence >= judge_mod.HARD_RULE


def test_keep_confidence_drops_for_doubtful_lines():
    lines = [L("x1", "오늘 날씨가 정말 좋아서 한강에 나왔어요", 0, 3),
             L("x2", "음 그니까 여기가 어", 3.5, 5),                        # 추임새 섞임
             L("x3", "아니 이거 말고", 5.5, 6.5)]                           # 지시어 비슷한 말
    rules = judge_mod.rule_decisions(lines, {})
    assert all(rules[i].keep for i in ("x1", "x2", "x3"))
    assert rules["x1"].confidence >= judge_mod.ASK_BELOW
    assert rules["x2"].confidence < judge_mod.ASK_BELOW and "추임새" in rules["x2"].note
    assert rules["x3"].confidence < judge_mod.ASK_BELOW
    assert judge_mod.uncertain_ids(lines, rules) == ["x2", "x3"]


class RecordingAI(ScriptedAI):
    def __init__(self, data):
        super().__init__(data)
        self.prompts = []

    def generate_json(self, prompt, schema=None, **kw):
        self.prompts.append(prompt)
        return super().generate_json(prompt, schema, **kw)


def test_hybrid_asks_only_uncertain_lines_with_context():
    texts = ["오늘은 아침 일찍 일어났어요", "날씨가 맑아서 기분이 좋네요", "버스를 타고 시장에 갔어요",
             "사람들이 생각보다 많더라고요", "떡볶이 가게 앞에 줄이 길었어요", "", "결국 국밥을 먹기로 했습니다",
             "국물이 진하고 고기가 부드러워요", "다 먹고 근처 공원을 걸었어요", "이제 집으로 돌아갑니다"]
    lines = [L(f"h{i}", t, i * 3, i * 3 + 2) for i, t in enumerate(texts)]
    lines[5] = L("h5", "음 그니까 여기가 어", 15, 17)
    ai = RecordingAI({"decisions": [
        {"id": "h5", "keep": False, "reason": "군더더기", "confidence": 0.8, "emphasis": False, "note": "머뭇거림"},
        {"id": "h4", "keep": False, "reason": "NG", "confidence": 0.9, "emphasis": False, "note": "문맥 문장"}]})
    decisions, engine, warnings, asked = judge_mod.judge_hybrid(lines, [], {}, ai)
    assert engine == "hybrid" and asked == {"h5"} and not warnings
    assert decisions["h5"].keep is False and decisions["h5"].source == "ai"
    assert decisions["h4"].keep and decisions["h4"].source == "rule"          # 문맥 문장은 판단하지 않는다
    prompt = ai.prompts[0]
    assert "★ h5" in prompt and "(문맥) h3" in prompt and "(문맥) h7" in prompt
    assert "h0 |" not in prompt and "h9 |" not in prompt                     # 멀리 떨어진 문장은 보내지 않는다


def test_hybrid_without_ai_or_doubt_is_rules_and_all_mode_prompt_is_unchanged():
    clear = [L("c1", "오늘 날씨가 정말 좋아서 한강에 나왔어요", 0, 3)]
    ai = RecordingAI({"decisions": []})
    assert judge_mod.judge_hybrid(clear, [], {}, ai)[1:] == ("rule", [], set()) and not ai.prompts
    decisions, engine, _, asked = judge_mod.judge_hybrid(LINES, [], {}, None)
    assert engine == "rule" and not asked and decisions == judge_mod.rule_decisions(LINES, {})
    rules = judge_mod.rule_decisions(LINES, {})
    prompt = judge_mod.build_prompt(LINES, rules, {}, {})
    assert "★" not in prompt and "(문맥)" not in prompt
