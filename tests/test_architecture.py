"""계층 규칙 검사: 위 계층은 아래 계층을 쓸 수 있고, 아래 계층은 위 계층을 모른다.

    5  server · cli                        입구 (HTTP·명령줄)
    4  services                            사용 사례 + 작업 큐
    3  analysis · editing · render · eval  기능
    2  ai                                  외부 AI 서비스
    1  media · storage                     ffmpeg, 디스크
    0  domain · errors · settings · log    순수 모델·규칙·설정

같은 층끼리는 써도 된다. 모든 파일의 import를 읽어 아래 층이 위 층을 import하면 실패한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "vibecut"
LAYERS = {
    "domain": 0, "errors": 0, "settings": 0, "log": 0,
    "media": 1, "storage": 1,
    "ai": 2,
    "analysis": 3, "editing": 3, "render": 3, "eval": 3,
    "services": 4,
    "server": 5, "cli": 5,
}
TOP_LEVEL_EXEMPT = {"__init__", "__main__"}


def _top(module: str) -> str:
    return module.split(".")[0]


def _imports(path: Path) -> list[str]:
    """파일이 import하는 vibecut 안쪽 모듈 (vibecut. 뒤 첫 이름)."""
    rel = path.relative_to(PACKAGE).with_suffix("")
    package_parts = list(rel.parts[:-1]) if rel.name != "__init__" else list(rel.parts[:-1])
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)] if node.level > 1 else package_parts
                target = [*base, *(node.module.split(".") if node.module else [])]
                if not target:            # from . import x (패키지 최상위)
                    target = [alias.name for alias in node.names][:1]
                found.append(".".join(target))
            elif node.module and node.module.startswith("vibecut."):
                found.append(node.module.removeprefix("vibecut."))
        elif isinstance(node, ast.Import):
            found += [a.name.removeprefix("vibecut.") for a in node.names if a.name.startswith("vibecut.")]
    return found


def test_lower_layers_never_import_upper_layers():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE)
        owner = rel.parts[0] if len(rel.parts) > 1 else rel.stem
        if owner in TOP_LEVEL_EXEMPT:
            continue
        assert owner in LAYERS, f"계층이 정해지지 않은 모듈: {rel} (tests/test_architecture.py LAYERS에 추가)"
        for target in _imports(path):
            top = _top(target)
            if top in LAYERS and LAYERS[top] > LAYERS[owner]:
                violations.append(f"{rel} → vibecut.{target}  ({owner} {LAYERS[owner]}층이 {top} {LAYERS[top]}층을 씀)")
    assert not violations, "계층 규칙 위반:\n" + "\n".join(violations)


def test_domain_has_no_io_dependencies():
    """domain은 순수 계층: 디스크·네트워크·프로세스·서드파티 SDK를 쓰지 않는다 (pydantic만)."""
    banned = {"subprocess", "httpx", "google", "fastapi", "numpy", "shutil"}
    for path in (PACKAGE / "domain").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name}가 {name}을 씀"
