"""프로젝트·타임라인·클립 (웹 업로드·명령줄 공통)."""

from __future__ import annotations

from pathlib import Path

from ..domain.models import ClipInfo, Project
from ..errors import BadRequest, Conflict, NotFound
from ..media.probe import MediaInfo
from ..storage.projects import ProjectStore
from .editing import edit_plan, recompile_and_save
from .jobs import JobManager


def import_clip(store: ProjectStore, project_id: str, tmp: Path, original_name: str, size: int, sha1: str,
                info: MediaInfo, add_to_timeline: bool = False) -> ClipInfo:
    """프로젝트 clips 폴더에 받아 둔 임시 파일을 클립으로 등록한다."""
    holder: dict = {}

    def add(p: Project):
        clip_id = store.next_clip_id(p)
        final = store.clip_path(project_id, f"{clip_id}{tmp.suffix.lower()}")
        tmp.replace(final)
        clip = ClipInfo(clip_id=clip_id, filename=Path(original_name).name[:120], stored_name=final.name,
                        duration=info.duration, width=info.width, height=info.height, fps=info.fps,
                        has_audio=info.has_audio, has_video=info.has_video, created_at=info.created_at,
                        size_bytes=size, sha1=sha1)
        p.clips.append(clip)
        if add_to_timeline:
            p.timeline.append(clip_id)
        holder["clip"] = clip

    store.update(project_id, add)
    return holder["clip"]


def update_project(store: ProjectStore, project_id: str, name: str | None = None, timeline: list[str] | None = None,
                   clip_ranges: list[tuple[str, float | None, float | None]] | None = None) -> Project:
    """이름·타임라인 순서·클립 사용 범위(clip_id, 시작, 끝)를 바꾸고 편집 계획을 다시 계산한다."""
    store.get(project_id)

    def change(p: Project):
        if name is not None:
            p.name = name.strip()[:80] or p.name
        if timeline is not None:
            ids = {c.clip_id for c in p.clips}
            unknown = [cid for cid in timeline if cid not in ids]
            if unknown or len(set(timeline)) != len(timeline):
                raise BadRequest(f"타임라인 클립 목록이 올바르지 않습니다: {unknown}")
            p.timeline = list(timeline)
        for clip_id, in_point, out_point in clip_ranges or []:
            clip = p.clip(clip_id)
            if clip is None:
                raise NotFound(f"클립을 찾을 수 없습니다: {clip_id}")
            if in_point is not None:
                clip.in_point = max(0.0, min(in_point, clip.duration - 0.1))
            if out_point is not None:
                clip.out_point = None if out_point >= clip.duration - 0.01 else max(clip.in_point + 0.1, out_point)

    project = store.update(project_id, change)
    edit_plan(store, project_id)
    return project


def delete_project(store: ProjectStore, jobs: JobManager, project_id: str) -> None:
    for job in jobs.list(project_id):
        jobs.cancel(job.job_id)
    store.delete(project_id)


def delete_clip(store: ProjectStore, jobs: JobManager, project_id: str, clip_id: str) -> Project:
    project = store.get(project_id)
    clip = project.clip(clip_id)
    if clip is None:
        raise NotFound("클립을 찾을 수 없습니다.")
    if jobs.active(project_id, "analyze") is not None and clip_id in project.timeline:
        raise Conflict("분석 중에는 타임라인의 클립을 삭제할 수 없습니다.")

    def change(p: Project):
        p.clips = [c for c in p.clips if c.clip_id != clip_id]
        p.timeline = [cid for cid in p.timeline if cid != clip_id]

    project = store.update(project_id, change)
    store.clip_path(project_id, clip.stored_name).unlink(missing_ok=True)
    store.proxy_path(project_id, clip_id).unlink(missing_ok=True)
    recompile_and_save(store, project, store.load_plan(project_id))
    return project


def sort_timeline_by_shooting_time(store: ProjectStore, project_id: str) -> Project:
    """촬영 시각 → 파일 이름 순으로 타임라인을 다시 놓는다 (명령줄 --sort)."""
    return store.update(project_id, lambda p: setattr(p, "timeline", [c.clip_id for c in sorted(
        p.timeline_clips(), key=lambda c: (c.created_at or 0, c.filename))]))
