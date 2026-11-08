/* 타임라인 (자석식: 클립을 순서대로 붙여 놓는다 → 내보낸 영상도 이 순서).
   - 왼쪽 목록에서 끌어다 놓기 / [＋] : 타임라인에 넣기, 클립 위 × : 빼기
   - 클립을 좌우로 끌기: 순서 바꾸기, 양 끝 손잡이: 앞뒤 잘라 내기(쓰는 범위)
   - 클립 아래 파란 줄: 결과에 남는 부분 (빨간 바탕은 뺀 부분)
   - 자막 칸 한 번 누르기: 그 문장 고르기 (미리보기가 그 위치로, ④ 문장 목록에서도 같은 문장 표시)
     두 번 누르기: 자막 글자 고치기 · 칸 위의 ×/↺ 또는 Delete 키: 빼기/살리기
     (흐린 칸은 고르지 않은 장면이라 결과에 없음)
   - 확대: 도구 줄의 −/＋·슬라이더·전체 보기, 또는 Ctrl+휠 (그냥 휠은 가로 이동) */

import { api } from "../core/api.js";
import { $, el, perFrame, toast } from "../core/dom.js";
import { clamp, fmt } from "../core/format.js";
import { cutReason, reasonLabel } from "../core/labels.js";
import { decisionOf, emit, linesOfClip, mutatePlan, on, pid, selectLine, setProject, state, timelineLayout,
         usableEnd } from "../core/store.js";
import { addToTimeline, draggingClipId, removeFromTimeline, setTimeline } from "./media.js";
import { currentPosition, showSource } from "./preview.js";

const OFFSET = 56;
const MIN_PX = 2, MAX_PX = 400;
let trim = null;
let move = null;
let playheadDrag = false;

const px = () => state.ui.pxPerSec;

function totalDuration() {
  const layout = timelineLayout();
  return layout.length ? layout[layout.length - 1].start + layout[layout.length - 1].dur : 0;
}

const renderDuringDrag = perFrame(() => renderTimeline());

/* 눈금·썸네일은 보이는 범위(앞뒤로 화면 한 폭씩 여유)만 만든다.
   긴 영상을 크게 확대하면 전체 폭이 수십만 px이라 다시 그릴 때마다 요소 수만 개를 만들었다. */
let drawn = { from: 0, to: Infinity };

function visibleWindow() {
  const scroll = $("tl-scroll");
  const width = scroll.clientWidth || 1200;
  const left = scroll.scrollLeft - OFFSET;
  return { from: Math.max(0, (left - width) / px()), to: (left + 2 * width) / px() };
}

const redrawOnScroll = perFrame(() => {
  const scroll = $("tl-scroll");
  const viewFrom = (scroll.scrollLeft - OFFSET) / px(), viewTo = viewFrom + scroll.clientWidth / px();
  if (viewFrom >= drawn.from && viewTo <= drawn.to) return;      // 아직 그려 둔 범위 안
  drawn = visibleWindow();
  renderRuler(Math.max(totalDuration(), 10));
  renderVideoTrack();
});

function renderTimeline() {
  const total = Math.max(totalDuration(), 10);
  $("tl-content").style.minWidth = `${OFFSET + total * px() + 160}px`;
  drawn = visibleWindow();
  renderRuler(total);
  renderVideoTrack();
  renderSubtitleTrack();
  renderStats();
  movePlayhead();
}

function renderRuler(total) {
  const body = $("ruler-body");
  body.innerHTML = "";
  const nice = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const label = nice.find(n => n >= 80 / px()) || 600;
  const minor = label / 5;
  const first = Math.floor(drawn.from / label) * label;          // 큰 눈금에서 시작해야 major 판정이 맞는다
  const last = Math.min(Math.ceil(total) + label, drawn.to);
  for (let i = 0, t = first; t <= last; i += 1, t = first + i * minor) {
    const major = i % 5 === 0;
    body.appendChild(el("div", { class: `ruler-tick ${major ? "major" : "minor"}`, style: { left: `${t * px()}px` } }));
    if (major) body.appendChild(el("div", { class: "ruler-label", style: { left: `${t * px()}px` } }, fmt(t)));
  }
}

function keepRangesOf(clipId) {
  return (state.plan?.keep || []).filter(k => k.clip_id === clipId);
}

