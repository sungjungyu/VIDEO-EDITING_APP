"""REST API (/api/...). 화면(static/js/api.js)은 이 엔드포인트만 쓴다.

프로젝트   POST/GET /projects, GET/PATCH/DELETE /projects/{pid}
클립       POST /projects/{pid}/clips (여러 개), DELETE …/clips/{cid}, GET …/clips/{cid}/file|proxy
분석       POST /projects/{pid}/analyze → 작업, GET …/analysis
편집 계획  GET/PUT /projects/{pid}/plan, PATCH …/plan/lines, POST …/select (AI 가편집), POST …/revise (채팅 수정)
렌더       POST /projects/{pid}/render → 작업, GET …/renders/{file}
작업       GET /jobs/{id}, POST /jobs/{id}/cancel, GET /projects/{pid}/jobs
기타       GET /config, GET /projects/{pid}/metrics
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..ai.gemini import GeminiClient
from ..ai.revise import revise as revise_lines
from ..ai.select import select_scenes
from ..ai.stt import whisper_available
from ..edit.planner import compile_plan, effective_decisions, flatten
from ..edit.validate import validate_plan
from ..eval.metrics import project_metrics
from ..media.ffmpeg import FFmpegError, ffmpeg_path, ffmpeg_version, probe
from ..models import ClipInfo, EditPlan, LineDecision, OutputSpec, PlanOptions, Project, Selection, StyleSpec
from ..render import fonts
from . import pipeline
from .storage import NotFound

router = APIRouter(prefix="/api")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}


def _state(request: Request):
    return request.app.state


def _project_or_404(request: Request, project_id: str) -> Project:
    try:
        return _state(request).store.get(project_id)
    except NotFound as error:
        raise HTTPException(404, str(error)) from error


def project_view(request: Request, project: Project) -> dict:
    jobs = _state(request).jobs
    data = project.model_dump()
    base = f"/api/projects/{project.project_id}"
    for clip in data["clips"]:
        clip["file_url"] = f"{base}/clips/{clip['clip_id']}/file"
        clip["proxy_url"] = f"{base}/clips/{clip['clip_id']}/proxy" if clip["proxy"] else None
    for render in data["renders"]:
        render["url"] = f"{base}/renders/{render['file']}"
    data["analysis_stale"] = project.analysis_stale
    data["active_jobs"] = [j.model_dump() for j in jobs.list(project.project_id) if not j.finished]
    return data


def plan_view(request: Request, project: Project, plan: EditPlan) -> dict:
    store = _state(request).store
    analysis = store.load_analysis(project.project_id)
    issues = validate_plan(plan, project.timeline_clips(), analysis, store.clip_files(project))
    return {"plan": plan.model_dump(), "issues": issues}


def _recompile_and_save(request: Request, project: Project, plan: EditPlan) -> EditPlan:
    store = _state(request).store
    compiled = compile_plan(plan, project.timeline_clips(), store.load_analysis(project.project_id))
    store.save_plan(project.project_id, compiled)
    return compiled


# ---------------------------------------------------------------- 설정·상태

@router.get("/config")
def get_config(request: Request) -> dict:
    settings = _state(request).settings
    try:
        ff = {"path": ffmpeg_path(), "version": ".".join(map(str, ffmpeg_version())), "ok": True}
    except FFmpegError as error:
        ff = {"ok": False, "error": str(error)}
    return {"version": __version__, **settings.public_dict(), "ffmpeg": ff, "whisper": whisper_available(),
            "font_metrics": fonts.font_metrics_table(), "fonts": fonts.available_fonts(),
            "reference_short_side": 1080}


# ---------------------------------------------------------------- 프로젝트

class ProjectCreate(BaseModel):
    name: str = "새 프로젝트"


class ClipPatch(BaseModel):
    clip_id: str
    in_point: float | None = None
    out_point: float | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    timeline: list[str] | None = None
    clips: list[ClipPatch] | None = None


@router.post("/projects")
def create_project(request: Request, body: ProjectCreate) -> dict:
    return project_view(request, _state(request).store.create(body.name))


@router.get("/projects")
def list_projects(request: Request) -> list[dict]:
    return [{"project_id": p.project_id, "name": p.name, "updated_at": p.updated_at, "clips": len(p.clips),
             "analysis": p.analysis.status} for p in _state(request).store.list()]


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> dict:
    return project_view(request, _project_or_404(request, project_id))


@router.patch("/projects/{project_id}")
def patch_project(request: Request, project_id: str, body: ProjectPatch) -> dict:
    store = _state(request).store
    project = _project_or_404(request, project_id)

    def change(p: Project):
        if body.name is not None:
            p.name = body.name.strip()[:80] or p.name
        if body.timeline is not None:
            ids = {c.clip_id for c in p.clips}
            unknown = [cid for cid in body.timeline if cid not in ids]
            if unknown or len(set(body.timeline)) != len(body.timeline):
                raise HTTPException(422, f"타임라인 클립 목록이 올바르지 않습니다: {unknown}")
            p.timeline = list(body.timeline)
        for patch in body.clips or []:
            clip = p.clip(patch.clip_id)
            if clip is None:
                raise HTTPException(404, f"클립을 찾을 수 없습니다: {patch.clip_id}")
            if patch.in_point is not None:
                clip.in_point = max(0.0, min(patch.in_point, clip.duration - 0.1))
            if patch.out_point is not None:
                clip.out_point = None if patch.out_point >= clip.duration - 0.01 else max(clip.in_point + 0.1,
                                                                                         patch.out_point)

    project = store.update(project.project_id, change)
    _recompile_and_save(request, project, store.load_plan(project_id))
    return project_view(request, project)


@router.delete("/projects/{project_id}")
def delete_project(request: Request, project_id: str) -> dict:
    state = _state(request)
    for job in state.jobs.list(project_id):
        state.jobs.cancel(job.job_id)
    try:
        state.store.delete(project_id)
    except NotFound as error:
        raise HTTPException(404, str(error)) from error
    return {"ok": True}


# ---------------------------------------------------------------- 클립

@router.post("/projects/{project_id}/clips")
async def upload_clips(request: Request, project_id: str, files: list[UploadFile] = File(...)) -> dict:
    state = _state(request)
    store, settings = state.store, state.settings
    _project_or_404(request, project_id)
    limit = settings.max_upload_mb * 1024 * 1024
    added: list[ClipInfo] = []
    for upload in files:
        suffix = Path(upload.filename or "video.mp4").suffix.lower()
        if suffix not in VIDEO_EXT:
            raise HTTPException(400, f"{upload.filename}: MP4·MOV·M4V·AVI·MKV·WEBM·3GP 영상만 올릴 수 있습니다.")
        tmp = store.project_dir(project_id) / "clips" / f".upload_{uuid.uuid4().hex[:8]}{suffix}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha1(), 0
        try:
            with open(tmp, "wb") as out:
                while chunk := await upload.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"{upload.filename}: 파일이 {settings.max_upload_mb}MB를 넘습니다.")
                    digest.update(chunk)
                    out.write(chunk)
            try:
                info = await run_in_threadpool(probe, tmp)
            except FFmpegError as error:
                raise HTTPException(400, f"{upload.filename}: 영상 정보를 읽지 못했습니다. ({error})") from error
            if not info.has_video:
                raise HTTPException(400, f"{upload.filename}: 영상 트랙이 없습니다.")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        clip = pipeline.add_clip(store, project_id, tmp, upload.filename or tmp.name, size, digest.hexdigest(), info)
        added.append(clip)
        state.jobs.submit("proxy", project_id, pipeline.run_proxy, store, project_id, clip.clip_id)
    project = store.get(project_id)
    return {"clips": [c.model_dump() for c in added], "project": project_view(request, project)}


@router.delete("/projects/{project_id}/clips/{clip_id}")
def delete_clip(request: Request, project_id: str, clip_id: str) -> dict:
    store = _state(request).store
    project = _project_or_404(request, project_id)
    clip = project.clip(clip_id)
    if clip is None:
        raise HTTPException(404, "클립을 찾을 수 없습니다.")
    analysis_job = _state(request).jobs.active(project_id, "analyze")
    if analysis_job is not None and clip_id in project.timeline:
        raise HTTPException(409, "분석 중에는 타임라인의 클립을 삭제할 수 없습니다.")

    def change(p: Project):
        p.clips = [c for c in p.clips if c.clip_id != clip_id]
        p.timeline = [cid for cid in p.timeline if cid != clip_id]

    project = store.update(project_id, change)
    store.clip_path(project_id, clip.stored_name).unlink(missing_ok=True)
    store.proxy_path(project_id, clip_id).unlink(missing_ok=True)
    _recompile_and_save(request, project, store.load_plan(project_id))
    return project_view(request, project)


def _media_response(path: Path, download_name: str | None = None) -> FileResponse:
    if not path.exists():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".mov":
        media_type = "video/quicktime"
    return FileResponse(path, media_type=media_type, filename=download_name,
                        content_disposition_type="attachment" if download_name else "inline")


@router.get("/projects/{project_id}/clips/{clip_id}/file")
def clip_file(request: Request, project_id: str, clip_id: str) -> FileResponse:
    project = _project_or_404(request, project_id)
    clip = project.clip(clip_id)
    if clip is None:
        raise HTTPException(404, "클립을 찾을 수 없습니다.")
    return _media_response(_state(request).store.clip_path(project_id, clip.stored_name))


@router.get("/projects/{project_id}/clips/{clip_id}/proxy")
def clip_proxy(request: Request, project_id: str, clip_id: str) -> FileResponse:
    _project_or_404(request, project_id)
    return _media_response(_state(request).store.proxy_path(project_id, clip_id))


# ---------------------------------------------------------------- 분석

class AnalyzeRequest(BaseModel):
    profile: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/analyze")
def analyze(request: Request, project_id: str, body: AnalyzeRequest) -> dict:
    state = _state(request)
    project = _project_or_404(request, project_id)
    if not project.timeline:
        raise HTTPException(422, "타임라인에 클립이 없습니다. 클립을 타임라인에 올린 뒤 분석하세요.")
    running = state.jobs.active(project_id, "analyze")
    if running is not None:
        return running.model_dump()
    job = state.jobs.submit("analyze", project_id, pipeline.run_analysis, state.store, state.settings, project_id,
                            body.profile)
    return job.model_dump()


@router.get("/projects/{project_id}/analysis")
def get_analysis(request: Request, project_id: str) -> dict:
    _project_or_404(request, project_id)
    analysis = _state(request).store.load_analysis(project_id)
    if analysis is None:
        raise HTTPException(404, "아직 분석하지 않았습니다.")
    return analysis.model_dump()


# ---------------------------------------------------------------- 편집 계획

class PlanUpdate(BaseModel):
    selection: Selection | None = None
    lines: dict[str, LineDecision] | None = None
    styles: dict[str, StyleSpec] | None = None
    output: OutputSpec | None = None
    options: PlanOptions | None = None


class LineChange(BaseModel):
    seg_id: str
    keep: bool | None = None
    text: str | None = None
    reset: bool = False


class LinesPatch(BaseModel):
    changes: list[LineChange]


@router.get("/projects/{project_id}/plan")
def get_plan(request: Request, project_id: str) -> dict:
    project = _project_or_404(request, project_id)
    plan = compile_plan(_state(request).store.load_plan(project_id), project.timeline_clips(),
                        _state(request).store.load_analysis(project_id))
    return plan_view(request, project, plan)


@router.put("/projects/{project_id}/plan")
def put_plan(request: Request, project_id: str, body: PlanUpdate) -> dict:
    project = _project_or_404(request, project_id)
    store = _state(request).store
    with store.lock(project_id):
        plan = store.load_plan(project_id)
        for field_name in ("selection", "lines", "styles", "output", "options"):
            value = getattr(body, field_name)
            if value is not None:
                setattr(plan, field_name, value)
        if "subtitle" not in plan.styles:
            plan.styles["subtitle"] = StyleSpec()
        compiled = _recompile_and_save(request, project, plan)
    return plan_view(request, project, compiled)


def apply_line_changes(plan: EditPlan, base: dict[str, LineDecision], changes: list[LineChange]) -> None:
    for ch in changes:
        if ch.reset:
            plan.lines.pop(ch.seg_id, None)
            continue
        current = plan.lines.get(ch.seg_id) or base.get(ch.seg_id) or LineDecision(seg_id=ch.seg_id)
        update: dict = {"source": "user"}
        if ch.keep is not None:
            update["keep"] = ch.keep
        if ch.text is not None:
            update["text"] = ch.text.strip() or None
        plan.lines[ch.seg_id] = current.model_copy(update=update)


@router.patch("/projects/{project_id}/plan/lines")
def patch_lines(request: Request, project_id: str, body: LinesPatch) -> dict:
    project = _project_or_404(request, project_id)
    store = _state(request).store
    analysis = store.load_analysis(project_id)
    if analysis is None:
        raise HTTPException(409, "먼저 분석하세요.")
    known = {line.seg_id for line in analysis.lines}
    with store.lock(project_id):
        plan = store.load_plan(project_id)
        apply_line_changes(plan, analysis.judgments, [c for c in body.changes if c.seg_id in known])
        compiled = _recompile_and_save(request, project, plan)
    return plan_view(request, project, compiled)


class SelectRequest(BaseModel):
    mode: Literal["all", "manual", "auto"] = "auto"
    target_sec: float | None = None
    user_prompt: str = ""
    locked_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    profile: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/select")
async def select(request: Request, project_id: str, body: SelectRequest) -> dict:
    state = _state(request)
    project = _project_or_404(request, project_id)
    analysis = state.store.load_analysis(project_id)
    if body.mode != "all" and analysis is None:
        raise HTTPException(409, "장면을 고르려면 먼저 분석하세요.")
    plan = state.store.load_plan(project_id)
    engine, warnings = "user", []
    if body.mode == "all":
        plan.selection = Selection(mode="all")
    elif body.mode == "manual":
        known = flatten(analysis.tree)
        plan.selection = plan.selection.model_copy(update={
            "mode": "manual", "node_ids": [i for i in body.node_ids if i in known],
            "locked_ids": [i for i in body.locked_ids if i in known], "target_sec": body.target_sec,
            "user_prompt": body.user_prompt})
    else:
        if not body.target_sec or body.target_sec <= 0:
            raise HTTPException(422, "목표 분량(초)을 입력하세요.")
        client = GeminiClient(state.settings, state.store.cache_dir / "ai")
        decisions = effective_decisions(plan, analysis)
        clips = {c.clip_id: c for c in project.timeline_clips()}
        plan.options = pipeline.apply_profile(plan.options, body.profile)
        selection, engine, warnings = await run_in_threadpool(
            select_scenes, analysis, clips, plan, decisions, body.target_sec, body.user_prompt, body.locked_ids,
            body.profile, client)
        plan.selection = selection
    compiled = _recompile_and_save(request, project, plan)
    view = plan_view(request, project, compiled)
    view.update({"engine": engine, "warnings": warnings})
    return view


class ReviseRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    profile: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/revise")
async def revise(request: Request, project_id: str, body: ReviseRequest) -> dict:
    state = _state(request)
    project = _project_or_404(request, project_id)
    analysis = state.store.load_analysis(project_id)
    if analysis is None:
        raise HTTPException(409, "먼저 분석하세요.")
    plan = state.store.load_plan(project_id)
    decisions = effective_decisions(plan, analysis)
    client = GeminiClient(state.settings, state.store.cache_dir / "ai")
    changes, message, engine = await run_in_threadpool(revise_lines, body.instruction, analysis.lines, decisions,
                                                       body.profile, client)
    with state.store.lock(project_id):
        plan = state.store.load_plan(project_id)
        line_changes = [LineChange(seg_id=sid, keep=c.get("keep"), text=c.get("text")) for sid, c in changes.items()]
        apply_line_changes(plan, analysis.judgments, line_changes)
        compiled = _recompile_and_save(request, project, plan)
    view = plan_view(request, project, compiled)
    view.update({"message": message, "changed": len(changes), "engine": engine})
    return view


# ---------------------------------------------------------------- 렌더

class RenderRequest(BaseModel):
    quality: Literal["preview", "final"] = "final"


@router.post("/projects/{project_id}/render")
def render(request: Request, project_id: str, body: RenderRequest) -> dict:
    state = _state(request)
    project = _project_or_404(request, project_id)
    plan = compile_plan(state.store.load_plan(project_id), project.timeline_clips(),
                        state.store.load_analysis(project_id))
    errors = [i for i in validate_plan(plan, project.timeline_clips(), state.store.load_analysis(project_id),
                                       state.store.clip_files(project)) if i["level"] == "error"]
    if errors:
        raise HTTPException(422, " / ".join(e["message"] for e in errors[:3]))
    job = state.jobs.submit("render", project_id, pipeline.run_render, state.store, project_id, body.quality)
    return job.model_dump()


@router.get("/projects/{project_id}/renders/{file_name}")
def get_render(request: Request, project_id: str, file_name: str) -> FileResponse:
    project = _project_or_404(request, project_id)
    render_info = next((r for r in project.renders if r.file == Path(file_name).name), None)
    if render_info is None:
        raise HTTPException(404, "결과 영상을 찾을 수 없습니다.")
    label = "미리보기" if render_info.quality == "preview" else "최종"
    safe_name = "".join(ch for ch in project.name if ch not in '\\/:*?"<>|').strip() or "vibecut"
    return _media_response(_state(request).store.render_path(project_id, render_info.file),
                           f"{safe_name}_{label}_{render_info.render_id}.mp4")


# ---------------------------------------------------------------- 작업

@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict:
    job = _state(request).jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job.model_dump()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict:
    job = _state(request).jobs.cancel(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job.model_dump()


@router.get("/projects/{project_id}/jobs")
def project_jobs(request: Request, project_id: str) -> list[dict]:
    _project_or_404(request, project_id)
    return [j.model_dump() for j in _state(request).jobs.list(project_id)[:30]]


# ---------------------------------------------------------------- 평가 지표

@router.get("/projects/{project_id}/metrics")
def metrics(request: Request, project_id: str) -> dict:
    state = _state(request)
    project = _project_or_404(request, project_id)
    analysis = state.store.load_analysis(project_id)
    plan = compile_plan(state.store.load_plan(project_id), project.timeline_clips(), analysis)
    return project_metrics(project, analysis, plan, state.jobs.list(project_id))
