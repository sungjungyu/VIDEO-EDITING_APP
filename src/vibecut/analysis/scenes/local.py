"""화면 변화 감지로 장면 나누기 (오프라인·키 없음·Gemini 실패 시). 장소·활동 이름은 모른다."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from ...media.convert import gray_frames

MIN_SCENE_SEC = 8.0


def local_scenes(video: Path, duration: float, min_sec: float = MIN_SCENE_SEC,
                 cancel: threading.Event | None = None) -> list[dict]:
    """화면 변화 감지. 경계 = 앞 화면과 평균 밝기 차이가 '평균 + 2.5×표준편차'(최소 12)를 넘는 곳."""
    frames = gray_frames(video, fps=1.0, size=64, cancel=cancel).astype(np.float32)
    if len(frames) < 2:
        return [{"start": 0.0, "end": duration}]
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    threshold = max(12.0, float(diffs.mean() + 2.5 * diffs.std()))
    cuts = [0.0] + [float(i + 1) for i, d in enumerate(diffs) if d >= threshold] + [duration]
    scenes = []
    for s, e in zip(cuts, cuts[1:]):
        e = min(e, duration)
        if e <= s:
            continue
        if scenes and (e - s < min_sec or scenes[-1]["end"] - scenes[-1]["start"] < min_sec):
            scenes[-1]["end"] = e
        else:
            scenes.append({"start": s, "end": e})
    if len(scenes) > 1 and scenes[-1]["end"] - scenes[-1]["start"] < min_sec:
        last = scenes.pop()
        scenes[-1]["end"] = last["end"]
    return scenes
