"""평가 벤치마크 (v4 설계안 T1): 사람이 검수한 '정답'과 그 판단에 필요한 분석 결과를 함께 담는다.

영상 파일은 담지 않는다 — 받아쓰기 문장·무음·장면만 있으면 컷 판단 방법들을 다시 돌려 채점할 수 있다.
(프로젝트는 서버를 켜고 끌 때 지워지므로 정답은 data/bench/에 따로 둔다: storage/bench.py)

정답 이유(reason)
    NG·반복·군더더기·지시어  자를 이유 (판단 엔진과 같은 이름)
    직접                    사람이 뺐지만 이유가 엔진의 자를 이유가 아닌 것
    일반                    남김
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .analysis import ClipSpan, Line, Scene
from .common import now_iso

CUT_REASONS = ("NG", "반복", "군더더기", "지시어")


class GoldLabel(BaseModel):
    keep: bool
    reason: str = "일반"


class BenchClip(BaseModel):
    clip_id: str
    filename: str
    sha1: str = ""
    duration: float = 0.0


class BenchCase(BaseModel):
    """정답 묶음 하나 (보통 프로젝트 하나를 검수한 것)."""
    case_id: str
    name: str
    person: str = ""                                  # 찍은 사람 — 조정용/시험용을 사람 단위로 나눌 때 쓴다
    split: Literal["tune", "test"] = "test"           # tune: 기준값 조정용, test: 결과 보고용
    created_at: str = Field(default_factory=now_iso)
    source_project: str = ""
    judge_engine: str = ""                            # 검수할 때 화면에 보였던 판단 엔진 (정답이 어디서 출발했는지)
    profile: dict = Field(default_factory=dict)       # 그때의 내 편집 스타일 (군말 빼기 강도 등)
    clips: list[BenchClip] = Field(default_factory=list)
    spans: list[ClipSpan] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    silences: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)
    gold: dict[str, GoldLabel] = Field(default_factory=dict)

    @property
    def spoken_ids(self) -> list[str]:
        """채점 대상: 글자가 있는 문장 (말소리만 있고 받아쓰기가 빈 문장은 뺀다)."""
        return [line.seg_id for line in self.lines if line.text.strip() and line.seg_id in self.gold]


def gold_reason(keep: bool, reason: str) -> str:
    if keep:
        return "일반"
    return reason if reason in CUT_REASONS else "직접"
