"""음량과 무음: 16kHz 모노 WAV에서 프레임별 음량(dB)을 재고 무음 구간을 찾는다.

Whisper 단어 시각은 문장 앞뒤에서 크게 틀린다 (실측: 첫 단어 시작이 앞 무음까지 최대 1.1초 당겨짐,
문장 끝이 뒤 무음까지 0.6초 늘어남, 말 시작보다 0.2초 늦게 시작해 앞소리가 잘림).
오디오에서 무음 구간을 직접 찾아, 무음 경계에 단어 경계를 맞춘다 (stt.postprocess.refine_with_silence).

무음 기준을 고정값(-35dB 등)으로 두면 배경 소음이 있을 때 무음이 잘게 쪼개지거나 아예 안 잡힌다.
그래서 클립마다 음량 분포를 보고 기준을 자동으로 정한다:
    배경 소음 = 하위 10% 음량, 말소리 = 상위 10% 음량, 기준 = 소음 + max(6dB, 둘 차이의 30%)

음량 계산은 WAV 전체를 읽으므로 클립마다 한 번만 하고(frame_levels) 결과를 넘겨 쓴다.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

FRAME_SEC = 0.05  # 음량 측정 단위(초)

Silence = tuple[float, float]


def wav_duration(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def read_samples(wav: Path) -> tuple[np.ndarray, int]:
    """16bit 모노 WAV → (-1~1 float32 배열, 샘플레이트)."""
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return x, sr


def frame_levels(wav: Path, frame_sec: float = FRAME_SEC) -> np.ndarray:
    """16bit 모노 WAV를 frame_sec 단위로 잘라 프레임별 음량(RMS, dB)을 돌려준다."""
    x, sr = read_samples(wav)
    n = int(sr * frame_sec)
    if len(x) < n:
        return np.zeros(0)
    x = x[: len(x) // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((x ** 2).mean(axis=1)) + 1e-10)


def auto_threshold(db: np.ndarray, ratio: float = 0.3, min_gap_db: float = 6.0, below_loud_db: float = 10.0) -> float:
    """쉬는 구간이 10%도 안 되게 계속 말하면 '하위 10%'가 말소리가 되어 기준이 말소리보다 높아지고
    전체가 무음으로 잡힌다. 그래서 기준은 말소리보다 최소 below_loud_db 아래로 제한한다."""
    floor = max(float(np.percentile(db, 10)), -70.0)
    loud = float(np.percentile(db, 90))
    return min(floor + max(min_gap_db, (loud - floor) * ratio), loud - below_loud_db)


def find_silences(db: np.ndarray, min_sec: float, threshold: float,
                  frame_sec: float = FRAME_SEC) -> list[tuple[float, float]]:
    """threshold보다 작은 프레임이 min_sec 이상 이어지는 구간 [(start, end), ...] (초)."""
    out, start = [], None
    for i, quiet in enumerate(np.append(db < threshold, False)):
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            if (i - start) * frame_sec >= min_sec - 1e-9:
                out.append((round(start * frame_sec, 3), round(i * frame_sec, 3)))
            start = None
    return out


def detect_silences(source: Path | np.ndarray, min_sec: float,
                    noise_db: float | None = None) -> tuple[list[Silence], float | None]:
    """무음 구간과 실제로 쓴 기준(dB)을 돌려준다. source는 WAV 경로 또는 이미 잰 frame_levels 결과.
    noise_db를 주면 자동 대신 그 값을 쓴다."""
    db = frame_levels(source) if isinstance(source, Path) else source
    if db.size == 0:
        return [], None
    threshold = noise_db if noise_db is not None else auto_threshold(db)
    return find_silences(db, min_sec, threshold), round(threshold, 1)
