"""프론트엔드·AI·렌더가 함께 쓰는 데이터 계약.

시간 단위는 모두 초(float)다. 기준점이 셋이라 이름으로 구분한다.
    클립 초      : 클립 파일 안의 시각 (Line, Scene, KeepRange, Effect)
    원본 초      : 타임라인 순서대로 클립을 이어 붙인 '분석용 원본'의 시각 (TreeNode)
    결과 초      : 렌더된 영상 안의 시각 (KeepRange.out_start, SubtitleEvent)

편집 결과의 중심은 EditPlan이다. 사용자가 바꾸는 값(selection, lines, styles, output, options)과
서버가 그 값으로 계산해 채우는 값(keep, effects, events, duration, warnings)을 한 객체에 담는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 분석 결과

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


class TreeNode(BaseModel):
    """4단 트리 노드 (원본 초). level 0=장소, 1=일, 2=상황, 3=대사."""
    id: str
    title: str
    level: int
    start: float
    end: float
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    seg_id: str | None = None
    children: list[TreeNode] = Field(default_factory=list)


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
    tree: list[TreeNode] = Field(default_factory=list)
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


# ---------------------------------------------------------------- 편집 계획

class Selection(BaseModel):
    """어떤 장면을 쓸지. all=전체, manual=사용자가 체크, auto=AI 가편집."""
    mode: Literal["all", "manual", "auto"] = "all"
    node_ids: list[str] = Field(default_factory=list)
    target_sec: float | None = None
    user_prompt: str = ""
    locked_ids: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    ai_node_ids: list[str] = Field(default_factory=list)


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


class OutputSpec(BaseModel):
    aspect: Literal["16:9", "9:16"] = "16:9"
    resolution: int = 1080      # 짧은 변 px
    fps: int = 30

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

    def user_part(self) -> dict:
        """사용자가 정하는 부분만 (실행취소 기록·비교용)."""
        return self.model_dump(include={"selection", "lines", "styles", "output", "options"})


# ---------------------------------------------------------------- 프로젝트·작업

class ClipInfo(BaseModel):
    clip_id: str
    filename: str
    stored_name: str
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = True
    has_video: bool = True
    created_at: float | None = None     # 촬영 시각 (epoch 초). 메타데이터가 없으면 None
    uploaded_at: str = Field(default_factory=now_iso)
    size_bytes: int = 0
    sha1: str = ""
    in_point: float = 0.0               # 타임라인에서 앞뒤를 잘라 낸 사용 범위
    out_point: float | None = None
    proxy: bool = False

    @property
    def usable_end(self) -> float:
        return self.duration if self.out_point is None else min(self.out_point, self.duration)


class AnalysisState(BaseModel):
    status: Literal["none", "running", "done", "failed"] = "none"
    job_id: str | None = None
    timeline: list[str] = Field(default_factory=list)   # 분석할 때의 클립 순서 (바뀌면 다시 분석)
    engines: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class RenderInfo(BaseModel):
    render_id: str
    quality: Literal["preview", "final"]
    file: str
    width: int
    height: int
    duration: float
    plan_duration: float
    error_ms: float
    elapsed_sec: float
    size_bytes: int
    created_at: str = Field(default_factory=now_iso)


class Project(BaseModel):
    project_id: str
    name: str = "새 프로젝트"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    clips: list[ClipInfo] = Field(default_factory=list)
    timeline: list[str] = Field(default_factory=list)   # 편집에 쓰는 클립 순서
    analysis: AnalysisState = Field(default_factory=AnalysisState)
    renders: list[RenderInfo] = Field(default_factory=list)

    def clip(self, clip_id: str) -> ClipInfo | None:
        return next((c for c in self.clips if c.clip_id == clip_id), None)

    def timeline_clips(self) -> list[ClipInfo]:
        by_id = {c.clip_id: c for c in self.clips}
        return [by_id[cid] for cid in self.timeline if cid in by_id]

    @property
    def analysis_stale(self) -> bool:
        return self.analysis.status == "done" and self.analysis.timeline != self.timeline


JobStatus = Literal["queued", "running", "done", "failed", "canceled"]


class Job(BaseModel):
    job_id: str
    kind: Literal["analyze", "render", "proxy"]
    project_id: str | None = None
    status: JobStatus = "queued"
    progress: float = 0.0
    stage: str = ""
    message: str = ""
    error: str | None = None
    result: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed", "canceled")
