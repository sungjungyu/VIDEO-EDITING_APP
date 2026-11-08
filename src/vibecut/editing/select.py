"""AI 가편집: 비트 점수(규칙 + 있으면 Gemini) + 목표 분량 최적화(동적계획법) (v4 설계안 T3).

점수 (score_beats)
    말 비트  : 남는 말 비중, 강조할 말, 사용자 요청 단어 일치, 처음·끝 위치
    B롤 비트 : 기본 점수 + 요청 단어 일치 (장면 설명 기준)
    중복     : 앞에서 고른 것과 같은 내용(글자 2개 묶음 유사도 ≥ REDUNDANT)을 말하는 비트는 점수를 깎는다
    Gemini를 쓸 수 있으면 비트마다 점수·꼭 넣기(must)·빼기(never)·이유를 받아 덮어쓴다 (분량은 묻지 않는다)

분량 맞추기 (fit_duration) — 0/1 배낭 문제를 0.1초 단위 동적계획법으로 푼다 (예전 greedy 대체)
    가치  = Σ 점수 × 실제로 남는 길이 − μ·|결과 길이 − 목표|·평균 점수
            (목표에서 1초 벗어나는 것은 평균 점수짜리 내용 μ초만큼의 손해 → 목표에 가깝게, 그 안에서 좋은 비트)
    제약  = 결과 길이 ∈ 목표 ±5%, 고정(📌)·must는 반드시 넣고 never는 넣지 않는다,
            B롤은 목표의 BROLL_SHARE까지만 (점수 높은 순). 이 제한 때문에 목표에 못 미치면 제한을 풀고 다시 푼다
    결과  = 시간 순서 그대로 (순서를 바꾸지 않는다)
비트 길이는 '그 비트만 골랐을 때 실제로 남는 길이'(자를 문장·긴 쉼을 뺀 길이, planner와 같은 계산)다.
비트를 붙여 고르면 여유·쉼 처리 때문에 합이 조금 달라질 수 있어, 고른 뒤 실제 길이를 다시 재고
목표에서 벗어났으면 목표를 그만큼 보정해 한 번 더 푼다.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from pydantic import BaseModel

from ..ai.client import GeminiClient
from ..domain.intervals import merge
from ..domain.korean import normalize
from ..domain.models import Analysis, Beat, ClipInfo, EditPlan, Line, LineDecision, Selection
from ..errors import AIError, AIUnavailable
from ..settings import TARGET_TOLERANCE as TOLERANCE
from .planner import plan_clip

log = logging.getLogger("vibecut.editing.select")
_STOP = {"장면", "위주", "위주로", "영상", "부분", "해줘", "빼줘", "만들어", "만들어줘", "주세요", "그리고", "쇼츠",
         "쇼츠용", "재밌는", "재미있는", "좋은", "편집", "편집해줘", "분량", "정도", "넣어줘", "나오는"}
_JOSA = ("에서", "으로", "부터", "까지", "은", "는", "이", "가", "을", "를", "도", "만", "의", "로", "요")
UNIT = 0.1               # 동적계획법 시간 단위 (초)
MU = 2.0                 # 목표에서 1초 벗어날 때의 손해 (평균 점수 1초의 몇 배인가 — 클수록 목표에 딱 맞춘다)
BROLL_SHARE = 0.25       # B롤은 목표 길이의 이 비율까지만
REDUNDANT = 0.6          # 이 이상 비슷한 말 비트는 중복으로 본다


def _strip_josa(word: str) -> str:
    word = word.strip()
    for j in _JOSA:
        if word.endswith(j) and len(word) - len(j) >= 2:
            return word[:-len(j)]
    return word


def _keywords(prompt: str) -> tuple[list[str], list[str]]:
    """사용자 요청 → (넣고 싶은 말, 빼고 싶은 말). '…는 빼줘', '…없이' 앞의 낱말은 빼고 싶은 말."""
    want, avoid = [], []
    for clause in re.split(r"[,.\n]| 그리고 ", prompt or ""):
        words = [_strip_josa(w) for w in clause.split()]
        words = [w for w in words if len(w) >= 2 and w not in _STOP]
        negative = re.search(r"(빼|제외|없이|말고|싫)", clause)
        (avoid if negative else want).extend(w for w in words if not re.search(r"(빼|제외|없이|말고|싫)", w))
    return want, avoid


# ---------------------------------------------------------------- 길이

def effective_seconds(beat: Beat, analysis: Analysis, clips: dict[str, ClipInfo], decisions: dict[str, LineDecision],
                      plan: EditPlan, lines_by_clip: dict[str, list[Line]] | None = None) -> float:
    """이 비트만 골랐을 때 실제로 남는 길이 (planner와 같은 계산)."""
    return selection_seconds([beat], analysis, clips, decisions, plan, lines_by_clip)


def selection_seconds(beats: list[Beat], analysis: Analysis, clips: dict[str, ClipInfo],
                      decisions: dict[str, LineDecision], plan: EditPlan,
                      lines_by_clip: dict[str, list[Line]] | None = None) -> float:
    """비트들을 함께 골랐을 때 실제로 남는 길이 (클립마다 구간을 합쳐서 planner와 같은 계산)."""
    lines_by_clip = lines_by_clip if lines_by_clip is not None else analysis.lines_by_clip()
    by_clip: dict[str, list[tuple[float, float]]] = {}
    for b in beats:
        by_clip.setdefault(b.clip_id, []).append((b.start, b.end))
    total = 0.0
    for clip_id, ranges in by_clip.items():
        clip = clips.get(clip_id)
        if clip is None:
            continue
        silences = [tuple(x) for x in analysis.silences.get(clip_id, [])]
        kept = plan_clip(clip, merge(ranges), lines_by_clip.get(clip_id, []), decisions, {}, silences, plan.options)
        total += sum(e - s for s, e in kept)
    return total


# ---------------------------------------------------------------- 점수

def _beat_text(beat: Beat, lines: dict[str, Line], decisions: dict[str, LineDecision]) -> str:
    kept = [lines[s].text for s in beat.seg_ids if s in lines and (decisions.get(s) is None or decisions[s].keep)]
    return " ".join(kept)


def _grams(text: str) -> Counter:
    t = normalize(text)
    return Counter(t[i:i + 2] for i in range(len(t) - 1))


def _similarity(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / ((sum(v * v for v in a.values()) ** 0.5) * (sum(v * v for v in b.values()) ** 0.5))


def score_beats(beats: list[Beat], analysis: Analysis, decisions: dict[str, LineDecision],
                prompt: str) -> dict[str, dict]:
    """비트마다 {score, must, never, reason} (규칙 점수)."""
    want, avoid = _keywords(prompt)
    lines = {line.seg_id: line for line in analysis.lines}
    speech = [b for b in beats if b.kind == "speech"]
    first, last = (speech[0].beat_id, speech[-1].beat_id) if speech else ("", "")
    out: dict[str, dict] = {}
    texts: dict[str, str] = {}
    for b in beats:
        dur = max(0.1, b.end - b.start)
        text = " ".join([b.title, b.summary, b.place, _beat_text(b, lines, decisions)])
        hit = [w for w in want if w in text]
        miss = [w for w in avoid if w in text]
        reasons = [f"요청 단어 포함: {', '.join(hit[:3])}"] if hit else []
        if b.kind == "speech":
            kept = [lines[s] for s in b.seg_ids if s in lines and (decisions.get(s) is None or decisions[s].keep)]
            talk = sum(line.end - line.start for line in kept) / dur
            emphasis = any(decisions.get(s) and decisions[s].emphasis for s in b.seg_ids)
            score = 0.35 + 0.25 * min(1.0, talk * 1.5) + (0.15 if emphasis else 0.0)
            score += 0.05 if b.beat_id in (first, last) else 0.0
            if emphasis:
                reasons.append("강조할 말이 있음")
            if b.beat_id == first:
                reasons.append("시작 장면")
            elif b.beat_id == last:
                reasons.append("마무리 장면")
            elif talk > 0.5:
                reasons.append("말이 많은 장면")
            texts[b.beat_id] = _beat_text(b, lines, decisions)
        else:
            score = 0.4
            reasons.append("말 없는 장면")
        score += 0.3 * (len(hit) / len(want)) if want else 0.0
        reason = f"요청에서 뺀 내용: {', '.join(miss[:3])}" if miss else ("; ".join(reasons) or "기본 점수")
        out[b.beat_id] = {"score": round(max(0.0, min(1.0, score)), 3), "must": False, "never": bool(miss),
                          "reason": reason}
    _penalize_repeats(speech, texts, out)
    return out


def _penalize_repeats(speech: list[Beat], texts: dict[str, str], scores: dict[str, dict]) -> None:
    """같은 내용을 다시 말한 비트: 점수가 낮은 쪽을 깎는다."""
    grams = {b.beat_id: _grams(texts.get(b.beat_id, "")) for b in speech}
    for i, a in enumerate(speech):
        for b in speech[i + 1:]:
            if _similarity(grams[a.beat_id], grams[b.beat_id]) < REDUNDANT:
                continue
            low = a if scores[a.beat_id]["score"] < scores[b.beat_id]["score"] else b
            entry = scores[low.beat_id]
            if "비슷함" not in entry["reason"]:
                entry["score"] = round(entry["score"] * 0.6, 3)
                entry["reason"] = "다른 장면과 내용이 비슷함"


class ScoreItem(BaseModel):
    id: str
    score: float
    must: bool
    never: bool
    reason: str


class ScoreResponse(BaseModel):
    scores: list[ScoreItem]


def build_prompt(beats: list[Beat], analysis: Analysis, decisions: dict[str, LineDecision], prompt: str,
                 target_sec: float, profile: dict) -> str:
    lines = {line.seg_id: line for line in analysis.lines}
    total = sum(s.duration for s in analysis.clips)
    rows = []
    for b in beats:
        kind = "말" if b.kind == "speech" else "풍경"
        said = _beat_text(b, lines, decisions)[:80] if b.kind == "speech" else (b.summary or b.title)[:80]
        rows.append(f"{b.beat_id} | {b.clip_id} {b.start:.0f}~{b.end:.0f}s | {kind} | {b.place[:20]} | "
                    f"{said or '(말 없음)'}")
    tempo = profile.get("cut_tempo") or "(선택 없음)"
    return f"""당신은 영상 편집자다. 아래 장면 목록을 보고 결과 영상에 넣을 가치를 장면마다 점수로 매겨라.

