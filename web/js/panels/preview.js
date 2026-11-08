/* 미리보기.
   원본 클립 : 클립 하나를 재생. 받아쓰기 문장을 자막으로 보여 주고, 뺀 문장은 줄을 그어 표시
   편집 결과 : 렌더하지 않고 편집 결과의 남길 구간(keep)만 이어서 재생. 자막은 서버가 계산한 결과 자막(events),
               강조 줌인(effects)도 그대로 → 내보낸 영상과 같은 화면
   미리보기 상자는 출력 비율(16:9/9:16) 그대로, 영상은 가운데를 잘라 채운다 (렌더의 scale+crop과 같음).
   비율 버튼은 미리보기 아래 재생 줄 오른쪽 끝에 있다 (어느 단계에서나 바꿀 수 있고, 영상 자리를 줄이지 않게). */

import { api } from "../core/api.js";
import { $, toast } from "../core/dom.js";
import { clamp, fmt } from "../core/format.js";
import { clipById, decisionOf, emit, linesOfClip, mutatePlan, on, pid, state } from "../core/store.js";
import { drawEvent, lineToEvent } from "../subtitle/draw.js";
import { mediaUrl } from "./media.js";
import { effectiveStyle } from "./style-panel.js";

const video = () => $("video");
let mode = "source";
let clipId = null;
let planIndex = -1;
let switching = false;
let lastDraw = 0;

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
  $("btn-mode-source").classList.toggle("active", mode === "source");
  $("btn-mode-plan").classList.toggle("active", mode === "plan");
  if (mode === "source") video().style.transform = "none";
  renderHint();
}

function renderHint() {
  const hint = $("preview-hint");
  if (mode === "plan") {
    hint.textContent = "뺀 부분은 건너뛰고 재생해요";
    hint.title = "렌더하지 않고 결과 영상처럼 이어서 재생합니다";
    return;
  }
  const clip = clipById(clipId);
  hint.textContent = !clip ? "" : state.analysis ? "자르지 않은 원본 · 뺀 문장은 줄로 표시" : "자르지 않은 원본";
  hint.title = clip ? clip.filename : "";
}

export async function showSource(id, time = null, play = false) {
  const clip = clipById(id);
  if (!clip) return;
  clipId = id;
  setMode("source");
  $("preview-empty").classList.add("hidden");
  $("btn-play").disabled = false;
  await load(mediaUrl(clip));
  if (time !== null) video().currentTime = clamp(time, 0, Math.max(0, clip.duration - 0.05));
  if (play) video().play().catch(() => {});
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

export async function showPlan(at = 0, play = true) {
  const ranges = keep();
  if (!ranges.length) return;
  setMode("plan");
  $("preview-empty").classList.add("hidden");
  $("btn-play").disabled = false;
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
  const box = $("preview-box");
  return [box.clientWidth || 1, box.clientHeight || 1];
}

/* 지금 보여야 할 자막 장면들 (event, 스타일, cut 표시) */
function visibleSubtitles(t) {
  if (mode === "plan") {
    return (state.plan?.events || []).filter(e => t >= e.start && t < e.end)
      .map(event => ({ event, style: effectiveStyle(event.style), cut: false }));
  }
  if (!clipId || !state.plan?.options?.subtitles) return [];
  const line = linesOfClip(clipId).find(l => t >= l.start && t < l.end);
  if (!line || !line.text) return [];
  const decision = decisionOf(line.seg_id);
  const style = effectiveStyle("subtitle");
  return [{ event: lineToEvent(line, decision, style), style, cut: !decision.keep, id: `${line.seg_id}|${decision.text || ""}` }];
}

/* 다시 그릴지 판단하는 열쇠: 보이는 자막·카라오케로 말한 단어 수·페이드 단계·상자 크기·스타일이 같으면 그대로 둔다
   (예전에는 33ms마다 자막 DOM을 전부 지우고 다시 만들었다 — 일시정지 중에도) */
function overlayKey(items, t, w, h) {
  const parts = [mode, w, h, styleVersion];
  for (const { event, style, cut, id } of items) {
    const spoken = style.karaoke ? (event.words || []).filter(word => t >= word.start).length : 0;
    const fade = style.fade ? Math.round(Math.min(1, (t - event.start) / 0.15, (event.end - t) / 0.15) * 10) : 10;
    parts.push(id || `${event.start}|${event.text}`, spoken, fade, cut);
  }
  return parts.join("/");
}

let lastOverlayKey = "";
let styleVersion = 0;

function drawOverlay() {
  const overlay = $("sub-overlay");
  const [w, h] = boxSize();
  const v = video();
  const t = mode === "plan" ? outTime() : v.currentTime;
  const items = visibleSubtitles(t);
  const key = overlayKey(items, t, w, h);
  if (key !== lastOverlayKey) {
    lastOverlayKey = key;
    overlay.innerHTML = "";
    for (const { event, style, cut } of items) drawEvent(overlay, event, style, w, h, t, { cut });
  }
  if (mode === "plan") {
    const k = keep()[planIndex];
    const scale = Math.max(1, ...(state.plan?.effects || [])        // 렌더와 같이: 겹치면 가장 큰 배율
      .filter(e => k && e.clip_id === k.clip_id && v.currentTime >= e.start && v.currentTime < e.end)
      .map(e => e.scale));
    v.style.transform = scale > 1 ? `scale(${scale})` : "none";
  }
}

/* ---------------------------------------------------------------- 시간 표시 */

function updateTimeUI() {
  const v = video();
  let t = v.currentTime || 0, total = Number.isFinite(v.duration) ? v.duration : 0;
  if (mode === "plan") { t = outTime(); total = state.plan?.duration || 0; }
  $("preview-time").textContent = `${fmt(t)} / ${fmt(total)}`;
  $("preview-progress-fill").style.width = total ? `${(t / total) * 100}%` : "0%";
}

let lastPositionKey = "";

function tick(now) {
  requestAnimationFrame(tick);
  if (mode === "plan") advance();
  if (now - lastDraw > 33) {
    lastDraw = now;
    drawOverlay();
    updateTimeUI();
    const pos = currentPosition();
    const key = `${pos.mode}|${pos.clipId}|${pos.time.toFixed(3)}`;
    if (key !== lastPositionKey) {           // 멈춰 있으면 재생 위치 알림(타임라인 재생 헤드)도 보내지 않는다
      lastPositionKey = key;
      emit("time", pos);
    }
  }
}

/* ---------------------------------------------------------------- 크기 */

function fitBox() {
  const area = $("preview-area");
  const box = $("preview-box");
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
    showPlan(0, true);
    return;
  }
  if (v.paused) v.play().catch(() => {}); else v.pause();
}

