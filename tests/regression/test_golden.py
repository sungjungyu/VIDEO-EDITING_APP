"""리팩터링 전 코드로 만든 골든 파일과 지금 결과가 같은지 확인한다 (snapshot.py 참고).

다르면 기능이 바뀐 것이다. 의도한 변경일 때만 VIBECUT_UPDATE_GOLDEN=1로 골든 파일을 다시 만든다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.regression.snapshot import build_snapshot, openapi_snapshot
from vibecut.server.app import create_app
from vibecut.settings import load_settings

GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.getenv("VIBECUT_UPDATE_GOLDEN") == "1"


def _normalize(data):
    return json.loads(json.dumps(data, ensure_ascii=False, sort_keys=True))


def _check(name: str, actual) -> None:
    path = GOLDEN / name
    actual = _normalize(actual)
    if UPDATE:
        path.write_text(json.dumps(actual, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        pytest.skip(f"골든 파일을 다시 만들었습니다: {name}")
    expected = json.loads(path.read_text(encoding="utf-8"))
    for section in expected:
        if isinstance(expected[section], dict):
            for key in expected[section]:
                assert actual[section].get(key) == expected[section][key], f"{name}: {section}.{key}가 달라졌습니다"
        assert actual[section] == expected[section], f"{name}: {section}가 달라졌습니다"
    assert set(actual) == set(expected)


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


def test_prompts_schemas_and_ai_cache_keys_unchanged(snapshot):
    expected = json.loads((GOLDEN / "snapshot.json").read_text(encoding="utf-8"))["prompts"]
    if UPDATE:
        pytest.skip("골든 갱신 중")
    actual = _normalize(snapshot["prompts"])
    for name, text in expected["texts"].items():
        assert actual["texts"][name] == text, f"프롬프트 '{name}'이 바뀌었습니다 (AI 캐시가 무효가 됩니다)"
    assert actual == expected


def test_rules_beats_and_plans_unchanged(snapshot):
    _check("snapshot.json", snapshot)


def test_openapi_unchanged(tmp_path):
    app = create_app(load_settings(data_dir=tmp_path, api_key=None))
    _check("openapi.json", openapi_snapshot(app))