[사용자 요청] {prompt.strip() or "(없음 — 재미·정보·감정이 큰 장면 위주)"}
[목표 분량] {target_sec:.0f}초 (원본 {total:.0f}초)  ※ 분량 계산은 하지 마라. 고르는 것은 프로그램이 한다.
[제작자 컷 템포] {tempo}
[규칙]
- score(0~1): 높을수록 넣을 가치가 크다. 요청에 맞는 장면, 처음 시작·마무리 장면, 사건이 있는 장면을 높게.
- 풍경 장면은 말 사이 분위기 전환용이다. 장소가 바뀌는 곳이나 볼거리가 있는 곳을 높게.
- must: 요청상 꼭 넣어야 하는 장면만 true.
- never: 요청에서 빼 달라고 한 내용(사람·장소·주제)이 있는 장면만 true.
- reason: 20자 이내 한국어 한 줄.
- 모든 장면 id를 빠짐없이 돌려준다.

[장면 목록] id | 클립 시각 | 종류 | 장소 | 내용
{chr(10).join(rows)}
"""


# ---------------------------------------------------------------- 분량 맞추기 (동적계획법)

def fit_duration(beats: list[Beat], seconds: dict[str, float], scores: dict[str, dict], locked: list[str],
                 target: float, tolerance: float = TOLERANCE) -> list[str]:
    """목표 분량에 맞게 고른 비트 id (시간순). B롤 제한 때문에 목표에 못 미치면 제한 없이 다시 푼다."""
    chosen, reached = _knapsack(beats, seconds, scores, locked, target, tolerance, BROLL_SHARE)
    if not reached and BROLL_SHARE < 1.0:
        chosen, _ = _knapsack(beats, seconds, scores, locked, target, tolerance, None)
    return chosen


def _knapsack(beats: list[Beat], seconds: dict[str, float], scores: dict[str, dict], locked: list[str],
              target: float, tolerance: float, broll_share: float | None) -> tuple[list[str], bool]:
    """0/1 배낭을 0.1초 단위로 정확히 푼다 → (고른 비트 id 시간순, 목표 범위에 들었나)."""
    hi_sec, lo_sec = target * (1 + tolerance), target * (1 - tolerance)
    forced = [b for b in beats if b.beat_id in locked or scores.get(b.beat_id, {}).get("must")]
    forced_ids = {b.beat_id for b in forced}
    forced_sec = sum(seconds.get(b.beat_id, 0.0) for b in forced)
    rest = [b for b in beats if b.beat_id not in forced_ids and not scores.get(b.beat_id, {}).get("never")
            and seconds.get(b.beat_id, 0.0) > 0]
    # B롤은 목표의 BROLL_SHARE까지만 (점수 높은 순으로 후보를 남긴다)
    forced_broll = sum(seconds.get(b.beat_id, 0.0) for b in forced if b.kind == "broll")
    broll_room = float("inf") if broll_share is None else broll_share * target - forced_broll
    items = []
    for b in sorted(rest, key=lambda x: -scores.get(x.beat_id, {}).get("score", 0.0)):
        if b.kind == "broll":
            if seconds[b.beat_id] > broll_room:
                continue
            broll_room -= seconds[b.beat_id]
        items.append(b)

    cap = int(round((hi_sec - forced_sec) / UNIT))
    if cap <= 0:
        return [b.beat_id for b in beats if b.beat_id in forced_ids], forced_sec >= lo_sec
    weights = [max(1, int(round(seconds[b.beat_id] / UNIT))) for b in items]
    values = [scores.get(b.beat_id, {}).get("score", 0.0) * seconds[b.beat_id] for b in items]
    neg = float("-inf")
    best = [neg] * (cap + 1)
    best[0] = 0.0
    took = []                                         # took[i][w]: i번 비트를 넣어서 w가 되었나
    for w_i, v_i in zip(weights, values):
        row = bytearray(cap + 1)
        for w in range(cap, w_i - 1, -1):
            prev = best[w - w_i]
            if prev != neg and prev + v_i > best[w]:
                best[w] = prev + v_i
                row[w] = 1
        took.append(row)

    mean_score = (sum(values) / sum(seconds[b.beat_id] for b in items)) if items else 0.0
    lo = max(0, int(round((lo_sec - forced_sec) / UNIT)))
    goal = (target - forced_sec) / UNIT
    reachable = [w for w in range(cap + 1) if best[w] != neg]
    in_band = [w for w in reachable if w >= lo]
    if in_band:
        w_best = max(in_band, key=lambda w: (best[w] - MU * abs(w - goal) * UNIT * mean_score, -abs(w - goal)))
    else:                                             # 재료가 모자라면 가장 길게
        w_best = max(reachable)
    chosen = set(forced_ids)
    w = w_best
    for i in range(len(items) - 1, -1, -1):
        if w > 0 and took[i][w]:
            chosen.add(items[i].beat_id)
            w -= weights[i]
    return [b.beat_id for b in beats if b.beat_id in chosen], bool(in_band)


def select_beats(analysis: Analysis, clips: dict[str, ClipInfo], plan: EditPlan, decisions: dict[str, LineDecision],
                 target_sec: float, user_prompt: str, locked: list[str], profile: dict | None,
                 client: GeminiClient | None) -> tuple[Selection, str, list[str]]:
    """(선택 결과, 엔진, 경고)."""
    profile = profile or {}
    beats = analysis.beats
    warnings: list[str] = []
    if not beats:
        return Selection(mode="all"), "rule", ["고를 장면이 없어 전체를 사용합니다. 먼저 분석하세요."]
    scores = score_beats(beats, analysis, decisions, user_prompt)
    engine = "rule"
    if client is not None:
        try:
            data = client.generate_json(build_prompt(beats, analysis, decisions, user_prompt, target_sec, profile),
                                        ScoreResponse, purpose="장면 점수", temperature=0.2)
            for item in data.get("scores", []):
                if item["id"] in scores:
                    scores[item["id"]] = {"score": max(0.0, min(1.0, float(item["score"]))),
                                          "must": bool(item["must"]), "never": bool(item["never"]),
                                          "reason": str(item["reason"])[:60]}
            engine = "ai"
        except AIUnavailable:
            pass
        except AIError as error:
            warnings.append(f"AI 장면 점수 실패 → 규칙 점수로 골랐습니다: {str(error)[:150]}")
    known = {b.beat_id for b in beats}
    locked = [i for i in locked if i in known]
    by_clip = analysis.lines_by_clip()
    seconds = {b.beat_id: effective_seconds(b, analysis, clips, decisions, plan, by_clip) for b in beats}

    chosen = fit_duration(beats, seconds, scores, locked, target_sec)
    actual = selection_seconds([b for b in beats if b.beat_id in chosen], analysis, clips, decisions, plan, by_clip)
    if actual > 0 and abs(actual / target_sec - 1) > TOLERANCE:          # 붙여 고를 때 생긴 차이를 한 번 보정
        retry = fit_duration(beats, seconds, scores, locked, target_sec * target_sec / actual)
        again = selection_seconds([b for b in beats if b.beat_id in retry], analysis, clips, decisions, plan, by_clip)
        if abs(again - target_sec) < abs(actual - target_sec):
            chosen, actual = retry, again

    locked_total = sum(seconds.get(i, 0.0) for i in locked)
    if locked_total > target_sec * (1 + TOLERANCE):
        warnings.append("고정한 장면만으로 목표 분량을 넘습니다.")
    available = sum(v for k, v in seconds.items() if not scores[k]["never"])
    if available < target_sec * (1 - TOLERANCE):
        warnings.append(f"쓸 수 있는 분량({available:.0f}초)이 목표({target_sec:.0f}초)보다 짧습니다.")
    elif actual < target_sec * (1 - TOLERANCE):
        warnings.append(f"장면을 통째로 고르면 목표에 못 미칩니다 (결과 약 {actual:.0f}초). "
                        "장면을 직접 더 고르거나 목표를 줄여 보세요.")
    reasons = {i: scores[i]["reason"] for i in chosen}
    selection = Selection(mode="auto", beat_ids=chosen, target_sec=target_sec, user_prompt=user_prompt,
                          locked_ids=locked, reasons=reasons, scores={i: v["score"] for i, v in scores.items()},
                          ai_beat_ids=list(chosen))
    return selection, engine, warnings
