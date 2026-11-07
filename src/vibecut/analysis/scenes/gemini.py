"""Gemini 영상 이해로 장면 목록 만들기 (조경우).

클립을 저해상도·무음으로 압축해 Gemini에 보내 "장소·활동이 바뀔 때마다 한 항목"인 장면 목록 JSON을 받고,
LLM 출력을 믿지 않고 코드로 정리한다 (clean_scenes). 이전 클립 요약·등장인물 라벨을 다음 클립에 넘겨
클립이 끊겨도 같은 장소·같은 사람으로 판단하게 한다.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ...ai.client import GeminiClient
from ...media.convert import make_lowres


@dataclass(frozen=True)
class SceneOptions:
    model: str
    mode: str = "static"           # 영상 처리 방식 (static | agentic)
    resolution: str = "low"        # Gemini가 영상을 볼 해상도 (low | medium | high | ultra_high)
    height: int = 360              # 전처리 세로 해상도
    min_sec: float = 10.0          # 이보다 짧은 장면은 합친다


# response_format에 넘길 JSON 스키마 (Structured outputs). AI 사용량·결과가 이 모양에 달려 있다.
# response_format에 넘길 JSON 스키마 (Structured outputs)
SCENE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["start", "end", "place", "activity", "people", "background_people", "event", "summary"],
        "properties": {
            "start":             {"type": "number"},
            "end":               {"type": "number"},
            "place":             {"type": "string"},
            "activity":          {"type": "string"},
            "people":            {"type": "string"},
            "background_people": {"type": "boolean"},
            "event":             {"type": "string"},
            "mood":              {"type": "string"},
            "summary":           {"type": "string"},
        },
    },
}

PROMPT_TEMPLATE = """당신은 브이로그 영상의 장면 기록자다. 소리는 없고 화면만 본다.
이 클립의 길이는 {duration:.1f}초다.

[장면을 나누는 기준]
- 장소가 바뀌거나 주된 활동이 바뀔 때 새 장면으로 나눈다.
- 같은 장소·활동에서 카메라 방향(셀카↔풍경)이나 화각만 바뀐 것은 같은 장면이다.
- {min_sec}초 미만의 짧은 변화는 앞 장면에 합친다.

[출력 규칙]
- 클립의 0초부터 {duration:.1f}초까지 빈틈없이, 겹치지 않게 나눈다.
- start, end는 이 클립 시작 기준 초 단위 숫자다.
- place, activity는 짧은 한국어 명사구로 쓴다. (예: "카페 실내", "음료 주문")
- people은 화면에 직접 등장하는 인물만 옷차림·외형 라벨로 쓴다. (예: "빨간 후드 촬영자", "남색 패딩") 아무도 없으면 빈 문자열. 이름 추정이나 얼굴로 신원 판단은 절대 금지.
- 이전 클립 인물과 같은 사람으로 보이면 반드시 같은 라벨을 재사용한다.
- background_people은 배경에 행인·군중이 보이면 true, 없으면 false.
- event는 눈에 띄는 화면 사건이 있으면 쓰고, 없으면 빈 문자열로 둔다.
- mood는 장면 분위기를 한 단어로 쓴다. (예: 차분, 활기, 긴장, 설렘, 무거움) 판단하기 어려우면 빈 문자열로 둔다.
- summary는 그 장면을 한 문장으로 요약한다.

[이전 클립 등장인물 라벨]
{known_people}

[이전 클립 요약]
{prev_summary}

JSON 배열만 출력한다. 다른 설명은 쓰지 않는다.
[{{"start": 0, "end": 0, "place": "", "activity": "", "people": "", "background_people": false, "event": "", "mood": "", "summary": ""}}]
"""  # noqa: E501 — 모델에 보내는 문장이라 줄을 나누지 않는다


def scene_prompt(duration: float, min_sec: float, prev_summary: str, known_people: str) -> str:
    return PROMPT_TEMPLATE.format(duration=duration, min_sec=min_sec, prev_summary=prev_summary or "(첫 클립)",
                                  known_people=known_people or "(없음)")


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


def clean_scenes(raw: list, duration: float, min_sec: float) -> list:
    """LLM 출력을 믿지 않고 코드로 정리: 범위 자르기, 정렬, 겹침·빈틈 처리, 짧은 장면·같은 장면 합치기."""
    scenes = []
    for s in raw:
        try:
            st, en = to_seconds(s.get("start", 0)), to_seconds(s.get("end", 0))
        except (ValueError, TypeError):
            continue
        st, en = max(0.0, min(st, duration)), max(0.0, min(en, duration))
        if en <= st:
            continue
        scenes.append({
            "start": st, "end": en,
            "place": str(s.get("place", "")).strip(),
            "activity": str(s.get("activity", "")).strip(),
            "people": str(s.get("people", "")).strip(),
            "background_people": bool(s.get("background_people", False)),
            "event": str(s.get("event", "")).strip(),
            "mood": str(s.get("mood", "")).strip(),
            "summary": str(s.get("summary", "")).strip(),
        })
    if not scenes:
        return [{"start": 0.0, "end": duration, "place": "", "activity": "",
                 "people": "", "background_people": False, "event": "", "mood": "",
                 "summary": "(장면 인식 실패)", "flag": "empty"}]

    scenes.sort(key=lambda x: x["start"])
    scenes[0]["start"] = 0.0
    for prev, cur in zip(scenes, scenes[1:]):
        boundary = (prev["end"] + cur["start"]) / 2 if prev["end"] != cur["start"] else cur["start"]
        prev["end"] = cur["start"] = boundary
    scenes[-1]["end"] = duration

    merged = [scenes[0]]
    for cur in scenes[1:]:
        last = merged[-1]
        same = (cur["place"], cur["activity"]) == (last["place"], last["activity"])
        if same or (cur["end"] - cur["start"]) < min_sec:
            last["end"] = cur["end"]
            if cur["event"] and cur["event"] not in last["event"]:
                last["event"] = (last["event"] + "; " + cur["event"]).strip("; ")
        else:
            merged.append(cur)
    return merged


def describe_scenes(client: GeminiClient, video: Path, lowres: Path, duration: float, options: SceneOptions,
                    prev_summary: str = "", known_people: str = "",
                    cancel: threading.Event | None = None) -> tuple[list[dict], dict]:
    """(정리된 장면 목록(클립 초), 사용량). lowres: 압축본을 둘 경로 (이미 있으면 다시 만들지 않는다)."""
    make_lowres(video, lowres, options.height)
    raw, usage = client.analyze_video(lowres, scene_prompt(duration, options.min_sec, prev_summary, known_people),
                                      SCENE_SCHEMA, model=options.model, resolution=options.resolution,
                                      mode=options.mode, cancel=cancel)
    return clean_scenes(raw, duration, options.min_sec), usage
