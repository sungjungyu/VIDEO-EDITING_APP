"""
VIBE CUT 1-3: 4단 트리 (장소·세션 → 행동 흐름 → 세부 행동 → 장면)

받아쓰기(transcriber.py)와 L4 장면 분석(shot_analyzer.py) 결과를 합쳐 4단 트리를 만든다.

    L1 장소·세션   카페 (1차 방문)        같은 장소라도 다른 곳에 다녀왔거나 촬영이 끊기면 새 세션
    L2 행동 흐름   주문 흐름              연속으로 이어지는 큰 행동 덩어리 (화면에서 보이는 것만)
    L3 세부 행동   메뉴판 보기 / 결제     흐름 안에서 맥락이 바뀌는 단계 (대사도 참고)
    L4 장면        카운터 앞에서 메뉴판을 올려다본다 (3~7초)  ← 그 시간의 대사(받아쓰기 문장)가 붙는다

앱 흐름의 2~4단계:
    2. 정형화        normalize_clips / normalize_lines / normalize_shots
                     두 결과를 같은 모양, 같은 시간축(전체 타임라인 초)으로 맞춘다
    3. 합치기·보정   build_units (코드)       장면 경계를 문장 사이 쉼으로 옮기고, 3~7초로 나누고, 대사를 붙인다
                     ask_tree (AI)            앞뒤 대사·화면 설명·화면 글자로 잘못 들은 단어를 고치고(보정),
                                              보정한 대사로 맥락을 읽어 L1~L3 경계·제목을 정한다
                     apply_corrections (코드)  AI 보정을 검사해서 적용 (발음이 비슷한 단어 바꿈만, 단어 시각 유지)
    4. 트리 구성     assemble_tree (코드)     AI가 고른 경계를 검증해 트리로. AI가 실패하면 규칙(fallback_structure)으로 묶는다

코드가 보장하는 규칙:
    - 자식 노드가 부모 구간을 빈틈·겹침 없이 덮는다 (부모 길이 = 자식 길이 합). 말 없는 장면도 L4 노드다.
    - 모든 가지가 L4까지 내려간다 (편집 설정 화면의 탭이 깊이 기준).
    - L4 경계는 문장 중간을 자르지 않는다 (13초쯤 넘는 아주 긴 문장만 단어 사이에서 자른다).
    - AI는 시각을 만들지 않는다. L3가 시작하는 장면 id만 고르고, 시각은 코드가 L4에서 계산한다.
    - L4 id(s0001…)는 AI의 묶음과 상관없이 정해진다.

노드 형식은 prompt_builder.normalize_tree / 화면 normalizeFakeTreeNode와 같다:
    {"id", "level", "title", "start", "end", "summary", "tags", "children", ...층별 정보}

사용 예:
    python transcriber.py   --input ./raw_clips --engine gemini --out transcript.json
    python shot_analyzer.py --input ./raw_clips --out shots.json
    python scene_tree.py --transcript transcript.json --shots shots.json --out tree.json
    python scene_tree.py --transcript transcript.json --shots shots.json --no-ai     # AI 없이 규칙만
"""

import argparse
import bisect
import difflib
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from shot_analyzer import clean_shots, empty_shot, merge_short, merge_shot

TREE_MODEL = os.getenv("TREE_MODEL", "gemini-3.5-flash")
TREE_FALLBACK_MODEL = os.getenv("TREE_FALLBACK_MODEL", "gemini-3.5-flash-lite")

LEVEL_NAMES = ("장소·세션", "행동 흐름", "세부 행동", "장면")
MIN_SHOT_SEC = 2.0        # 이보다 짧은 화면 장면은 이웃과 합친다
UNIT_MIN_SEC = 3.0        # L4 장면 목표 길이 (3~7초)
UNIT_MAX_SEC = 7.0
SNAP_PAD = 0.3            # 장면 경계를 문장 밖으로 옮길 때 문장에서 띄우는 최대 거리 (초)
SESSION_GAP_SEC = 600.0   # 클립 사이 촬영 간격이 이보다 길면 무조건 새 세션 (10분)
MAX_UNITS_PER_CALL = 240  # AI 한 번에 보내는 장면 수 (넘으면 나눠 보낸다, 약 20분)
MIN_SOUND_SIMILARITY = 0.5  # 보정 전후 발음(자모) 유사도가 이보다 낮으면 보정을 받지 않는다
EPS = 0.05

# L4 나누기 비용 (작을수록 선호). 문장 사이 쉼 < 말 없는 곳 < 단어 사이
# 7초를 넘는 조각은 1초당 1.0. → 말 없는 장면은 7.6초부터 나누고, 문장은 13초까지 통째로 둔다.
CUT_COST_SENTENCE = 0.2
CUT_COST_SILENT = 0.6
CUT_COST_WORD = 6.0
MAX_PIECE_SEC = 20.0      # 나누기 계산에서 보는 최대 조각 길이 (계산량 제한)


def _r(x: float) -> float:
    return round(float(x), 3)


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _short(text: str, n: int) -> str:
    text = _text(text)
    return text if len(text) <= n else text[:n - 1] + "…"


# ================================================================ 2. 정형화

