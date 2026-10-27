"""JSON 파일 읽기·쓰기. 쓰기는 임시 파일에 쓰고 바꿔치기한다 (쓰다가 꺼져도 파일이 깨지지 않게)."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def write_json(path: Path, data, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # Windows: 다른 스레드가 잠깐 읽고 있으면 실패할 수 있다
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def read_json(path: Path):
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    return json.loads(path.read_text(encoding="utf-8"))
