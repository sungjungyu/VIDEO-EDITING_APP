/* T1 텍스트 트랙: 제목(처음 3초)·촬영지 자막. 결과 초로 계산된 것이라 원본 보기에서는 원본 위치로 옮겨 놓는다. */

import { el } from "../../../core/dom.js";
import { state } from "../../../core/store.js";
import { clipRangeToTimeline, outputToClips, SEQUENCE } from "../model.js";
import { tl, xOf } from "../state.js";

const LABELS = { title: "제목", location: "촬영지" };

export function renderOverlay(layer, ctxInfo) {
  const { height, segs } = ctxInfo;
  layer.innerHTML = "";
  for (const event of (state.plan?.events || []).filter(e => e.style !== "subtitle")) {
    const pieces = tl.view === SEQUENCE ? [{ start: event.start, end: event.end }]
      : outputToClips(state.plan.keep, event.start, event.end)
        .flatMap(p => clipRangeToTimeline(segs, p.clipId, p.start, p.end));
    for (const piece of pieces) {
      const w = Math.max(xOf(piece.end - piece.start), 3);
      const text = event.text.replace(/\n/g, " ");
      const chip = el("div", { class: `tl-text tl-text-${event.style}`, title: `${LABELS[event.style] || "텍스트"}: ${text}`,
                               dataset: { style: event.style },
                               style: { left: `${xOf(piece.start)}px`, width: `${w}px`, top: "3px", height: `${height - 6}px` } },
        w > 30 ? el("span", { class: "tl-text-label" }, `${event.style === "location" ? "📍 " : "T "}${text}`) : null);
      layer.appendChild(chip);
    }
  }
}