def _epoch(value) -> float | None:
    """촬영 시각: epoch 초 또는 ISO 문자열 → epoch 초. 모르면 None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def normalize_clips(clips: list[dict]) -> list[dict]:
    """[{"id", "file", "duration", "offset", "created"(epoch 초 또는 None)}] (offset 순)"""
    out = []
    for i, c in enumerate(clips or [], 1):
        out.append({"id": str(c.get("id") or f"c{i:02d}"), "file": str(c.get("file") or ""),
                    "duration": float(c.get("duration") or 0.0), "offset": float(c.get("offset") or 0.0),
                    "created": _epoch(c.get("created", c.get("created_at")))})
    out.sort(key=lambda c: c["offset"])
    return out


def _clip_at(t: float, clips: list[dict]) -> dict:
    for c in clips:
        if t < c["offset"] + c["duration"]:
            return c
    return clips[-1]


def normalize_lines(segments: list[dict], clips: list[dict]) -> list[dict]:
    """받아쓰기 결과(transcript.json segments 또는 앱의 segments) → 대사 목록 (전체 타임라인 초).
    [{"id": "t0001", "clip_id", "start", "end", "text", "words": [{"word", "start", "end"}]}]"""
    lines = []
    for s in segments or []:
        try:
            st, en = float(s["start"]), float(s["end"])
        except (KeyError, TypeError, ValueError):
            continue
        text = _text(s.get("text"))
        if not text or en <= st:
            continue
        words = []
        for w in s.get("words") or []:
            word = _text(w.get("word"))
            try:
                ws, we = float(w["start"]), float(w["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if word:
                words.append({"word": word, "start": ws, "end": max(ws, we)})
        clip_id = s.get("clip_id") or (_clip_at((st + en) / 2, clips)["id"] if clips else "c01")
        lines.append({"id": str(s.get("seg_id") or s.get("id") or ""), "clip_id": str(clip_id),
                      "start": st, "end": en, "text": text, "words": words})
    lines.sort(key=lambda x: (x["start"], x["end"]))
    ids = [x["id"] for x in lines]
    if not all(ids) or len(set(ids)) != len(ids):
        for i, x in enumerate(lines, 1):
            x["id"] = f"t{i:04d}"
    return lines


def normalize_shots(shots: list[dict], clips: list[dict], min_sec: float = MIN_SHOT_SEC) -> list[dict]:
    """장면 분석 결과 → 클립마다 빈틈없이 덮는 화면 장면 목록 (전체 타임라인 초).
    shots.json(clip_id + 클립 안 초 clip_start/clip_end)과 앱 결과(clip_id 없이 영상 안 초, 클립 1개) 모두 받는다.
    장면 분석이 없거나 실패한 클립은 "(영상분석 없음)" 장면 하나로 덮는다."""
    clip_by_id = {c["id"]: c for c in clips}
    single = clips[0]["id"] if len(clips) == 1 else None
    raw_by_clip = {c["id"]: [] for c in clips}
    for s in shots or []:
        clip = clip_by_id.get(s.get("clip_id") or single)
        if clip is None:
            continue
        if "clip_start" in s:              # shots.json: 클립 안 초가 따로 있다
            st, en = s["clip_start"], s.get("clip_end", s["end"])
        elif s.get("clip_id"):             # clip_id + 전체 타임라인 초
            st, en = float(s["start"]) - clip["offset"], float(s["end"]) - clip["offset"]
        else:                              # 앱: 영상 안 초
            st, en = s["start"], s["end"]
        raw_by_clip[clip["id"]].append({**s, "start": st, "end": en})
    out = []
    for c in clips:
        raw = raw_by_clip[c["id"]]
        local = clean_shots(raw, c["duration"], min_sec) if raw else \
            [empty_shot(0.0, c["duration"], "(영상분석 없음)", "missing")]
        out += [{**s, "clip_id": c["id"], "start": s["start"] + c["offset"], "end": s["end"] + c["offset"]}
                for s in local]
    return out


# ================================================================ 3-1. 합치기 (코드): 화면 장면 + 대사 → L4 장면

def _line_at(t: float, lines: list[dict]) -> dict | None:
    """t초가 문장 안쪽(앞뒤 EPS 제외)에 떨어지는 문장."""
    for line in lines:
        if line["start"] + EPS < t < line["end"] - EPS:
            return line
        if line["start"] > t:
            return None
    return None


def _pad(line: dict, lines: list[dict], before: bool) -> float:
    """문장 앞(또는 뒤) 쉼의 절반, 최대 SNAP_PAD. 이웃 문장이 없으면 SNAP_PAD."""
    if before:
        prev_end = max((x["end"] for x in lines if x["end"] <= line["start"] + 1e-9 and x is not line), default=None)
        gap = None if prev_end is None else line["start"] - prev_end
    else:
        next_start = min((x["start"] for x in lines if x["start"] >= line["end"] - 1e-9 and x is not line), default=None)
        gap = None if next_start is None else next_start - line["end"]
    return SNAP_PAD if gap is None else max(0.0, min(SNAP_PAD, gap / 2))


def snap_to_lines(pieces: list[dict], lines: list[dict]) -> list[dict]:
    """화면 장면 경계가 문장 안에 떨어지면 그 문장 앞이나 뒤의 쉼으로 옮긴다 (가까운 쪽).
    옮길 곳이 없으면(문장이 이웃 장면보다 길면) 두 장면을 합친다. pieces는 한 클립을 빈틈없이 덮는다."""
    pieces = [dict(p) for p in pieces]
    i = 0
    while i < len(pieces) - 1:
        a, b = pieces[i], pieces[i + 1]
        line = _line_at(a["end"], lines)
        if line is not None:
            cands = sorted((line["start"] - _pad(line, lines, True), line["end"] + _pad(line, lines, False)),
                           key=lambda t: abs(t - a["end"]))
            ok = [t for t in cands if a["start"] + EPS < t < b["end"] - EPS]
            if not ok:
                pieces[i:i + 2] = [merge_shot(a, b)]
                continue
            a["end"] = b["start"] = ok[0]
        i += 1
    return pieces


def _piece_cost(d: float, umin: float, umax: float) -> float:
    balance = 0.01 * (d - (umin + umax) / 2) ** 2      # 비용이 같으면 고른 길이(4+4초 > 5+3초)를 고른다
    if d < umin:
        return (umin - d) * 2.0 + balance
    if d > umax:
        return (d - umax) * 1.0 + balance
    return balance


def split_points(start: float, end: float, lines: list[dict], umin: float = UNIT_MIN_SEC,
                 umax: float = UNIT_MAX_SEC, step: float = 0.5) -> list[float]:
    """umax초보다 긴 장면을 umin~umax초 조각으로 나눌 지점을 고른다 (동적 계획법, 비용 최소).
    자를 수 있는 곳: 문장 사이 쉼(가장 선호) > 말 없는 곳(step초 간격) > 문장 안 단어 사이(아주 긴 문장만)."""
    if end - start <= umax + EPS:
        return []
    inside = [x for x in lines if x["end"] > start + EPS and x["start"] < end - EPS]
    cands: dict[float, float] = {}

    def add(t: float, cost: float):
        if start + 0.5 <= t <= end - 0.5:
            t = round(t, 3)
            cands[t] = min(cost, cands.get(t, cost))

    for p, q in zip(inside, inside[1:]):
        add((p["end"] + q["start"]) / 2, CUT_COST_SENTENCE)
    t = start + step
    while t < end:
        if not any(x["start"] - 0.2 < t < x["end"] + 0.2 for x in inside):
            add(t, CUT_COST_SILENT)
        t += step
    for x in inside:
        words = x.get("words") or []
        for w1, w2 in zip(words, words[1:]):
            add((w1["end"] + w2["start"]) / 2, CUT_COST_WORD)

    pts = [start] + sorted(cands) + [end]
    best = [0.0] + [float("inf")] * (len(pts) - 1)
    prev = [-1] * len(pts)
    for j in range(1, len(pts)):
        cut_cost = 0.0 if j == len(pts) - 1 else cands[pts[j]]
        for i in range(j - 1, -1, -1):
            d = pts[j] - pts[i]
            if d > MAX_PIECE_SEC and i < j - 1:
                break
            cost = best[i] + _piece_cost(d, umin, umax) + cut_cost
            if cost < best[j] - 1e-9:
                best[j], prev[j] = cost, i
    cuts, j = [], len(pts) - 1
    while prev[j] > 0:
        j = prev[j]
        cuts.append(pts[j])
    return sorted(cuts)


def attach_lines(units: list[dict], lines: list[dict]):
    """대사를 L4 장면에 붙인다 (unit["lines"]). 단어 가운데 시각이 속한 장면으로 보낸다.
    장면 경계가 문장을 자른 드문 경우엔 문장이 두 장면에 나뉘고 조각에 "part": true가 붙는다."""
    for u in units:
        u["lines"] = []
    if not units:
        return
    starts = [u["start"] for u in units]

    def unit_of(t: float) -> dict:
        return units[max(0, min(bisect.bisect_right(starts, t) - 1, len(units) - 1))]

    for line in lines:
        extra = {"fixed": True, "text_raw": line["text_raw"]} if line.get("fixes") else {}
        words = line.get("words") or []
        if not words:
            unit_of((line["start"] + line["end"]) / 2)["lines"].append(
                {"id": line["id"], "text": line["text"], "start": _r(line["start"]), "end": _r(line["end"]), **extra})
            continue
        groups: dict[str, tuple[dict, list]] = {}
        for w in words:
            u = unit_of((w["start"] + w["end"]) / 2)
            groups.setdefault(u["id"], (u, []))[1].append(w)
        whole = len(groups) == 1
        for u, ws in groups.values():
            frag = {"id": line["id"], "text": line["text"] if whole else " ".join(w["word"] for w in ws),
                    "start": _r(ws[0]["start"]), "end": _r(ws[-1]["end"]), **extra}
            if not whole:
                frag["part"] = True
            u["lines"].append(frag)


def build_units(shots: list[dict], lines: list[dict], clips: list[dict],
                umin: float = UNIT_MIN_SEC, umax: float = UNIT_MAX_SEC) -> list[dict]:
    """화면 장면 + 대사 → L4 장면 (전체 타임라인을 빈틈없이 덮는다, 클립을 넘지 않는다).
    1) 경계가 문장 안이면 문장 밖 쉼으로 옮김  2) 2초 미만은 이웃과 합침  3) 7초 넘으면 3~7초로 나눔  4) 대사 붙임"""
    units = []
    for clip in clips:
        lo = clip["offset"]
        pieces = sorted((s for s in shots if s["clip_id"] == clip["id"]), key=lambda s: s["start"])
        clines = [x for x in lines if x["clip_id"] == clip["id"]]
        if not pieces:
            continue
        pieces = merge_short(snap_to_lines(pieces, clines), MIN_SHOT_SEC)
        for p in pieces:
            bounds = [p["start"]] + split_points(p["start"], p["end"], clines, umin, umax) + [p["end"]]
            n = len(bounds) - 1
            for k, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
                unit = {key: p[key] for key in ("desc", "place", "action", "people", "visible_text", "event", "mood")
                        if key in p}
                unit.update({"clip_id": clip["id"], "start": _r(a), "end": _r(b),
                             "clip_start": _r(a - lo), "clip_end": _r(b - lo)})
                if n > 1:
                    unit["part"] = [k, n]
                if p.get("flag"):
                    unit["flag"] = p["flag"]
                units.append(unit)
    for i, u in enumerate(units, 1):
        u["id"] = f"s{i:04d}"
    attach_lines(units, lines)
    return units


def session_breaks(units: list[dict], clips: list[dict], gap_sec: float = SESSION_GAP_SEC) -> dict[int, dict]:
    """클립이 바뀌는 L4 장면 위치 → {"hard": 촬영이 gap_sec 넘게 끊겼는지, "note": AI에게 보여 줄 표시}.
    hard면 무조건 새 L1 세션이 시작된다 (사용자 정의: 같은 공간이어도 시간이 끊기면 새 세션)."""
    first_unit = {}
    for i, u in enumerate(units):
        first_unit.setdefault(u["clip_id"], i)
    out = {}
    for prev, clip in zip(clips, clips[1:]):
        i = first_unit.get(clip["id"])
        if i is None or i == 0:
            continue
        gap = None
        if prev["created"] is not None and clip["created"] is not None:
            gap = clip["created"] - (prev["created"] + prev["duration"])
        hard = gap is not None and gap > gap_sec
        if gap is None:
            note = f"[클립 바뀜: {clip['id']}, 촬영 간격 모름]"
        elif hard:
            note = f"[촬영 끊김: 약 {gap / 60:.0f}분 뒤 다시 촬영]"
        else:
            note = f"[클립 바뀜: {clip['id']}, 약 {max(gap, 0) / 60:.0f}분 뒤]"
        out[i] = {"hard": hard, "note": note}
    return out


# ================================================================ 3-2. 보정 (AI 제안 → 코드 검사)

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ",
         "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]


def _jamo(text: str) -> str:
    """한글 음절을 자모로 푼다 ("맑" → "ㅁㅏㄺ"). 공백·문장부호는 뺀다."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_CHO[code // 588] + _JUNG[(code % 588) // 28] + _JONG[code % 28])
        elif ch.isalnum():
            out.append(ch.lower())
    return "".join(out)


