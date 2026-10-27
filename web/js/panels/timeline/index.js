/* 타임라인 (영상 편집 프로그램 방식).
     보기     : 편집본(결과 영상 시간축, 기본) / 원본(클립 이어 붙인 시간축, 잘린 곳 빗금)
     트랙     : C1 자막 · T1 텍스트 · V1 영상 · A1 소리 + 눈금 위 장면 마커
     그리기   : 눈금·필름 띠·파형·빗금은 '보이는 폭만큼'의 캔버스, 클립·자막 칸은 DOM(보이는 범위만)
     다시 그리기는 화면 갱신 주기에 한 번, 바뀐 부분만 (전체 / 스크롤 / 재생 헤드)
   조작은 interact.js(확대·스크롤·끌기·붙기), edit.js(선택·단축키·메뉴·자막 고치기)에 있다. */

import { $, el, perFrame } from "../../core/dom.js";
import { clamp } from "../../core/format.js";
import { on, state } from "../../core/store.js";
import { currentPosition, isPlaying, showSource, startPlan, togglePlay } from "../preview.js";
import { initEdit, pruneSelection } from "./edit.js";
import { ICONS } from "./icons.js";
import { initInteract, scrollToTime } from "./interact.js";
import { fromTimeline, joins, rulerLabel, SEQUENCE, SOURCE, toTimelineNearest } from "./model.js";
import { drawRuler, renderMarkers } from "./ruler.js";
import { fps, HEADER_W, MAX_PX, MIN_PX, savePrefs, segments, total, trackHeight, trackPref, TRACKS, tl, xOf } from "./state.js";
import { buildToolbar, updateToolbar } from "./toolbar.js";
import { drawAudio } from "./tracks/audio.js";
import { captionItems, renderCaptions } from "./tracks/captions.js";
import { renderOverlay } from "./tracks/overlay.js";
import { cutRegions, drawVideo, renderVideoDom } from "./tracks/video.js";

const TRACK_ICONS = { captions: ICONS.captions, overlay: ICONS.text, video: ICONS.video, audio: ICONS.audio };
const lanes = {};                       // 트랙 id → { row, lane, canvas, layer }
let handlers = {};
let lastTime = 0;                       // 재생 헤드 시각 (지금 보기의 타임라인 초)
let pendingSeek = null;                 // 이동을 요청했지만 영상이 아직 따라오지 않은 시각

/* ---------------------------------------------------------------- 그리기 예약 */

const dirty = { all: false, scroll: false };
const flush = perFrame(() => {
  if (dirty.all) renderAll();
  else if (dirty.scroll) renderScroll();
  dirty.all = dirty.scroll = false;
});
export function invalidate() { dirty.all = true; flush(); }
export function invalidateScroll() { dirty.scroll = true; flush(); }

function viewport() {
  const scroll = $("tl-scroll");
  return { scrollLeft: scroll.scrollLeft, width: Math.max(1, scroll.clientWidth - HEADER_W) };
}

function ctxFor(id) {
  const { scrollLeft, width } = viewport();
  return { scrollLeft, width, height: trackHeight(TRACKS.find(t => t.id === id)), segs: segments() };
}

function renderAll() {
  const segs = segments();
  const { width } = viewport();
  const contentW = Math.max(xOf(total()) + 240, width);
  $("tl-content").style.width = `${HEADER_W + contentW}px`;
  $("tl-ruler").style.width = `${contentW}px`;
  for (const track of TRACKS) {
    const { row, lane } = lanes[track.id];
    const pref = trackPref(track.id);
    row.style.height = `${trackHeight(track)}px`;
    row.classList.toggle("collapsed", !!pref.hidden);
    row.classList.toggle("locked", !!pref.locked);
    lane.style.width = `${contentW}px`;
    syncHeader(track);
  }
  renderMarkers(handlers.markerPick);
  renderDom("V1");
  renderDom("T1");
  renderScroll();
  renderEmpty(segs);
  renderPlayhead();
}

