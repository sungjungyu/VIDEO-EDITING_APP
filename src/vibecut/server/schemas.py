"""API 요청 본문 (클래스 이름이 OpenAPI 스키마 이름이 된다 — 화면이 보내는 모양과 같아야 한다)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..domain.models import LineDecision, OutputSpec, PlanOptions, Selection, StyleSpec
from ..services.editing import LineChange


class ProjectCreate(BaseModel):
    name: str = "새 프로젝트"


class ClipPatch(BaseModel):
    clip_id: str
    in_point: float | None = None
    out_point: float | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    timeline: list[str] | None = None
    clips: list[ClipPatch] | None = None


class AnalyzeRequest(BaseModel):
    profile: dict = Field(default_factory=dict)


class PlanUpdate(BaseModel):
    selection: Selection | None = None
    lines: dict[str, LineDecision] | None = None
    styles: dict[str, StyleSpec] | None = None
    output: OutputSpec | None = None
    options: PlanOptions | None = None


class LinesPatch(BaseModel):
    changes: list[LineChange]


class SelectRequest(BaseModel):
    mode: Literal["all", "manual", "auto"] = "auto"
    target_sec: float | None = None
    user_prompt: str = ""
    locked_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    profile: dict = Field(default_factory=dict)


class ReviseRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    profile: dict = Field(default_factory=dict)


class BenchCaseRequest(BaseModel):
    name: str = Field(default="", max_length=80)
    person: str = Field(default="", max_length=40)
    split: Literal["tune", "test"] = "test"
    profile: dict = Field(default_factory=dict)


class RenderRequest(BaseModel):
    quality: Literal["preview", "final"] = "final"
