/* 타임라인 조작: 확대·스크롤, 눈금 훑어보기(스크럽), 클립 순서 바꾸기·앞뒤 자르기, 붙기(스냅), 미디어 끌어 놓기, 패널 높이 조절. */

import { api } from "../../core/api.js";
import { $ } from "../../core/dom.js";
import { clamp, fmt } from "../../core/format.js";
import { clipById, emit, pid, setProject, state } from "../../core/store.js";
import { addToTimeline, draggingClipId, setTimeline } from "../media.js";
import { showSource } from "../preview.js";
import { selectClip } from "./edit.js";
import { snapTo, SOURCE, timecode } from "./model.js";
import { fps, HEADER_W, isLocked, MAX_PX, MIN_PX, savePrefs, segments, tl, tOf, xOf } from "./state.js";
import { captionItems } from "./tracks/captions.js";

const SNAP_PX = 8;
let app;

/* ---------------------------------------------------------------- 좌표 */

/* 화면 x(clientX) → 타임라인 초 */
function timeAt(clientX) {
  const scroll = $("tl-scroll");
  const rect = scroll.getBoundingClientRect();
  return Math.max(0, tOf(clientX - rect.left - HEADER_W + scroll.scrollLeft));
}

/* ---------------------------------------------------------------- 붙기 */

/* 붙기 지점: 끌기를 시작할 때 한 번만 계산한다 (끄는 동안 바뀌는 자기 위치에 다시 붙지 않게)
   clipId: 그 클립의 경계는 빼기 (앞뒤 자르는 클립) · playhead: 재생 헤드를 넣을지 (재생 헤드를 끌 때는 빼기) */
function snapTargets({ clipId = null, playhead = true } = {}) {
  const targets = [0];
  if (playhead) targets.push(app.currentTime());
  for (const s of segments()) {
    if (s.clipId === clipId) continue;
    targets.push(s.start, s.start + s.dur);
  }
  for (const c of captionItems(segments())) targets.push(c.start, c.end);
  return targets;
}

/* bypass: Alt를 누르고 끌면 그동안만 붙기를 끈다 */
function snapped(t, targets, bypass = false) {
  if (!tl.prefs.snap || bypass) { hideGuide(); return t; }
  const hit = snapTo(t, targets, SNAP_PX / tl.px);
  if (hit === null) { hideGuide(); return t; }
  showGuide(hit);
  return hit;
}

function showGuide(t) {
  const guide = $("tl-snap-guide");
  guide.style.transform = `translateX(${HEADER_W + xOf(t)}px)`;
  guide.classList.add("show");
}

function hideGuide() { $("tl-snap-guide").classList.remove("show"); }

function tooltip(clientX, clientY, text) {
  const tip = $("tl-tooltip");
  if (!text) { tip.classList.add("hidden"); return; }
  tip.textContent = text;
  tip.style.left = `${clientX + 12}px`;
  tip.style.top = `${clientY - 30}px`;
  tip.classList.remove("hidden");
}

/* ---------------------------------------------------------------- 확대·스크롤 */

export function zoomTo(px, clientX = null) {
  const scroll = $("tl-scroll");
  const rect = scroll.getBoundingClientRect();
  const anchorX = clientX === null ? xOf(app.currentTime()) - scroll.scrollLeft : clientX - rect.left - HEADER_W;
  const anchorT = tOf(scroll.scrollLeft + anchorX);
  tl.px = clamp(px, MIN_PX, MAX_PX);
  tl.fitted = false;
  app.invalidate();
  requestAnimationFrame(() => { scroll.scrollLeft = Math.max(0, xOf(anchorT) - anchorX); });
  const hint = $("zoom-hint");
  hint.textContent = `확대 ${Math.round(tl.px)}px/초`;
  hint.classList.add("show");
  clearTimeout(zoomTo.timer);
  zoomTo.timer = setTimeout(() => hint.classList.remove("show"), 900);
}

/* 재생 중 재생 헤드가 화면 밖으로 나가면 한 화면씩 넘긴다 (Premiere의 페이지 스크롤) */
export function scrollToTime(t, { follow = false } = {}) {
  const scroll = $("tl-scroll");
  const width = scroll.clientWidth - HEADER_W;
  const x = xOf(t);
  if (follow && x >= scroll.scrollLeft && x <= scroll.scrollLeft + width - 24) return;
  if (!follow && x >= scroll.scrollLeft + 24 && x <= scroll.scrollLeft + width - 24) return;
  scroll.scrollLeft = Math.max(0, follow ? x - 24 : x - width / 2);
}