/* 스크롤하면 바뀌는 것: 캔버스(보이는 폭만 그린다)와 보이는 범위만 그리는 자막 칸 */
function renderScroll() {
  const { scrollLeft, width } = viewport();
  drawRuler(scrollLeft, width);
  if (!trackPref("V1").hidden) drawVideo(lanes.V1.canvas, ctxFor("V1"), invalidateScroll);
  if (!trackPref("A1").hidden) drawAudio(lanes.A1.canvas, ctxFor("A1"), invalidateScroll);
  renderDom("C1");
}

function renderDom(id) {
  const { layer } = lanes[id];
  if (trackPref(id).hidden) { layer.innerHTML = ""; return; }
  if (id === "V1") renderVideoDom(layer, ctxFor(id));
  if (id === "C1") renderCaptions(layer, ctxFor(id));
  if (id === "T1") renderOverlay(layer, ctxFor(id));
}

function renderEmpty(segs) {
  const layer = lanes.V1.layer;
  layer.querySelector(".tl-empty")?.remove();
  if (segs.length) return;
  const hasClips = (state.project?.timeline || []).length > 0;
  layer.appendChild(el("div", { class: "tl-empty" }, hasClips && tl.view === SEQUENCE
    ? "남는 구간이 없습니다 — [원본] 보기에서 잘린 곳을 확인하세요"
    : "왼쪽 클립을 여기로 끌어 놓거나 [+] 버튼을 누르세요"));
}

/* ---------------------------------------------------------------- 트랙 안 조작 (트랙 단위로 받는다) */

function bindLaneEvents() {
  const video = lanes.V1.layer, captions = lanes.C1.layer, text = lanes.T1.layer;
  const segOf = block => segments()[Number(block.dataset.index)];
  video.addEventListener("mousedown", e => {
    if (e.target.closest(".tl-join, [data-act=remove]")) { e.stopPropagation(); return; }
    const block = e.target.closest(".tl-clip");
    const seg = block && segOf(block);
    if (!seg) return;
    const trim = e.target.closest(".tl-trim");
    if (trim) { e.stopPropagation(); e.preventDefault(); handlers.trimDown(e, seg, trim.dataset.edge); return; }
    handlers.clipDown(e, seg, block);
  });
  video.addEventListener("click", e => {
    const join = e.target.closest(".tl-join");
    if (join) { e.stopPropagation(); handlers.openJoin(e, joins(segments())[Number(join.dataset.join)]); return; }
    const remove = e.target.closest("[data-act=remove]");
    if (remove) { e.stopPropagation(); handlers.removeClip(remove.closest(".tl-clip").dataset.clip); }
  });
  video.addEventListener("dblclick", e => {
    const block = e.target.closest(".tl-clip");
    if (block && !e.target.closest(".tl-trim, [data-act=remove]")) handlers.openSource(segOf(block));
  });
  video.addEventListener("contextmenu", e => {
    const block = e.target.closest(".tl-clip");
    if (block) handlers.clipMenu(e, segOf(block));
  });
  const itemOf = chip => captionItems(segments()).find(c => c.segId === chip.dataset.seg);
  const onCaption = fn => e => {
    const chip = e.target.closest(".tl-cap");
    const item = chip && itemOf(chip);
    if (item) fn(e, item, chip);
  };
  captions.addEventListener("mousedown", onCaption((e, item) => handlers.captionDown(e, item)));
  captions.addEventListener("dblclick", onCaption((e, item, chip) => handlers.captionEdit(e, item, chip)));
  captions.addEventListener("contextmenu", onCaption((e, item) => handlers.captionMenu(e, item)));
  text.addEventListener("mousedown", e => { if (e.target.closest(".tl-text")) handlers.seekAt(e); });
  text.addEventListener("dblclick", e => {
    const chip = e.target.closest(".tl-text");
    if (chip) handlers.openTextStyle(chip.dataset.style);
  });
}

