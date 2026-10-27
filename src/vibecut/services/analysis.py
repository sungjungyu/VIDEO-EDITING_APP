"""분석 작업: 타임라인의 클립 전체를 한 번에 분석한다. 작업 큐(백그라운드 스레드)나 명령줄에서 실행한다.

분석 순서 (진행률)
    오디오 추출 (0~8%)  →  받아쓰기 ∥ 장면 분석 (8~75%, 동시에)  →  컷 판단 (75~90%)
    →  4단 트리 (90~95%)  →  편집 계획 계산 (95~100%)
받아쓰기·장면 분석·컷 판단의 Gemini 사용량은 모두 ctx.usage에 모여 작업 기록·평가 지표에 남는다.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..ai.client import GeminiClient
from ..analysis import judge as judge_mod
from ..analysis.scenes import analyze_clip_scenes
from ..analysis.stt import transcribe_clip
from ..analysis.tree import build_tree
from ..domain.models import (
    Analysis,
    AnalysisState,
    ClipInfo,
    EditPlan,
    Line,
    PlanOptions,
    Scene,
    Word,
    flatten_tree,
    now_iso,
)
from ..domain.timebase import clip_spans
from ..editing.planner import compile_plan
from ..errors import Canceled
from ..settings import Settings
from ..storage.projects import ProjectStore
from .context import RunContext
from .media import audio_wav

log = logging.getLogger("vibecut.services.analysis")


def apply_profile(options: PlanOptions, profile: dict | None) -> PlanOptions:
    """제작자 프로필의 '컷 템포' → 남기는 문장 사이 쉼을 얼마나 줄일지."""
    tempo = str((profile or {}).get("cut_tempo") or "")
    pauses = {"느림": 1.5, "보통": 0.8, "빠름": 0.4}
    for key, value in pauses.items():
        if tempo.startswith(key):
            return options.model_copy(update={"max_pause": value})
    return options


def _clip_labels(clips: list[ClipInfo]) -> dict[str, str]:
    return {c.clip_id: f"클립 {i} · {Path(c.filename).stem[:24]}" for i, c in enumerate(clips, 1)}


def _line_key(line: Line) -> tuple:
    return line.clip_id, round(line.start, 2), line.text


def _tree_key(nodes) -> list:
    return [(n.id, round(n.start, 2), round(n.end, 2)) for n in nodes]


def carry_over_plan(plan: EditPlan, old: Analysis | None, new: Analysis) -> tuple[EditPlan, list[str]]:
    """다시 분석했을 때 사용자 결정 중 '같은 문장·같은 트리'에 해당하는 것만 이어받는다."""
    notes: list[str] = []
    old_lines = {line.seg_id: _line_key(line) for line in old.lines} if old else {}
    new_lines = {line.seg_id: _line_key(line) for line in new.lines}
    kept = {sid: d for sid, d in plan.lines.items()
            if d.source == "user" and sid in new_lines and old_lines.get(sid) == new_lines[sid]}
    if len(kept) < sum(1 for d in plan.lines.values() if d.source == "user"):
        notes.append("받아쓰기가 바뀌어 일부 문장 결정(남김/자름, 자막 수정)을 초기화했습니다.")
    plan.lines = kept
    same_tree = (old is not None
                 and _tree_key(flatten_tree(old.tree).values()) == _tree_key(flatten_tree(new.tree).values()))
    if plan.selection.mode != "all" and not same_tree:
        plan.selection = plan.selection.model_copy(update={"mode": "all", "node_ids": [], "reasons": {},
                                                           "ai_node_ids": []})
        notes.append("장면 트리가 바뀌어 장면 선택을 '전체 사용'으로 되돌렸습니다.")
    return plan, notes


# ---------------------------------------------------------------- 분석

def run_analysis(ctx: RunContext, store: ProjectStore, settings: Settings, project_id: str,
                 profile: dict | None = None, client: GeminiClient | None = None) -> dict:
    profile = profile or {}
    project = store.get(project_id)
    clips = project.timeline_clips()
    if not clips:
        raise ValueError("타임라인에 클립이 없습니다. 클립을 타임라인에 올린 뒤 분석하세요.")
    timeline = list(project.timeline)
    store.update(project_id, lambda p: setattr(p, "analysis", AnalysisState(status="running", job_id=ctx.job_id,
                                                                           timeline=timeline)))
    try:
        return _analyze(ctx, store, settings, project_id, clips, timeline, profile, client)
    except BaseException as error:
        state = AnalysisState(status="none" if isinstance(error, Canceled) else "failed", job_id=ctx.job_id,
                              timeline=timeline, warnings=[str(error)[:300]], updated_at=now_iso())
        store.update(project_id, lambda p: setattr(p, "analysis", state))
        raise


def _analyze(ctx: RunContext, store: ProjectStore, settings: Settings, project_id: str, clips: list[ClipInfo],
             timeline: list[str], profile: dict, client: GeminiClient | None) -> dict:
    client = (client or GeminiClient(settings, store.cache_dir / "ai")).with_usage(ctx.usage)
    vocab = [w for w in profile.get("frequent_words") or [] if isinstance(w, str) and w.strip()][:30]
    spans = clip_spans(clips)
    warnings: list[str] = []

    with ctx.stage("audio"):
        wavs: dict[str, Path | None] = {}
        for i, c in enumerate(clips):
            ctx.check()
            ctx.progress(8 * i / len(clips), "오디오 추출", c.filename)
            wavs[c.clip_id] = audio_wav(store, project_id, c)

    stt: dict[str, dict] = {}
    scene_out: dict[str, dict] = {}
    progress_lock = threading.Lock()
    done = {"stt": 0, "scenes": 0}

    def tick(kind: str, label: str):
        with progress_lock:
            done[kind] += 1
            total = 2 * len(clips)
            ctx.progress(8 + 67 * (done["stt"] + done["scenes"]) / total, "받아쓰기·영상 분석", label)

    def do_stt():
        for c in clips:
            ctx.check()
            wav = wavs[c.clip_id]
            if wav is None:
                stt[c.clip_id] = {"segments": [], "silences": [], "engine": "no-audio", "warnings": []}
            else:
                stt[c.clip_id] = transcribe_clip(wav, c.sha1, settings, store.cache_dir / "stt", vocab,
                                                  ctx.cancel, client)
            tick("stt", f"받아쓰기 {c.filename}")

    def do_scenes():
        prev_summary, people = "", ""
        for c in clips:
            ctx.check()
            r = analyze_clip_scenes(store.clip_path(project_id, c.stored_name), c.sha1, c.duration, settings,
                                    store.cache_dir / "scenes", store.work_dir(project_id, f"scene_{ctx.job_id}"),
                                    prev_summary, people, ctx.cancel, client)
            scene_out[c.clip_id] = r
            if r["scenes"]:
                prev_summary = " / ".join(s.get("summary", "") for s in r["scenes"][-3:])
                people = ", ".join(sorted({s.get("people", "") for s in r["scenes"] if s.get("people")}))
            tick("scenes", f"영상 분석 {c.filename}")

    with ctx.stage("transcribe_and_scenes"), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(do_stt), pool.submit(do_scenes)]
        for f in futures:
            f.result()

    lines: list[Line] = []
    silences: dict[str, list] = {}
    scenes: list[Scene] = []
    engines = {"stt": "", "scenes": ""}
    for c in clips:
        r = stt[c.clip_id]
        warnings += r["warnings"]
        engines["stt"] = engines["stt"] or r["engine"]
        silences[c.clip_id] = [[round(a, 3), round(b, 3)] for a, b in r["silences"]]
        for seg in r["segments"]:
            lines.append(Line(seg_id=f"t{len(lines) + 1:04d}", clip_id=c.clip_id, start=round(seg["start"], 3),
                              end=round(seg["end"], 3), text=seg.get("text", "").strip(), speaker=seg.get("speaker"),
                              words=[Word(word=w["word"], start=round(w["start"], 3), end=round(w["end"], 3),
                                          probability=w.get("probability")) for w in seg.get("words", [])]))
        s = scene_out[c.clip_id]
        warnings += s["warnings"]
        engines["scenes"] = engines["scenes"] or s["engine"]
        source = "gemini" if s["engine"].startswith("gemini") else "local"
        for sc in s["scenes"]:
            scenes.append(Scene(scene_id=f"s{len(scenes) + 1:03d}", clip_id=c.clip_id, start=round(sc["start"], 3),
                                end=round(sc["end"], 3), place=sc.get("place", ""), activity=sc.get("activity", ""),
                                people=sc.get("people", ""), event=sc.get("event", ""), mood=sc.get("mood", ""),
                                summary=sc.get("summary", ""), source=source))

    ctx.check()
    with ctx.stage("judge"):
        ctx.progress(76, "컷 판단", f"문장 {len(lines)}개")
        judgments, engines["judge"], judge_warnings = judge_mod.judge_lines(lines, scenes, profile, client)
        warnings += judge_warnings

    with ctx.stage("tree"):
        ctx.progress(91, "장면 트리")
        tree = build_tree(spans, scenes, lines, judgments, _clip_labels(clips))

    analysis = Analysis(clips=spans, lines=lines, scenes=scenes, tree=tree, silences=silences, judgments=judgments,
                        engines=engines, warnings=list(dict.fromkeys(warnings)))
    old = store.load_analysis(project_id)
    store.save_analysis(project_id, analysis)

    ctx.progress(96, "편집 계획")
    plan, notes = carry_over_plan(store.load_plan(project_id), old, analysis)
    plan.options = apply_profile(plan.options, profile)
    plan = compile_plan(plan, store.get(project_id).timeline_clips(), analysis)
    store.save_plan(project_id, plan)
    analysis_state = AnalysisState(status="done", job_id=ctx.job_id, timeline=timeline, engines=engines,
                                   warnings=analysis.warnings + notes, updated_at=now_iso())
    store.update(project_id, lambda p: setattr(p, "analysis", analysis_state))
    cut = sum(1 for d in judgments.values() if not d.keep)
    ctx.log.info("분석 완료: 문장 %d (자름 제안 %d), 장면 %d, 엔진 %s", len(lines), cut, len(scenes), engines)
    return {"lines": len(lines), "cut_suggested": cut, "scenes": len(scenes), "tree_nodes": len(flatten_tree(tree)),
            "plan_duration": plan.duration, "engines": engines, "warnings": analysis_state.warnings}