function renderVideoTrack() {
  const body = $("video-track-body");
  const hint = $("tl-empty-hint");
  body.innerHTML = "";
  body.appendChild(hint);
  const layout = timelineLayout();
  hint.style.display = layout.length ? "none" : "";
  const analyzed = new Set((state.analysis?.clips || []).map(s => s.clip_id));
  for (const { clip, start, dur } of layout) {
    const width = Math.max(dur * px(), 24);
    const block = el("div", {
      class: ["tl-clip", clip.clip_id === state.ui.selectedClipId ? "selected" : "",
              move?.clipId === clip.clip_id && move.moved ? "clip-moving" : ""].filter(Boolean).join(" "),
      style: { left: `${start * px()}px`, width: `${width}px` }, dataset: { id: clip.clip_id },
    });
    const info = state.media.get(clip.clip_id);
    if (info?.thumbnails?.length) {
      const strip = el("div", { class: "tl-clip-filmstrip" });
      const fw = info.thumbW || 85, iv = info.thumbInterval || 1;
      const x0 = Math.max(0, Math.floor((drawn.from - start) * px() / fw) * fw);    // 블록 안 보이는 범위
      const x1 = Math.min(width + fw, (drawn.to - start) * px());
      strip.style.paddingLeft = `${x0}px`;
      for (let x = x0; x < x1; x += fw) {
        const idx = clamp(Math.floor((clip.in_point + x / px()) / iv), 0, info.thumbnails.length - 1);
        strip.appendChild(el("img", { src: info.thumbnails[idx], draggable: "false", style: { width: `${fw}px`, height: "100%" } }));
      }
      block.appendChild(strip);
    }
    const kept = keepRangesOf(clip.clip_id).reduce((a, k) => a + (k.end - k.start), 0);
    block.appendChild(el("div", { class: "tl-clip-overlay" },
      el("div", { class: "tl-clip-name" }, clip.filename),
      el("div", { class: "tl-clip-dur" }, state.analysis ? `${fmt(dur)} → 남는 길이 ${fmt(kept)}` : fmt(dur))));
    if (state.analysis && !analyzed.has(clip.clip_id)) {
      block.appendChild(el("div", { class: "tl-clip-warn", title: "이 영상은 아직 분석하지 않았어요" }, "분석 필요"));
    }
    if (state.plan) {
      const strip = el("div", { class: "tl-keep-strip" });
      for (const k of keepRangesOf(clip.clip_id)) {
        strip.appendChild(el("div", { class: "tl-keep-seg", style: {
          left: `${(k.start - clip.in_point) * px()}px`, width: `${Math.max(1, (k.end - k.start) * px())}px` } }));
      }
      block.appendChild(strip);
    }
    for (const edge of ["left", "right"]) {
      const handle = el("div", { class: `trim-handle trim-${edge}`,
                                 title: edge === "left" ? "끌어서 앞부분 잘라 내기" : "끌어서 뒷부분 잘라 내기" });
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
  const body = $("subtitle-track-body");
  body.innerHTML = "";
  if (!state.analysis) {                // 자막은 AI 분석(받아쓰기)이 만든다 → 빈 줄 대신 이유와 갈 곳을 보여 준다
    if (!timelineLayout().length) return;
    const hint = el("div", { class: "tl-sub-hint" },
      state.ui.analyzing ? `받아쓰는 중… ${Math.round(state.ui.analyzing.progress)}%` : "자막은 AI 분석을 하면 여기에 생겨요");
    if (!state.ui.analyzing) hint.appendChild(el("button", { class: "btn-mini", dataset: { go: "2" } }, "② AI 분석으로"));
    body.appendChild(hint);
    return;
  }
  for (const { clip, start } of timelineLayout()) {
    const ranges = keepRangesOf(clip.clip_id);
    for (const line of linesOfClip(clip.clip_id)) {
      if (line.end <= clip.in_point || line.start >= usableEnd(clip)) continue;
      const d = decisionOf(line.seg_id);
      const inOutput = ranges.some(k => k.start < line.end && line.start < k.end);
      const left = (start + Math.max(0, line.start - clip.in_point)) * px();
      const width = Math.max((Math.min(line.end, usableEnd(clip)) - Math.max(line.start, clip.in_point)) * px(), 6);
      const tag = d.keep ? (d.emphasis ? "강조" : "") : reasonLabel(cutReason(d));
      const seg = el("div", {
        class: ["sub-seg", d.keep ? "sub-keep" : "sub-cut", d.keep && !inOutput ? "sub-dim" : "",
                d.keep && d.emphasis ? "sub-emph" : "", state.ui.flash.has(line.seg_id) ? "flash" : "",
                state.ui.selectedLineId === line.seg_id ? "selected" : ""].filter(Boolean).join(" "),
        style: { left: `${left}px`, width: `${width}px` }, dataset: { seg: line.seg_id },
        title: `${d.text || line.text || "(받아쓰기 없음)"}\n${d.keep ? "살림" : `뺌 · ${reasonLabel(cutReason(d))}`}${d.note ? ` · ${d.note}` : ""}`
               + `${d.keep && !inOutput ? "\n(고르지 않은 장면이라 결과에 없어요)" : ""}`
               + `\n누르기: 고르기 · 두 번 누르기: 글자 고치기 · Delete: ${d.keep ? "빼기" : "살리기"}`,
      }, el("span", { class: "sub-seg-text" }, (d.text || line.text) || "…"), tag ? el("span", { class: "sub-seg-tag" }, tag) : null);
      const act = el("button", { class: `sub-seg-act${d.keep ? "" : " is-cut"}`, title: d.keep ? "이 문장 빼기" : "이 문장 살리기" },
                     d.keep ? "×" : "↺");
      act.addEventListener("click", e => { e.stopPropagation(); toggleLine(line.seg_id); });
      act.addEventListener("dblclick", e => e.stopPropagation());
      seg.appendChild(act);
      seg.addEventListener("click", () => selectLine(line, "timeline"));
      seg.addEventListener("dblclick", () => emit("edit-line", line));
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
  const node = $("tl-stats");
  if (!layout.length) { node.textContent = ""; return; }
  const source = layout.reduce((a, l) => a + l.dur, 0);
  const parts = [`영상 ${layout.length}개`, `원본 ${fmt(source)}`];
  if (state.plan && state.analysis) parts.push(`결과 ${fmt(state.plan.duration)}`);
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
  if (x !== null) $("playhead").style.left = `${OFFSET + x}px`;
}

function seekToTimelineX(x) {
  const t = Math.max(0, x / px());
  const item = timelineLayout().find(l => t >= l.start && t < l.start + l.dur) || timelineLayout().at(-1);
  if (!item) return;
  showSource(item.clip.clip_id, item.clip.in_point + clamp(t - item.start, 0, item.dur));
}

/* ---------------------------------------------------------------- 끌어다 놓기 */

function dropIndexAt(clientX, excludeId = null) {
  const body = $("video-track-body");
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
  const body = $("video-track-body");
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
      renderDuringDrag();          // 마우스 이벤트가 몰려도 화면 갱신 주기마다 한 번만 다시 그린다
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
      const ruler = $("ruler-body").getBoundingClientRect();
      const x = Math.max(0, e.clientX - ruler.left);
      $("playhead").style.left = `${OFFSET + x}px`;
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

  $("playhead-handle").addEventListener("mousedown", e => {
    playheadDrag = true; e.preventDefault(); e.stopPropagation();
  });
  $("ruler-body").addEventListener("click", e => {
    seekToTimelineX(e.clientX - e.currentTarget.getBoundingClientRect().left);
  });

  $("tl-scroll").addEventListener("scroll", redrawOnScroll, { passive: true });
  new ResizeObserver(redrawOnScroll).observe($("tl-scroll"));
  $("tl-scroll").addEventListener("wheel", e => {
    const scroll = e.currentTarget;
    e.preventDefault();
    if (!e.ctrlKey) { scroll.scrollLeft += e.deltaY || e.deltaX; return; }
    setZoom(px() * (e.deltaY < 0 ? 1.12 : 1 / 1.12), e.clientX - scroll.getBoundingClientRect().left);
  }, { passive: false });
  $("btn-zoom-in").addEventListener("click", () => setZoom(px() * 1.5));
  $("btn-zoom-out").addEventListener("click", () => setZoom(px() / 1.5));
  $("btn-zoom-fit").addEventListener("click", zoomToFit);
  $("tl-zoom-range").addEventListener("input", e => setZoom(MIN_PX * (MAX_PX / MIN_PX) ** (Number(e.target.value) / 100)));

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
  on("flash", renderSubtitleTrack);
  on("analyzing", () => { if (!state.analysis) renderSubtitleTrack(); });
  on("reveal-line", revealLine);
  on("line-selected", ({ line, from }) => {
    // 다시 그리지 않고 표시만 옮긴다 (다시 그리면 두 번 누르기가 새 요소에 떨어져 dblclick이 안 생긴다)
    const body = $("subtitle-track-body");
    body.querySelectorAll(".sub-seg.selected").forEach(n => n.classList.remove("selected"));
    if (!line) return;
    body.querySelector(`.sub-seg[data-seg="${CSS.escape(line.seg_id)}"]`)?.classList.add("selected");
    showSource(line.clip_id, line.start);
    if (from === "list") revealLine(line);
  });
}

/* 확대 배율을 바꾼다. anchorX(스크롤 영역 안 x)의 시각이 제자리에 있게 (없으면 가운데) */
function setZoom(next, anchorX = null) {
  const scroll = $("tl-scroll");
  const x = anchorX ?? scroll.clientWidth / 2;
  const sec = (x + scroll.scrollLeft - OFFSET) / px();
  state.ui.pxPerSec = clamp(next, MIN_PX, MAX_PX);
  renderTimeline();
  scroll.scrollLeft = sec * px() + OFFSET - x;
  syncZoomRange();
}

function syncZoomRange() {
  $("tl-zoom-range").value = String(Math.round(100 * Math.log(px() / MIN_PX) / Math.log(MAX_PX / MIN_PX)));
}

/* 문장 하나가 보이게 타임라인을 옮긴다 (수정 요청으로 바뀐 문장 보여 주기) */
function revealLine(line) {
  const item = timelineLayout().find(l => l.clip.clip_id === line.clip_id);
  if (!item) return;
  const scroll = $("tl-scroll");
  const x = (item.start + Math.max(0, line.start - item.clip.in_point)) * px();
  scroll.scrollLeft = Math.max(0, x - scroll.clientWidth / 3);
}

/* 긴 영상도 처음엔 타임라인 폭에 맞게 */
export function zoomToFit() {
  const total = totalDuration();
  const width = $("tl-scroll").clientWidth - OFFSET - 40;
  if (total > 0 && width > 0) state.ui.pxPerSec = clamp(width / total, MIN_PX, 120);
  renderTimeline();
  syncZoomRange();
}
