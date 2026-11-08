"""배경음악 사용 사례: 고를 수 있는 곡(기본 곡 + 추천), 내 음악 저장, 렌더할 때 쓸 파일 찾기."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..domain.models import EditPlan, MusicSpec, Project
from ..editing.music import recommend_mood
from ..errors import NotFound
from ..storage.music import MusicLibrary
from ..storage.projects import ProjectStore
from .editing import edit_plan

USER_FILE = "user"          # 프로젝트 music/ 안의 내 음악 파일 이름 (확장자는 원본 그대로)


def _user_file(store: ProjectStore, project_id: str) -> Path | None:
    folder = store.project_dir(project_id) / "music"
    return next(iter(sorted(folder.glob(f"{USER_FILE}.*"))), None) if folder.exists() else None


def music_choices(store: ProjectStore, library: MusicLibrary, project_id: str) -> dict:
    """{"tracks": 기본 곡 목록, "recommended": 장면 분위기에 맞는 곡 id, "mood", "user": 올린 파일 이름 또는 None}"""
    store.get(project_id)
    tracks = library.tracks()
    analysis = store.load_analysis(project_id)
    mood = recommend_mood(analysis.scenes) if analysis else None
    recommended = next((t.id for t in tracks if mood and t.mood == mood), None)
    plan = store.load_plan(project_id)
    user = _user_file(store, project_id)
    return {"tracks": [t.model_dump() for t in tracks], "recommended": recommended, "mood": mood,
            "user": (plan.music.title or user.name) if user else None}


def save_user_music(store: ProjectStore, project_id: str, uploaded: Path, filename: str) -> tuple[Project, EditPlan]:
    """올린 음악을 프로젝트 music/user.<확장자>로 두고(예전 것은 지움) 배경음악을 '내 음악'으로 바꾼다."""
    folder = store.project_dir(project_id) / "music"
    folder.mkdir(parents=True, exist_ok=True)
    old = _user_file(store, project_id)
    if old is not None:
        old.unlink(missing_ok=True)
    target = folder / f"{USER_FILE}{uploaded.suffix.lower()}"
    shutil.move(str(uploaded), target)

    def change(plan: EditPlan):
        plan.music = plan.music.model_copy(update={"source": "user", "track": target.name,
                                                   "title": Path(filename).stem[:60]})
    return edit_plan(store, project_id, change)


def music_file(store: ProjectStore, library: MusicLibrary, project_id: str, music: MusicSpec) -> Path | None:
    """렌더에 쓸 음악 파일. 없음이거나 파일을 찾지 못하면 None (음악 없이 만든다)."""
    if music.source == "user":
        return _user_file(store, project_id)
    if music.source == "library" and music.track:
        try:
            return library.path(music.track)
        except NotFound:
            return None
    return None
