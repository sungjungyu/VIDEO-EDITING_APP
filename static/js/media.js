/* 클립 목록·업로드·썸네일·출력 비율.
   업로드한 파일은 서버 프로젝트에 남는다 (새로고침해도 유지). 같은 세션에서는 로컬 파일(blob)로 바로 재생하고,
   서버가 540p 미리보기 사본(프록시)을 만들면 그것을 쓴다 (어디로 이동해도 빨리 보임). */

import { api } from "./api.js";
import { clipById, emit, mutatePlan, on, pid, setProject, state } from "./store.js";
import { el, fmt, toast } from "./util.js";

export function mediaUrl(clip) {
  if (!clip) return "";
  return clip.proxy_url || state.media.get(clip.clip_id)?.blobUrl || clip.file_url;
}

/* ---------------------------------------------------------------- 썸네일 */

const thumbJobs = new Map();

export function ensureThumbnails(clip) {
  if (!clip || thumbJobs.has(clip.clip_id)) return thumbJobs.get(clip?.clip_id);
  const job = makeThumbnails(clip).catch(() => null);
  thumbJobs.set(clip.clip_id, job);
  return job;
}

async function makeThumbnails(clip) {
  const info = state.media.get(clip.clip_id) || {};
  const url = info.blobUrl || clip.proxy_url || clip.file_url;
  const THUMB_H = 48, THUMB_W = Math.round(THUMB_H * 16 / 9), MAX = 30;
  const interval = Math.max(0.5, clip.duration / MAX);
  const video = document.createElement("video");
  video.src = url; video.muted = true; video.playsInline = true; video.preload = "auto";
  await new Promise((resolve, reject) => {
    video.onloadedmetadata = resolve;
    video.onerror = reject;
    setTimeout(resolve, 8000);
  });
  const canvas = document.createElement("canvas");
  canvas.width = THUMB_W; canvas.height = THUMB_H;
  const ctx = canvas.getContext("2d");
  const thumbs = [];
  for (let t = 0; t < clip.duration && thumbs.length < MAX; t += interval) {
    video.currentTime = Math.min(t, clip.duration - 0.05);
    const ok = await new Promise(r => { video.onseeked = () => r(true); setTimeout(() => r(false), 3000); });
    if (!ok) break;
    try { ctx.drawImage(video, 0, 0, THUMB_W, THUMB_H); thumbs.push(canvas.toDataURL("image/jpeg", 0.55)); }
    catch (e) { break; }
  }
  video.removeAttribute("src"); video.load();
  state.media.set(clip.clip_id, { ...(state.media.get(clip.clip_id) || {}), thumbnails: thumbs, thumbInterval: interval,
                                   thumbW: THUMB_W });
  emit("thumbnails", clip.clip_id);
  return thumbs;
}

/* ---------------------------------------------------------------- 업로드 */

export async function uploadFiles(files) {
  const videos = files.filter(f => f.type.startsWith("video/") || /\.(mp4|mov|m4v|avi|mkv|webm|3gp)$/i.test(f.name));
  if (!videos.length) { toast("영상 파일만 올릴 수 있습니다.", "error"); return; }
  for (const file of videos) {
    const pending = { name: file.name, progress: 0 };
    state.pendingUploads.push(pending);
    renderClipList();
    emit("uploads");
    try {
      const data = await api.uploadClip(pid(), file, p => { pending.progress = p; updatePending(pending); });
      const clip = data.clips[0];
      state.media.set(clip.clip_id, { ...(state.media.get(clip.clip_id) || {}), blobUrl: URL.createObjectURL(file) });
      setProject(data.project);
      ensureThumbnails(clipById(clip.clip_id));
    } catch (err) {
      toast(`${file.name}: ${err.message}`, "error", 7000);
    } finally {
      state.pendingUploads.splice(state.pendingUploads.indexOf(pending), 1);
      renderClipList();
      emit("uploads");
    }
  }
}

function updatePending(pending) {
  const bar = document.querySelector(`[data-pending="${CSS.escape(pending.name)}"] .clip-upload-bar > div`);
  if (bar) bar.style.width = `${Math.round(pending.progress * 100)}%`;
}

/* ---------------------------------------------------------------- 타임라인에 넣기·빼기 */

export async function setTimeline(ids) {
  try {
    setProject(await api.patchProject(pid(), { timeline: ids }));
    emit("timeline-changed");
  } catch (err) {
    toast(err.message, "error");
  }
}

export function addToTimeline(clipId, index = null) {
  const ids = state.project.timeline.filter(id => id !== clipId);
  ids.splice(index === null ? ids.length : index, 0, clipId);
  return setTimeline(ids);
}

export function removeFromTimeline(clipId) {
  return setTimeline(state.project.timeline.filter(id => id !== clipId));
}

