"""받아쓰기 문장 + 장면 → 비트(편집 단위) 목록 (v4 설계안 T3, 예전 4단 트리를 대체).

비트 두 종류 (모두 클립 초)
    speech  한 주제로 이어지는 말 묶음. 장면을 고르거나 AI 가편집이 고르는 기본 단위
    broll   말 없는 구간(2.5초 이상)에서 고른 2~5초 화면 — 말 사이에 넣어 장면 전환을 자연스럽게

말 비트 나누기 (자체 알고리즘)
    1. 큰 경계: 클립이 바뀌거나, 장면(장소·활동)이 바뀌거나, 쉼이 GAP_SPLIT초 이상이면 무조건 나눈다
    2. 주제 경계 (TextTiling 방식): 경계 앞 WINDOW문장과 뒤 WINDOW문장의 글자 2개 묶음 분포가
       얼마나 다른지(코사인 유사도의 '골 깊이') + 그 자리의 쉼 길이로 경계 점수를 매긴다
    3. 길이 맞추기: MAX_BEAT초보다 길면 가장 점수가 높은 경계에서 나누고(재귀), 그보다 짧아도
       IDEAL_BEAT초를 넘고 경계 점수가 STRONG 이상이면 나눈다. 양쪽 모두 MIN_BEAT초 이상일 때만

B롤 구간은 pick_window가 고른다 — 기본은 말 없는 구간 앞쪽 몇 초, 분석에서는 화면 품질 곡선으로
가장 볼만한 2~5초(analysis/quality.py best_window). 품질이 min_quality보다 나쁘면(흔들림·어두움) B롤로 쓰지 않는다.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable

from ..domain.korean import normalize
from ..domain.models import Beat, ClipSpan, Line, Scene

GAP_SPLIT = 2.0          # 이 이상 쉬면 다른 비트
WINDOW = 3               # 주제 경계를 볼 때 앞뒤로 비교할 문장 수
MIN_BEAT = 6.0           # 나눈 조각은 이보다 짧으면 안 된다
IDEAL_BEAT = 15.0        # 이보다 길고 주제가 뚜렷하게 바뀌면 나눈다
MAX_BEAT = 30.0          # 이보다 길면 반드시 나눈다 (가편집이 고를 때 너무 큰 덩어리가 되지 않게)
STRONG = 0.6             # 뚜렷한 주제 경계 점수 (0~1)
BROLL_MIN_GAP = 2.5      # 말 없는 구간이 이보다 짧으면 B롤로 쓰지 않는다
BROLL_MAX = 5.0          # B롤 비트 최대 길이
SPEECH_MARGIN = 0.3      # 말 앞뒤 이만큼은 말 구간으로 본다 (B롤이 말소리를 물지 않게)

# (클립 id, 말 없는 구간 시작, 끝) → 쓸 구간 (시작, 끝, 화면 품질 0~1 또는 모름 None)
PickWindow = Callable[[str, float, float], tuple[float, float, float | None]]


def _short(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _bigrams(lines: list[Line]) -> Counter:
    grams: Counter = Counter()
    for line in lines:
        t = normalize(line.text)
        grams.update(t[i:i + 2] for i in range(len(t) - 1))
    return grams


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def boundary_scores(lines: list[Line], window: int = WINDOW) -> list[float]:
    """문장 i-1과 i 사이(i=1..n-1)의 경계 점수 0~1. 앞 index 0은 쓰지 않는다 (0.0)."""
    n = len(lines)
    if n < 2:
        return [0.0] * n
    sims = [0.0] + [_cosine(_bigrams(lines[max(0, i - window):i]), _bigrams(lines[i:i + window]))
                    for i in range(1, n)]
    scores = [0.0]
    for i in range(1, n):
        left = max(sims[1:i + 1])                  # 골 깊이: 양쪽 봉우리에서 얼마나 내려왔나
        right = max(sims[i:])
        depth = min(1.0, ((left - sims[i]) + (right - sims[i])) / 2 + (1 - sims[i]) / 2)
        pause = min(1.0, max(0.0, lines[i].start - lines[i - 1].end) / GAP_SPLIT)
        scores.append(round(0.75 * depth + 0.25 * pause, 4))
    return scores


def split_topics(lines: list[Line]) -> list[list[Line]]:
    """한 덩어리(같은 장면, 긴 쉼 없음)의 문장들을 주제 경계로 나눈다."""
    if len(lines) < 2:
        return [lines]
    duration = lines[-1].end - lines[0].start
    scores = boundary_scores(lines)
    ok = [i for i in range(1, len(lines))
          if lines[i - 1].end - lines[0].start >= MIN_BEAT and lines[-1].end - lines[i].start >= MIN_BEAT]
    if not ok:
        return [lines]
    best = max(ok, key=lambda i: (scores[i], -abs((lines[i].start - lines[0].start) - duration / 2)))
    if duration > MAX_BEAT or (duration > IDEAL_BEAT and scores[best] >= STRONG):
        return split_topics(lines[:best]) + split_topics(lines[best:])
    return [lines]


def _scene_at(scenes: list[Scene], t: float) -> Scene | None:
    return next((sc for sc in scenes if sc.start <= t < sc.end), scenes[-1] if scenes and t >= scenes[-1].end else None)


def _runs(lines: list[Line], scenes: list[Scene]) -> list[list[Line]]:
    """큰 경계(장면이 바뀜, 긴 쉼)로 나눈 덩어리."""
    runs: list[list[Line]] = []
    last_scene = None
    for line in lines:
        sc = _scene_at(scenes, (line.start + line.end) / 2)
        key = sc.scene_id if sc else None
        if runs and key == last_scene and line.start - runs[-1][-1].end < GAP_SPLIT:
            runs[-1].append(line)
        else:
            runs.append([line])
        last_scene = key
    return runs


def _quiet_regions(lines: list[Line], duration: float) -> list[tuple[float, float]]:
    """말이 없는 구간 (말 앞뒤 SPEECH_MARGIN초는 말 구간으로 본다)."""
    busy = sorted((max(0.0, line.start - SPEECH_MARGIN), min(duration, line.end + SPEECH_MARGIN)) for line in lines)
    out, t = [], 0.0
    for s, e in busy:
        if s > t:
            out.append((t, s))
        t = max(t, e)
    if duration > t:
        out.append((t, duration))
    return [(s, e) for s, e in out if e - s >= BROLL_MIN_GAP]


def first_seconds(clip_id: str, start: float, end: float) -> tuple[float, float, float | None]:
    """기본 B롤 구간: 말 없는 구간의 앞쪽 최대 BROLL_MAX초 (경계에서 조금 띄운다). 품질은 모름."""
    s = start + 0.2
    return s, min(end - 0.2, s + BROLL_MAX), None


def _place(sc: Scene | None, label: str) -> str:
    return (sc.place if sc and sc.place else "") or label


def build_beats(spans: list[ClipSpan], scenes: list[Scene], lines: list[Line], clip_labels: dict[str, str],
                pick_window: PickWindow = first_seconds, min_quality: float = 0.0) -> list[Beat]:
    """타임라인 순서(spans)대로 클립마다 말 비트와 B롤 비트를 만들어 시간순으로 돌려준다."""
    beats: list[Beat] = []
    for span in spans:
        cid = span.clip_id
        clip_lines = sorted((line for line in lines if line.clip_id == cid), key=lambda x: x.start)
        clip_scenes = sorted((sc for sc in scenes if sc.clip_id == cid), key=lambda x: x.start)
        label = clip_labels.get(cid, cid)
        clip_beats: list[Beat] = []
        for run in _runs(clip_lines, clip_scenes):
            for group in split_topics(run):
                start, end = group[0].start, group[-1].end
                sc = _scene_at(clip_scenes, (start + end) / 2)
                spoken = [line.text.strip() for line in group if line.text.strip()]
                clip_beats.append(Beat(
                    beat_id=f"b-{group[0].seg_id}", kind="speech", clip_id=cid, start=round(start, 3),
                    end=round(end, 3), seg_ids=[line.seg_id for line in group], place=_place(sc, label),
                    title=_short(spoken[0] if spoken else "(말소리)", 30), summary=_short(" ".join(spoken), 120)))
        for qs, qe in _quiet_regions(clip_lines, span.duration):
            s, e, quality = pick_window(cid, qs, qe)
            if e - s < 1.0 or (quality is not None and quality < min_quality):
                continue
            sc = _scene_at(clip_scenes, (s + e) / 2)
            what = (sc.event or sc.summary) if sc else ""
            clip_beats.append(Beat(
                beat_id=f"r-{cid}-{int(round(s * 10))}", kind="broll", clip_id=cid, start=round(s, 3),
                end=round(e, 3), place=_place(sc, label), title=_short(what or "말 없는 장면", 30),
                summary=_short(sc.summary if sc else "", 120), quality=quality))
        beats += sorted(clip_beats, key=lambda b: b.start)
    return beats
