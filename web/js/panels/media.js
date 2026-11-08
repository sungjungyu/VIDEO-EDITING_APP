/* 왼쪽 영상 패널: 업로드·올린 영상 목록·썸네일·선택한 클립 정보.
   올린 영상은 바로 타임라인 끝에 붙인다 (처음 쓰는 사람이 '타임라인에 넣기'를 따로 몰라도 되게).
   업로드한 파일은 서버가 켜져 있는 동안 프로젝트에 남는다 (새로고침해도 유지, 서버를 켜거나 끄면 지운다).
   같은 세션에서는 로컬 파일(blob)로 바로 재생하고,
   서버가 540p 미리보기 사본(프록시)을 만들면 그것을 쓴다 (어디로 이동해도 빨리 보임). */

import { api } from "../core/api.js";
import { $, el, toast } from "../core/dom.js";
import { fmt } from "../core/format.js";
import { clipById, emit, on, pid, setProject, state } from "../core/store.js";

export function mediaUrl(clip) {
  if (!clip) return "";
  return clip.proxy_url || state.media.get(clip.clip_id)?.blobUrl || clip.file_url;
}

/* ---------------------------------------------------------------- 썸네일 */

const thumbJobs = new Map();
let generation = 0;

/* 다른 프로젝트를 열 때: clip_id(c01…)는 프로젝트마다 다시 시작하므로 이전 프로젝트의 blob·썸네일을 버린다 */
export function resetMedia() {
  for (const info of state.media.values()) if (info.blobUrl) URL.revokeObjectURL(info.blobUrl);
  state.media.clear();
  thumbJobs.clear();
  generation += 1;
}

function ensureThumbnails(clip) {
  if (!clip || thumbJobs.has(clip.clip_id)) return thumbJobs.get(clip?.clip_id);
  const job = makeThumbnails(clip).catch(() => null);
  thumbJobs.set(clip.clip_id, job);
  return job;
}

async function makeThumbnails(clip) {
  const started = generation;
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
  if (started !== generation) return thumbs;        // 만드는 사이 다른 프로젝트를 열었다
  state.media.set(clip.clip_id, { ...(state.media.get(clip.clip_id) || {}), thumbnails: thumbs, thumbInterval: interval,
                                   thumbW: THUMB_W });
  emit("thumbnails", clip.clip_id);
  return thumbs;
}

/* ---------------------------------------------------------------- 업로드 */

