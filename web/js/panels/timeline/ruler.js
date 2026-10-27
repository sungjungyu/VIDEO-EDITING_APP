/* 눈금 (시각·프레임) + 장면 구간 마커 (장소 · 일). 마커는 눌러서 그 장면으로 이동한다. */

import { $, el } from "../../core/dom.js";
import { state } from "../../core/store.js";
import { prepareCanvas, token } from "./canvas.js";
import { clipRangeToTimeline, globalToClips, rulerLabel, tickSpacing } from "./model.js";
import { fps, RULER_H, segments, tl, xOf } from "./state.js";

const MARKER_COLORS = ["#7C6CF0", "#2FA8A0", "#D9822B", "#C2577E", "#4F8FD6", "#8DA34B", "#B0703C", "#6F7F9C"];

export function drawRuler(scrollLeft, width) {
  const ctx = prepareCanvas($("tl-ruler-canvas"), scrollLeft, width, RULER_H);
  const left = scrollLeft, right = scrollLeft + width;
  ctx.fillStyle = token("--tl-ruler");
  ctx.fillRect(left, 0, width, RULER_H);
  const { major, minor, frames } = tickSpacing(tl.px, fps());
  const step = major / minor;
  const first = Math.max(0, Math.floor(left / tl.px / step) * step);
  ctx.font = "10px \"JetBrains Mono\", Consolas, \"Courier New\", monospace";
  ctx.textBaseline = "top";
  for (let i = 0, t = first; xOf(t) <= right + 1; i++, t = first + i * step) {
    const x = Math.round(xOf(t)) + 0.5;
    const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6;
    ctx.strokeStyle = isMajor ? token("--tl-tick-major") : token("--tl-tick");
    ctx.beginPath();
    ctx.moveTo(x, isMajor ? 9 : 15);
    ctx.lineTo(x, 22);
    ctx.stroke();
    if (isMajor) {
      ctx.fillStyle = token("--tl-label");
      ctx.fillText(rulerLabel(t, frames, fps()), x + 4, 3);
    }
  }
  ctx.strokeStyle = token("--tl-grid");
  ctx.beginPath();
  ctx.moveTo(left, RULER_H - 0.5);
  ctx.lineTo(right, RULER_H - 0.5);
  ctx.stroke();
}

/* 트리의 '일'(없으면 '장소') 단위 장면을 지금 보기의 타임라인 조각으로 */
export function sceneMarkers() {
  const tree = state.analysis?.tree || [];
  const spans = state.analysis?.clips || [];
  const segs = segments();
  const out = [];
  tree.forEach((place, pi) => {
    const units = place.children?.length ? place.children : [place];
    for (const unit of units) {
      const label = unit === place ? place.title : `${place.title} · ${unit.title}`;
      for (const piece of globalToClips(spans, unit.start, unit.end)) {
        for (const r of clipRangeToTimeline(segs, piece.clipId, piece.start, piece.end)) {
          const last = out[out.length - 1];        // 편집본에서 잘린 곳을 사이에 둔 같은 장면 조각은 하나로
          if (last && last.nodeId === unit.id && r.start - last.end < 1e-3) last.end = r.end;
          else out.push({ ...r, label, color: MARKER_COLORS[pi % MARKER_COLORS.length], nodeId: unit.id });
        }
      }
    }
  });
  return out;
}

export function renderMarkers(onPick) {
  const box = $("tl-markers");
  box.innerHTML = "";
  for (const m of sceneMarkers()) {
    const width = xOf(m.end - m.start);
    if (width < 2) continue;
    const node = el("div", { class: "tl-marker", title: `장면: ${m.label}`,
                             style: { left: `${xOf(m.start)}px`, width: `${width}px` } },
      width > 46 ? el("span", { class: "tl-marker-label" }, m.label) : null);
    node.style.setProperty("--marker", m.color);
    node.addEventListener("mousedown", e => { e.stopPropagation(); onPick(m); });
    box.appendChild(node);
  }
}
