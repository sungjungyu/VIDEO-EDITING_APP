/* 타임라인 (자석식: 클립을 순서대로 붙여 놓는다 → 렌더도 이 순서).
   - 왼쪽 목록에서 끌어다 놓기 / [+] : 타임라인에 넣기, 클립 위 × : 빼기
   - 클립을 좌우로 끌기: 순서 바꾸기, 양 끝 손잡이: 앞뒤 잘라 내기(사용 범위)
   - 클립 아래 파란 줄: 편집 계획에서 실제로 남는 구간 (빨간 바탕은 잘린 곳)
   - 자막 칸 클릭: 그 문장 남김/자름 전환 (흐린 칸은 고르지 않은 장면이라 결과에 없음) */

import { api } from "./api.js";
import { decisionOf, emit, linesOfClip, mutatePlan, on, pid, setProject, state, timelineLayout,
         usableEnd } from "./store.js";
import { addToTimeline, draggingClipId, removeFromTimeline, setTimeline } from "./media.js";
import { currentPosition, showSource } from "./preview.js";
import { clamp, el, fmt, toast } from "./util.js";

const OFFSET = 52;
let trim = null;
let move = null;
let playheadDrag = false;

const px = () => state.ui.pxPerSec;

function totalDuration() {
  const layout = timelineLayout();
  return layout.length ? layout[layout.length - 1].start + layout[layout.length - 1].dur : 0;
}

export function renderTimeline() {
  const total = Math.max(totalDuration(), 10);
  document.getElementById("tl-content").style.minWidth = `${OFFSET + total * px() + 160}px`;
  renderRuler(total);
  renderVideoTrack();
  renderSubtitleTrack();
  renderStats();
  movePlayhead();
}

function renderRuler(total) {
  const body = document.getElementById("ruler-body");
  body.innerHTML = "";
  const nice = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const label = nice.find(n => n >= 80 / px()) || 600;
  const minor = label / 5;
  for (let t = 0; t <= Math.ceil(total) + label; t += minor) {
    const major = Math.abs(t % label) < minor * 0.5;
    body.appendChild(el("div", { class: `ruler-tick ${major ? "major" : "minor"}`, style: { left: `${t * px()}px` } }));
    if (major) body.appendChild(el("div", { class: "ruler-label", style: { left: `${t * px()}px` } }, fmt(t)));
  }
}

function keepRangesOf(clipId) {
  return (state.plan?.keep || []).filter(k => k.clip_id === clipId);
}

function renderVideoTrack() {
  const body = document.getElementById("video-track-body");
  const hint = document.getElementById("tl-empty-hint");
  body.innerHTML = "";
  body.appendChild(hint);
  const layout = timelineLayout();
  hint.style.display = layout.length ? "none" : "";
  const analyzed = new Set((state.analysis?.clips || []).map(s => s.clip_id));
  for (const { clip, start, dur } of layout) {
    const width = Math.max(dur * px(), 24);
    const block = el("div", {
      class: ["tl-clip", clip.clip_id === state.ui.selectedClipId ? "selected" : "",
              analyzed.has(clip.clip_id) ? "analyzed" : "", state.analysis && !analyzed.has(clip.clip_id) ? "needs-analysis" : "",
              move?.clipId === clip.clip_id && move.moved ? "clip-moving" : ""].filter(Boolean).join(" "),
      style: { left: `${start * px()}px`, width: `${width}px` }, dataset: { id: clip.clip_id },
    });
    const info = state.media.get(clip.clip_id);
    if (info?.thumbnails?.length) {
      const strip = el("div", { class: "tl-clip-filmstrip" });
      const fw = info.thumbW || 85, iv = info.thumbInterval || 1;
      for (let x = 0; x < width + fw; x += fw) {
        const idx = clamp(Math.floor((clip.in_point + x / px()) / iv), 0, info.thumbnails.length - 1);
        strip.appendChild(el("img", { src: info.thumbnails[idx], draggable: "false", style: { width: `${fw}px`, height: "100%" } }));
      }
      block.appendChild(strip);
    }
    const kept = keepRangesOf(clip.clip_id).reduce((a, k) => a + (k.end - k.start), 0);
    block.appendChild(el("div", { class: "tl-clip-overlay" },
      el("div", { class: "tl-clip-name" }, clip.filename),
      el("div", { class: "tl-clip-dur" }, state.plan ? `${fmt(dur)} → 결과 ${fmt(kept)}` : fmt(dur))));
    if (state.plan) {
      const strip = el("div", { class: "tl-keep-strip" });
      for (const k of keepRangesOf(clip.clip_id)) {
        strip.appendChild(el("div", { class: "tl-keep-seg", style: {
          left: `${(k.start - clip.in_point) * px()}px`, width: `${Math.max(1, (k.end - k.start) * px())}px` } }));
      }
      block.appendChild(strip);
    }
    for (const edge of ["left", "right"]) {
      const handle = el("div", { class: `trim-handle trim-${edge}` });
      handle.addEventListener("mousedown", e => {
        e.preventDefault(); e.stopPropagation();
        trim = { clipId: clip.clip_id, edge, x: e.clientX, in0: clip.in_point, out0: usableEnd(clip) };
      });
      block.appendChild(handle);
    }
    block.appendChild(el("button", { class: "tl-clip-remove", title: "타임라인에서 빼기",
      onmousedown: e => e.stopPropagation(),
      onclick: e => { e.stopPropagation(); removeFromTimeline(clip.clip_id); } }, "×"));
    block.addEventListener("mousedown", e => {
      if (e.target.closest(".trim-handle") || e.button !== 0) return;
      e.preventDefault();
      move = { clipId: clip.clip_id, x: e.clientX, moved: false, target: null };
    });
    block.addEventListener("dblclick", () => showSource(clip.clip_id, clip.in_point, true));
    body.appendChild(block);
  }
}

