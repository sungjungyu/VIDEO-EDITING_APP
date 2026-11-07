"""'기능 그대로' 확인용 스냅샷 — 같은 입력으로 프롬프트·스키마·AI 캐시 키·편집 계획·자막·트리·API 모양을 만든다.

구조를 바꿔도 이 결과는 한 글자도 달라지면 안 된다.
    - 프롬프트·스키마가 바뀌면 AI 응답 캐시 키가 바뀌어 저장해 둔 응답(오프라인 시연)이 무효가 된다
    - 편집 계획(keep·events·duration)이 바뀌면 같은 영상의 결과가 달라진다
골든 파일 다시 만들기: VIBECUT_UPDATE_GOLDEN=1 pytest tests/regression
"""

from __future__ import annotations

import hashlib
import json
from unittest import mock

from vibecut.ai.client import GeminiClient, schema_payload
from vibecut.analysis.judge import JudgeResponse, rule_decisions
from vibecut.analysis.judge import build_prompt as judge_prompt
from vibecut.analysis.scenes.gemini import SCENE_SCHEMA, scene_prompt
from vibecut.analysis.tree import build_tree, group_tree
from vibecut.domain.models import (
    Analysis,
    ClipInfo,
    ClipSpan,
    EditPlan,
    Line,
    LineDecision,
    PlanOptions,
    Scene,
    Selection,
    Word,
)
from vibecut.editing.planner import compile_plan, effective_decisions, validate_plan
from vibecut.editing.revise import ReviseResponse
from vibecut.editing.revise import build_prompt as revise_prompt
from vibecut.editing.select import ScoreResponse, select_scenes
from vibecut.editing.select import build_prompt as select_prompt
from vibecut.render.ass import build_ass
from vibecut.settings import load_settings

FPS = 30
# ASS 글자 크기는 설치된 글꼴의 메트릭(line_ratio)을 따른다. 골든은 이 값(Windows 맑은 고딕)으로 만들었으므로
# 어느 PC에서든 같게 고정한다 (리눅스 CI에는 맑은 고딕이 없어 나눔고딕 비율로 계산돼 크기가 달랐다)
GOLDEN_LINE_RATIO = 1.330078125


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line(seg_id, start, end, text, clip_id) -> Line:
    toks = text.split()
    step = (end - start) / len(toks)
    words = [Word(word=t, start=round(start + i * step, 3), end=round(start + (i + 1) * step - 0.02, 3),
                  probability=0.9) for i, t in enumerate(toks)]
    return Line(seg_id=seg_id, clip_id=clip_id, start=start, end=end, text=text, words=words)


def inputs() -> tuple[Analysis, list[ClipInfo]]:
    """클립 2개, 문장 10개(NG·군더더기·지시어·강조 포함), 장면 4개, 트리."""
    clips = [ClipInfo(clip_id="c01", filename="cafe.mp4", stored_name="c01.mp4", duration=40.0, fps=FPS),
             ClipInfo(clip_id="c02", filename="street.mp4", stored_name="c02.mp4", duration=24.0, fps=FPS,
                      in_point=1.0, out_point=22.0)]
    lines = [
        _line("t0001", 0.8, 3.0, "안녕하세요 오늘은 성수동에 왔어요", "c01"),
        _line("t0002", 3.4, 3.9, "음", "c01"),
        _line("t0003", 4.3, 6.6, "여기 라떼가 유명하다고 해서", "c01"),
        _line("t0004", 7.0, 9.2, "여기 라떼가 유명하다고 해서 와봤어요", "c01"),
        _line("t0005", 10.5, 12.0, "아 다시 할게", "c01"),
        _line("t0006", 15.0, 18.2, "와 진짜 대박 맛있다!", "c01"),
        _line("t0007", 26.0, 29.5, "창가 자리가 정말 예쁘네요", "c01"),
        _line("t0008", 2.0, 4.5, "이제 거리를 걸어볼게요", "c02"),
        _line("t0009", 9.0, 9.6, "어 그니까", "c02"),
        _line("t0010", 12.0, 16.0, "오늘 브이로그는 여기까지 구독 부탁드려요", "c02"),
    ]
    scenes = [
        Scene(scene_id="s001", clip_id="c01", start=0.0, end=14.0, place="카페", activity="주문",
              event="라떼 주문", mood="설렘", people="빨간 후드", summary="카페에 들어가 주문한다", source="gemini"),
        Scene(scene_id="s002", clip_id="c01", start=14.0, end=40.0, place="카페", activity="시음",
              summary="라떼를 마신다", source="gemini"),
        Scene(scene_id="s003", clip_id="c02", start=0.0, end=10.0, place="거리", activity="산책",
              summary="거리를 걷는다", source="gemini"),
        Scene(scene_id="s004", clip_id="c02", start=10.0, end=24.0, place="거리", activity="마무리",
              event="인사", summary="마무리 인사", source="gemini"),
    ]
    spans = [ClipSpan(clip_id="c01", offset=0.0, duration=40.0), ClipSpan(clip_id="c02", offset=40.0, duration=24.0)]
    judgments = rule_decisions(lines, {"filler_removal": "강", "frequent_words": ["성수동"]})
    labels = {"c01": "클립 1 · cafe", "c02": "클립 2 · street"}
    tree = build_tree(spans, scenes, lines, judgments, labels)
    silences = {"c01": [(3.0, 3.35), (6.65, 6.95), (12.1, 14.9), (18.3, 25.9)],
                "c02": [(0.0, 1.9), (4.6, 8.9), (9.7, 11.9)]}
    analysis = Analysis(clips=spans, lines=lines, scenes=scenes, tree=tree, silences=silences, judgments=judgments,
                        engines={"stt": "test", "scenes": "test", "judge": "rule"}, created_at="2026-01-01T00:00:00")
    return analysis, clips


