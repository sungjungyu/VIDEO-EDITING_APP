"""화면 장면(shot) 정리 도우미.

feature/tree-l4-length의 shot_analyzer.py·scene_analyzer.py에서 트리에 필요한 것만 옮겼다 (로직은 그대로).
장면 = {"start", "end", "desc", "place", "action", "people"[목록], "visible_text", "event", "mood", "flag"?}
"""

from __future__ import annotations

import re

MIN_SHOT_SEC = 2.0     # 이보다 짧은 장면은 이웃 장면에 합친다


def to_seconds(v) -> float:
    """숫자, "MM:SS", "HH:MM:SS"를 모두 초로 바꾼다."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    parts = [float(p) for p in s.split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _labels(value) -> list[str]:
    """["a", "b"] 또는 "a, b" → 중복 없는 라벨 목록."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    out = []
    for item in items:
        label = _text(item)
        if label and label not in out:
            out.append(label)
    return out


def empty_shot(start: float, end: float, desc: str, flag: str) -> dict:
    return {"start": start, "end": end, "desc": desc, "place": "", "action": "", "people": [],
            "visible_text": "", "event": "", "mood": "", "flag": flag}


def merge_shot(a: dict, b: dict) -> dict:
    """이웃한 두 장면을 하나로. 설명·장소·행동은 더 긴 쪽을 따르고, 인물·글자·사건은 합친다."""
    main = a if a["end"] - a["start"] >= b["end"] - b["start"] else b
    merged = {**main, "start": a["start"], "end": b["end"],
              "people": _labels(a.get("people", []) + b.get("people", []))}
    for key in ("visible_text", "event"):
        parts = [x for x in (a.get(key, ""), b.get(key, "")) if x]
        merged[key] = "; ".join(dict.fromkeys(parts))
    return merged


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("desc", "place", "action"))


def clean_shots(raw: list, duration: float, min_sec: float = MIN_SHOT_SEC) -> list[dict]:
    """LLM 출력을 믿지 않고 코드로 정리한다 (조각 안 초 기준).
    - 범위 자르기, 시작 순 정렬, 같은 시작 중복 제거
    - 빈틈은 가운데에서, 겹침은 뒤 장면 시작에서 잘라 0~duration을 빈틈없이 덮게 만든다
    - min_sec보다 짧은 장면, 설명·장소·행동이 똑같은 이웃 장면은 합친다"""
    shots = []
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        try:
            st, en = to_seconds(s.get("start", 0)), to_seconds(s.get("end", 0))
        except (ValueError, TypeError):
            continue
        st, en = max(0.0, min(st, duration)), max(0.0, min(en, duration))
        if en <= st:
            continue
        shot = {"start": st, "end": en, "desc": _text(s.get("desc")), "place": _text(s.get("place")),
                "action": _text(s.get("action")), "people": _labels(s.get("people")),
                "visible_text": _text(s.get("visible_text")), "event": _text(s.get("event")),
                "mood": _text(s.get("mood"))}
        if s.get("flag"):
            shot["flag"] = str(s["flag"])
        shots.append(shot)
    if not shots:
        return [empty_shot(0.0, duration, "(장면 인식 실패)", "empty")]

    shots.sort(key=lambda x: (x["start"], -x["end"]))
    unique = [shots[0]]
    for cur in shots[1:]:
        if cur["start"] > unique[-1]["start"] + 0.05:
            unique.append(cur)
    # 경계: 빈틈이면 가운데, 겹치면 뒤 장면 시작. 항상 앞 장면 시작보다 뒤라서 순서가 유지된다.
    for prev, cur in zip(unique, unique[1:]):
        boundary = (prev["end"] + cur["start"]) / 2 if prev["end"] <= cur["start"] else cur["start"]
        prev["end"] = cur["start"] = boundary
    unique[0]["start"], unique[-1]["end"] = 0.0, duration

    merged = [unique[0]]
    for cur in unique[1:]:
        if _same(merged[-1], cur):
            merged[-1] = merge_shot(merged[-1], cur)
        else:
            merged.append(cur)
    return merge_short(merged, min_sec)


def merge_short(shots: list[dict], min_sec: float) -> list[dict]:
    """min_sec보다 짧은 장면을 앞뒤 중 더 짧은 이웃과 합친다 (가장 짧은 것부터)."""
    shots = list(shots)
    while len(shots) > 1:
        lengths = [s["end"] - s["start"] for s in shots]
        i = min(range(len(shots)), key=lengths.__getitem__)
        if lengths[i] >= min_sec - 1e-6:
            break
        if i == 0:
            j = 1
        elif i == len(shots) - 1:
            j = i - 1
        else:
            j = i - 1 if lengths[i - 1] <= lengths[i + 1] else i + 1
        lo, hi = min(i, j), max(i, j)
        shots[lo:hi + 1] = [merge_shot(shots[lo], shots[hi])]
    return shots