function renderSubtitleTrack() {
  const body = document.getElementById("subtitle-track-body");
  body.innerHTML = "";
  if (!state.analysis) return;
  for (const { clip, start } of timelineLayout()) {
    const ranges = keepRangesOf(clip.clip_id);
    for (const line of linesOfClip(clip.clip_id)) {
      if (line.end <= clip.in_point || line.start >= usableEnd(clip)) continue;
      const d = decisionOf(line.seg_id);
      const inOutput = ranges.some(k => k.start < line.end && line.start < k.end);
      const left = (start + Math.max(0, line.start - clip.in_point)) * px();
      const width = Math.max((Math.min(line.end, usableEnd(clip)) - Math.max(line.start, clip.in_point)) * px(), 6);
      const tag = d.keep ? (d.emphasis ? "강조" : "남김") : d.reason;
      const seg = el("div", {
        class: ["sub-seg", d.keep ? "sub-keep" : "sub-cut", d.keep && !inOutput ? "sub-dim" : "",
                d.keep && d.emphasis ? "sub-emph" : ""].filter(Boolean).join(" "),
        style: { left: `${left}px`, width: `${width}px` },
        title: `${line.text || "(받아쓰기 없음)"}\n${d.keep ? "남김" : `자름 · ${d.reason}`}${d.note ? ` · ${d.note}` : ""}`
               + `${d.keep && !inOutput ? "\n(고르지 않은 장면이라 결과에 없음)" : ""}\n클릭: 남김/자름 전환`,
      }, el("span", { class: "sub-seg-text" }, (d.text || line.text) || "…"), el("span", { class: "sub-seg-tag" }, tag));
      seg.addEventListener("click", () => toggleLine(line.seg_id));
      body.appendChild(seg);
    }
  }
}

export async function toggleLine(segId) {
  const d = decisionOf(segId);
  try {
    await mutatePlan(() => api.patchLines(pid(), [{ seg_id: segId, keep: !d.keep }]));
  } catch (err) {
    toast(err.message, "error");
  }
}

function renderStats() {
  const layout = timelineLayout();
  const node = document.getElementById("tl-stats");
  if (!layout.length) { node.textContent = ""; return; }
  const source = layout.reduce((a, l) => a + l.dur, 0);
  const parts = [`클립 ${layout.length}개`, `원본 ${fmt(source)}`];
  if (state.plan) parts.push(`결과 ${fmt(state.plan.duration)} (구간 ${state.plan.keep.length}개)`);
  node.textContent = parts.join("  ·  ");
}

/* ---------------------------------------------------------------- 재생 위치 */

function timelineXOf(pos) {
  const item = timelineLayout().find(l => l.clip.clip_id === pos.clipId);
  if (!item) return null;
  return (item.start + clamp(pos.time - item.clip.in_point, 0, item.dur)) * px();
}

function movePlayhead(pos = currentPosition()) {
  if (playheadDrag) return;
  const x = timelineXOf(pos);
  if (x !== null) document.getElementById("playhead").style.left = `${OFFSET + x}px`;
}

function seekToTimelineX(x) {
  const t = Math.max(0, x / px());
  const item = timelineLayout().find(l => t >= l.start && t < l.start + l.dur) || timelineLayout().at(-1);
  if (!item) return;
  showSource(item.clip.clip_id, item.clip.in_point + clamp(t - item.start, 0, item.dur));
}

/* ---------------------------------------------------------------- 끌어다 놓기 */

function dropIndexAt(clientX, excludeId = null) {
  const body = document.getElementById("video-track-body");
  const x = (clientX - body.getBoundingClientRect().left) / px();
  const layout = timelineLayout().filter(l => l.clip.clip_id !== excludeId);
  for (let i = 0; i < layout.length; i++) {
    if (x < layout[i].start + layout[i].dur / 2) return i;
  }
  return layout.length;
}

function markDrop(index, excludeId) {
  document.querySelectorAll(".tl-clip").forEach(b => b.classList.remove("drop-before", "drop-after"));
  const blocks = [...document.querySelectorAll(".tl-clip")].filter(b => b.dataset.id !== excludeId);
  if (!blocks.length) return;
  if (index < blocks.length) blocks[index].classList.add("drop-before");
  else blocks[blocks.length - 1].classList.add("drop-after");
}

