"""분석 결과: 받아쓰기 문장·장면·비트(편집 단위)·문장별 판단 (시각은 모두 클립 초)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .common import now_iso


class Word(BaseModel):
    word: str
    start: float
    end: float
    probability: float | None = None


class Line(BaseModel):
    """받아쓰기 문장 하나 (클립 초)."""
    seg_id: str
    clip_id: str
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)
    speaker: str | None = None


class Scene(BaseModel):
    """화면이 바뀌는 단위의 장면 하나 (클립 초). source는 gemini(영상 이해) 또는 local(화면 변화 감지)."""
    scene_id: str
    clip_id: str
    start: float
    end: float
    place: str = ""
    activity: str = ""
    people: str = ""
    event: str = ""
    mood: str = ""
    summary: str = ""
    source: str = "local"


class Beat(BaseModel):
    """편집 단위 하나 (클립 초, v4 설계안 T3). 장면을 고르거나 AI 가편집이 고르는 단위.
    speech: 한 주제로 이어지는 말 묶음 (문장 여러 개)  ·  broll: 말 없는 구간에서 고른 2~5초 화면."""
    beat_id: str
    kind: Literal["speech", "broll"]
    clip_id: str
    start: float
    end: float
    seg_ids: list[str] = Field(default_factory=list)
    place: str = ""
    title: str = ""
    summary: str = ""


class ClipSpan(BaseModel):
    """분석용 원본 타임라인에서 클립 하나가 차지하는 자리."""
    clip_id: str
    offset: float
    duration: float


class LineDecision(BaseModel):
    """문장 하나를 남길지 자를지. source: ai(Gemini) / rule(규칙) / user(사용자가 직접 바꿈)."""
    seg_id: str
    keep: bool = True
    reason: str = "일반"
    note: str = ""
    confidence: float = 0.5
    emphasis: bool = False
    source: Literal["ai", "rule", "user"] = "rule"
    text: str | None = None


class Analysis(BaseModel):
    clips: list[ClipSpan] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
    silences: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)
    judgments: dict[str, LineDecision] = Field(default_factory=dict)
    engines: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)

    def lines_by_clip(self) -> dict[str, list[Line]]:
        out: dict[str, list[Line]] = {}
        for line in sorted(self.lines, key=lambda x: (x.clip_id, x.start)):
            out.setdefault(line.clip_id, []).append(line)
        return out



def beats_by_id(beats: list[Beat]) -> dict[str, Beat]:
    return {b.beat_id: b for b in beats}
