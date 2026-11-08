"""설정 읽기: 잘못 쓴 값은 안전한 쪽으로."""

from __future__ import annotations

from vibecut.settings import load_settings


def test_unknown_ai_mode_falls_back_to_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBECUT_AI_MODE", "ofline")                 # 오타
    settings = load_settings(root_dir=tmp_path, api_key="test-key", data_dir=tmp_path)
    assert settings.ai_mode == "offline" and not settings.ai_live    # 예전: live → Gemini 한도를 썼다


def test_judge_mode_defaults_to_all_and_accepts_hybrid(monkeypatch, tmp_path):
    assert load_settings(root_dir=tmp_path, data_dir=tmp_path).judge_mode == "all"
    monkeypatch.setenv("VIBECUT_JUDGE_MODE", "Hybrid")
    assert load_settings(root_dir=tmp_path, data_dir=tmp_path).judge_mode == "hybrid"
    monkeypatch.setenv("VIBECUT_JUDGE_MODE", "hybird")              # 오타 → 지금 방식
    assert load_settings(root_dir=tmp_path, data_dir=tmp_path).judge_mode == "all"
