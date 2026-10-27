"""라우트가 함께 쓰는 앱 상태 (create_app이 채운다)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..ai.client import GeminiClient
from ..services.jobs import JobManager
from ..settings import Settings
from ..storage.projects import ProjectStore


@dataclass
class AppState:
    settings: Settings
    store: ProjectStore
    jobs: JobManager
    ai: GeminiClient


def state(request: Request) -> AppState:
    return request.app.state.vibecut
