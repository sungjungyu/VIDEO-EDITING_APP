"""테스트 공용 fixture."""

from __future__ import annotations

import pytest

from vibecut.settings import load_settings


@pytest.fixture
def make_settings():
    """Gemini를 '쓸 수 있는' 설정 (실제로는 호출하지 않는다 — 테스트가 응답을 대신 넣는다)."""
    def build(tmp_path, **overrides):
        values = dict(api_key="test-key", ai_mode="live", data_dir=tmp_path, gemini_retries=2)
        values.update(overrides)
        return load_settings(**values)
    return build
