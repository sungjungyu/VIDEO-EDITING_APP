"""클립 오디오: 분석·파형이 함께 쓰는 16kHz WAV와 타임라인 오디오 트랙 파형."""

from __future__ import annotations

from pathlib import Path

from ..analysis.audio import waveform_peaks
from ..domain.models import ClipInfo
from ..errors import NotFound
from ..media.convert import extract_audio
from ..storage.cache import JsonCache
from ..storage.projects import ProjectStore

WAVEFORM_RATE = 50          # 파형: 1초에 50개 (20ms마다 가장 큰 소리)


def audio_wav(store: ProjectStore, project_id: str, clip: ClipInfo) -> Path | None:
    """클립의 16kHz 모노 WAV (data/cache/audio, 분석과 파형이 같은 파일을 쓴다). 소리가 없으면 None."""
    wav = store.cache_dir / "audio" / f"{clip.sha1[:20]}.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    ok = clip.has_audio and extract_audio(store.clip_path(project_id, clip.stored_name), wav)
    return wav if ok else None


def clip_waveform(store: ProjectStore, project_id: str, clip_id: str) -> dict:
    """타임라인 오디오 트랙 파형 {"rate": 1초당 개수, "peaks": [0~255, …]} (클립 초 기준). 한 번 만들면 캐시."""
    clip = store.get(project_id).clip(clip_id)
    if clip is None:
        raise NotFound("클립을 찾을 수 없습니다.")
    cache = JsonCache(store.cache_dir / "waveform")
    name = f"{clip.sha1[:20]}_{WAVEFORM_RATE}.json"
    cached = cache.get(name)
    if cached is not None:
        return cached
    wav = audio_wav(store, project_id, clip)
    data = {"rate": WAVEFORM_RATE, "peaks": waveform_peaks(wav, WAVEFORM_RATE) if wav else []}
    cache.put(name, data)
    return data