async function finishTrim() {
  const t = trim;
  trim = null;
  const clip = state.project.clips.find(c => c.clip_id === t.clipId);
  try {
    setProject(await api.patchProject(pid(), { clips: [{ clip_id: clip.clip_id, in_point: clip.in_point,
                                                         out_point: clip.out_point ?? clip.duration }] }));
    emit("timeline-changed");
  } catch (err) {
    toast(err.message, "error");
  }
}

export function initTimeline() {
  const body = document.getElementById("video-track-body");
  body.addEventListener("dragover", e => { e.preventDefault(); if (draggingClipId) markDrop(dropIndexAt(e.clientX)); });
  body.addEventListener("dragleave", () => markDrop(-1));
  body.addEventListener("drop", e => {
    e.preventDefault();
    if (!draggingClipId) return;
    const index = dropIndexAt(e.clientX, draggingClipId);
    addToTimeline(draggingClipId, index);
  });
  body.addEventListener("click", e => {          // 빈 곳을 누르면 선택 해제 (클립 선택은 mouseup에서)
    if (e.target !== body && e.target.id !== "tl-empty-hint") return;
    state.ui.selectedClipId = null;
    emit("selection");
    renderVideoTrack();
  });

  document.addEventListener("mousemove", e => {
    if (trim) {
      const clip = state.project.clips.find(c => c.clip_id === trim.clipId);
      const delta = (e.clientX - trim.x) / px();
      if (trim.edge === "left") clip.in_point = clamp(trim.in0 + delta, 0, trim.out0 - 0.5);
      else clip.out_point = clamp(trim.out0 + delta, clip.in_point + 0.5, clip.duration);
      renderTimeline();
      return;
    }
    if (move) {
      if (!move.moved && Math.abs(e.clientX - move.x) < 5) return;
      move.moved = true;
      move.target = dropIndexAt(e.clientX, move.clipId);
      markDrop(move.target, move.clipId);
      return;
    }
    if (playheadDrag) {
      const ruler = document.getElementById("ruler-body").getBoundingClientRect();
      const x = Math.max(0, e.clientX - ruler.left);
      document.getElementById("playhead").style.left = `${OFFSET + x}px`;
      seekToTimelineX(x);
    }
  });
  document.addEventListener("mouseup", () => {
    if (trim) finishTrim();
    if (move) {
      const m = move;
      move = null;
      markDrop(-1);
      if (m.moved && m.target !== null) {
        const ids = state.project.timeline.filter(id => id !== m.clipId);
        ids.splice(m.target, 0, m.clipId);
        if (ids.join() !== state.project.timeline.join()) setTimeline(ids);
        else renderTimeline();
      } else {
        state.ui.selectedClipId = m.clipId;
        emit("selection");
        const clip = state.project.clips.find(c => c.clip_id === m.clipId);
        showSource(m.clipId, clip.in_point);
        renderVideoTrack();
      }
    }
    playheadDrag = false;
  });

  document.getElementById("playhead-handle").addEventListener("mousedown", e => {
    playheadDrag = true; e.preventDefault(); e.stopPropagation();
  });
  document.getElementById("ruler-body").addEventListener("click", e => {
    seekToTimelineX(e.clientX - e.currentTarget.getBoundingClientRect().left);
  });

  let zoomTimer = null;
  document.getElementById("tl-scroll").addEventListener("wheel", e => {
    const scroll = e.currentTarget;
    e.preventDefault();
    if (!e.ctrlKey) { scroll.scrollLeft += e.deltaY || e.deltaX; return; }
    const rect = scroll.getBoundingClientRect();
    const sec = (e.clientX - rect.left + scroll.scrollLeft - OFFSET) / px();
    state.ui.pxPerSec = clamp(px() * (e.deltaY < 0 ? 1.12 : 1 / 1.12), 2, 400);
    renderTimeline();
    scroll.scrollLeft = sec * px() + OFFSET - (e.clientX - rect.left);
    const hint = document.getElementById("zoom-hint");
    hint.textContent = `확대 ${Math.round(px())}px/초`;
    hint.classList.add("show");
    clearTimeout(zoomTimer);
    zoomTimer = setTimeout(() => hint.classList.remove("show"), 900);
  }, { passive: false });

  let lastCount = -1;
  on("project", () => {
    const count = state.project?.timeline.length || 0;
    if (count !== lastCount) {                 // 클립을 넣거나 빼면 전체가 보이게 배율을 맞춘다
      const first = timelineLayout()[0];
      if (lastCount <= 0 && first && !currentPosition().clipId) showSource(first.clip.clip_id, first.clip.in_point);
      lastCount = count;
      zoomToFit();
      return;
    }
    renderTimeline();
  });
  on("plan", renderTimeline);
  on("analysis", renderTimeline);
  on("thumbnails", renderVideoTrack);
  on("time", movePlayhead);
}

/* 긴 영상도 처음엔 타임라인 폭에 맞게 */
export function zoomToFit() {
  const total = totalDuration();
  const width = document.getElementById("tl-scroll").clientWidth - OFFSET - 40;
  if (total > 0 && width > 0) state.ui.pxPerSec = clamp(width / total, 2, 120);
  renderTimeline();
}
