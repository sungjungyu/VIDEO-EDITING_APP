"""분석 결과: 받아쓰기 문장·장면·4단 트리·문장별 판단 (시각은 클립 초, 트리만 원본 초)."""

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


def flatten_tree(tree: list[TreeNode]) -> dict[str, TreeNode]:
    """트리의 모든 노드를 id → 노드로 펼친다."""
    out: dict[str, TreeNode] = {}
    stack = list(tree)
    while stack:
        node = stack.pop()
        out[node.id] = node
        stack.extend(node.children)
    return out