/* ---------------------------------------------------------------- 끌기 */

function startDrag(drag, onMove, onUp) {
  tl.drag = drag;
  const move = e => onMove(e);
  const up = e => {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", up);
    hideGuide();
    tooltip(0, 0, null);
    const changed = tl.drag?.kind !== "move" || tl.drag.moved;
    onUp(e);
    tl.drag = null;
    if (changed) app.invalidate();           // 그냥 클릭(선택)이면 다시 그리지 않는다
  };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

function scrub(e) {
  e.preventDefault();
  app.seek(timeAt(e.clientX));
  const targets = snapTargets({ playhead: false });
  startDrag({ kind: "scrub" }, ev => app.seek(snapped(timeAt(ev.clientX), targets, ev.altKey)), () => {});
}

/* 클립 순서: 마우스 위치가 어느 클립 사이인지 (클립 단위 — 편집본에서 클립이 여러 조각이어도) */
function clipSpans() {
  const spans = new Map();
  for (const s of segments()) {
    const span = spans.get(s.clipId) || { start: s.start, end: s.start + s.dur };
    span.start = Math.min(span.start, s.start);
    span.end = Math.max(span.end, s.start + s.dur);
    spans.set(s.clipId, span);
  }
  return spans;
}

function dropIndex(t, exclude = null) {
  const spans = clipSpans();
  const ids = (state.project?.timeline || []).filter(id => id !== exclude);
  let index = 0;
  for (const id of ids) {
    const span = spans.get(id);
    if (span && t > (span.start + span.end) / 2) index++;
  }
  return index;
}

function dropX(index, exclude = null) {
  const spans = clipSpans();
  const ids = (state.project?.timeline || []).filter(id => id !== exclude && spans.has(id));
  if (!ids.length) return 0;
  return index >= ids.length ? spans.get(ids[ids.length - 1]).end : spans.get(ids[index]).start;
}

function clipDown(e, seg, block) {
  if (e.button !== 0) return;
  e.preventDefault();
  selectClip(seg.clipId);                   // 다시 그리지 않고 표시만 (더블클릭이 이어지게)
  if (isLocked("V1")) return;
  const x0 = e.clientX;
  startDrag({ kind: "move", clipId: seg.clipId, moved: false, target: null }, ev => {
    const drag = tl.drag;
    if (!drag.moved && Math.abs(ev.clientX - x0) < 5) return;
    drag.moved = true;
    block?.classList.add("moving");
    drag.target = dropIndex(timeAt(ev.clientX), seg.clipId);
    showGuide(dropX(drag.target, seg.clipId));
    tooltip(ev.clientX, ev.clientY, `${drag.target + 1}번째로 옮기기`);
  }, () => {
    const drag = tl.drag;
    if (!drag?.moved || drag.target === null) return;
    const ids = state.project.timeline.filter(id => id !== seg.clipId);
    ids.splice(drag.target, 0, seg.clipId);
    if (ids.join() !== state.project.timeline.join()) setTimeline(ids);
  });
}

/* 앞뒤 자르기: 클립의 사용 범위(in/out)를 바꾼다. 편집본에서는 클립의 첫 조각 앞·마지막 조각 뒤 손잡이 */
function trimDown(e, seg, edge) {
  const clip = clipById(seg.clipId);
  if (!clip || isLocked("V1")) return;
  const x0 = e.clientX;
  const in0 = clip.in_point, out0 = clip.out_point ?? clip.duration;
  const edgeT = edge === "left" ? seg.start : seg.start + seg.dur;
  const targets = snapTargets({ clipId: clip.clip_id });
  // 편집본은 서버가 다시 계산해야 길이가 바뀌므로, 끄는 동안 늘리고 줄인 구간을 따로 보여 준다
  const ghost = document.createElement("div");
  ghost.className = "tl-trim-ghost";
  if (tl.view !== SOURCE) app.lanes.V1.layer.appendChild(ghost);
  startDrag({ kind: "trim", clipId: clip.clip_id, edge }, ev => {
    let delta = (ev.clientX - x0) / tl.px;
    delta = snapped(edgeT + delta, targets, ev.altKey) - edgeT;
    if (edge === "left") delta = clamp(in0 + delta, 0, out0 - 0.5) - in0;
    else delta = clamp(out0 + delta, in0 + 0.5, clip.duration) - out0;
    ghost.style.left = `${xOf(edgeT + Math.min(delta, 0))}px`;       // 늘리거나 줄인 만큼의 구간
    ghost.style.width = `${Math.max(2, xOf(Math.abs(delta)))}px`;
    ghost.classList.toggle("shrink", edge === "left" ? delta > 0 : delta < 0);
    tl.drag.delta = delta;
    const value = edge === "left" ? in0 + delta : out0 + delta;
    tooltip(ev.clientX, ev.clientY, `${edge === "left" ? "시작" : "끝"} ${timecode(value, fps())}`
      + `  (${delta >= 0 ? "+" : ""}${delta.toFixed(2)}초)`);
    if (tl.view === SOURCE) {                 // 원본 보기는 클립 길이가 바로 바뀌어 보인다
      if (edge === "left") clip.in_point = in0 + delta; else clip.out_point = out0 + delta;
      app.invalidate();
    }
  }, async () => {
    ghost.remove();
    const delta = tl.drag?.delta || 0;
    if (Math.abs(delta) < 1e-3) return;
    const patch = { clip_id: clip.clip_id, in_point: edge === "left" ? in0 + delta : in0,
                    out_point: edge === "right" ? out0 + delta : out0 };
    try {
      setProject(await api.patchProject(pid(), { clips: [patch] }));
      emit("timeline-changed");
    } catch (err) {
      clip.in_point = in0;
      clip.out_point = out0;
      app.invalidate();
    }
  });
}

/* ---------------------------------------------------------------- 패널 높이 */

function resizerDown(e) {
  e.preventDefault();
  const panel = $("timeline-panel");
  const y0 = e.clientY, h0 = panel.getBoundingClientRect().height;
  startDrag({ kind: "resize" }, ev => {
    const h = clamp(h0 - (ev.clientY - y0), 150, Math.round(window.innerHeight * 0.7));
    panel.style.height = `${h}px`;
    tl.prefs.height = h;
    app.invalidateScroll();
  }, () => savePrefs());
}

/* ---------------------------------------------------------------- 초기화 */

export function initInteract(context) {
  app = context;
  const scroll = $("tl-scroll");
  $("timeline-panel").style.height = `${tl.prefs.height}px`;
  $("tl-resizer").addEventListener("mousedown", resizerDown);
  scroll.addEventListener("scroll", () => app.invalidateScroll());
  scroll.addEventListener("wheel", e => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) { zoomTo(tl.px * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX); return; }
    if (e.shiftKey) { scroll.scrollTop += e.deltaY; return; }
    scroll.scrollLeft += e.deltaY || e.deltaX;
  }, { passive: false });
  $("tl-ruler").addEventListener("mousedown", scrub);
  $("tl-playhead-cap").addEventListener("mousedown", scrub);
  $("tl-ruler").addEventListener("mousemove", e => {
    if (!tl.drag) tooltip(e.clientX, e.clientY, fmt(timeAt(e.clientX)));
  });
  $("tl-ruler").addEventListener("mouseleave", () => { if (!tl.drag) tooltip(0, 0, null); });

  const videoLane = app.lanes.V1.lane;
  videoLane.addEventListener("dragover", e => {
    if (!draggingClipId || isLocked("V1")) return;
    e.preventDefault();
    showGuide(dropX(dropIndex(timeAt(e.clientX))));
  });
  videoLane.addEventListener("dragleave", hideGuide);
  videoLane.addEventListener("drop", e => {
    e.preventDefault();
    hideGuide();
    if (draggingClipId && !isLocked("V1")) addToTimeline(draggingClipId, dropIndex(timeAt(e.clientX), draggingClipId));
  });
  return {
    clipDown, trimDown, zoomTo,
    openSource: seg => showSource(seg.clipId, seg.in, true),
    seekAt: e => { e.stopPropagation(); app.seek(timeAt(e.clientX)); },
    markerPick: marker => app.seek(marker.start),
    timeAt,
  };
}
