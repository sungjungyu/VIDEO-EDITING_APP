"""편집 계획(EditPlan): 사용자가 정하는 값 + 서버가 계산해 채우는 값 (keep·effects·events·duration)."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .analysis import LineDecision, Word
from .common import now_iso

# 자막에 쓸 수 있는 글꼴 (화면 목록·render/fonts.py의 파일 후보와 같은 이름)
SUBTITLE_FONTS = ("Malgun Gothic", "NanumGothic", "NanumMyeongjo", "Noto Sans KR", "Arial")
_FONT_BY_LOWER = {name.lower(): name for name in SUBTITLE_FONTS}


def _clamp(value: float, lo: float, hi: float) -> float:
    """API 값·저장된 값을 렌더가 감당할 수 있는 범위로 맞춘다 (거절하면 예전 plan.json을 못 연다).
    NaN·무한대는 아래 끝으로."""
    value = float(value)
    return lo if not math.isfinite(value) else max(lo, min(hi, value))


class Selection(BaseModel):
    """어떤 비트(편집 단위)를 쓸지. all=전체, manual=사용자가 체크, auto=AI 가편집."""
    mode: Literal["all", "manual", "auto"] = "all"
    beat_ids: list[str] = Field(default_factory=list)
    target_sec: float | None = None
    user_prompt: str = ""
    locked_ids: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    ai_beat_ids: list[str] = Field(default_factory=list)


class StyleSpec(BaseModel):
    """자막 스타일. 크기·여백·두께는 '출력 영상의 짧은 변이 1080px일 때'의 px 값이다.
    (16:9 1920x1080과 9:16 1080x1920 모두 짧은 변이 1080이라 같은 숫자가 같은 비율로 보인다)
    미리보기도 같은 기준으로 축소해 그리므로 미리보기와 렌더 결과가 같다."""
    version: int = 2
    preset: str = "정석맛"
    font: str = "Malgun Gothic"
    color: str = "#ffffff"
    size: float = 54
    weight: Literal["normal", "bold", "extra-bold"] = "normal"
    italic: bool = False
    outline: bool = True
    outline_color: str = "#000000"
    outline_width: float = 3
    shadow: bool = False
    shadow_distance: float = 4
    background_box: bool = False
    bg_color: str = "#000000"
    bg_opacity: float = 60
    position: Literal["top", "center", "bottom"] = "bottom"
    bottom_margin: float = 60
    max_chars_per_line: int = 20
    karaoke: bool = False
    fade: bool = False

    @field_validator("color", "outline_color", "bg_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.startswith("#"):
            v = "#" + v
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
            raise ValueError(f"색상은 #RRGGBB 형식이어야 합니다: {v}")
        return "#" + h.lower()

    @field_validator("max_chars_per_line")
    @classmethod
    def _chars(cls, v: int) -> int:
        return max(4, min(60, int(v)))

    @field_validator("font")
    @classmethod
    def _font(cls, v: str) -> str:
        """목록에 없는 글꼴은 기본 글꼴로 (글꼴 이름이 ASS Style 줄에 그대로 들어간다 — 쉼표·줄바꿈 차단)."""
        return _FONT_BY_LOWER.get(str(v or "").strip().lower(), "Malgun Gothic")

    @field_validator("size")
    @classmethod
    def _size(cls, v: float) -> float:
        return _clamp(v, 8, 300)

    @field_validator("outline_width", "shadow_distance")
    @classmethod
    def _thickness(cls, v: float) -> float:
        return _clamp(v, 0, 50)

    @field_validator("bg_opacity")
    @classmethod
    def _opacity(cls, v: float) -> float:
        return _clamp(v, 0, 100)

    @field_validator("bottom_margin")
    @classmethod
    def _margin(cls, v: float) -> float:
        return _clamp(v, 0, 1000)


class OutputSpec(BaseModel):
    """결과 영상 설정. aspect_source=auto면 편집 계획을 계산할 때 타임라인 영상 방향(세로가 많으면 9:16)을 따른다.
    비율을 직접 정하면(화면의 비율 버튼, --aspect, OutputSpec(aspect=...)) user가 되어 더는 자동으로 바꾸지 않는다."""
    aspect: Literal["16:9", "9:16"] = "16:9"
    aspect_source: Literal["auto", "user"] = "auto"
    resolution: int = 1080      # 짧은 변 px
    fps: int = 30

    @model_validator(mode="before")
    @classmethod
    def _explicit_aspect_is_user(cls, data):
        if isinstance(data, dict) and "aspect" in data and "aspect_source" not in data:
            return {**data, "aspect_source": "user"}
        return data

    @field_validator("resolution")
    @classmethod
    def _resolution(cls, v: int) -> int:
        """360~2160 사이 짝수 (libx264 yuv420p는 가로·세로가 짝수여야 한다)."""
        return int(_clamp(v, 360, 2160)) // 2 * 2

    @field_validator("fps")
    @classmethod
    def _fps(cls, v: int) -> int:
        return int(_clamp(v, 12, 60))

    def size(self, resolution: int | None = None) -> tuple[int, int]:
        short = resolution or self.resolution
        long = round(short * 16 / 9 / 2) * 2
        return (long, short) if self.aspect == "16:9" else (short, long)


class PlanOptions(BaseModel):
    pad_start: float = 0.08         # 말 시작 앞 여유 (초)
    pad_end: float = 0.12           # 말 끝 뒤 여유 (초)
    max_pause: float | None = 0.8   # 남기는 문장 사이 쉼이 이보다 길면 줄인다 (None이면 그대로)
    pause_limit: float = 4.0        # 이보다 긴 쉼은 '말 없는 장면'으로 보고 줄이지 않는다
    swallow_pause: float = 1.5      # 자르는 문장 앞뒤 쉼이 이보다 짧으면 함께 지운다
    min_gap: float = 0.25           # 이보다 짧은 틈은 이어 붙인다
    min_keep: float = 0.4           # 이보다 짧은 조각은 버린다 (문장을 통째로 품으면 예외)
    snap_to_silence: bool = True    # 경계를 근처 무음 쪽으로 옮긴다
    fade_ms: int = 25               # 컷마다 오디오 페이드 (튀는 소리 방지)
    loudness: bool = True           # 클립마다 다른 음량을 고르게 (EBU R128, -16 LUFS)
    punch_in: bool = True           # 강조 문장에 살짝 줌인
    punch_scale: float = 1.08
    subtitles: bool = True
    location_captions: bool = False  # 장소가 바뀔 때 '촬영지 자막'
    title_text: str = ""            # 처음 3초 '제목' 자막

    @field_validator("pad_start", "pad_end")
    @classmethod
    def _pad(cls, v: float) -> float:
        return _clamp(v, 0, 2)

    @field_validator("fade_ms")
    @classmethod
    def _fade(cls, v: int) -> int:
        return int(_clamp(v, 0, 500))

    @field_validator("punch_scale")
    @classmethod
    def _punch(cls, v: float) -> float:
        """1보다 작으면 줌 사본이 출력 크기보다 작아져 crop이 실패한다."""
        return _clamp(v, 1.0, 1.5)

    @field_validator("title_text")
    @classmethod
    def _title(cls, v: str) -> str:
        return v[:200]


class KeepRange(BaseModel):
    clip_id: str
    start: float
    end: float
    out_start: float = 0.0
    origin: str = ""


class Effect(BaseModel):
    type: Literal["punch_in"] = "punch_in"
    clip_id: str
    start: float
    end: float
    scale: float = 1.08
    seg_id: str | None = None


class SubtitleEvent(BaseModel):
    """결과 영상 위에 나타날 자막 한 장면 (결과 초). text의 줄바꿈은 \\n."""
    start: float
    end: float
    text: str
    style: str = "subtitle"
    words: list[Word] = Field(default_factory=list)
    word_lines: list[int] = Field(default_factory=list)
    seg_id: str | None = None


def default_styles() -> dict[str, StyleSpec]:
    return {
        "subtitle": StyleSpec(),
        "title": StyleSpec(preset="제목", size=84, weight="bold", position="top", bottom_margin=80,
                           max_chars_per_line=18, fade=True),
        "location": StyleSpec(preset="촬영지", size=44, position="top", bottom_margin=50,
                              background_box=True, bg_opacity=55, outline=False, fade=True),
    }


class EditPlan(BaseModel):
    version: int = 1
    selection: Selection = Field(default_factory=Selection)
    lines: dict[str, LineDecision] = Field(default_factory=dict)
    styles: dict[str, StyleSpec] = Field(default_factory=default_styles)
    output: OutputSpec = Field(default_factory=OutputSpec)
    options: PlanOptions = Field(default_factory=PlanOptions)
    # ↓ planner.compile_plan이 계산해서 채운다
    keep: list[KeepRange] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    events: list[SubtitleEvent] = Field(default_factory=list)
    duration: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=now_iso)
