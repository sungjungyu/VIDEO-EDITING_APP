/* 미리보기.
   원본 모드  : 클립 하나를 재생. 받아쓰기 문장을 자막으로 보여 주고, 자른 문장은 줄을 그어 표시
   편집본 모드: 렌더하지 않고 편집 계획의 남길 구간(keep)만 이어서 재생. 자막은 서버가 계산한 결과 자막(events),
               강조 줌인(effects)도 그대로 → 렌더 결과와 같은 화면 (계획서 2차 '선택 결과 바로 미리보기')
   미리보기 상자는 출력 비율(16:9/9:16) 그대로, 영상은 가운데를 잘라 채운다 (렌더의 scale+crop과 같음). */

import { clipById, decisionOf, emit, linesOfClip, on, state } from "./store.js";
import { drawEvent, lineToEvent } from "./style.js";
import { effectiveStyle } from "./stylepanel.js";
import { mediaUrl } from "./media.js";
import { clamp, fmt } from "./util.js";

const video = () => document.getElementById("video");
let mode = "source";
let clipId = null;
let planIndex = -1;
let switching = false;
let lastDraw = 0;

export const currentMode = () => mode;

export function currentPosition() {
  const v = video();
  return { mode, clipId, time: v.currentTime || 0, outTime: mode === "plan" ? outTime() : null };
}

function keep() {
  return state.plan?.keep || [];
}

function outTime() {
  const k = keep()[planIndex];
  if (!k) return 0;
  return k.out_start + clamp(video().currentTime - k.start, 0, k.end - k.start);
}

async function load(url) {
  const v = video();
  if (v.dataset.url === url) return;
  v.dataset.url = url;
  v.src = url;
  await new Promise(resolve => {
    const done = () => { v.removeEventListener("loadedmetadata", done); resolve(); };
    v.addEventListener("loadedmetadata", done);
    setTimeout(resolve, 6000);
  });
}

function setMode(next) {
  mode = next;
  document.getElementById("btn-mode-source").classList.toggle("active", mode === "source");
  document.getElementById("btn-mode-plan").classList.toggle("active", mode === "plan");
  const badge = document.getElementById("preview-badge");
  badge.style.display = "";
  badge.className = "preview-badge" + (mode === "plan" ? " plan" : "");
  if (mode === "source") video().style.transform = "none";
  updateBadge();
}

function updateBadge() {
  const badge = document.getElementById("preview-badge");
  if (mode === "plan") badge.textContent = `편집본 미리보기 · ${keep().length}구간`;
  else badge.textContent = `원본 · ${clipById(clipId)?.filename || ""}`;
}

export async function showSource(id, time = null, play = false) {
  const clip = clipById(id);
  if (!clip) return;
  clipId = id;
  setMode("source");
  document.getElementById("preview-empty").classList.add("hidden");
  document.getElementById("btn-play").disabled = false;
  await load(mediaUrl(clip));
  if (time !== null) video().currentTime = clamp(time, 0, Math.max(0, clip.duration - 0.05));
  if (play) video().play().catch(() => {});
  updateBadge();
  emit("preview-clip-changed", id);
}

async function seekRange(index, offset = 0) {
  const k = keep()[index];
  if (!k) return;
  planIndex = index;
  clipId = k.clip_id;
  switching = true;
  try {
    await load(mediaUrl(clipById(k.clip_id)));
    video().currentTime = k.start + clamp(offset, 0, k.end - k.start - 0.01);
  } finally {
    switching = false;
  }
}

export async function startPlan(at = 0, play = true) {
  const ranges = keep();
  if (!ranges.length) return;
  setMode("plan");
  document.getElementById("preview-empty").classList.add("hidden");
  document.getElementById("btn-play").disabled = false;
  let index = ranges.findIndex(k => at >= k.out_start && at < k.out_start + (k.end - k.start));
  if (index < 0) index = at <= 0 ? 0 : ranges.length - 1;
  await seekRange(index, at - ranges[index].out_start);
  if (play) video().play().catch(() => {});
}

function advance() {
  const ranges = keep();
  const k = ranges[planIndex];
  if (!k || switching) return;
  const v = video();
  if (v.currentTime < k.end - 0.03 && !v.ended) return;
  if (planIndex + 1 >= ranges.length) {
    v.pause();
    return;
  }
  const wasPlaying = !v.paused || v.ended;
  seekRange(planIndex + 1, 0).then(() => { if (wasPlaying) v.play().catch(() => {}); });
}

