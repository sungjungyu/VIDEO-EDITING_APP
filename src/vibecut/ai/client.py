"""Gemini 통합 클라이언트 — Gemini 호출은 모두 여기를 거친다.

    generate_json     글 판단 (컷 판단·장면 점수·수정 요청)   SDK generate_content + 응답 스키마
    analyze_video     영상 장면 이해 (장면 분석)              SDK files 업로드 + interactions
    transcribe_audio  받아쓰기 (단어 시각)                    REST generateContent (SDK가 audioTranscription을 버림)

재시도·대체 모델·오류 분류(한도 초과 / 일시 오류 / 치명 오류)·사용량 집계를 세 호출이 함께 쓴다.

예전 문제와 대응
    - 30초 타임아웃이 실제로는 안 걸렸다 → SDK의 HTTP 타임아웃(http_options.timeout)을 쓴다
    - 들여쓴 JSON을 '복구 로직'이 망가뜨려 AI 판단이 버려졌다 → 응답 스키마 강제, 파싱은 원문 그대로 먼저
    - 키·모델 이름·재시도가 파일마다 달랐다 → settings 한 곳 + 여기 한 곳
    - 같은 입력이면 같은 응답을 저장해 다시 쓴다 → 한도 절약, 오프라인 시연 때 그대로 재생
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..errors import AIError, AIUnavailable
from ..settings import Settings
from ..storage.cache import JsonCache

log = logging.getLogger("vibecut.ai")

T = TypeVar("T")
REST_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_SETTINGS_TIMEOUT = -1.0


@dataclass
class Usage:
    """요청 수·토큰. 작업(job) 기록과 평가 지표에 남긴다."""
    requests: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    by_model: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, prompt_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.requests += 1
            self.prompt_tokens += prompt_tokens
            self.output_tokens += output_tokens
            self.by_model[model] = self.by_model.get(model, 0) + 1

    def hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def to_dict(self) -> dict:
        return {"requests": self.requests, "cache_hits": self.cache_hits, "prompt_tokens": self.prompt_tokens,
                "output_tokens": self.output_tokens, "by_model": dict(self.by_model)}


def classify_error(error: BaseException) -> str:
    """quota(한도 초과: 다른 모델로) | transient(잠시 후 재시도) | fatal(재시도해도 소용없음)."""
    text = f"{type(error).__name__} {error}"
    if "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        return "quota"
    transient = ("500", "502", "503", "504", "UNAVAILABLE", "INTERNAL", "DEADLINE", "Timeout", "timed out",
                 "ConnectError", "RemoteProtocolError", "ReadError", "Connection", "JSONDecodeError", "empty")
    if isinstance(error, (TimeoutError, json.JSONDecodeError, ConnectionError)) or any(t in text for t in transient):
        return "transient"
    return "fatal"


def strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_json(text: str) -> Any:
    """응답 문자열 → JSON. 원문 그대로 먼저, 안 되면 바깥 {…}/[…]만, 배열이 잘렸으면 완성된 객체까지만."""
    text = strip_fence(text)
    if not text:
        raise json.JSONDecodeError("빈 응답", "", 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise json.JSONDecodeError("JSON이 아닙니다", text, 0)
    start = min(starts)
    closer = "}" if text[start] == "{" else "]"
    end = text.rfind(closer)
    if end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    if text[start] == "[":                       # 잘린 배열: 마지막으로 닫힌 객체까지
        last = text.rfind("}")
        if last > start:
            return json.loads(text[start:last + 1] + "]")
    raise json.JSONDecodeError("JSON을 해석하지 못했습니다", text, 0)


def clean_schema(node: Any) -> Any:
    """Gemini JSON Schema가 지원하지 않는 키(default 등)를 뺀다."""
    if isinstance(node, dict):
        return {k: clean_schema(v) for k, v in node.items() if k not in ("default", "examples")}
    if isinstance(node, list):
        return [clean_schema(v) for v in node]
    return node


def schema_payload(schema: type[BaseModel] | dict | None) -> Any:
    """응답 스키마 → Gemini에 보낼 JSON Schema. (AI 캐시 키에도 들어가므로 모델 클래스 이름을 바꾸지 않는다)"""
    if schema is None:
        return None
    if isinstance(schema, dict):
        return clean_schema(schema)
    return clean_schema(schema.model_json_schema())


def _token_count(usage: Any, *names: str) -> int:
    """SDK·REST 응답마다 다른 이름의 토큰 수를 찾는다."""
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if value:
            return int(value)
    return 0


class GeminiClient:
    def __init__(self, settings: Settings, cache_dir: Path | None = None, usage: Usage | None = None,
                 sleep=time.sleep):
        self.settings = settings
        self.cache = JsonCache(cache_dir)
        self.usage = usage or Usage()
        self._sleep = sleep
        self._clients: dict[float | None, Any] = {}
        self._client_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.settings.ai_live

    def with_usage(self, usage: Usage) -> GeminiClient:
        """SDK 연결·캐시는 같이 쓰고 사용량만 따로 모으는 사본 (작업마다 사용량을 기록할 때)."""
        clone = GeminiClient.__new__(GeminiClient)
        clone.__dict__.update(self.__dict__)
        clone.usage = usage
        return clone

    def _require(self) -> None:
        if not self.available:
            raise AIUnavailable("오프라인 모드이거나 Gemini 키가 없습니다.")

    # ------------------------------------------------------------ 공통: 재시도

    def _attempts(self, call: Callable[[], T], purpose: str, model: str) -> T:
        """일시 오류는 잠시 쉬고 다시, 한도 초과·치명 오류는 바로 실패 (마지막 오류를 그대로 올린다)."""
        retries = self.settings.gemini_retries
        for attempt in range(retries + 1):
            try:
                return call()
            except Exception as error:  # SDK 예외 종류가 버전마다 달라 문자열로 분류한다
                kind = classify_error(error)
                log.warning("Gemini %s 실패 (%s, %s, %d회차): %s", purpose or "호출", model, kind,
                            attempt + 1, str(error)[:200])
                if kind == "quota" or (kind == "fatal" and not isinstance(error, ValueError)) or attempt >= retries:
                    raise
                self._sleep(min(20.0, 1.5 * (2 ** attempt)) + random.uniform(0, 0.5))
        raise AssertionError("unreachable")

    @staticmethod
    def _failure(error: BaseException | None) -> AIError:
        message = str(error)[:300] if error else "알 수 없는 오류"
        if error is not None and classify_error(error) == "quota":
            message = "Gemini 사용 한도를 다 썼습니다 (무료 키는 모델마다 하루 횟수 제한). " + message
        return AIError(message)

    # ------------------------------------------------------------ SDK 연결

    def _sdk(self, timeout: float | None = _SETTINGS_TIMEOUT):
        """SDK 클라이언트. timeout None은 제한 없음 (영상 업로드·분석은 오래 걸린다)."""
        timeout = self.settings.gemini_timeout if timeout == _SETTINGS_TIMEOUT else timeout
        with self._client_lock:
            if timeout not in self._clients:
                from google import genai
                from google.genai import types
                options = types.HttpOptions(timeout=int(timeout * 1000)) if timeout else None
                self._clients[timeout] = genai.Client(api_key=self.settings.api_key, http_options=options)
            return self._clients[timeout]

    # ------------------------------------------------------------ 글 판단 (JSON)

    def cache_key(self, model: str, prompt: str, schema: Any, temperature: float) -> str:
        raw = json.dumps([model, prompt, schema, temperature], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _call(self, model: str, prompt: str, schema: Any, temperature: float, max_output_tokens: int) -> str:
        from google.genai import types
        config = types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_output_tokens,
                                             response_mime_type="application/json")
        if schema is not None:
            config.response_json_schema = schema
        response = self._sdk().models.generate_content(model=model, contents=prompt, config=config)
        meta = getattr(response, "usage_metadata", None)
        self.usage.add(model, _token_count(meta, "prompt_token_count"), _token_count(meta, "candidates_token_count"))
        text = getattr(response, "text", None) or ""
        if not text.strip():
            raise AIError("Gemini가 빈 응답을 돌려줬습니다 (empty).")
        return text

    def generate_json(self, prompt: str, schema: type[BaseModel] | dict | None = None, *, model: str | None = None,
                      temperature: float = 0.2, max_output_tokens: int = 8192, purpose: str = "") -> Any:
        """JSON 응답을 받아 파싱해 돌려준다. schema가 Pydantic 모델이면 그 모델로 검증한 dict.
        한도 초과면 대체 모델로 넘어간다."""
        schema_json = schema_payload(schema)
        primary = model or self.settings.models.text
        key = self.cache_key(primary, prompt, schema_json, temperature)
        cached = self.cache.get(f"{key}.json")
        if isinstance(cached, dict) and "data" in cached:
            self.usage.hit()
            log.info("AI 응답 캐시 사용 (%s)", purpose or primary)
            return cached["data"]
        self._require()
        models = [primary]
        fallback = self.settings.models.text_fallback
        if fallback and fallback != primary:
            models.append(fallback)
        last: BaseException | None = None
        for model_name in models:
            def call(model_name: str = model_name) -> Any:
                data = parse_json(self._call(model_name, prompt, schema_json, temperature, max_output_tokens))
                if isinstance(schema, type) and issubclass(schema, BaseModel):
                    data = schema.model_validate(data).model_dump()
                return data
            try:
                data = self._attempts(call, purpose, model_name)
            except Exception as error:
                last = error
                continue
            self.cache.put(f"{key}.json", {"model": model_name, "saved_at": time.time(), "data": data})
            if model_name != primary:
                log.warning("대체 모델 %s로 응답을 받았습니다 (%s)", model_name, purpose)
            return data
        raise self._failure(last)

    # ------------------------------------------------------------ 영상 장면 이해

    def analyze_video(self, video: Path, prompt: str, schema: dict, *, model: str, resolution: str = "low",
                      mode: str = "static") -> tuple[list, dict]:
        """영상을 올려 처리가 끝나기를 기다린 뒤 장면 목록(JSON 배열)을 받는다. 올린 파일은 끝나면 지운다.
        resolution: low|medium|high|ultra_high, mode(processing): static|agentic"""
        self._require()
        client = self._sdk(timeout=None)
        uploaded = client.files.upload(file=str(video))
        try:
            while not uploaded.state or uploaded.state.name != "ACTIVE":
                if uploaded.state and uploaded.state.name == "FAILED":
                    raise AIError("Gemini 파일 처리 실패")
                self._sleep(3)
                uploaded = client.files.get(name=uploaded.name)

            def call() -> tuple[list, dict]:
                inter = client.interactions.create(
                    model=model,
                    input=[{"type": "video", "uri": uploaded.uri, "mime_type": uploaded.mime_type,
                            "resolution": resolution, "processing": mode},
                           {"type": "text", "text": prompt}],
                    response_format={"type": "text", "mime_type": "application/json", "schema": schema},
                )
                raw = parse_json(inter.output_text)
                if not isinstance(raw, list):
                    raise ValueError("응답이 JSON 배열이 아님")
                usage = getattr(inter, "usage", None)
                usage = usage.model_dump() if hasattr(usage, "model_dump") else (usage or {})
                self.usage.add(model, _token_count(usage, "total_input_tokens", "input_tokens", "prompt_tokens"),
                               _token_count(usage, "total_output_tokens", "output_tokens", "completion_tokens"))
                return raw, usage

            try:
                return self._attempts(call, "장면 분석", model)
            except Exception as error:
                raise self._failure(error) from error
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    # ------------------------------------------------------------ 받아쓰기

    def transcribe_audio(self, audio: Path, *, model: str, language: str = "", diarize: bool = False,
                         vocab: list[str] | tuple[str, ...] = ()) -> dict:
        """FLAC 오디오 → generateContent 응답 (audioTranscription: 단어 시각·화자).
        temperature 0이라 같은 입력이면 같은 결과. 설정 이름은 공식 API 스키마 기준
        (wordTimestamp 단어 시각, diarization 화자 구분, customVocabulary 고유명사 힌트, mode VERBATIM)."""
        import httpx

        self._require()
        cfg: dict = {"wordTimestamp": True, "mode": "VERBATIM"}
        if language:
            cfg["languageCodes"] = [language]
        if diarize:
            cfg["diarization"] = True
        words = [v.strip() for v in vocab if v.strip()]
        if words:
            cfg["customVocabulary"] = words
        body = {"contents": [{"role": "user", "parts": [{"inline_data": {
                    "mime_type": "audio/flac", "data": base64.b64encode(audio.read_bytes()).decode()}}]}],
                "generationConfig": {"temperature": 0, "audioTranscriptionConfig": cfg}}

        def call() -> dict:
            r = httpx.post(REST_URL.format(model=model), headers={"x-goog-api-key": self.settings.api_key or ""},
                           json=body, timeout=600)
            if r.status_code != 200:
                try:
                    message = r.json().get("error", {}).get("message", "")
                except ValueError:
                    message = r.text[:300]
                raise AIError(f"Gemini 오류 {r.status_code}: {message}")
            data = r.json()
            meta = data.get("usageMetadata") or {}
            self.usage.add(model, _token_count(meta, "promptTokenCount"), _token_count(meta, "candidatesTokenCount"))
            return data

        try:
            return self._attempts(call, "받아쓰기", model)
        except Exception as error:
            raise self._failure(error) from error
