"""프론트엔드·AI·렌더가 함께 쓰는 데이터 계약 (저장 파일 data/projects/*.json의 모양이기도 하다).

시간 단위는 모두 초(float)다. 기준점이 셋이라 이름으로 구분한다.
    클립 초      : 클립 파일 안의 시각 (Line, Scene, KeepRange, Effect)
    원본 초      : 타임라인 순서대로 클립을 이어 붙인 '분석용 원본'의 시각 (TreeNode)
    결과 초      : 렌더된 영상 안의 시각 (KeepRange.out_start, SubtitleEvent)

편집 결과의 중심은 EditPlan이다. 사용자가 바꾸는 값(selection, lines, styles, output, options)과
서버가 그 값으로 계산해 채우는 값(keep, effects, events, duration, warnings)을 한 객체에 담는다.
"""

from .analysis import Analysis, ClipSpan, Line, LineDecision, Scene, TreeNode, Word, flatten_tree
from .bench import BenchCase, BenchClip, GoldLabel, gold_reason
from .common import now_iso
from .job import Job, JobStatus
from .plan import (
    EditPlan,
    Effect,
    KeepRange,
    OutputSpec,
    PlanOptions,
    Selection,
    StyleSpec,
    SubtitleEvent,
    default_styles,
)
from .project import AnalysisState, ClipInfo, Project, RenderInfo

__all__ = [
    "Analysis", "AnalysisState", "BenchCase", "BenchClip", "ClipInfo", "ClipSpan", "EditPlan", "Effect",
    "GoldLabel", "Job", "JobStatus", "KeepRange", "gold_reason",
    "Line", "LineDecision", "OutputSpec", "PlanOptions", "Project", "RenderInfo", "Scene", "Selection", "StyleSpec",
    "SubtitleEvent", "TreeNode", "Word", "default_styles", "flatten_tree", "now_iso",
]