async function deleteClip(clip) {
  if (!window.confirm(`"${clip.filename}"을(를) 프로젝트에서 삭제할까요? (원본 파일도 서버에서 지워집니다)`)) return;
  try {
    setProject(await api.deleteClip(pid(), clip.clip_id));
    const info = state.media.get(clip.clip_id);
    if (info?.blobUrl) URL.revokeObjectURL(info.blobUrl);
    state.media.delete(clip.clip_id);
    emit("timeline-changed");
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ---------------------------------------------------------------- 목록 */

export let draggingClipId = null;

function statusOf(clip) {
  const onTimeline = state.project.timeline.includes(clip.clip_id);
  const analyzed = state.analysis?.clips?.some(s => s.clip_id === clip.clip_id);
  if (!onTimeline) return ["ready", "대기"];
  if (analyzed && !state.project.analysis_stale) return ["analyzed", "분석 완료"];
  return ["review", "타임라인"];
}

export function renderClipList() {
  const list = document.getElementById("clip-list");
  list.innerHTML = "";
  const clips = state.project?.clips || [];
  if (!clips.length && !state.pendingUploads.length) {
    list.appendChild(el("div", { style: { color: "var(--muted)", fontSize: "11px", textAlign: "center",
                                          padding: "20px 0" } }, "영상을 추가하면 여기에 표시됩니다"));
    return;
  }
  for (const clip of clips) {
    const [badgeClass, badgeText] = statusOf(clip);
    const first = state.media.get(clip.clip_id)?.thumbnails?.[0];
    const thumb = first ? el("img", { class: "clip-thumb", src: first, alt: "" }) : el("div", { class: "clip-thumb" });
    const item = el("div", { class: "clip-item" + (state.project.timeline.includes(clip.clip_id) ? " on-timeline" : ""),
                             draggable: "true", dataset: { id: clip.clip_id } },
      el("div", { class: "clip-thumb-wrap" }, thumb),
      el("div", { class: "clip-info" },
        el("div", { class: "clip-name", title: clip.filename }, clip.filename),
        el("div", { class: "clip-meta" },
          el("span", { class: `clip-status-badge badge-${badgeClass}` }, badgeText),
          el("span", { class: "clip-dur" }, fmt(clip.duration)),
          clip.proxy ? null : el("span", { class: "clip-dur", title: "브라우저 미리보기용 사본을 만드는 중" }, "· 사본 준비 중"))),
      el("button", { class: "clip-add-btn", title: "타임라인 끝에 추가",
                     onclick: e => { e.stopPropagation(); addToTimeline(clip.clip_id); } }, "+"),
      el("button", { class: "clip-delete-btn", title: "삭제",
                     onclick: e => { e.stopPropagation(); deleteClip(clip); } }, "🗑"));
    item.addEventListener("dragstart", e => { draggingClipId = clip.clip_id; e.dataTransfer.effectAllowed = "copy"; });
    item.addEventListener("dragend", () => { draggingClipId = null; });
    item.addEventListener("dblclick", () => emit("preview-clip", { clipId: clip.clip_id, time: 0 }));
    list.appendChild(item);
  }
  for (const pending of state.pendingUploads) {
    list.appendChild(el("div", { class: "clip-item", dataset: { pending: pending.name } },
      el("div", { class: "clip-info" },
        el("div", { class: "clip-name" }, pending.name),
        el("div", { class: "clip-meta" }, el("span", { class: "clip-status-badge badge-uploading" }, "업로드 중")),
        el("div", { class: "clip-upload-bar" }, el("div", { style: { width: `${Math.round(pending.progress * 100)}%` } })))));
  }
}

/* ---------------------------------------------------------------- 초기화 */

export function initMedia() {
  const input = document.getElementById("file-input");
  const button = document.getElementById("upload-btn");
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", e => { if (e.target.files.length) uploadFiles(Array.from(e.target.files)); input.value = ""; });
  button.addEventListener("dragover", e => { e.preventDefault(); button.style.borderColor = "var(--accent)"; });
  button.addEventListener("dragleave", () => { button.style.borderColor = ""; });
  button.addEventListener("drop", e => {
    e.preventDefault(); button.style.borderColor = "";
    uploadFiles(Array.from(e.dataTransfer.files));
  });
  document.getElementById("btn-sort-clips").addEventListener("click", () => {
    const sorted = [...state.project.timeline].map(clipById).filter(Boolean)
      .sort((a, b) => (a.created_at ?? Infinity) - (b.created_at ?? Infinity) || a.filename.localeCompare(b.filename));
    setTimeline(sorted.map(c => c.clip_id));
  });
  document.querySelectorAll(".aspect-btn").forEach(btn => btn.addEventListener("click", async () => {
    if (!state.plan || state.plan.output.aspect === btn.dataset.ratio) return;
    try {
      await mutatePlan(() => api.putPlan(pid(), { output: { ...state.plan.output, aspect: btn.dataset.ratio } }));
    } catch (err) { toast(err.message, "error"); }
  }));
  on("project", () => {
    renderClipList();
    for (const clip of state.project.clips) ensureThumbnails(clip);
  });
  on("analysis", renderClipList);
  on("thumbnails", renderClipList);
  on("plan", () => {
    document.querySelectorAll(".aspect-btn").forEach(b => b.classList.toggle("active", b.dataset.ratio === state.plan.output.aspect));
  });
}
