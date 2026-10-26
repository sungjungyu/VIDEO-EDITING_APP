"""Gemini 통합 클라이언트 — 글 판단(JSON)용 호출을 모두 여기로 모은다.

예전 문제와 대응
    - main.py의 30초 타임아웃이 실제로는 안 걸렸다 (`with ThreadPoolExecutor`가 끝날 때 호출이 끝나기를 기다림)
      → SDK의 HTTP 타임아웃(http_options.timeout)을 쓴다
    - 들여쓴 JSON을 '복구 로직'이 망가뜨려 AI 판단이 버려졌다
      → 응답 스키마(response_schema)를 강제하고, 파싱은 원문 그대로 먼저 시도
    - 키 로딩·모델 이름·재시도가 파일마다 달랐다 → settings 한 곳 + 여기 한 곳
    - 같은 입력이면 같은 응답을 디스크에 저장해 다시 쓴다 → 한도 절약, 오프라인 시연 때 그대로 재생

사용량(요청 수·토큰)은 Usage에 모아 작업(job) 기록에 남긴다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..settings import Settings

log = logging.getLogger("vibecut.ai.gemini")


class AIUnavailable(RuntimeError):
    """키가 없거나 오프라인 모드라 Gemini를 부를 수 없음 (캐시에도 없음)."""


class AIError(RuntimeError):
    """재시도·대체 모델까지 써도 실패."""


@dataclass
class Usage:
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


def _clean_schema(node: Any) -> Any:
    """Gemini JSON Schema가 지원하지 않는 키(default 등)를 뺀다."""
    if isinstance(node, dict):
        return {k: _clean_schema(v) for k, v in node.items() if k not in ("default", "examples")}
    if isinstance(node, list):
        return [_clean_schema(v) for v in node]
    return node


def _schema_payload(schema: type[BaseModel] | dict | None) -> Any:
    if schema is None:
        return None
    if isinstance(schema, dict):
        return _clean_schema(schema)
    return _clean_schema(schema.model_json_schema())


class GeminiClient:
    def __init__(self, settings: Settings, cache_dir: Path | None = None, usage: Usage | None = None,
                 sleep=time.sleep):
        self.settings = settings
        self.cache_dir = cache_dir
        self.usage = usage or Usage()
        self._sleep = sleep
        self._client = None
        self._client_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.settings.ai_live

    # ------------------------------------------------------------ 캐시

    def _key(self, model: str, prompt: str, schema: Any, temperature: float) -> str:
        raw = json.dumps([model, prompt, schema, temperature], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Any | None:
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["data"]
        except (OSError, ValueError, KeyError):
            return None

    def _cache_put(self, key: str, data: Any, model: str) -> None:
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_dir / f"{key}.tmp"
        tmp.write_text(json.dumps({"model": model, "saved_at": time.time(), "data": data}, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.cache_dir / f"{key}.json")

    # ------------------------------------------------------------ 호출

    def _sdk(self):
        with self._client_lock:
            if self._client is None:
                from google import genai
                from google.genai import types
                self._client = genai.Client(
                    api_key=self.settings.api_key,
                    http_options=types.HttpOptions(timeout=int(self.settings.gemini_timeout * 1000)),
                )
            return self._client

    def _call(self, model: str, prompt: str, schema: Any, temperature: float, max_output_tokens: int) -> str:
        from google.genai import types
        config = types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_output_tokens,
                                             response_mime_type="application/json")
        if schema is not None:
            config.response_json_schema = schema
        response = self._sdk().models.generate_content(model=model, contents=prompt, config=config)
        meta = getattr(response, "usage_metadata", None)
        self.usage.add(model, int(getattr(meta, "prompt_token_count", 0) or 0),
                       int(getattr(meta, "candidates_token_count", 0) or 0))
        text = getattr(response, "text", None) or ""
        if not text.strip():
            raise AIError("Gemini가 빈 응답을 돌려줬습니다 (empty).")
        return text

    def generate_json(self, prompt: str, schema: type[BaseModel] | dict | None = None, *, model: str | None = None,
                      temperature: float = 0.2, max_output_tokens: int = 8192, purpose: str = "") -> Any:
        """JSON 응답을 받아 파싱해 돌려준다. schema가 Pydantic 모델이면 그 모델로 검증한 dict."""
        schema_json = _schema_payload(schema)
        primary = model or self.settings.models.text
        key = self._key(primary, prompt, schema_json, temperature)
        cached = self._cache_get(key)
        if cached is not None:
            self.usage.hit()
            log.info("AI 응답 캐시 사용 (%s)", purpose or primary)
            return cached
        if not self.available:
            raise AIUnavailable("오프라인 모드이거나 Gemini 키가 없습니다.")
        models = [primary]
        fallback = self.settings.models.text_fallback
        if fallback and fallback != primary:
            models.append(fallback)
        last: BaseException | None = None
        for model_name in models:
            for attempt in range(self.settings.gemini_retries + 1):
                try:
                    data = parse_json(self._call(model_name, prompt, schema_json, temperature, max_output_tokens))
                    if isinstance(schema, type) and issubclass(schema, BaseModel):
                        data = schema.model_validate(data).model_dump()
                    self._cache_put(key, data, model_name)
                    if model_name != primary:
                        log.warning("대체 모델 %s로 응답을 받았습니다 (%s)", model_name, purpose)
                    return data
                except Exception as error:  # SDK 예외 종류가 버전마다 달라 문자열로 분류한다
                    last = error
                    kind = classify_error(error)
                    log.warning("Gemini %s 실패 (%s, %s, %d회차): %s", purpose or "호출", model_name, kind,
                                attempt + 1, str(error)[:200])
                    if kind == "quota":
                        break
                    if kind == "fatal" and not isinstance(error, ValueError):
                        break
                    if attempt < self.settings.gemini_retries:
                        self._sleep(min(20.0, 1.5 * (2 ** attempt)) + random.uniform(0, 0.5))
        message = str(last)[:300] if last else "알 수 없는 오류"
        if last is not None and classify_error(last) == "quota":
            message = "Gemini 사용 한도를 다 썼습니다 (무료 키는 모델마다 하루 횟수 제한). " + message
        raise AIError(message)
