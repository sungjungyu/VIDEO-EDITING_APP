"""백그라운드 작업(분석·렌더·미리보기 사본) 상태."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .common import now_iso

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
