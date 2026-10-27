"""같은 입력이면 다시 쓰는 결과 캐시 (data/cache/…): AI 응답·받아쓰기·장면 분석.

파일 이름이 곧 캐시 키다. 키 규칙을 바꾸면 저장해 둔 결과(오프라인 시연용)를 못 쓰게 되므로 조심한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .files import write_json


class JsonCache:
    def __init__(self, directory: Path | None):
        self.directory = Path(directory) if directory is not None else None

    def get(self, name: str) -> Any | None:
        """저장된 값. 없거나 읽을 수 없으면 None."""
        if self.directory is None:
            return None
        path = self.directory / name
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, name: str, data: Any) -> None:
        if self.directory is not None:
            write_json(self.directory / name, data, indent=None)
