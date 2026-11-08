"""배경음악 파일.

기본 곡 (앱에 들어 있는 곡, 저장소에 함께 올라간다)
    assets/music/tracks.json   [{"id", "title", "mood": 잔잔|경쾌|감성|웃김, "file", "source", "license", "url"?}, ...]
    assets/music/<file>        음원 (CC0 등 앱에 넣어 배포해도 되는 곡만 — 곡마다 출처·라이선스를 tracks.json에)
내 음악 (사용자가 올린 파일): data/projects/{pid}/music/ — 프로젝트와 함께 서버를 켜고 끌 때 지워진다
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from ..errors import NotFound
from .files import read_json

log = logging.getLogger("vibecut.storage.music")
MUSIC_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac")


class Track(BaseModel):
    id: str
    title: str
    mood: str = "잔잔"
    file: str
    source: str = ""
    license: str = ""
    url: str = ""


class MusicLibrary:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def tracks(self) -> list[Track]:
        """tracks.json에 있고 파일도 있는 곡만."""
        index = self.directory / "tracks.json"
        if not index.exists():
            return []
        try:
            items = [Track.model_validate(t) for t in read_json(index)]
        except (OSError, ValueError) as error:
            log.warning("tracks.json을 읽지 못했습니다: %s", error)
            return []
        return [t for t in items if (self.directory / Path(t.file).name).exists()]

    def track(self, track_id: str) -> Track:
        found = next((t for t in self.tracks() if t.id == track_id), None)
        if found is None:
            raise NotFound(f"기본 곡이 없습니다: {track_id}")
        return found

    def path(self, track_id: str) -> Path:
        return self.directory / Path(self.track(track_id).file).name
