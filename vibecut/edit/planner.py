"""편집 계획 계산 (자체 알고리즘): 고른 장면 + 문장별 판단 → 실제로 남길 구간(KeepRange).

    keep  = 고른 장면 구간의 합집합                       (말 없는 장면도 그대로 남는다)
    keep -= 자를 문장 구간 (앞뒤 쉼이 짧으면 쉼까지 함께)   (NG·반복·군더더기·지시어)
    keep -= 남기는 문장 사이의 긴 쉼                       (컷 템포: max_pause보다 긴 쉼을 짧게)
    경계  : 남길 문장 중간이면 문장 끝까지 넓히고, 단어 안에서 자르지 않고, 근처 무음 쪽으로 옮긴다
    여유  : 말 시작 앞 pad_start, 끝 뒤 pad_end. 짧은 틈은 메우고 너무 짧은 조각은 버린다
    마지막: 클립 프레임 단위로 맞춘다 → 영상·소리 조각 길이가 정확히 같아 컷이 많아도 싱크가 밀리지 않는다

시간은 클립 초. 장면 선택(트리 노드)만 원본 초라 global_to_clip으로 바꿔 쓴다.
"""

from __future__ import annotations

from ..models import (
    Analysis,
    ClipInfo,
    EditPlan,
    Effect,
    KeepRange,
    Line,
    LineDecision,
    PlanOptions,
    StyleSpec,
    TreeNode,
    now_iso,
)
from .timeline import build_overlay_events, build_subtitle_events, global_to_clip

Interval = tuple[float, float]


# ---------------------------------------------------------------- 구간 연산

def merge(intervals: list[Interval], gap: float = 0.0) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(intervals):
        if e <= s:
            continue
        if out and s <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract(base: list[Interval], cuts: list[Interval]) -> list[Interval]:
    cuts = merge(cuts)
    out: list[Interval] = []
    for s, e in base:
        cur = s
        for cs, ce in cuts:
            if ce <= cur or cs >= e:
                continue
            if cs > cur:
                out.append((cur, cs))
            cur = max(cur, ce)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def clamp(intervals: list[Interval], lo: float, hi: float) -> list[Interval]:
    return [(max(s, lo), min(e, hi)) for s, e in intervals if min(e, hi) > max(s, lo)]


# ---------------------------------------------------------------- 판단·선택

def effective_decisions(plan: EditPlan, analysis: Analysis | None) -> dict[str, LineDecision]:
    """AI·규칙 판단 위에 사용자 결정을 덮어쓴다."""
    merged = dict(analysis.judgments) if analysis else {}
    merged.update(plan.lines)
    return merged


def flatten(tree: list[TreeNode]) -> dict[str, TreeNode]:
    out: dict[str, TreeNode] = {}
    stack = list(tree)
    while stack:
        node = stack.pop()
        out[node.id] = node
        stack.extend(node.children)
    return out


def selected_ranges(plan: EditPlan, analysis: Analysis | None) -> list[Interval] | None:
    """고른 장면의 원본 초 구간. None이면 '전체 사용'."""
    if plan.selection.mode == "all" or analysis is None or not analysis.tree:
        return None
    nodes = flatten(analysis.tree)
    return merge([(nodes[i].start, nodes[i].end) for i in plan.selection.node_ids if i in nodes])


# ---------------------------------------------------------------- 클립 하나

def _fix_boundaries(base: list[Interval], lines: list[Line], flags: list[bool], opts: PlanOptions) -> list[Interval]:
    """장면 경계가 문장 중간에 걸리면: 문장 가운데가 구간 안이면 문장 끝까지 넓히고, 아니면 문장을 뺀다."""
    out = []
    for s, e in base:
        for line, keep in zip(lines, flags):
            mid = (line.start + line.end) / 2
            if line.start < s < line.end:
                s = line.start - opts.pad_start if keep and mid >= s else line.end + 0.02
            if line.start < e < line.end:
                e = line.end + opts.pad_end if keep and mid < e else line.start - 0.02
        if e - s > 0.05:
            out.append((s, e))
    return merge(out)