def _is_hangul(text: str) -> bool:
    letters = [ch for ch in text if ch.isalnum()]
    return bool(letters) and all(0xAC00 <= ord(ch) <= 0xD7A3 for ch in letters)


def sound_similarity(a: str, b: str) -> float:
    """두 말에서 바뀐 부분의 발음이 얼마나 비슷한지 (자모 기준, 0~1). 잘못 들은 단어는 발음이 비슷하다.
    같은 앞뒤 글자는 빼고 비교한다 ("두 잔이요"→"세 잔이요"는 "두"↔"세"만 본다 → 0)."""
    a, b = re.sub(r"\W", "", a), re.sub(r"\W", "", b)
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    a, b = a[k:], b[k:]
    k = 0
    while k < min(len(a), len(b)) and a[-1 - k] == b[-1 - k]:
        k += 1
    ja, jb = _jamo(a[:len(a) - k]), _jamo(b[:len(b) - k])
    if not ja or not jb:
        return 0.0
    return difflib.SequenceMatcher(None, ja, jb).ratio()


_EDGE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)


def _core(token: str) -> str:
    return _EDGE.match(token).group(2)


def _replace_in_line(line: dict, wrong: str, right: str) -> bool:
    """line의 단어 중 wrong과 같은 연속 어절을 찾아 right로 바꾼다. 단어 앞뒤 문장부호는 남긴다 ("말라서," → "맑아서,").
    어절 수가 같으면 한 어절씩 바꿔 단어 시각을 그대로 두고 (카라오케용), 다르면 한 단어로 합친다
    (시각은 첫 단어 시작~끝 단어 끝). 단어 시각이 없는 대사는 글자만 바꾼다."""
    words = line["words"]
    if not words:
        if wrong in line["text"]:
            line["text"] = line["text"].replace(wrong, right, 1)
            return True
        return False
    target = [_core(t) for t in wrong.split()]
    cores = [_core(w["word"]) for w in words]
    span = None
    for i in range(len(words) - len(target) + 1):
        if cores[i:i + len(target)] == target:
            span = (i, i + len(target) - 1)
            break
    if span is None:                       # 띄어쓰기만 다르게 적은 경우 ("성수 동" ↔ "성수동")
        flat = "".join(target)
        for i in range(len(words)):
            acc = ""
            for j in range(i, len(words)):
                acc += cores[j]
                if acc == flat:
                    span = (i, j)
                    break
                if len(acc) >= len(flat):
                    break
            if span:
                break
    if span is None:
        return False
    i, j = span
    news = right.split()
    if len(news) == j - i + 1:
        for w, new in zip(words[i:j + 1], news):
            lead, _, trail = _EDGE.match(w["word"]).groups()
            w["word"] = lead + _core(new) + trail
    else:
        lead, trail = _EDGE.match(words[i]["word"]).group(1), _EDGE.match(words[j]["word"]).group(3)
        words[i:j + 1] = [{"word": lead + right + trail, "start": words[i]["start"], "end": words[j]["end"]}]
    line["text"] = " ".join(w["word"] for w in words)
    return True


