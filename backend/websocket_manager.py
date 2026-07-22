"""
job_id별 WebSocket 커넥션 관리

렌더링 스레드(블로킹)에서 비동기 WebSocket으로 메시지를 보내야 하므로
asyncio.run_coroutine_threadsafe를 사용한다.
"""
import asyncio
import json
import threading
from typing import Any

from fastapi import WebSocket


_lock = threading.Lock()
_connections: dict[str, WebSocket] = {}
_loops: dict[str, asyncio.AbstractEventLoop] = {}


def register(job_id: str, ws: WebSocket, loop: asyncio.AbstractEventLoop) -> None:
    with _lock:
        _connections[job_id] = ws
        _loops[job_id] = loop


def unregister(job_id: str) -> None:
    with _lock:
        _connections.pop(job_id, None)
        _loops.pop(job_id, None)


def send_from_thread(job_id: str, payload: dict[str, Any]) -> None:
    """렌더링 스레드에서 호출 — 비동기 WebSocket으로 안전하게 전송."""
    with _lock:
        ws = _connections.get(job_id)
        loop = _loops.get(job_id)
    if ws is None or loop is None:
        return
    future = asyncio.run_coroutine_threadsafe(
        ws.send_text(json.dumps(payload, ensure_ascii=False)),
        loop,
    )
    try:
        future.result(timeout=5)
    except Exception:
        pass


async def send(job_id: str, payload: dict[str, Any]) -> None:
    """비동기 컨텍스트에서 호출."""
    with _lock:
        ws = _connections.get(job_id)
    if ws is None:
        return
    await ws.send_text(json.dumps(payload, ensure_ascii=False))
