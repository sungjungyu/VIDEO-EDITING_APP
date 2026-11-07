"""프로젝트: 클립 목록·타임라인 순서·분석 상태·렌더 목록."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .common import now_iso


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
    hdr: bool = False
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