async function uploadFiles(files) {
  const extensions = state.config?.video_extensions || [];
  const videos = files.filter(f => f.type.startsWith("video/")
                                   || extensions.some(ext => f.name.toLowerCase().endsWith(ext)));
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
      if (!state.project.timeline.includes(clip.clip_id)) await addToTimeline(clip.clip_id);
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
  if (!window.confirm(`"${clip.filename}"을(를) 프로젝트에서 지울까요? (서버에 올린 파일도 지워집니다)`)) return;
  try {
    setProject(await api.deleteClip(pid(), clip.clip_id));
    const info = state.media.get(clip.clip_id);
    if (info?.blobUrl) URL.revokeObjectURL(info.blobUrl);
    state.media.delete(clip.clip_id);
    if (state.ui.selectedClipId === clip.clip_id) { state.ui.selectedClipId = null; emit("selection"); }
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
  if (!onTimeline) return ["off", "타임라인 밖"];
  if (analyzed && !state.project.analysis_stale) return ["done", "분석 완료"];
  return ["on", "타임라인"];
}

function renderClipList() {
  const list = $("clip-list");
  list.innerHTML = "";
  const clips = state.project?.clips || [];
  if (!clips.length && !state.pendingUploads.length) {
    list.appendChild(el("div", { class: "clip-empty" }, "아직 올린 영상이 없어요.\n위 상자를 눌러 시작하세요."));
    return;
  }
  for (const clip of clips) {
    const [kind, label] = statusOf(clip);
    const onTimeline = state.project.timeline.includes(clip.clip_id);
    const first = state.media.get(clip.clip_id)?.thumbnails?.[0];
    const thumb = first ? el("img", { class: "clip-thumb", src: first, alt: "" }) : el("div", { class: "clip-thumb" });
    const item = el("div", { class: `clip-item${clip.clip_id === state.ui.selectedClipId ? " selected" : ""}`,
                             draggable: "true", dataset: { id: clip.clip_id },
                             title: "타임라인으로 끌어 놓을 수 있어요 · 두 번 누르면 미리보기" },
      el("div", { class: "clip-thumb-wrap" }, thumb),
      el("div", { class: "clip-info" },
        el("div", { class: "clip-name", title: clip.filename }, clip.filename),
        el("div", { class: "clip-meta" },
          el("span", { class: `clip-status status-${kind}` }, label),
          el("span", {}, fmt(clip.duration)),
          clip.proxy ? null : el("span", { title: "브라우저 미리보기용 사본을 만드는 중" }, "· 준비 중"))),
      el("div", { class: "clip-actions" },
        onTimeline ? null : el("button", { class: "clip-act", title: "타임라인 끝에 넣기",
                                          onclick: e => { e.stopPropagation(); addToTimeline(clip.clip_id); } }, "＋"),
        el("button", { class: "clip-act danger", title: "프로젝트에서 지우기",
                       onclick: e => { e.stopPropagation(); deleteClip(clip); } }, "🗑")));
    item.addEventListener("dragstart", e => { draggingClipId = clip.clip_id; e.dataTransfer.effectAllowed = "copy"; });
    item.addEventListener("dragend", () => { draggingClipId = null; });
    item.addEventListener("click", () => selectClip(clip.clip_id));
    item.addEventListener("dblclick", () => emit("preview-clip", { clipId: clip.clip_id, time: 0 }));
    list.appendChild(item);
  }
  for (const pending of state.pendingUploads) {
    list.appendChild(el("div", { class: "clip-item", dataset: { pending: pending.name } },
      el("div", { class: "clip-info" },
        el("div", { class: "clip-name" }, pending.name),
        el("div", { class: "clip-meta" }, el("span", { class: "clip-status status-uploading" }, "올리는 중")),
        el("div", { class: "clip-upload-bar" }, el("div", { style: { width: `${Math.round(pending.progress * 100)}%` } })))));
  }
}

export function selectClip(clipId) {
  state.ui.selectedClipId = clipId;
  emit("selection");
  const clip = clipById(clipId);
  if (clip) emit("preview-clip", { clipId, time: clip.in_point });
}

/* 선택한 클립 정보 (목록 아래) */
function renderClipDetail() {
  const box = $("clip-detail");
  const clip = clipById(state.ui.selectedClipId);
  box.classList.toggle("hidden", !clip);
  if (!clip) return;
  const kept = (state.plan?.keep || []).filter(k => k.clip_id === clip.clip_id).reduce((a, k) => a + k.end - k.start, 0);
  const created = clip.created_at ? new Date(clip.created_at * 1000).toLocaleString("ko-KR") : "알 수 없음";
  const used = `${fmt(clip.in_point)} ~ ${fmt(clip.out_point ?? clip.duration)}`;
  const rows = [["길이", fmt(clip.duration)], ["쓰는 범위", used], ["결과에 남는 길이", state.plan ? fmt(kept) : "-"],
                ["화질", `${clip.width}x${clip.height} · ${clip.fps}fps`], ["소리", clip.has_audio ? "있음" : "없음"],
                ["찍은 시각", created]];
  box.innerHTML = "";
  box.appendChild(el("div", { class: "clip-detail-title", title: clip.filename }, clip.filename));
  for (const [k, v] of rows) box.appendChild(el("div", { class: "clip-prop" }, el("span", {}, k), el("span", {}, v)));
}

/* ---------------------------------------------------------------- 초기화 */

export function initMedia() {
  const input = $("file-input");
  const button = $("upload-btn");
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", e => { if (e.target.files.length) uploadFiles(Array.from(e.target.files)); input.value = ""; });
  const panel = document.querySelector(".media-panel");
  panel.addEventListener("dragover", e => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    button.classList.add("drag-over");
  });
  panel.addEventListener("dragleave", e => { if (!panel.contains(e.relatedTarget)) button.classList.remove("drag-over"); });
  panel.addEventListener("drop", e => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    button.classList.remove("drag-over");
    uploadFiles(Array.from(e.dataTransfer.files));
  });
  $("btn-sort-clips").addEventListener("click", () => {
    const sorted = [...state.project.timeline].map(clipById).filter(Boolean)
      .sort((a, b) => (a.created_at ?? Infinity) - (b.created_at ?? Infinity) || a.filename.localeCompare(b.filename));
    setTimeline(sorted.map(c => c.clip_id));
  });
  on("project", () => {
    renderClipList();
    renderClipDetail();
    for (const clip of state.project.clips) ensureThumbnails(clip);
  });
  on("analysis", renderClipList);
  on("thumbnails", renderClipList);
  on("selection", () => { renderClipList(); renderClipDetail(); });
  on("plan", renderClipDetail);
}