/* ---------------------------------------------------------------- 트랙 머리 */

function buildTracks() {
  const box = $("tl-tracks");
  box.innerHTML = "";
  for (const track of TRACKS) {
    const head = el("div", { class: "tl-head" },
      el("span", { class: `tl-head-icon role-${track.kind}` }),
      el("span", { class: "tl-head-code" }, track.id),
      track.id === "C1" ? el("button", { class: "tl-head-name", id: "sub-track-label", type: "button",
                                         title: "자막 스타일 편집" }, track.name)
        : el("span", { class: "tl-head-name" }, track.name),
      el("div", { class: "tl-head-tools" },
        el("button", { class: "tl-head-btn", type: "button", dataset: { act: "hide" } }),
        track.lockable ? el("button", { class: "tl-head-btn", type: "button", dataset: { act: "lock" } }) : null,
        el("button", { class: "tl-head-btn", type: "button", dataset: { act: "size" }, title: "트랙 높이 (작게·보통·크게)" })));
    head.querySelector(".tl-head-icon").innerHTML = TRACK_ICONS[track.kind];
    head.querySelector('[data-act="size"]').innerHTML = ICONS.height;
    head.addEventListener("click", e => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (!act) return;
      const pref = trackPref(track.id);
      if (act === "hide") pref.hidden = !pref.hidden;
      if (act === "lock") pref.locked = !pref.locked;
      if (act === "size") pref.size = ((pref.size ?? 1) + 1) % track.sizes.length;
      savePrefs();
      invalidate();
    });
    const canvas = track.kind === "video" || track.kind === "audio" ? el("canvas", { class: "tl-canvas" }) : null;
    const layer = el("div", { class: "tl-layer" });
    const lane = el("div", { class: `tl-lane lane-${track.kind}`, dataset: { track: track.id } }, canvas, layer);
    const row = el("div", { class: `tl-row tl-track track-${track.kind}`, dataset: { track: track.id } }, head, lane);
    box.appendChild(row);
    lanes[track.id] = { row, lane, canvas, layer };
  }
}

function syncHeader(track) {
  const pref = trackPref(track.id);
  const head = lanes[track.id].row.querySelector(".tl-head");
  const hide = head.querySelector('[data-act="hide"]');
  hide.innerHTML = pref.hidden ? ICONS.eyeOff : ICONS.eye;
  hide.title = pref.hidden ? "트랙 펼치기" : "트랙 접기";
  hide.classList.toggle("off", !!pref.hidden);
  const lock = head.querySelector('[data-act="lock"]');
  if (lock) {
    lock.innerHTML = pref.locked ? ICONS.lock : ICONS.unlock;
    lock.title = pref.locked ? "잠금 풀기" : "잠그기 (실수로 고치지 않게)";
    lock.classList.toggle("on", !!pref.locked);
  }
}

/* ---------------------------------------------------------------- 재생 헤드·시각 */

/* 지금 영상 위치 → 지금 보기의 타임라인 초 */
function positionTime(pos = currentPosition()) {
  if (pendingSeek !== null) return pendingSeek;
  if (pos.mode === "plan" && tl.view === SEQUENCE && pos.outTime !== null) return pos.outTime;
  if (!pos.clipId) return lastTime;
  return toTimelineNearest(segments(), pos.clipId, pos.time) ?? lastTime;
}

/* 잘린 곳 수: 두 보기 모두 원본 기준으로 센다 (클립 앞뒤가 잘린 것 포함) */
const cutCount = () => cutRegions(segments(SOURCE)).length;

function renderPlayhead(pos) {
  lastTime = positionTime(pos);
  const x = xOf(lastTime);
  $("tl-playhead").style.transform = `translateX(${HEADER_W + x}px)`;
  const cap = $("tl-playhead-cap");
  cap.style.transform = `translateX(${x}px)`;
  cap.classList.toggle("at-start", x < 34);         // 맨 앞에서는 시각 말풍선이 잘리지 않게 오른쪽으로
  $("tl-playhead-time").textContent = rulerLabel(lastTime, true, fps());
  updateToolbar(lastTime, isPlaying(), cutCount());
}