def _plan_dump(plan: EditPlan) -> dict:
    return plan.model_dump(exclude={"updated_at"})


def _plans(analysis: Analysis, clips: list[ClipInfo]) -> dict:
    out = {}
    out["all"] = compile_plan(EditPlan(), clips, analysis)
    manual = EditPlan(selection=Selection(mode="manual", node_ids=[analysis.tree[0].children[0].id]))
    out["manual"] = compile_plan(manual, clips, analysis)
    user = EditPlan(lines={
        "t0002": LineDecision(seg_id="t0002", keep=True, source="user"),
        "t0006": LineDecision(seg_id="t0006", keep=True, text="와 진짜 맛있다", source="user"),
        "t0007": LineDecision(seg_id="t0007", keep=False, reason="NG", source="user"),
    })
    out["user"] = compile_plan(user, clips, analysis)
    extras = EditPlan(options=PlanOptions(max_pause=None, title_text="성수동 카페 브이로그", location_captions=True,
                                          punch_in=False, snap_to_silence=False))
    extras.styles["subtitle"].max_chars_per_line = 8
    extras.styles["subtitle"].karaoke = True
    extras.output.aspect = "9:16"
    out["extras"] = compile_plan(extras, clips, analysis)
    snapshot = {name: _plan_dump(p) for name, p in out.items()}
    snapshot["issues"] = {name: validate_plan(p, clips, analysis) for name, p in out.items()}
    w, h = out["extras"].output.size()
    with mock.patch("vibecut.render.fonts.line_ratio", lambda family, bold=False: GOLDEN_LINE_RATIO):
        snapshot["ass_extras"] = build_ass(out["extras"].events, out["extras"].styles, w, h)
    for target in (20.0, 35.0):
        sel, engine, warnings = select_scenes(analysis, {c.clip_id: c for c in clips}, EditPlan(),
                                              effective_decisions(EditPlan(), analysis), target, "카페 장면 위주로",
                                              [], {}, None)
        snapshot[f"select_{int(target)}"] = {"selection": sel.model_dump(), "engine": engine, "warnings": warnings}
    return snapshot


def _prompts(analysis: Analysis) -> dict:
    profile = {"cut_tempo": "빠름", "filler_removal": "강", "frequent_words": ["성수동", "라떼"]}
    lines = sorted(analysis.lines, key=lambda x: x.seg_id)
    scenes_by_clip: dict[str, list[Scene]] = {}
    for sc in analysis.scenes:
        scenes_by_clip.setdefault(sc.clip_id, []).append(sc)
    decisions = effective_decisions(EditPlan(), analysis)
    from vibecut.editing.select import candidate_nodes
    nodes = candidate_nodes(analysis.tree)
    texts = {
        "judge": judge_prompt(lines, analysis.judgments, scenes_by_clip, profile),
        "select": select_prompt(nodes, analysis, decisions, "카페 장면 위주로", 30.0, profile),
        "revise": revise_prompt("말더듬 다 잘라줘", lines, decisions),
        "scene": scene_prompt(duration=42.5, min_sec=10.0, prev_summary="카페: 주문한다", known_people="빨간 후드"),
        "scene_first": scene_prompt(duration=12.0, min_sec=10.0, prev_summary="", known_people=""),
    }
    schemas = {
        "judge": schema_payload(JudgeResponse),
        "select": schema_payload(ScoreResponse),
        "revise": schema_payload(ReviseResponse),
        "scene": SCENE_SCHEMA,
    }
    settings = load_settings(api_key=None, ai_mode="offline")
    client = GeminiClient(settings)
    keys = {
        name: client.cache_key("gemini-3.5-flash", texts[name], schemas[name], temp)
        for name, temp in (("judge", 0.1), ("select", 0.2), ("revise", 0.2))
    }
    return {"text_sha256": {k: _sha(v) for k, v in texts.items()},
            "schema_sha256": {k: _sha(json.dumps(v, ensure_ascii=False, sort_keys=True)) for k, v in schemas.items()},
            "cache_keys": keys, "texts": texts}


def _tree(analysis: Analysis) -> dict:
    groups = group_tree(
        [{"start": 0.0, "end": 20.0, "place": "카페", "activity": "주문", "event": "메뉴", "summary": "메뉴판",
          "mood": "설렘", "people": "빨간 후드"},
         {"start": 20.0, "end": 45.0, "place": "카페", "activity": "주문", "summary": "음료"}],
        [{"start": 1.0, "end": 3.0, "text": "안녕", "seg_id": "t1"},
         {"start": 18.0, "end": 23.0, "text": "아메리카노 두 잔이요", "cut": True, "seg_id": "t2"}], 45.0)
    return {"group_tree": groups, "analysis_tree": [n.model_dump() for n in analysis.tree]}


def build_snapshot() -> dict:
    analysis, clips = inputs()
    return {"rules": {k: v.model_dump() for k, v in analysis.judgments.items()},
            "tree": _tree(analysis), "prompts": _prompts(analysis), "plans": _plans(analysis, clips)}


def openapi_snapshot(app) -> dict:
    spec = app.openapi()
    ops = sorted(f"{method.upper()} {path}" for path, d in spec["paths"].items() for method in d)
    schemas = {name: sorted((s.get("properties") or {}).keys())
               for name, s in spec.get("components", {}).get("schemas", {}).items()}
    return {"operations": ops, "schemas": schemas}