export function initPreview() {
  const v = video();
  v.addEventListener("play", () => {
    $("icon-play").style.display = "none";
    $("icon-pause").style.display = "";
  });
  v.addEventListener("pause", () => {
    $("icon-play").style.display = "";
    $("icon-pause").style.display = "none";
  });
  $("btn-play").addEventListener("click", togglePlay);
  $("preview-progress").addEventListener("click", e => {
    const r = e.currentTarget.getBoundingClientRect();
    const f = clamp((e.clientX - r.left) / r.width, 0, 1);
    if (mode === "plan") showPlan(f * (state.plan?.duration || 0), !v.paused);
    else if (Number.isFinite(v.duration)) v.currentTime = f * v.duration;
  });
  $("btn-mode-source").addEventListener("click", () => {
    const id = clipId || state.project?.timeline[0];
    if (id) showSource(id, mode === "plan" ? v.currentTime : null);
  });
  $("btn-mode-plan").addEventListener("click", () => showPlan(0, true));
  new ResizeObserver(fitBox).observe($("preview-area"));
  on("plan", () => {
    fitBox();
    $("btn-mode-plan").disabled = !keep().length;
    if (mode === "plan" && planIndex >= keep().length) planIndex = keep().length - 1;
  });
  document.querySelectorAll(".aspect-btn").forEach(btn => btn.addEventListener("click", async () => {
    if (!state.plan || state.plan.output.aspect === btn.dataset.ratio) return;
    try {
      await mutatePlan(() => api.putPlan(pid(), { output: { ...state.plan.output, aspect: btn.dataset.ratio,
                                                             aspect_source: "user" } }));
    } catch (err) { toast(err.message, "error"); }
  }));
  on("plan", () => {
    const { aspect, aspect_source: source } = state.plan?.output || {};
    document.querySelectorAll(".aspect-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.ratio === aspect);
      b.title = source === "auto" && b.dataset.ratio === aspect ? "영상 방향에 맞춰 자동으로 골랐어요" : "";
    });
  });
  on("preview-clip", ({ clipId: id, time }) => showSource(id, time, false));
  on("analysis", renderHint);
  const restyle = () => { styleVersion += 1; };        // 스타일이 바뀌면 자막을 다시 그린다
  on("style-draft", restyle);
  on("plan", restyle);
  requestAnimationFrame(tick);
}
