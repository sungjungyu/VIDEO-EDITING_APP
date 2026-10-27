/* V1 영상 트랙.
   캔버스: 필름 띠(썸네일), 원본 보기의 잘린 곳(빗금 + 빨간 윗선 + 이유), 줌인 효과 밑줄
   DOM   : 클립 블록(이름·길이·선택 테두리·앞뒤 자르기 손잡이·빼기 버튼), 편집본 이음매(✂), 줌인 배지 */

import { el } from "../../../core/dom.js";
import { fmt } from "../../../core/format.js";
import { clipById, decisionOf, state } from "../../../core/store.js";
import { hatch, prepareCanvas, roundRect, token } from "../canvas.js";
import { clipRangeToTimeline, cutRanges, cutReason, joins, SEQUENCE, SOURCE } from "../model.js";
import { isLocked, tl, xOf } from "../state.js";

const images = new Map();          // 썸네일 dataURL → Image (한 번만 만든다)

function image(src, onReady) {
  let img = images.get(src);
  if (!img) {
    img = new Image();
    img.onload = onReady;
    img.src = src;
    images.set(src, img);
  }
  return img.complete && img.naturalWidth ? img : null;
}

/* 원본 보기: 잘린 곳 (타임라인 조각 + 이유) */
export function cutRegions(segs) {
  const clips = segs.map(s => clipById(s.clipId)).filter(Boolean);
  const lines = state.analysis?.lines || [];
  const mode = state.plan?.selection?.mode;
  const out = [];
  for (const range of cutRanges(clips, state.plan?.keep)) {
    const reason = cutReason(range, lines, decisionOf, mode);
    for (const piece of clipRangeToTimeline(segs, range.clipId, range.start, range.end)) {
      out.push({ ...piece, reason, clipId: range.clipId, clipStart: range.start, clipEnd: range.end });
    }
  }
  return out;
}

export function drawVideo(canvas, ctxInfo, redraw) {
  const { scrollLeft, width, height, segs } = ctxInfo;
  const ctx = prepareCanvas(canvas, scrollLeft, width, height);
  const left = scrollLeft, right = scrollLeft + width;
  const top = 3, h = height - 6;
  for (const seg of segs) {
    const x = xOf(seg.start), w = Math.max(xOf(seg.dur), 2);
    if (x > right || x + w < left) continue;
    ctx.save();
    roundRect(ctx, x + 0.5, top, w - 1, h, 6);
    ctx.clip();
    ctx.fillStyle = token("--tl-clip-video");
    ctx.fillRect(x, top, w, h);
    const media = state.media.get(seg.clipId);
    const thumbs = media?.thumbnails || [];
    if (thumbs.length && h > 20) {
      const tileW = h * 16 / 9;
      const from = Math.max(x, left - tileW), to = Math.min(x + w, right + tileW);
      for (let tx = x + Math.floor((from - x) / tileW) * tileW; tx < to; tx += tileW) {
        const t = seg.in + (tx - x) / tl.px;
        const index = Math.min(thumbs.length - 1, Math.max(0, Math.floor(t / (media.thumbInterval || 1))));
        const img = image(thumbs[index], redraw);
        if (img) ctx.drawImage(img, tx, top, tileW, h);
      }
      ctx.fillStyle = "rgba(10,14,20,.28)";
      ctx.fillRect(x, top, w, h);
    }
    ctx.restore();
  }
  if (tl.view === SOURCE) {
    ctx.font = "600 10px Pretendard, 'Segoe UI', sans-serif";
    ctx.textBaseline = "middle";
    for (const cut of cutRegions(segs)) {
      const x = xOf(cut.start), w = xOf(cut.end - cut.start);
      if (x > right || x + w < left || w < 1) continue;
      hatch(ctx, x, top, w, h);
      ctx.fillStyle = token("--cut");
      ctx.fillRect(x, top, w, 2);
      if (w > 44) {
        ctx.fillStyle = "rgba(255,170,170,.95)";
        const label = `✂ ${cut.reason}`;
        const tw = ctx.measureText(label).width;
        if (tw + 8 < w) ctx.fillText(label, x + (w - tw) / 2, top + h / 2);
      }
    }
  }
  for (const fx of state.plan?.effects || []) {
    for (const piece of clipRangeToTimeline(segs, fx.clip_id, fx.start, fx.end)) {
      const x = xOf(piece.start), w = xOf(piece.end - piece.start);
      if (x > right || x + w < left) continue;
      ctx.fillStyle = token("--emph");
      ctx.fillRect(x, top + h - 3, w, 3);
    }
  }
}

