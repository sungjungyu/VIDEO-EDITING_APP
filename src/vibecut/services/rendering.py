"""렌더 작업과 브라우저 미리보기 사본(프록시) 작업."""

from __future__ import annotations

import uuid

from ..domain.models import RenderInfo
from ..editing.planner import compile_plan, validate_plan
from ..media.convert import make_proxy
from ..media.probe import MediaInfo
from ..render.renderer import render_plan
from ..storage.projects import ProjectStore
from .context import RunContext

MAX_FINAL_RENDERS = 10
MAX_PREVIEW_RENDERS = 3


def run_render(ctx: RunContext, store: ProjectStore, project_id: str, quality: str) -> dict:
    project = store.get(project_id)
    clips = project.timeline_clips()
    analysis = store.load_analysis(project_id)
    plan = compile_plan(store.load_plan(project_id), clips, analysis)
    files = store.clip_files(project)
    errors = [i["message"] for i in validate_plan(plan, clips, analysis, files) if i["level"] == "error"]
    if errors:
        raise ValueError("렌더 전 검사 실패: " + " / ".join(errors[:3]))
    render_id = uuid.uuid4().hex[:10]
    out = store.render_path(project_id, f"{render_id}_{quality}.mp4")
    ctx.progress(2, "렌더링", f"구간 {len(plan.keep)}개, {plan.duration:.1f}초")
    with ctx.stage("render"):
        result = render_plan(plan, {c.clip_id: c for c in clips}, files, quality, out,
                             store.work_dir(project_id, f"render_{render_id}"), ctx.sub(2, 99, "렌더링"), ctx.cancel)
    info = RenderInfo(render_id=render_id, quality=quality, file=out.name, **result)

    def add(p):
        p.renders.insert(0, info)
        kept = []
        counts: dict[str, int] = {}
        limits = {"final": MAX_FINAL_RENDERS, "preview": MAX_PREVIEW_RENDERS}
        for r in p.renders:
            limit = limits.get(r.quality, MAX_FINAL_RENDERS)
            if counts.get(r.quality, 0) < limit:
                counts[r.quality] = counts.get(r.quality, 0) + 1
                kept.append(r)
            else:
                store.render_path(project_id, r.file).unlink(missing_ok=True)
        p.renders[:] = kept

    store.update(project_id, add)
    ctx.metrics.update({"render_x_realtime": round(result["elapsed_sec"] / max(result["duration"], 0.1), 2)})
    return {"render": info.model_dump()}


# ---------------------------------------------------------------- 미리보기 사본

def run_proxy(ctx: RunContext, store: ProjectStore, project_id: str, clip_id: str) -> dict:
    project = store.get(project_id)
    clip = project.clip(clip_id)
    if clip is None:
        raise ValueError("클립이 삭제되었습니다.")
    info = MediaInfo(duration=clip.duration, width=clip.width, height=clip.height, fps=clip.fps,
                     has_video=clip.has_video, has_audio=clip.has_audio, hdr=clip.hdr)
    dst = store.proxy_path(project_id, clip_id)
    make_proxy(store.clip_path(project_id, clip.stored_name), dst, info, 540, ctx.sub(0, 100, "미리보기 사본"),
               ctx.cancel)

    def mark(p):
        c = p.clip(clip_id)
        if c is not None:
            c.proxy = True

    store.update(project_id, mark)
    return {"clip_id": clip_id}
