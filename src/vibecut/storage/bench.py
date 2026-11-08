"""평가 벤치마크 저장소. 프로젝트와 달리 서버를 켜고 꺼도 지우지 않는다.

data/bench/
    cases/{case_id}.json      정답 묶음 (BenchCase) — 영상 없이 문장·장면·무음·정답만
    results/{시각}.json        vibecut bench 실행 결과

data/ 전체가 .gitignore에 있으므로 개인 영상의 받아쓰기가 저장소에 올라가지 않는다.
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from ..domain.models import BenchCase
from ..errors import NotFound
from .files import read_json, write_json

_ID = re.compile(r"^[0-9a-z_-]{1,64}$")


class BenchStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "bench"
        self.cases_dir = self.root / "cases"
        self.results_dir = self.root / "results"

    @staticmethod
    def new_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]

    def _case_path(self, case_id: str) -> Path:
        if not _ID.match(case_id):
            raise NotFound(f"정답 묶음 id가 올바르지 않습니다: {case_id}")
        return self.cases_dir / f"{case_id}.json"

    def save_case(self, case: BenchCase) -> BenchCase:
        write_json(self._case_path(case.case_id), case.model_dump())
        return case

    def load_case(self, case_id: str) -> BenchCase:
        path = self._case_path(case_id)
        if not path.exists():
            raise NotFound(f"정답 묶음이 없습니다: {case_id}")
        return BenchCase.model_validate(read_json(path))

    def list_cases(self) -> list[BenchCase]:
        if not self.cases_dir.exists():
            return []
        cases = [BenchCase.model_validate(read_json(p)) for p in sorted(self.cases_dir.glob("*.json"))]
        return sorted(cases, key=lambda c: c.created_at)

    def find_by_project(self, project_id: str) -> BenchCase | None:
        """같은 프로젝트를 다시 검수하면 새로 만들지 않고 덮어쓴다."""
        return next((c for c in self.list_cases() if c.source_project == project_id), None)

    def save_result(self, result: dict) -> Path:
        path = self.results_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
        write_json(path, result)
        return path