def apply_corrections(lines: list[dict], corrections: list[dict],
                      min_similarity: float = MIN_SOUND_SIMILARITY) -> tuple[list[dict], list[dict], list[dict]]:
    """AI가 제안한 보정을 검사해서 적용한다. 반환: (보정된 대사 목록 사본, 적용한 것, 거절한 것과 이유)
    받는 조건: 있는 대사 id, 대사에 실제로 있는 어절, 한글끼리면 발음(자모) 유사도 ≥ min_similarity.
    고친 대사에는 text_raw(원문)와 fixes(무엇을 왜 고쳤는지)가 남는다."""
    out = [{**x, "words": [dict(w) for w in x["words"]]} for x in lines]
    by_id = {x["id"]: x for x in out}
    applied, rejected = [], []
    for c in corrections or []:
        if not isinstance(c, dict):
            continue
        rec = {"line": str(c.get("line", "")).strip(), "wrong": _text(c.get("wrong")),
               "right": _text(c.get("right")), "reason": _text(c.get("reason"))}
        line = by_id.get(rec["line"])
        if line is None:
            rejected.append({**rec, "why": "없는 대사 id"})
            continue
        if not rec["wrong"] or not rec["right"] or _jamo(rec["wrong"]) == _jamo(rec["right"]):
            rejected.append({**rec, "why": "바뀌는 내용 없음 (띄어쓰기·문장부호만 다름)"})
            continue
        sim = sound_similarity(rec["wrong"], rec["right"])
        if _is_hangul(rec["wrong"]) and _is_hangul(rec["right"]) and sim < min_similarity:
            rejected.append({**rec, "why": f"발음이 너무 다름 (유사도 {sim:.2f})"})
            continue
        original = line["text"]
        if not _replace_in_line(line, rec["wrong"], rec["right"]):
            rejected.append({**rec, "why": "대사에서 그 어절을 찾지 못함"})
            continue
        line.setdefault("text_raw", original)
        line.setdefault("fixes", []).append(rec)
        applied.append({**rec, "similarity": round(sim, 2)})
    return out, applied, rejected


# ================================================================ 3-3. 맥락 파악 (AI): 보정 + L1~L3 경계

_S = {"type": "string"}
TREE_SCHEMA = {
    "type": "object",
    "required": ["corrections", "sessions"],
    "properties": {
        "corrections": {"type": "array", "items": {
            "type": "object", "required": ["line", "wrong", "right", "reason"],
            "properties": {"line": _S, "wrong": _S, "right": _S, "reason": _S}}},
        "sessions": {"type": "array", "items": {
            "type": "object", "required": ["title", "summary", "flows"],
            "properties": {"title": _S, "summary": _S, "flows": {"type": "array", "items": {
                "type": "object", "required": ["title", "summary", "steps"],
                "properties": {"title": _S, "summary": _S, "steps": {"type": "array", "items": {
                    "type": "object", "required": ["start", "title", "summary"],
                    "properties": {"start": _S, "title": _S, "summary": _S,
                                   "tags": {"type": "array", "items": _S}}}}}}}}}},
    },
}

TREE_PROMPT = """너는 브이로그 편집자다. 아래 [장면 목록]은 영상(여러 클립이면 촬영 순서대로 이어 붙인 것)을 3~7초 장면으로 나눈 것이다.
장면마다 화면 설명(소리 없이 화면만 보고 쓴 것)과, 그 시간에 들린 대사(받아쓰기)가 있다. 아래 두 가지를 순서대로 한다.

[1] 받아쓰기 보정 (corrections)
- 받아쓰기는 발음이 비슷한 다른 말로 잘못 알아들은 단어가 있을 수 있다.
- 앞뒤 대사의 흐름과 그 시간의 화면 설명·화면 글자를 근거로, 잘못 들은 것이 확실한 단어만 고친다.
- 발음이 비슷한 말로만 고친다. 맞춤법, 띄어쓰기, 말투, 문장부호는 고치지 않는다. 내용을 더하거나 빼지 않는다.
- line은 대사 id, wrong은 대사에 적힌 그대로의 어절(띄어쓰기 단위, 여러 어절이면 공백으로 잇는다), right는 고친 말, reason은 근거 한 줄.
- 확실하지 않으면 고치지 않는다. 고칠 것이 없으면 빈 배열.

[2] 4단 구조 (sessions → flows → steps). [1]에서 보정한 대사로 맥락을 읽는다.
- L1 세션(sessions): 한 장소에 머문 한 번의 방문. 같은 장소라도 다른 곳에 다녀왔거나 [촬영 끊김]이 있으면 새 세션이다.
  title은 "카페 (1차 방문)"처럼 장소와 몇 번째 방문인지 쓴다.
- L2 행동 흐름(flows): 세션 안에서 연속으로 이어지는 큰 행동 덩어리. 화면에서 관찰되는 행동만 기준으로 나눈다.
  (예: "주문 흐름", "착석·식사 흐름", "해변 산책 흐름")
- L3 세부 행동(steps): 흐름 안에서 맥락이 바뀌는 단계. 화면과 대사를 함께 본다. (예: "메뉴판 보기", "주문 말하기", "결제")
  보통 장면 2~6개다.
- step은 시작 장면 id(start)만 정한다. 다음 step이 시작하기 전까지가 그 step이다.
  step의 start는 목록 순서대로 커져야 하고, 맨 처음 step은 {first}에서 시작한다. 모든 장면이 어느 step에든 들어간다.
- summary는 그 구간에서 일어나는 일을 한 문장으로 쓴다. step의 summary에는 중요한 대사 내용을 넣는다.
- step의 tags는 편집에 쓸 짧은 꼬리표 0~3개 (예: "리액션", "웃음", "정보", "이동", "풍경", "인사").
{continuation}
[장면 목록]
{units}

JSON으로만 답한다."""