export function currentTime() { return lastTime; }

/* 타임라인 초 t로 이동 (편집본이면 미리보기도 편집본, 원본이면 원본) */
export async function seek(t, { play = null } = {}) {
  t = clamp(t, 0, total());
  const playing = play ?? isPlaying();
  pendingSeek = t;
  renderPlayhead();
  try {
    if (tl.view === SEQUENCE) {
      await startPlan(Math.min(t, Math.max(0, total() - 1e-3)), playing);
    } else {
      const at = fromTimeline(segments(), t);
      if (at) await showSource(at.clipId, at.time, playing);
    }
  } finally {
    pendingSeek = null;
    renderPlayhead();
  }
}

/* 프레임 격자에 맞춰 이동 (1/30초를 여러 번 더해도 오차가 쌓이지 않게) */
export function step(dt) {
  $("video").pause();
  return seek(Math.round((lastTime + dt) * fps()) / fps(), { play: false });
}

/* 보기 바꾸기: 지금 보고 있는 클립 위치를 그대로 두고 시간축만 바꾼다 */
export function setView(view, { syncPreview = true } = {}) {
  if (view === tl.view) return;
  const pos = currentPosition();
  tl.view = view;
  tl.selected.clear();
  if (tl.fitted) zoomToFit(); else invalidate();
  if (!syncPreview) return;
  const t = pos.clipId ? toTimelineNearest(segments(), pos.clipId, pos.time) ?? 0 : 0;
  seek(t, { play: false });
}

export function zoomToFit() {
  const { width } = viewport();
  const t = total();
  if (t > 0 && width > 0) tl.px = clamp((width - 48) / t, MIN_PX, MAX_PX);
  tl.fitted = true;
  invalidate();
}

/* ---------------------------------------------------------------- 초기화 */

export function initTimeline() {
  buildTracks();
  const actions = {
    seek: t => seek(t), step, togglePlay, setView, fit: zoomToFit,
    toggleSnap: () => { tl.prefs.snap = !tl.prefs.snap; savePrefs(); renderPlayhead(); },
    zoomBy: k => handlers.zoomTo(tl.px * k), zoomTo: px => handlers.zoomTo(px),
    nextCut: dir => handlers.nextCut(dir), toggleHelp: () => handlers.toggleHelp(),
  };
  buildToolbar(actions);
  handlers = { ...initInteract({ invalidate, invalidateScroll, seek, currentTime, lanes }),
               ...initEdit({ invalidate, seek, currentTime, lanes, setView }) };
  bindLaneEvents();

  let initialized = null;               // 프로젝트를 처음 열면 편집본 처음으로 (영상 편집 프로그램처럼)
  let lastCount = -1;
  on("project", () => {
    const count = state.project?.timeline.length || 0;
    if (count !== lastCount) { lastCount = count; zoomToFit(); } else invalidate();
  });
  on("plan", () => {
    pruneSelection();
    invalidate();
    const id = state.project?.project_id;
    if (id && initialized !== id && state.plan?.keep?.length) {
      initialized = id;
      if (tl.view === SEQUENCE) startPlan(0, false);
    }
  });
  on("analysis", invalidate);
  on("thumbnails", invalidateScroll);
  on("time", pos => {
    renderPlayhead(pos);
    if (isPlaying()) scrollToTime(lastTime, { follow: true });
  });
  on("preview-mode", mode => {          // 미리보기의 [원본]/[편집본] 버튼과 타임라인 보기를 맞춘다
    const view = mode === "plan" ? SEQUENCE : SOURCE;
    if (view !== tl.view) setView(view, { syncPreview: false });
  });
  window.addEventListener("resize", invalidate);
}
