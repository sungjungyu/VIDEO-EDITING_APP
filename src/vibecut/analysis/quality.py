"""화면 품질 곡선 (v4 설계안 T4): 말 없는 장면(B롤)에서 가장 볼만한 2~5초를 고르는 기준.

초당 FPS장, SIZE×SIZE 흑백 프레임으로 세 가지를 잰다 (numpy만 사용).
    선명도   라플라시안(이웃 4칸과의 차이) 분산 — 초점이 나가거나 움직임이 번지면 작다.
             클립마다 중앙값 대비로 0~1 (같은 클립 안에서 덜 흐린 곳을 고르는 것이 목적)
    노출     평균 밝기가 50~205면 1, 너무 어둡거나(≤15) 하얗게 날아가면(≥245) 0
    안정     위상 상관(phase correlation)으로 앞 프레임과의 화면 이동량(dx, dy)을 구하고,
             그 이동량이 '얼마나 갑자기 바뀌는가'(가속도)로 손떨림을 잰다.
             천천히 패닝하면 이동량이 일정해서 괜찮고, 손이 흔들리면 이동 방향이 계속 바뀌어 점수가 낮다

품질 = 0.4·선명도 + 0.3·노출 + 0.3·안정 (0~1)
best_window: 말 없는 구간 안에서 품질 평균이 가장 높은 구간 (길이 BROLL_MIN~BROLL_MAX초)
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import numpy as np

from ..media.convert import gray_frames
from ..storage.cache import JsonCache

FPS = 2.0
SIZE = 128
JITTER_PX = 3.0          # 이동량 변화가 이만큼(px, 128px 기준)이면 안정 점수 약 0.37
MIN_QUALITY = 0.35       # B롤 후보로 쓰기에 이보다 나쁘면 버린다
WINDOW_MIN = 2.0
WINDOW_MAX = 5.0
VERSION = 1              # 계산 방법을 바꾸면 올린다 (캐시 이름에 들어감)


def sharpness(frames: np.ndarray) -> np.ndarray:
    f = frames.astype(np.float32)
    lap = (-4 * f[:, 1:-1, 1:-1] + f[:, :-2, 1:-1] + f[:, 2:, 1:-1] + f[:, 1:-1, :-2] + f[:, 1:-1, 2:])
    return lap.reshape(len(f), -1).var(axis=1)


def exposure(frames: np.ndarray) -> np.ndarray:
    mean = frames.reshape(len(frames), -1).mean(axis=1)
    low = np.clip((mean - 15) / 35, 0, 1)             # 15 → 0, 50 → 1
    high = np.clip((245 - mean) / 40, 0, 1)           # 205 → 1, 245 → 0
    return np.minimum(low, high)


def _hann(n: int) -> np.ndarray:
    w = np.hanning(n).astype(np.float32)
    return np.outer(w, w)


def shifts(frames: np.ndarray) -> np.ndarray:
    """앞 프레임 대비 화면 이동량 (N, 2) [dy, dx] px. 첫 프레임은 0."""
    n, h, w = frames.shape
    out = np.zeros((n, 2), np.float32)
    if n < 2:
        return out
    window = _hann(h) if h == w else np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    spectra = np.fft.fft2(frames.astype(np.float32) * window)
    for i in range(1, n):
        cross = spectra[i] * np.conj(spectra[i - 1])
        cross /= np.abs(cross) + 1e-9
        corr = np.fft.ifft2(cross).real
        dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
        out[i] = (dy - h if dy > h // 2 else dy, dx - w if dx > w // 2 else dx)
    return out


def stability(frames: np.ndarray) -> np.ndarray:
    """손떨림이 적을수록 1. 이동량의 변화(가속도) 크기로 잰다."""
    d = shifts(frames)
    jerk = np.zeros(len(d), np.float32)
    if len(d) > 2:
        jerk[2:] = np.linalg.norm(d[2:] - d[1:-1], axis=1)
        jerk[1] = jerk[2]
    smooth = np.convolve(jerk, np.ones(3) / 3, mode="same") if len(jerk) >= 3 else jerk
    return np.exp(-smooth / JITTER_PX)


def quality_curve(frames: np.ndarray) -> dict:
    """프레임 배열 → {"fps", "q": [...], "sharp": [...], "exposure": [...], "stable": [...]} (값은 0~1)."""
    if len(frames) == 0:
        return {"fps": FPS, "q": [], "sharp": [], "exposure": [], "stable": []}
    sharp = sharpness(frames)
    ref = float(np.median(sharp)) or 1.0
    sharp_n = np.clip(sharp / (1.5 * ref), 0, 1)
    expo = exposure(frames)
    stable = stability(frames)
    q = 0.4 * sharp_n + 0.3 * expo + 0.3 * stable
    r = lambda a: [round(float(x), 3) for x in a]  # noqa: E731
    return {"fps": FPS, "q": r(q), "sharp": r(sharp_n), "exposure": r(expo), "stable": r(stable)}


def clip_quality(video: Path, sha1: str, cache_dir: Path | None,
                 cancel: threading.Event | None = None) -> dict:
    """영상 하나의 품질 곡선 (같은 영상이면 캐시에서)."""
    cache = JsonCache(cache_dir)
    name = f"{sha1[:20]}_quality_v{VERSION}_{FPS:g}fps_{SIZE}.json"
    cached = cache.get(name)
    if cached is not None:
        return cached
    curve = quality_curve(gray_frames(video, fps=FPS, size=SIZE, cancel=cancel))
    cache.put(name, curve)
    return curve


def best_window(curve: dict | None, start: float, end: float, min_len: float = WINDOW_MIN,
                max_len: float = WINDOW_MAX, margin: float = 0.2) -> tuple[float, float, float | None]:
    """[start, end] 안에서 품질 평균이 가장 높은 구간 → (시작, 끝, 평균 품질). 곡선이 없으면 앞쪽, 품질 None."""
    s0, e0 = start + margin, end - margin
    length = min(max_len, e0 - s0)
    if curve is None or not curve.get("q") or length < min_len:
        return s0, min(e0, s0 + max_len), None
    fps = float(curve["fps"])
    q = np.asarray(curve["q"], np.float32)
    first, last = max(0, math.ceil(s0 * fps)), min(len(q), math.floor(e0 * fps))
    n = max(1, int(round(length * fps)))
    if last - first < n:
        return s0, s0 + length, float(q[first:last].mean()) if last > first else None
    sums = np.convolve(q[first:last], np.ones(n), mode="valid") / n
    lo = first + int(np.argmax(sums))
    hi = lo + n                                       # [lo, hi) 프레임
    keep = max(1, int(round(min_len * fps)))
    mean = float(q[lo:hi].mean())
    while hi - lo > keep:                             # 양 끝에 품질이 확 떨어지는 부분은 잘라 낸다
        if q[hi - 1] < 0.8 * mean and q[hi - 1] <= q[lo]:
            hi -= 1
        elif q[lo] < 0.8 * mean:
            lo += 1
        else:
            break
        mean = float(q[lo:hi].mean())
    s = lo / fps
    return round(s, 3), round(min(e0, hi / fps), 3), round(mean, 3)
