/* A1 소리 트랙: 파형(서버 /clips/{id}/waveform, 20ms마다 가장 큰 소리) + 무음 구간(옅은 띠) + 원본 보기의 잘린 곳. */

import { api } from "../../../core/api.js";
import { pid, state } from "../../../core/store.js";
import { hatch, prepareCanvas, roundRect, token } from "../canvas.js";
import { SOURCE } from "../model.js";
import { tl, xOf } from "../state.js";
import { cutRegions } from "./video.js";

/* 파형은 클립마다 한 번만 받아 둔다 */
function waveform(clipId, onReady) {
  const key = `${pid()}/${clipId}`;            // 프로젝트마다 클립 id(c01 …)가 겹친다
  const cached = tl.waveforms.get(key);
  if (cached && cached !== "loading") return cached;
  if (!cached && pid()) {
    tl.waveforms.set(key, "loading");
    api.waveform(pid(), clipId)
      .then(data => { tl.waveforms.set(key, data); onReady(); })
      .catch(() => tl.waveforms.delete(key));
  }
  return null;
}

export function drawAudio(canvas, ctxInfo, redraw) {
  const { scrollLeft, width, height, segs } = ctxInfo;
  const ctx = prepareCanvas(canvas, scrollLeft, width, height);
  const left = scrollLeft, right = scrollLeft + width;
  const top = 3, h = height - 6, mid = top + h / 2;
  for (const seg of segs) {
    const x = xOf(seg.start), w = Math.max(xOf(seg.dur), 2);
    if (x > right || x + w < left) continue;
    ctx.save();
    roundRect(ctx, x + 0.5, top, w - 1, h, 6);
    ctx.clip();
    ctx.fillStyle = token("--tl-clip-audio");
    ctx.fillRect(x, top, w, h);
    for (const [a, b] of state.analysis?.silences?.[seg.clipId] || []) {     // 무음: 컷 경계가 붙는 곳
      const s = Math.max(a, seg.in), e = Math.min(b, seg.in + seg.dur);
      if (e <= s) continue;
      ctx.fillStyle = "rgba(255,255,255,.035)";
      ctx.fillRect(x + xOf(s - seg.in), top, xOf(e - s), h);
    }
    const wave = waveform(seg.clipId, redraw);
    if (wave?.peaks?.length) {
      // 조용한 클립도 보이게 클립에서 가장 큰 소리를 기준으로 키운다 (최대 4배)
      if (wave.max === undefined) wave.max = wave.peaks.reduce((m, v) => (v > m ? v : m), 0);
      const gain = Math.min(4, 255 / Math.max(1, wave.max));
      ctx.fillStyle = token("--role-audio");
      const from = Math.max(x, left), to = Math.min(x + w, right);
      for (let px = Math.floor(from); px < to; px++) {
        const t0 = seg.in + (px - x) / tl.px, t1 = seg.in + (px + 1 - x) / tl.px;
        const i0 = Math.max(0, Math.floor(t0 * wave.rate)), i1 = Math.min(wave.peaks.length, Math.ceil(t1 * wave.rate));
        let peak = 0;
        for (let i = i0; i < i1; i++) if (wave.peaks[i] > peak) peak = wave.peaks[i];
        const bar = Math.max(1, Math.min(1, (peak * gain) / 255) * (h / 2 - 2));
        ctx.fillRect(px, mid - bar, 1, bar * 2);
      }
    }
    ctx.restore();
  }
  if (tl.view === SOURCE) {
    for (const cut of cutRegions(segs)) {
      const x = xOf(cut.start), w = xOf(cut.end - cut.start);
      if (x > right || x + w < left || w < 1) continue;
      hatch(ctx, x, top, w, h, "rgba(0,0,0,.5)", "rgba(255,255,255,.05)");
    }
  }
}