/* ---------------------------------------------------------------- 자막·줌 */

function boxSize() {
  const box = document.getElementById("preview-box");
  return [box.clientWidth || 1, box.clientHeight || 1];
}

function drawOverlay() {
  const overlay = document.getElementById("sub-overlay");
  overlay.innerHTML = "";
  const [w, h] = boxSize();
  const v = video();
  if (mode === "plan") {
    const t = outTime();
    for (const event of state.plan?.events || []) {
      if (t >= event.start && t < event.end) drawEvent(overlay, event, effectiveStyle(event.style), w, h, t);
    }
    const k = keep()[planIndex];
    const fx = (state.plan?.effects || []).find(e => k && e.clip_id === k.clip_id && v.currentTime >= e.start
                                                     && v.currentTime < e.end);
    v.style.transform = fx ? `scale(${fx.scale})` : "none";
    return;
  }
  if (!clipId || !state.plan?.options?.subtitles) return;
  const t = v.currentTime;
  const line = linesOfClip(clipId).find(l => t >= l.start && t < l.end);
  if (!line || !line.text) return;
  const decision = decisionOf(line.seg_id);
  const S = effectiveStyle("subtitle");
  drawEvent(overlay, lineToEvent(line, decision, S), S, w, h, t, { cut: !decision.keep });
}

/* ---------------------------------------------------------------- 시간 표시 */

function updateTimeUI() {
  const v = video();
  let t = v.currentTime || 0, total = Number.isFinite(v.duration) ? v.duration : 0;
  if (mode === "plan") { t = outTime(); total = state.plan?.duration || 0; }
  document.getElementById("preview-time").textContent = `${fmt(t)} / ${fmt(total)}`;
  document.getElementById("preview-progress-fill").style.width = total ? `${(t / total) * 100}%` : "0%";
}

function tick(now) {
  requestAnimationFrame(tick);
  if (mode === "plan") advance();
  if (now - lastDraw > 33) {
    lastDraw = now;
    drawOverlay();
    updateTimeUI();
    emit("time", currentPosition());
  }
}

/* ---------------------------------------------------------------- 크기 */

export function fitBox() {
  const area = document.getElementById("preview-area");
  const box = document.getElementById("preview-box");
  const ratio = state.plan?.output?.aspect === "9:16" ? 9 / 16 : 16 / 9;
  const W = area.clientWidth, H = area.clientHeight;
  if (!W || !H) return;
  let w = W, h = W / ratio;
  if (h > H) { h = H; w = H * ratio; }
  box.style.width = `${Math.floor(w)}px`;
  box.style.height = `${Math.floor(h)}px`;
}

export function togglePlay() {
  const v = video();
  if (!v.src) return;
  if (mode === "plan" && v.paused && planIndex === keep().length - 1 && v.currentTime >= keep()[planIndex].end - 0.05) {
    startPlan(0, true);
    return;
  }
  if (v.paused) v.play().catch(() => {}); else v.pause();
}

export function initPreview() {
  const v = video();
  v.addEventListener("play", () => {
    document.getElementById("icon-play").style.display = "none";
    document.getElementById("icon-pause").style.display = "";
  });
  v.addEventListener("pause", () => {
    document.getElementById("icon-play").style.display = "";
    document.getElementById("icon-pause").style.display = "none";
  });
  document.getElementById("btn-play").addEventListener("click", togglePlay);
  document.getElementById("preview-progress").addEventListener("click", e => {
    const r = e.currentTarget.getBoundingClientRect();
    const f = clamp((e.clientX - r.left) / r.width, 0, 1);
    if (mode === "plan") startPlan(f * (state.plan?.duration || 0), !v.paused);
    else if (Number.isFinite(v.duration)) v.currentTime = f * v.duration;
  });
  document.getElementById("btn-mode-source").addEventListener("click", () => {
    const id = clipId || state.project?.timeline[0];
    if (id) showSource(id, mode === "plan" ? v.currentTime : null);
  });
  document.getElementById("btn-mode-plan").addEventListener("click", () => startPlan(0, true));
  new ResizeObserver(fitBox).observe(document.getElementById("preview-area"));
  on("plan", () => {
    fitBox();
    document.getElementById("btn-mode-plan").disabled = !keep().length;
    if (mode === "plan" && planIndex >= keep().length) planIndex = keep().length - 1;
    updateBadge();
  });
  on("preview-clip", ({ clipId: id, time }) => showSource(id, time, false));
  requestAnimationFrame(tick);
}
