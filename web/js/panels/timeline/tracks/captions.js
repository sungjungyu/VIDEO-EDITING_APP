/* C1 자막 트랙.
   편집본: 결과 영상에 실제로 나오는 자막 장면(plan.events) — 화면에 보이는 그대로
   원본  : 받아쓰기 문장 전체. 자른 문장은 점선·취소선, 고르지 않은 장면의 문장은 흐리게
   보이는 범위(+ 여유)만 그린다 → 문장이 수천 개여도 DOM 수가 일정하다.
   클릭·더블클릭·메뉴는 트랙 단위로 받는다 (index.js bindLaneEvents) — 다시 그려도 더블클릭이 끊기지 않게. */

import { el } from "../../../core/dom.js";
import { decisionOf, linesOfClip, state } from "../../../core/store.js";
import { clipRangeToTimeline, SEQUENCE } from "../model.js";
import { tl, xOf } from "../state.js";

const REASON_CLASS = { NG: "ng", 반복: "repeat", 군더더기: "filler", 지시어: "cue" };

/* 지금 보기의 자막 칸 목록 [{segId, start, end, text, decision, inOutput}] */
export function captionItems(segs) {
  if (tl.view === SEQUENCE) {
    return (state.plan?.events || []).filter(e => e.style === "subtitle" && e.seg_id)
      .map(e => ({ segId: e.seg_id, start: e.start, end: e.end, text: e.text.replace(/\n/g, " "),
                   decision: decisionOf(e.seg_id), inOutput: true }));
  }
  const items = [];
  const keep = state.plan?.keep || [];
  for (const seg of segs) {
    for (const line of linesOfClip(seg.clipId)) {
      for (const piece of clipRangeToTimeline([seg], seg.clipId, line.start, line.end)) {
        const d = decisionOf(line.seg_id);
        const inOutput = keep.some(k => k.clip_id === line.clip_id && k.start < line.end && line.start < k.end);
        items.push({ segId: line.seg_id, start: piece.start, end: piece.end, text: (d.text || line.text) || "",
                     decision: d, inOutput });
      }
    }
  }
  return items;
}

export function renderCaptions(layer, ctxInfo) {
  const { scrollLeft, width, height, segs } = ctxInfo;
  const buffer = width;                        // 양옆으로 한 화면씩 더 그려 둔다 (스크롤할 때 빈칸이 안 보이게)
  const from = scrollLeft - buffer, to = scrollLeft + width + buffer;
  layer.innerHTML = "";
  for (const item of captionItems(segs)) {
    const x = xOf(item.start), w = Math.max(xOf(item.end - item.start), 3);
    if (x > to || x + w < from) continue;
    const d = item.decision;
    const classes = ["tl-cap", d.keep ? "keep" : `cut reason-${REASON_CLASS[d.reason] || "etc"}`,
      d.keep && d.emphasis ? "emph" : "", d.source === "user" ? "user" : "",
      d.keep && !item.inOutput ? "dim" : "", tl.selected.has(item.segId) ? "selected" : "",
      w < 26 ? "narrow" : ""];
    const label = item.text || "(말소리)";
    const tip = `${label}\n${d.keep ? (d.emphasis ? "남김 · 강조" : "남김") : `자름 · ${d.reason}`}${d.note ? ` — ${d.note}` : ""}`
      + `${d.source === "user" ? "\n(내가 바꿈)" : d.source === "ai" ? "\n(AI 판단)" : "\n(규칙 판단)"}`
      + `${d.keep && !item.inOutput ? "\n고르지 않은 장면이라 결과에 없음" : ""}`;
    const chip = el("div", { class: classes.filter(Boolean).join(" "), dataset: { seg: item.segId },
                             style: { left: `${x}px`, width: `${w}px`, top: "3px", height: `${height - 6}px` },
                             title: tip, role: "button", "aria-label": tip, "aria-pressed": String(tl.selected.has(item.segId)) },
      w >= 26 ? el("span", { class: "tl-cap-text" }, label) : null);
    layer.appendChild(chip);
  }
}