def _cuts(lines: list[Line], flags: list[bool], opts: PlanOptions) -> list[Interval]:
    cuts: list[Interval] = []
    for i, (line, keep) in enumerate(zip(lines, flags)):
        if keep:
            continue
        cs, ce = line.start - 0.05, line.end + 0.05
        if i > 0 and line.start - lines[i - 1].end <= opts.swallow_pause:
            cs = min(lines[i - 1].end + (opts.pad_end if flags[i - 1] else 0.0), line.start)
        if i + 1 < len(lines) and lines[i + 1].start - line.end <= opts.swallow_pause:
            ce = max(lines[i + 1].start - (opts.pad_start if flags[i + 1] else 0.0), line.end)
        cuts.append((cs, ce))
    if opts.max_pause:
        kept = [line for line, keep in zip(lines, flags) if keep]
        for a, b in zip(kept, kept[1:]):
            if opts.max_pause < b.start - a.end <= opts.pause_limit:
                cs, ce = a.end + opts.pad_end, b.start - opts.pad_start
                if ce - cs > 0.05:
                    cuts.append((cs, ce))
    return merge(cuts)


def _snap_start(s: float, silences: list[tuple[float, float]], reach: float = 0.15) -> float:
    for a, b in silences:
        if a <= s <= b:
            return s
        if 0 <= s - b <= reach:          # 무음이 막 끝난 뒤에서 시작 → 말 첫소리가 잘리지 않게 앞으로
            return max(a, b - 0.05)
    return s


def _snap_end(e: float, silences: list[tuple[float, float]], reach: float = 0.15) -> float:
    for a, b in silences:
        if a <= e <= b:
            return e
        if 0 <= a - e <= reach:          # 곧 무음이 시작되는데 그 전에 끝남 → 말끝이 잘리지 않게 뒤로
            return min(b, a + 0.05)
    return e


def _snap(intervals: list[Interval], words: list[tuple[float, float, bool]],
          silences: list[tuple[float, float]], opts: PlanOptions) -> list[Interval]:
    out = []
    for s, e in intervals:
        for ws, we, keep in words:      # 단어 안에서 시작·끝나지 않게
            if ws < s < we:
                s = ws - 0.02 if keep else we + 0.01
            if ws < e < we:
                e = we + 0.02 if keep else ws - 0.01
        if opts.snap_to_silence and silences:
            s, e = _snap_start(s, silences), _snap_end(e, silences)
        if e - s > 0.02:
            out.append((s, e))
    return merge(out)


def _quantize(intervals: list[Interval], fps: float) -> list[Interval]:
    if not fps or fps <= 0:
        return intervals
    out = []
    for s, e in intervals:
        qs, qe = round(s * fps) / fps, round(e * fps) / fps
        if qe - qs >= 1 / fps:
            out.append((qs, qe))
    return merge(out)


def _contains_kept_line(iv: Interval, lines: list[Line], flags: list[bool]) -> bool:
    return any(keep and iv[0] <= line.start and line.end <= iv[1] for line, keep in zip(lines, flags))


def plan_clip(clip: ClipInfo, base: list[Interval], lines: list[Line], decisions: dict[str, LineDecision],
              user_lines: dict[str, LineDecision], silences: list[tuple[float, float]],
              opts: PlanOptions) -> list[Interval]:
    """클립 하나에서 남길 구간 (클립 초)."""
    lo, hi = clip.in_point, clip.usable_end
    lines = sorted(lines, key=lambda x: x.start)
    flags = [decisions[line.seg_id].keep if line.seg_id in decisions else True for line in lines]
    base = clamp(_fix_boundaries(clamp(base, lo, hi), lines, flags, opts), lo, hi)
    kept = subtract(base, _cuts(lines, flags, opts))
    forced = [(line.start - opts.pad_start, line.end + opts.pad_end) for line in lines
              if (d := user_lines.get(line.seg_id)) is not None and d.keep and d.source == "user"]
    kept = merge(kept + clamp(forced, lo, hi))
    words = sorted((w.start, w.end, keep) for line, keep in zip(lines, flags) for w in line.words)
    kept = clamp(_snap(kept, words, silences, opts), lo, hi)
    kept = merge(kept, gap=opts.min_gap)
    kept = [iv for iv in kept if iv[1] - iv[0] >= opts.min_keep or _contains_kept_line(iv, lines, flags)]
    return clamp(_quantize(kept, clip.fps), lo, hi)


