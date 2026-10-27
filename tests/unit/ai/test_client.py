"""Gemini 클라이언트 테스트 (네트워크 없음): JSON 해석, 오류 분류, 재시도·대체 모델, 캐시 재생."""

from __future__ import annotations

import json

import pytest

from vibecut.ai.client import GeminiClient, classify_error, parse_json
from vibecut.errors import AIError, AIUnavailable


def test_parse_json_variants():
    pretty = json.dumps([{"id": "t1", "keep": False}, {"id": "t2", "keep": True}], indent=2)
    assert parse_json(pretty)[1]["id"] == "t2"                     # 예전 '복구 로직'이 망가뜨리던 형태
    assert parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert parse_json('설명: {"a": [1, 2]} 끝') == {"a": [1, 2]}
    assert parse_json('[{"id": 1}, {"id": 2}, {"id"') == [{"id": 1}, {"id": 2}]      # 잘린 배열
    with pytest.raises(json.JSONDecodeError):
        parse_json("그냥 글")


def test_classify_error():
    assert classify_error(RuntimeError("429 RESOURCE_EXHAUSTED")) == "quota"
    assert classify_error(RuntimeError("503 UNAVAILABLE")) == "transient"
    assert classify_error(TimeoutError("timed out")) == "transient"
    assert classify_error(RuntimeError("400 INVALID_ARGUMENT")) == "fatal"


class FakeClient(GeminiClient):
    def __init__(self, settings, replies, cache_dir=None):
        self.sleeps = []
        super().__init__(settings, cache_dir, sleep=self.sleeps.append)
        self.replies = list(replies)
        self.calls = []

    def _call(self, model, prompt, schema, temperature, max_output_tokens):
        self.calls.append(model)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_retry_then_success_with_backoff(make_settings, tmp_path):
    client = FakeClient(make_settings(tmp_path), [RuntimeError("503 UNAVAILABLE"), '{"ok": true}'])
    assert client.generate_json("p") == {"ok": True}
    assert client.calls == ["gemini-3.5-flash", "gemini-3.5-flash"] and len(client.sleeps) == 1


def test_quota_moves_to_fallback_model(make_settings, tmp_path):
    client = FakeClient(make_settings(tmp_path), [RuntimeError("429 RESOURCE_EXHAUSTED"), '{"ok": 1}'])
    assert client.generate_json("p") == {"ok": 1}
    assert client.calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_fatal_error_stops_and_reports(make_settings, tmp_path):
    client = FakeClient(make_settings(tmp_path), [RuntimeError("400 INVALID_ARGUMENT")] * 4)
    with pytest.raises(AIError):
        client.generate_json("p")
    assert client.calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_cache_replays_offline(make_settings, tmp_path):
    live = FakeClient(make_settings(tmp_path), ['{"v": 7}'], cache_dir=tmp_path / "ai")
    assert live.generate_json("같은 질문") == {"v": 7}
    offline = FakeClient(make_settings(tmp_path, ai_mode="offline"), [], cache_dir=tmp_path / "ai")
    assert offline.generate_json("같은 질문") == {"v": 7}               # 녹화된 응답 재생
    assert offline.usage.cache_hits == 1 and offline.calls == []
    with pytest.raises(AIUnavailable):
        offline.generate_json("처음 보는 질문")


def test_with_usage_shares_connection_but_counts_separately(make_settings, tmp_path):
    from vibecut.ai.client import Usage
    client = FakeClient(make_settings(tmp_path), ['{"a": 1}'])
    usage = Usage()
    job_client = client.with_usage(usage)
    assert job_client.usage is usage and client.usage is not usage
    assert job_client.cache.directory == client.cache.directory and job_client._clients is client._clients