def _fmt_mmss(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_units(units: list[dict], breaks: dict[int, dict], offset: int = 0) -> str:
    """AI에게 보여 줄 장면 목록 (장면 하나에 2~3줄)."""
    rows = []
    for k, u in enumerate(units):
        if offset + k in breaks:
            rows.append(breaks[offset + k]["note"])
        info = [f"장소: {u.get('place') or '-'}", f"행동: {u.get('action') or '-'}"]
        if u.get("people"):
            info.append("인물: " + ", ".join(u["people"]))
        if u.get("visible_text"):
            info.append(f"화면 글자: {u['visible_text']}")
        if u.get("event"):
            info.append(f"사건: {u['event']}")
        rows.append(f"[{u['id']}] {_fmt_mmss(u['start'])} ({u['end'] - u['start']:.1f}초) " + " | ".join(info))
        rows.append(f"  화면: {u.get('desc') or '(화면 정보 없음)'}")
        if u["lines"]:
            rows.append("  대사: " + " / ".join(f"[{x['id']}] {x['text']}" + (" …" if x.get("part") else "")
                                              for x in u["lines"]))
    return "\n".join(rows)


def _chunks(n: int, breaks: dict[int, dict], max_units: int) -> list[tuple[int, int]]:
    """AI에게 나눠 보낼 장면 범위. 촬영 끊김에서 먼저 자르고, 그래도 길면 고르게 자른다."""
    cuts = [0] + sorted(i for i, b in breaks.items() if b["hard"]) + [n]
    out = []
    for lo, hi in zip(cuts, cuts[1:]):
        parts = max(1, -(-(hi - lo) // max_units))
        size = -(-(hi - lo) // parts)
        out += [(a, min(a + size, hi)) for a in range(lo, hi, size)]
    merged = []   # 촬영 끊김으로 생긴 작은 범위는 앞 범위에 붙인다 (호출 수 줄이기)
    for lo, hi in out:
        if merged and (hi - merged[-1][0]) <= max_units:
            merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def _gemini_ask(prompt: str, schema: dict, api_key: str | None, model: str, fallback: str | None,
                cache_dir: Path | None = None, refresh: bool = False, retries: int = 2) -> dict:
    """Gemini에 JSON(스키마 고정)을 요청한다. 혼잡(503 등)·깨진 JSON은 재시도, 한도 초과(429)는 fallback 모델로.
    cache_dir가 있으면 같은 지시문의 응답을 저장해 두고 다시 쓴다 (CLI에서 코드만 고쳐 다시 돌릴 때)."""
    from google.genai import types
    from shot_analyzer import make_client

    key = hashlib.sha1(f"{model}\n{prompt}".encode("utf-8")).hexdigest()[:16]
    cache = cache_dir / f"tree_{key}.json" if cache_dir else None
    if cache and cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))

    client = make_client(api_key, timeout_ms=300_000)
    config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=32768,
                                         response_mime_type="application/json", response_json_schema=schema)
    last = None
    for name in [model] + ([fallback] if fallback and fallback != model else []):
        for attempt in range(retries + 1):
            try:
                resp = client.models.generate_content(model=name, contents=prompt, config=config)
                data = _parse_json_object(getattr(resp, "text", "") or "")
            except ValueError as e:        # JSON이 깨짐 (응답이 잘림 등) → 다시
                last = e
                continue
            except Exception as e:
                last = e
                text = str(e)
                if "429" in text or "RESOURCE_EXHAUSTED" in text:
                    break
                if not any(c in text for c in ("503", "UNAVAILABLE", "500", "INTERNAL", "504", "DEADLINE")):
                    raise
                time.sleep(2 * (attempt + 1))
                continue
            if cache:
                cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
    raise RuntimeError(f"Gemini 호출 실패: {last}")


def _parse_json_object(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON 객체를 찾지 못함")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("응답이 JSON 객체가 아님")
    return data


def parse_structure(resp: dict, units: list[dict], lo: int, hi: int) -> tuple[dict | None, list[str]]:
    """AI 응답(sessions→flows→steps, step은 시작 장면 id만) → 경계 목록 {"sessions", "flows", "steps"}.
    각 항목은 {"start": 장면 순번, "title", "summary"(, "tags")}. 검사:
    - 없는 id, 범위 밖 id, 앞 step보다 앞서는 id는 버린다 (그 장면들은 앞 step에 들어간다)
    - 첫 step은 무조건 범위의 첫 장면부터 (빠진 앞부분 방지)
    - 흐름·세션은 자기 첫 step이 시작하는 곳에서 시작한다 → 세션 경계 ⊆ 흐름 경계 ⊆ step 경계"""
    index = {u["id"]: i for i, u in enumerate(units)}
    out = {"sessions": [], "flows": [], "steps": []}
    warnings, last = [], lo - 1
    for s in resp.get("sessions") or []:
        s_open = False
        for f in (s.get("flows") or []) if isinstance(s, dict) else []:
            f_open = False
            for st in (f.get("steps") or []) if isinstance(f, dict) else []:
                if not isinstance(st, dict):
                    continue
                sid = str(st.get("start", "")).strip()
                i = index.get(sid)
                if i is None or not lo <= i < hi:
                    warnings.append(f"없는 장면 id {sid!r}는 버림")
                    continue
                if i <= last:
                    warnings.append(f"순서가 어긋난 시작 장면 {sid}는 버림")
                    continue
                if not out["steps"]:
                    i = lo
                out["steps"].append({"start": i, "title": _text(st.get("title")), "summary": _text(st.get("summary")),
                                     "tags": [_text(t) for t in st.get("tags") or [] if _text(t)][:3]})
                if not f_open:
                    out["flows"].append({"start": i, "title": _text(f.get("title")), "summary": _text(f.get("summary"))})
                    f_open = True
                if not s_open:
                    out["sessions"].append({"start": i, "title": _text(s.get("title")), "summary": _text(s.get("summary"))})
                    s_open = True
                last = i
    if not out["steps"]:
        return None, warnings + ["쓸 수 있는 step이 하나도 없음"]
    return out, warnings


def ask_tree(units: list[dict], breaks: dict[int, dict], ask=None, max_units: int = MAX_UNITS_PER_CALL,
             log=print) -> dict:
    """장면 목록을 AI에게 보내 보정 + L1~L3 경계를 받는다 (긴 영상은 나눠 보낸다).
    ask(prompt, schema) → dict 를 넘기면 그걸로 부른다 (테스트용). 반환:
    {"corrections": [...], "parts": [(lo, hi, 경계 목록 또는 None)], "warnings": [...]}"""
    corrections, parts, warnings = [], [], []
    prev_titles = None
    chunks = _chunks(len(units), breaks, max_units)
    for k, (lo, hi) in enumerate(chunks, 1):
        log(f"🧠 AI 보정·구조화 중 (장면 {units[lo]['id']}~{units[hi - 1]['id']}"
            + (f", {k}/{len(chunks)}번째" if len(chunks) > 1 else "") + ")")
        continuation = ""
        if prev_titles:
            continuation = (f"\n[앞부분 이어서] 이 목록은 앞 장면들에 이어진다. 앞부분은 세션 \"{prev_titles[0]}\", "
                            f"흐름 \"{prev_titles[1]}\"에서 끝났다. 같은 세션·흐름이 이어지면 같은 제목을 그대로 쓴다.\n")
        prompt = TREE_PROMPT.format(first=units[lo]["id"], continuation=continuation,
                                    units=format_units(units[lo:hi], breaks, lo))
        structure, why = None, []
        for attempt in range(2):
            try:
                resp = ask(prompt if attempt == 0 else prompt + _feedback(why), TREE_SCHEMA)
            except Exception as e:
                why = [f"호출 실패: {e}"]
                break
            structure, why = parse_structure(resp, units, lo, hi)
            if structure is not None:
                corrections += [c for c in resp.get("corrections") or [] if isinstance(c, dict)]
                break
        warnings += [f"장면 {units[lo]['id']}~{units[hi - 1]['id']}: {w}" for w in why]
        parts.append((lo, hi, structure))
        if structure:
            prev_titles = (structure["sessions"][-1]["title"], structure["flows"][-1]["title"])
    return {"corrections": corrections, "parts": parts, "warnings": warnings}


def _feedback(problems: list[str]) -> str:
    return ("\n\n[이전 응답의 문제]\n" + "\n".join(f"- {p}" for p in problems[:10])
            + "\n위 문제를 고쳐 다시 JSON으로만 답한다. step의 start는 목록에 있는 장면 id여야 하고 순서대로 커져야 한다.")


# ================================================================ 4. 트리 구성

def _smooth(labels: list[str]) -> list[str]:
    """앞뒤가 같은 라벨인데 한 장면만 다르면 앞뒤 라벨로 (장면 분석의 흔들림 제거)."""
    out = list(labels)
    for i in range(1, len(out) - 1):
        if out[i] != out[i - 1] and out[i - 1] == out[i + 1]:
            out[i] = out[i - 1]
    return out


def fallback_structure(units: list[dict], breaks: dict[int, dict], lo: int = 0, hi: int | None = None,
                       visits: Counter | None = None) -> dict:
    """AI 없이 규칙으로 묶는다 (units[lo:hi] 범위).
    세션 = 장소 라벨이 바뀌거나 촬영이 끊긴 곳, 흐름 = 세션 전체, 세부 행동 = 행동 라벨이 바뀌는 곳
    (영상분석이 없어 행동 라벨이 없으면 장면 4개씩). visits는 범위를 넘어 'n차 방문'을 세는 데 쓴다."""
    hi = len(units) if hi is None else hi
    visits = Counter() if visits is None else visits
    # 장소는 첫 낱말로 묶는다 ("해변 계단", "해변 모래사장" → 해변). 장면 분석이 같은 곳을 조금씩 다르게 부르기 때문
    places = _smooth([_text(u.get("place")).split(" ")[0] for u in units[lo:hi]])
    actions = _smooth([_text(u.get("action")) for u in units[lo:hi]])
    starts = [k for k in range(hi - lo)
              if k == 0 or breaks.get(lo + k, {}).get("hard") or places[k] != places[k - 1]]
    out = {"sessions": [], "flows": [], "steps": []}
    for a, b in zip(starts, starts[1:] + [hi - lo]):
        visits[places[a]] += 1
        top = Counter(x for x in actions[a:b] if x).most_common(1)
        out["sessions"].append({"start": lo + a, "title": f"{places[a] or '장소 미상'} ({visits[places[a]]}차 방문)",
                                "summary": ""})
        out["flows"].append({"start": lo + a, "title": f"{top[0][0]} 흐름" if top else "전체 흐름", "summary": ""})
        run = 0
        for k in range(a, b):
            changed = actions[k] != actions[k - 1] if (actions[k] or actions[k - 1]) else run >= 4
            if k == a or changed:
                u = units[lo + k]
                title = actions[k] or _short(u["lines"][0]["text"] if u["lines"] else (u.get("desc") or "구간"), 20)
                out["steps"].append({"start": lo + k, "title": title, "summary": "", "tags": []})
                run = 0
            run += 1
    return out


def combine_parts(units: list[dict], parts: list[tuple], breaks: dict[int, dict]) -> tuple[dict, list[str]]:
    """나눠 받은 경계 목록을 하나로 잇는다. 실패한 범위(None)는 규칙으로 채운다.
    이음매에서 앞뒤 세션 제목이 같으면 같은 세션이 이어지는 것으로 보고 합친다 (흐름도 제목이 같으면 합침).
    촬영 끊김에는 세션 경계를 강제로 넣는다."""
    merged = {"sessions": [], "flows": [], "steps": []}
    notes, visits = [], Counter()
    for lo, hi, structure in parts:
        if structure is None:
            structure = fallback_structure(units, breaks, lo, hi, visits)
            notes.append(f"{units[lo]['id']}~{units[hi - 1]['id']}")
        sessions, flows, steps = ([dict(x) for x in structure[k]] for k in ("sessions", "flows", "steps"))
        hard = breaks.get(lo, {}).get("hard")
        if merged["sessions"] and not hard and sessions and sessions[0]["start"] == lo \
                and sessions[0]["title"] == merged["sessions"][-1]["title"]:
            sessions = sessions[1:]
            if flows and flows[0]["start"] == lo and flows[0]["title"] == merged["flows"][-1]["title"]:
                flows = flows[1:]
        merged["sessions"] += sessions
        merged["flows"] += flows
        merged["steps"] += steps
    for i, b in sorted(breaks.items()):
        if b["hard"]:
            for level in ("steps", "flows", "sessions"):
                _ensure_start(merged[level], i, " (이어서)")
    return ensure_nested(merged), notes


def _ensure_start(items: list[dict], i: int, suffix: str):
    if any(x["start"] == i for x in items):
        return
    k = max((n for n, x in enumerate(items) if x["start"] < i), default=None)
    base = items[k] if k is not None else {"title": "", "summary": ""}
    new = {**base, "start": i, "title": (base.get("title") or "") + suffix}
    items.insert(0 if k is None else k + 1, new)


def ensure_nested(structure: dict) -> dict:
    """세션 경계 ⊆ 흐름 경계 ⊆ step 경계가 되게 맞추고, 각 목록을 시작 순으로 정렬한다.
    (흐름이 세션 첫 장면에서 시작하지 않으면 그 세션의 첫 흐름을 만든다)"""
    out = {k: sorted((dict(x) for x in structure[k]), key=lambda x: x["start"]) for k in ("sessions", "flows", "steps")}
    for upper, lower in (("sessions", "flows"), ("flows", "steps")):
        starts = {x["start"] for x in out[lower]}
        for x in out[upper]:
            if x["start"] not in starts:
                out[lower].append({"start": x["start"], "title": x["title"], "summary": x.get("summary", ""),
                                   **({"tags": []} if lower == "steps" else {})})
        out[lower].sort(key=lambda x: x["start"])
    for k in out:   # 같은 시작이 둘이면 앞의 것만
        seen, kept = set(), []
        for x in out[k]:
            if x["start"] not in seen:
                seen.add(x["start"])
                kept.append(x)
        out[k] = kept
    return out


def _unit_node(u: dict) -> dict:
    title = u.get("desc") or (u["lines"][0]["text"] if u["lines"] else "") or "(화면 설명 없음)"
    if u.get("part"):
        title = f"{_short(title, 40)} ({u['part'][0]}/{u['part'][1]})"
    tags = ["대사" if u["lines"] else "말 없음"]
    if any(x.get("fixed") for x in u["lines"]):
        tags.append("AI 보정")
    if u.get("flag") in ("error", "empty", "missing"):
        tags.append("영상분석 없음")
    node = {"id": u["id"], "level": 4, "title": _short(title, 60), "start": u["start"], "end": u["end"],
            "summary": u.get("desc", ""), "tags": tags, "children": [],
            "clip_id": u["clip_id"], "clip_start": u["clip_start"], "clip_end": u["clip_end"],
            "lines": u["lines"]}
    for key in ("place", "action", "people", "visible_text", "event", "mood"):
        if u.get(key):
            node[key] = u[key]
    return node


def _people(units: list[dict]) -> list[str]:
    seen = []
    for u in units:
        for p in u.get("people") or []:
            if p not in seen:
                seen.append(p)
    return seen


def assemble_tree(units: list[dict], structure: dict) -> list[dict]:
    """경계 목록 + L4 장면 → 4단 트리. id: L1 p01, L2 p01-f01, L3 p01-f01-a01, L4 s0001."""
    structure = ensure_nested(structure)
    n = len(units)

    def spans(items: list[dict], lo: int, hi: int) -> list[tuple[dict, int, int]]:
        inside = [x for x in items if lo <= x["start"] < hi]
        return [(x, x["start"], inside[k + 1]["start"] if k + 1 < len(inside) else hi) for k, x in enumerate(inside)]

    tree = []
    for si, (s, s_lo, s_hi) in enumerate(spans(structure["sessions"], 0, n), 1):
        pid = f"p{si:02d}"
        flows = []
        for fi, (f, f_lo, f_hi) in enumerate(spans(structure["flows"], s_lo, s_hi), 1):
            fid = f"{pid}-f{fi:02d}"
            steps = []
            for ai, (a, a_lo, a_hi) in enumerate(spans(structure["steps"], f_lo, f_hi), 1):
                members = units[a_lo:a_hi]
                tags = list(a.get("tags") or [])
                if not any(u["lines"] for u in members):
                    tags.append("말 없음")
                tags += [f"인물:{p}" for p in _people(members)[:3]]
                summary = a.get("summary") or " / ".join(
                    _short(u["lines"][0]["text"] if u["lines"] else u.get("desc", ""), 30) for u in members[:3])
                steps.append({"id": f"{fid}-a{ai:02d}", "level": 3, "title": a["title"] or "세부 행동",
                              "start": members[0]["start"], "end": members[-1]["end"], "summary": summary,
                              "tags": tags, "people": _people(members),
                              "children": [_unit_node(u) for u in members]})
            flows.append({"id": fid, "level": 2, "title": f["title"] or "행동 흐름", "start": steps[0]["start"],
                          "end": steps[-1]["end"], "summary": f.get("summary", ""), "tags": [], "children": steps})
        members = units[s_lo:s_hi]
        places = Counter(u.get("place") for u in members if u.get("place")).most_common(1)
        tree.append({"id": pid, "level": 1, "title": s["title"] or (places[0][0] if places else "장소"),
                     "start": flows[0]["start"], "end": flows[-1]["end"], "summary": s.get("summary", ""), "tags": [],
                     "place": places[0][0] if places else "", "people": _people(members),
                     "clip_ids": list(dict.fromkeys(u["clip_id"] for u in members)), "children": flows})
    return tree


def validate_tree(tree: list[dict]) -> list[str]:
    """트리 규칙 검사. 문제 목록(빈 리스트면 통과)."""
    problems, ids = [], []

    def walk(node: dict, depth: int):
        ids.append(node["id"])
        if node["level"] != depth:
            problems.append(f"{node['id']}: level {node['level']} ≠ 깊이 {depth}")
        if node["end"] - node["start"] <= 0:
            problems.append(f"{node['id']}: 길이 0 이하")
        kids = node["children"]
        if depth < 4:
            if not kids:
                problems.append(f"{node['id']}: L4까지 내려가지 않음")
                return
            if abs(kids[0]["start"] - node["start"]) > 1e-6 or abs(kids[-1]["end"] - node["end"]) > 1e-6:
                problems.append(f"{node['id']}: 자식이 부모 구간 끝까지 덮지 않음")
            for a, b in zip(kids, kids[1:]):
                if abs(a["end"] - b["start"]) > 1e-6:
                    problems.append(f"{a['id']}→{b['id']}: 빈틈 또는 겹침")
        elif kids:
            problems.append(f"{node['id']}: L4 아래에 자식이 있음")
        for k in kids:
            walk(k, depth + 1)

    for root in tree:
        walk(root, 1)
    for a, b in zip(tree, tree[1:]):
        if abs(a["end"] - b["start"]) > 1e-6:
            problems.append(f"{a['id']}→{b['id']}: 세션 사이 빈틈 또는 겹침")
    if len(ids) != len(set(ids)):
        problems.append("id 중복")
    return problems


# ================================================================ 전체: 2 → 3 → 4

def build_scene_tree(clips: list[dict], shots: list[dict], segments: list[dict], *, use_ai: bool = True,
                     api_key: str | None = None, model: str = TREE_MODEL, fallback_model: str | None = TREE_FALLBACK_MODEL,
                     ask=None, cache_dir: Path | None = None, refresh: bool = False, log=print) -> dict:
    """받아쓰기 + 장면 분석 → 4단 트리 (앱 흐름 2~4단계). AI(보정·구조화)가 실패해도 규칙으로 트리를 만든다.
    clips: [{"id", "duration", "offset", "created"?}], shots: shots.json의 shots 또는 앱의 장면 목록,
    segments: transcript.json의 segments 또는 앱의 segments. ask(prompt, schema) → dict 를 넘기면 Gemini 대신 쓴다.
    반환: {"tree", "units", "lines"(보정된 대사), "corrections", "rejected", "source": "ai"|"rules"|"mixed",
           "notes"(화면에 보여 줄 안내), "warnings"(AI 응답·트리 검사에서 걸린 것)}"""
    clips = normalize_clips(clips)
    lines = normalize_lines(segments, clips)
    units = build_units(normalize_shots(shots, clips), lines, clips)
    breaks = session_breaks(units, clips)
    log(f"🌳 4단 트리: L4 장면 {len(units)}개, 대사 {len(lines)}개")

    notes, warnings, applied, rejected = [], [], [], []
    parts = [(0, len(units), None)] if units else []
    if use_ai and units:
        if ask is None:
            def ask(prompt, schema):
                return _gemini_ask(prompt, schema, api_key, model, fallback_model, cache_dir, refresh)
        result = ask_tree(units, breaks, ask, log=log)
        lines, applied, rejected = apply_corrections(lines, result["corrections"])
        attach_lines(units, lines)       # 보정한 대사로 다시 붙인다
        parts, warnings = result["parts"], result["warnings"]
        if applied or rejected:
            log(f"✏️ 대사 보정 {len(applied)}건" + (f" (받지 않음 {len(rejected)}건)" if rejected else ""))
    structure, failed = combine_parts(units, parts, breaks)
    ok_parts = len(parts) - len(failed)
    source = "rules" if not use_ai or ok_parts == 0 else ("ai" if not failed else "mixed")
    if use_ai and units and ok_parts == 0:
        notes.append("AI 보정·구조화에 실패해 규칙으로 묶었습니다" + (f" ({warnings[-1][:200]})" if warnings else ""))
    elif use_ai and failed:
        notes.append(f"AI 구조화가 일부 실패해 규칙으로 묶었습니다 (장면 {', '.join(failed)})")
    tree = assemble_tree(units, structure) if units else []
    problems = validate_tree(tree)
    log(f"✅ 4단 트리 완료 ({source}): 세션 {len(tree)}개, "
        f"세부 행동 {sum(len(f['children']) for s in tree for f in s['children'])}개"
        + (f", 검사 문제 {len(problems)}건" if problems else ""))
    return {"tree": tree, "units": units, "lines": lines, "corrections": applied, "rejected": rejected,
            "source": source, "notes": notes, "warnings": warnings + problems}


def lines_to_segments(lines: list[dict], offset: float = 0.0) -> list[dict]:
    """보정된 대사 → 앱·미디어엔진 segments 형식 [{"start", "end", "text", "words"}] (offset만큼 당김)."""
    return [{"start": _r(x["start"] - offset), "end": _r(x["end"] - offset), "text": x["text"],
             "words": [{"word": w["word"], "start": _r(w["start"] - offset), "end": _r(w["end"] - offset)}
                       for w in x["words"]]}
            for x in lines]


def mark_cut_suggestions(tree: list[dict], segments: list[dict]):
    """컷 판단(main.py step3) 결과를 L4 장면에 표시한다: 장면 안 문장이 모두 cut이면 "AI 컷 제안" 꼬리표."""
    for s in tree:
        for f in s["children"]:
            for a in f["children"]:
                for u in a["children"]:
                    inside = [x for x in segments if u["start"] <= (x["start"] + x["end"]) / 2 < u["end"]]
                    if inside and all(x.get("cut") for x in inside) and "AI 컷 제안" not in u["tags"]:
                        u["tags"].append("AI 컷 제안")


def scene_context(tree: list[dict]) -> list[dict]:
    """컷 판단(main.py step3)에 넘길 화면 문맥: L3 세부 행동마다 한 줄."""
    return [{"start": a["start"], "end": a["end"], "place": s["title"], "activity": f["title"],
             "event": a["title"], "summary": a["summary"]}
            for s in tree for f in s["children"] for a in f["children"]]


# ================================================================ 확인용 표·CLI

def write_markdown(result: dict, path: Path):
    lines = [f"# 4단 트리 ({result['source']})", ""]
    for s in result["tree"]:
        lines.append(f"## {s['title']}  ({_fmt_mmss(s['start'])}~{_fmt_mmss(s['end'])}, {s['end'] - s['start']:.0f}초)")
        if s["summary"]:
            lines.append(f"{s['summary']}")
        for f in s["children"]:
            lines += ["", f"### {f['title']}  ({f['end'] - f['start']:.0f}초)" + (f" — {f['summary']}" if f["summary"] else "")]
            for a in f["children"]:
                tags = f"  `{', '.join(a['tags'])}`" if a["tags"] else ""
                lines.append(f"- **{a['title']}** ({a['end'] - a['start']:.1f}초) {a['summary']}{tags}")
                for u in a["children"]:
                    said = " / ".join(f"\"{x['text']}\"" for x in u["lines"])
                    lines.append(f"  - `{u['id']}` {_fmt_mmss(u['start'])} {u['end'] - u['start']:.1f}초 · {u['title']}"
                                 + (f" — {said}" if said else ""))
        lines.append("")
    if result["corrections"]:
        lines += ["## 대사 보정", "", "| 대사 | 원래 | 고침 | 발음 유사도 | 근거 |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {c['line']} | {c['wrong']} | {c['right']} | {c['similarity']} | {c['reason']} |"
                  for c in result["corrections"]]
    if result["rejected"]:
        lines += ["", "## 받지 않은 보정", "", "| 대사 | 원래 | 제안 | 이유 |", "| --- | --- | --- | --- |"]
        lines += [f"| {c['line']} | {c['wrong']} | {c['right']} | {c['why']} |" for c in result["rejected"]]
    if result["notes"] or result["warnings"]:
        lines += ["", "## 안내·경고", ""] + [f"- {x}" for x in result["notes"] + result["warnings"]]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):     # 진행 로그의 이모지가 한글(cp949) 콘솔에서 오류 나지 않게 (app.py와 같음)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="VIBE CUT 4단 트리 (받아쓰기 + L4 장면 → 장소·세션/행동 흐름/세부 행동/장면)")
    ap.add_argument("--transcript", required=True, help="transcriber.py 결과 (transcript.json)")
    ap.add_argument("--shots", default=None, help="shot_analyzer.py 결과 (shots.json). 없으면 대사만으로")
    ap.add_argument("--out", default="tree.json")
    ap.add_argument("--model", default=TREE_MODEL)
    ap.add_argument("--no-ai", action="store_true", help="AI 보정·구조화 없이 규칙으로만")
    ap.add_argument("--cache", default=".vibecut_cache", help="AI 응답 캐시 폴더")
    ap.add_argument("--refresh", action="store_true", help="AI 응답 캐시를 무시")
    args = ap.parse_args()

    transcript = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    shots_doc = json.loads(Path(args.shots).read_text(encoding="utf-8")) if args.shots else {"clips": [], "shots": []}
    clips = shots_doc.get("clips") or transcript["clips"]
    t_clips = {c["id"]: (round(c["duration"], 1), round(c["offset"], 1)) for c in transcript["clips"]}
    s_clips = {c["id"]: (round(c["duration"], 1), round(c["offset"], 1)) for c in clips}
    if args.shots and t_clips != s_clips:
        sys.exit(f"transcript와 shots의 클립 표가 다릅니다 (같은 폴더·같은 정렬로 만들었는지 확인):\n{t_clips}\n{s_clips}")

    cache = Path(args.cache)
    cache.mkdir(exist_ok=True)
    t0 = time.time()
    result = build_scene_tree(clips, shots_doc.get("shots", []), transcript["segments"], use_ai=not args.no_ai,
                              model=args.model, cache_dir=cache, refresh=args.refresh)
    doc = {
        "meta": {"source": result["source"], "model": None if args.no_ai else args.model,
                 "elapsed_sec": round(time.time() - t0, 1), "created_at": datetime.now().isoformat(timespec="seconds"),
                 "levels": list(LEVEL_NAMES)},
        "clips": clips,
        "tree": result["tree"],
        "corrections": result["corrections"],
        "rejected": result["rejected"],
        "notes": result["notes"],
        "warnings": result["warnings"],
    }
    out = Path(args.out)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result, out.with_suffix(".md"))
    print(f"\n완료: {out}, {out.with_suffix('.md')} ({doc['meta']['elapsed_sec']}초, 경고 {len(result['warnings'])}건)")


if __name__ == "__main__":
    main()