# ---------------------------------------------------------------- 연출 효과

def _effects(keep: list[KeepRange], lines_by_clip: dict[str, list[Line]], decisions: dict[str, LineDecision],
             opts: PlanOptions, min_spacing: float = 8.0) -> list[Effect]:
    """강조 문장에 펀치인(살짝 줌인). 너무 자주 나오지 않게 결과 영상 기준 8초 간격."""
    if not opts.punch_in:
        return []
    candidates = []
    for k in keep:
        for line in lines_by_clip.get(k.clip_id, []):
            d = decisions.get(line.seg_id)
            if not d or not d.keep or not d.emphasis:
                continue
            s, e = max(line.start, k.start), min(line.end, k.end)
            if e - s >= 0.8:
                candidates.append((k.out_start + s - k.start,
                                   Effect(clip_id=k.clip_id, start=round(s, 4), end=round(e, 4),
                                          scale=opts.punch_scale, seg_id=line.seg_id)))
    chosen, last = [], -min_spacing
    for out_t, effect in sorted(candidates, key=lambda x: x[0]):
        if out_t - last >= min_spacing:
            chosen.append(effect)
            last = out_t
    return chosen


# ---------------------------------------------------------------- 전체

def compile_plan(plan: EditPlan, clips: list[ClipInfo], analysis: Analysis | None) -> EditPlan:
    """사용자 값(selection, lines, styles, options) → keep·effects·events·duration을 계산해 채운 새 계획."""
    plan = plan.model_copy(deep=True)
    opts = plan.options
    warnings: list[str] = []
    decisions = effective_decisions(plan, analysis)
    lines_by_clip = analysis.lines_by_clip() if analysis else {}
    spans = analysis.clips if analysis else []
    analyzed = {s.clip_id for s in spans}
    sel = selected_ranges(plan, analysis)
    if sel is not None and not sel:
        warnings.append("고른 장면이 없습니다. 편집 설정에서 장면을 고르거나 AI 가편집을 실행하세요.")

    keep: list[KeepRange] = []
    cursor = 0.0
    for clip in clips:
        lo, hi = clip.in_point, clip.usable_end
        if hi - lo <= 0.05:
            continue
        if sel is None or clip.clip_id not in analyzed:
            base = [(lo, hi)]
            if analysis is not None and clip.clip_id not in analyzed:
                warnings.append(f"'{clip.filename}'은 아직 분석하지 않아 전체를 넣었습니다. "
                                "다시 분석하면 자막과 컷이 생깁니다.")
        else:
            base = merge([(s, e) for gs, ge in sel for cid, s, e in global_to_clip(gs, ge, spans)
                          if cid == clip.clip_id])
        silences = [tuple(x) for x in analysis.silences.get(clip.clip_id, [])] if analysis else []
        intervals = plan_clip(clip, base, lines_by_clip.get(clip.clip_id, []), decisions, plan.lines, silences, opts)
        for s, e in intervals:
            keep.append(KeepRange(clip_id=clip.clip_id, start=round(s, 4), end=round(e, 4),
                                  out_start=round(cursor, 4)))
            cursor += e - s

    plan.keep = keep
    plan.duration = round(cursor, 3)
    plan.effects = _effects(keep, lines_by_clip, decisions, opts)
    style = plan.styles.get("subtitle") or StyleSpec()
    events = build_subtitle_events(keep, lines_by_clip, decisions, style, cursor) if opts.subtitles else []
    events += build_overlay_events(keep, analysis.tree if analysis else [], spans, plan.styles, opts, cursor)
    plan.events = events
    if not keep and clips:
        warnings.append("남길 구간이 없습니다.")
    target = plan.selection.target_sec
    if target and plan.duration and abs(plan.duration / target - 1) > 0.1:
        warnings.append(f"결과 길이 {plan.duration:.1f}초가 목표 {target:.0f}초와 10% 넘게 다릅니다.")
    plan.warnings = warnings
    plan.updated_at = now_iso()
    return plan
