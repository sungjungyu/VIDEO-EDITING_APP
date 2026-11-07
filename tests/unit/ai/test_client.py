"""Gemini 클라이언트 테스트 (네트워크 없음): JSON 해석, 오류 분류, 재시도·대체 모델, 캐시 재생."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from vibecut.ai.client import GeminiClient, classify_error, parse_json
from vibecut.errors import AIError, AIUnavailable, Canceled


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
    assert classify_error(RuntimeError("400 max tokens 8500 exceeded")) == "fatal"


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


# ---------------------------------------------------------------- 영상 장면 분석 (처리 대기·취소)

class FakeVideoSdk:
    """files.upload/get/delete + interactions.create만 흉내. states: get이 차례로 돌려줄 처리 상태."""

    def __init__(self, states):
        self.states = list(states)
        self.deleted = []
        self.files = self
        self.interactions = self

    def _file(self, state):
        return SimpleNamespace(name="files/v1", uri="gs://v1", mime_type="video/mp4",
                               state=SimpleNamespace(name=state))

    def upload(self, file):
        return self._file("PROCESSING")

    def get(self, name):
        return self._file(self.states.pop(0) if self.states else "PROCESSING")

    def delete(self, name):
        self.deleted.append(name)

    def create(self, **kwargs):
        return SimpleNamespace(output_text='[{"start": 0, "end": 5}]', usage=None)


def video_client(make_settings, tmp_path, states):
    sdk = FakeVideoSdk(states)
    client = GeminiClient(make_settings(tmp_path), sleep=lambda s: None)
    client._sdk = lambda timeout=None: sdk
    return client, sdk


def test_analyze_video_waits_for_processing(make_settings, tmp_path):
    client, sdk = video_client(make_settings, tmp_path, ["PROCESSING", "ACTIVE"])
    scenes, _ = client.analyze_video(tmp_path / "v.mp4", "p", {}, model="m")
    assert scenes == [{"start": 0, "end": 5}] and sdk.deleted == ["files/v1"]


def test_analyze_video_gives_up_when_processing_never_ends(make_settings, tmp_path):
    client, sdk = video_client(make_settings, tmp_path, [])              # 계속 PROCESSING
    with pytest.raises(AIError, match="끝나지 않았습니다"):
        client.analyze_video(tmp_path / "v.mp4", "p", {}, model="m")
    assert sdk.deleted == ["files/v1"]                                   # 올린 파일은 지운다


def test_analyze_video_stops_on_cancel(make_settings, tmp_path):
    client, sdk = video_client(make_settings, tmp_path, [])
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Canceled):                                        # AIError로 감싸지 않는다
        client.analyze_video(tmp_path / "v.mp4", "p", {}, model="m", cancel=cancel)
    assert sdk.deleted == ["files/v1"]