export function renderVideoDom(layer, ctxInfo) {
  const { segs, height } = ctxInfo;
  layer.innerHTML = "";
  const analyzed = new Set((state.analysis?.clips || []).map(s => s.clip_id));
  const locked = isLocked("V1");
  segs.forEach((seg, index) => {
    const clip = clipById(seg.clipId);
    if (!clip) return;
    const x = xOf(seg.start), w = Math.max(xOf(seg.dur), 4);
    const kept = (state.plan?.keep || []).filter(k => k.clip_id === clip.clip_id).reduce((a, k) => a + k.end - k.start, 0);
    const classes = ["tl-clip",
      clip.clip_id === state.ui.selectedClipId ? "selected" : "",
      state.analysis && !analyzed.has(clip.clip_id) ? "needs-analysis" : "",
      clip.proxy ? "" : "proxy-pending",
      tl.drag?.kind === "move" && tl.drag.clipId === clip.clip_id && tl.drag.moved ? "moving" : ""];
    const block = el("div", { class: classes.filter(Boolean).join(" "), dataset: { clip: clip.clip_id, index: String(index) },
                              style: { left: `${x}px`, width: `${w}px`, top: "3px", height: `${height - 6}px` },
                              title: `${clip.filename}\n원본 ${fmt(seg.dur)}${tl.view === SOURCE ? ` → 결과 ${fmt(kept)}` : ""}` });
    if (w > 36) {
      block.appendChild(el("div", { class: "tl-clip-head" },
        el("span", { class: "tl-clip-name" }, clip.filename),
        w > 120 ? el("span", { class: "tl-clip-dur" }, tl.view === SOURCE ? `${fmt(seg.dur)} → ${fmt(kept)}` : fmt(seg.dur)) : null));
    }
    if (!locked) {
      if (tl.view === SOURCE || seg.first) block.appendChild(handle("left"));
      if (tl.view === SOURCE || seg.last) block.appendChild(handle("right"));
      if (w > 48 && (tl.view === SOURCE || seg.first)) {
        block.appendChild(el("button", { class: "tl-clip-remove", type: "button", title: "타임라인에서 빼기",
                                         dataset: { act: "remove" } }, "×"));
      }
    }
    layer.appendChild(block);
  });
  for (const fx of state.plan?.effects || []) {
    for (const piece of clipRangeToTimeline(segs, fx.clip_id, fx.start, fx.end)) {
      if (xOf(piece.end - piece.start) < 18) continue;
      layer.appendChild(el("div", { class: "tl-fx-badge", title: "강조 줌인", style: { left: `${xOf(piece.start) + 3}px` } }, "🔍"));
    }
  }
  if (tl.view === SEQUENCE) {
    joins(segs).forEach((join, i) => {
      layer.appendChild(el("button", { class: "tl-join", type: "button", style: { left: `${xOf(join.t)}px` },
                                       dataset: { join: String(i) }, title: "잘린 곳 — 눌러서 무엇이 잘렸는지 보기" }, "✂"));
    });
  }
}

function handle(edge) {
  return el("div", { class: `tl-trim tl-trim-${edge}`, dataset: { edge }, title: edge === "left" ? "앞 자르기" : "뒤 자르기" });
}
