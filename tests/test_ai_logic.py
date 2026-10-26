"""AI 계층 테스트 (네트워크 없음): Gemini 클라이언트의 재시도·대체·캐시, 컷 판단 규칙과 병합,
장면 분량 맞추기, 수정 요청."""

from __future__ import annotations

import json

import pytest

from vibecut.ai import judge as judge_mod
from vibecut.ai.gemini import AIError, AIUnavailable, GeminiClient, classify_error, parse_json
from vibecut.ai.revise import revise
from vibecut.ai.select import fit_duration, select_scenes
from vibecut.edit.planner import compile_plan, effective_decisions
from vibecut.models import Analysis, ClipInfo, ClipSpan, EditPlan, Line, LineDecision, TreeNode
from vibecut.settings import load_settings


def settings(tmp_path, **kw):
    base = dict(api_key="test-key", ai_mode="live", data_dir=tmp_path, gemini_retries=2)
    base.update(kw)
    return load_settings(**base)


# ---------------------------------------------------------------- JSON·오류 분류

def test_parse_json_variants():
    pretty = json.dumps([{"id": "t1", "keep": False}, {"id": "t2", "keep": True}], indent=2)
    assert parse_json(pretty)[1]["id"] == "t2"                     # 예전 '복구 로직'이 망가뜨리던 형태
    assert parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert parse_json('설명: {"a": [1, 2]} 끝') == {"a": [1, 2]}
    assert parse_json('[{"id": 1}, {"id": 2}, {"id"') == [{"id": 1}, {"id": 2}]      # 잘린 배열
    with pytest.raises(json.JSONDecodeError):
        parse_json("그냥 글")


def test_classify_error():
    assert classify_error(RuntimeError("429 RESOURCE_EXHAUSTED")) == "quota"
    assert classify_error(RuntimeError("503 UNAVAILABLE")) == "transient"
    assert classify_error(TimeoutError("timed out")) == "transient"
    assert classify_error(RuntimeError("400 INVALID_ARGUMENT")) == "fatal"


# ---------------------------------------------------------------- 클라이언트

class FakeClient(GeminiClient):
    def __init__(self, settings, replies, cache_dir=None):
        self.sleeps = []
        super().__init__(settings, cache_dir, sleep=self.sleeps.append)
        self.replies = list(replies)
        self.calls = []

    def _call(self, model, prompt, schema, temperature, max_output_tokens):
        self.calls.append(model)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_retry_then_success_with_backoff(tmp_path):
    client = FakeClient(settings(tmp_path), [RuntimeError("503 UNAVAILABLE"), '{"ok": true}'])
    assert client.generate_json("p") == {"ok": True}
    assert client.calls == ["gemini-3.5-flash", "gemini-3.5-flash"] and len(client.sleeps) == 1


def test_quota_moves_to_fallback_model(tmp_path):
    client = FakeClient(settings(tmp_path), [RuntimeError("429 RESOURCE_EXHAUSTED"), '{"ok": 1}'])
    assert client.generate_json("p") == {"ok": 1}
    assert client.calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_fatal_error_stops_and_reports(tmp_path):
    client = FakeClient(settings(tmp_path), [RuntimeError("400 INVALID_ARGUMENT")] * 4)
    with pytest.raises(AIError):
        client.generate_json("p")
    assert client.calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_cache_replays_offline(tmp_path):
    live = FakeClient(settings(tmp_path), ['{"v": 7}'], cache_dir=tmp_path / "ai")
    assert live.generate_json("같은 질문") == {"v": 7}
    offline = FakeClient(settings(tmp_path, ai_mode="offline"), [], cache_dir=tmp_path / "ai")
    assert offline.generate_json("같은 질문") == {"v": 7}               # 녹화된 응답 재생
    assert offline.usage.cache_hits == 1 and offline.calls == []
    with pytest.raises(AIUnavailable):
        offline.generate_json("처음 보는 질문")


# ---------------------------------------------------------------- 컷 판단

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


# ---------------------------------------------------------------- 장면 선택

def test_fit_duration_hits_target_band():
    nodes = [TreeNode(id=f"s{i}", title="", level=2, start=i * 30, end=(i + 1) * 30) for i in range(6)]
    seconds = {n.id: 30.0 for n in nodes}
    scores = {"s0": {"score": 0.9}, "s1": {"score": 0.2}, "s2": {"score": 0.8}, "s3": {"score": 0.1, "never": True},
              "s4": {"score": 0.5}, "s5": {"score": 0.3, "must": True}}
    chosen = fit_duration(nodes, seconds, scores, [], 90.0, {}, {})
    assert set(chosen) == {"s5", "s0", "s2"}                          # must + 점수 높은 순, never 제외


def tree_analysis():
    lines, nodes, t = [], [], 0.0
    for i in range(8):                                               # 30초 장면 8개, 장면마다 대사 3개
        children = []
        for j in range(3):
            sid = f"t{i * 3 + j + 1:04d}"
            s = t + j * 9 + 1
            lines.append(Line(seg_id=sid, clip_id="c01", start=s, end=s + 6, text=f"장면{i} 대사{j} 이야기"))
            children.append(TreeNode(id=f"n{i}-l{j}", title="", level=3, start=s, end=s + 6, seg_id=sid))
        nodes.append(TreeNode(id=f"n{i}", title=f"장면{i}", level=2, start=t, end=t + 30, children=children,
                              summary="카페" if i in (2, 5) else ""))
        t += 30
    tree = [TreeNode(id="p", title="장소", level=0, start=0, end=240, children=[
        TreeNode(id="a", title="일", level=1, start=0, end=240, children=nodes)])]
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0, duration=240)], lines=lines, tree=tree)
    clip = ClipInfo(clip_id="c01", filename="a.mp4", stored_name="c01.mp4", duration=240, fps=30)
    return analysis, clip


@pytest.mark.parametrize("target", [60.0, 95.0, 150.0])
def test_select_scenes_offline_reaches_target(target):
    analysis, clip = tree_analysis()
    plan = EditPlan()
    selection, engine, warnings = select_scenes(analysis, {"c01": clip}, plan, {}, target, "카페 장면 위주로",
                                                [], {}, None)
    assert engine == "rule" and selection.mode == "auto"
    plan.selection = selection
    out = compile_plan(plan, [clip], analysis)
    assert abs(out.duration / target - 1) <= 0.06, (out.duration, target)
    assert "n2" in selection.node_ids or "n5" in selection.node_ids   # 요청 단어(카페)가 있는 장면 우선
    assert selection.reasons


def test_revise_offline_commands():
    decisions = effective_decisions(EditPlan(), Analysis(lines=LINES, judgments=judge_mod.rule_decisions(LINES)))
    changes, message, engine = revise("전체 살려줘", LINES, decisions, {}, None)
    assert engine == "rule" and all(c == {"keep": True} for c in changes.values()) and len(changes) == 3
    keep_all = {line.seg_id: LineDecision(seg_id=line.seg_id) for line in LINES}
    changes, message, engine = revise("말더듬이랑 군더더기 잘라줘", LINES, keep_all, {}, None)
    assert {"t0002", "t0004"} <= set(changes)
