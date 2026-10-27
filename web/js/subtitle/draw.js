/* 자막 그리기: 스타일 → 미리보기 CSS. 서버 src/vibecut/render/ass.py의 style_values와 같은 규칙이다 (미리보기 = 렌더).

   - 크기·여백·두께는 '출력 영상의 짧은 변이 1080px일 때'의 px → 미리보기 상자의 짧은 변 비율로 줄인다
   - 글자 크기는 CSS font-size(em) 그대로, 줄 높이는 글꼴의 (winAscent+winDescent)/unitsPerEm
     (libass가 ASS 크기를 이 높이로 맞추므로 서버는 Fontsize = px × 비율로 쓴다 → 같은 크기)
   - 배경 상자: libass BorderStyle 4처럼 글자 묶음 전체를 감싸고, 여백 = 글자 크기의 20%
   - 외곽선: 16방향 text-shadow, 그림자: 오른쪽 아래로 검정 75% (상자가 있으면 그림자 대신 상자)
   - 카라오케: 이미 말한 단어를 강조색으로 (글자색이 노란 계열이면 흰색) */

import { state } from "../core/store.js";
import { alignWordsToLines, wrapText } from "./wrap.js";

const BOX_PAD_RATIO = 0.2;

/* 크기·여백·두께의 기준: 출력 영상의 짧은 변이 이 값(px)일 때의 값 (서버 render/ass.py와 같음) */
const referenceShortSide = () => state.config?.reference_short_side || 1080;

function lineRatio(font) {
  return state.config?.font_metrics?.[font] || 1.33;
}

function karaokeHighlight(hex) {
  const h = (hex || "#ffffff").replace("#", "");
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return r > 200 && g > 180 && b < 120 ? "#ffffff" : "#ffe600";
}

function hexToRgba(hex, pct) {
  const h = (hex || "#000000").replace("#", "");
  const a = Math.max(0, Math.min(100, Number(pct) || 0)) / 100;
  return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${a.toFixed(2)})`;
}

function outlineShadows(width, color) {
  if (width <= 0.15) return [];
  const steps = width > 2 ? 16 : 8, out = [];
  for (let i = 0; i < steps; i++) {
    const a = (Math.PI * 2 * i) / steps;
    out.push(`${(Math.cos(a) * width).toFixed(2)}px ${(Math.sin(a) * width).toFixed(2)}px 0 ${color}`);
  }
  return out;
}

function textCss(S, boxW, boxH) {
  const scale = Math.min(boxW, boxH) / referenceShortSide();
  const bold = S.weight === "bold" || S.weight === "extra-bold";
  const css = {
    fontFamily: `"${S.font}", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif`,
    fontSize: `${S.size * scale}px`,
    lineHeight: String(lineRatio(S.font)),
    color: S.color,
    fontWeight: S.weight === "extra-bold" ? "900" : bold ? "700" : "400",
    fontStyle: S.italic ? "italic" : "normal",
    background: "transparent", padding: "0", margin: "0",
  };
  const shadows = S.outline ? outlineShadows(S.outline_width * scale, S.outline_color) : [];
  if (S.background_box) {
    const pad = Math.max(4, S.size * BOX_PAD_RATIO) * scale;
    css.background = hexToRgba(S.bg_color, S.bg_opacity);
    css.padding = `${pad}px`;
    css.margin = `${-pad}px`;          // 글자 위치는 그대로 두고 상자만 바깥으로 (libass와 같음)
  } else if (S.shadow) {
    const d = S.shadow_distance * scale;
    shadows.push(`${d.toFixed(2)}px ${d.toFixed(2)}px 0 rgba(0,0,0,0.75)`);
  }
  css.textShadow = shadows.join(", ") || "none";
  return css;
}

function blockCss(S, boxW, boxH) {
  const m = S.bottom_margin * Math.min(boxW, boxH) / referenceShortSide();
  if (S.position === "top") return { top: `${m}px`, bottom: "auto", transform: "none" };
  if (S.position === "center") return { top: "50%", bottom: "auto", transform: "translateY(-50%)" };
  return { top: "auto", bottom: `${m}px`, transform: "none" };
}

/* 자막 한 장면을 container에 그린다. t는 event와 같은 시간축의 현재 시각 */
export function drawEvent(container, event, S, boxW, boxH, t, { cut = false } = {}) {
  const block = document.createElement("div");
  block.className = "sub-block" + (cut ? " is-cut" : "");
  Object.assign(block.style, blockCss(S, boxW, boxH));
  const text = document.createElement("span");
  text.className = "sub-text";
  Object.assign(text.style, textCss(S, boxW, boxH));
  const words = event.words || [], lines = event.word_lines || [];
  if (S.karaoke && words.length && lines.length === words.length) {
    text.style.setProperty("--kw-hl", karaokeHighlight(S.color));
    let prev = lines[0];
    words.forEach((w, i) => {
      if (lines[i] !== prev) { text.appendChild(document.createTextNode("\n")); prev = lines[i]; }
      else if (i > 0) text.appendChild(document.createTextNode(" "));
      const span = document.createElement("span");
      span.className = "kw" + (t >= w.start ? " spoken" : "");
      span.textContent = w.word;
      text.appendChild(span);
    });
  } else {
    text.textContent = event.text;
  }
  if (S.fade) {
    const k = Math.min(1, (t - event.start) / 0.15, (event.end - t) / 0.15);
    block.style.opacity = String(Math.max(0, k));
  }
  block.appendChild(text);
  if (cut) {
    const mark = document.createElement("span");
    mark.className = "sub-cut-mark";
    mark.textContent = "자름";
    block.appendChild(mark);
  }
  container.appendChild(block);
  return block;
}

/* 원본 미리보기: 받아쓰기 문장 → 자막 장면 (렌더와 같은 줄바꿈, 단어 시각이 맞으면 카라오케) */
export function lineToEvent(line, decision, S) {
  const text = (decision?.text || line.text || "").trim();
  const words = decision?.text ? [] : (line.words || []);
  const wordLines = words.length ? alignWordsToLines(text, words.map(w => w.word), S.max_chars_per_line) : null;
  return {
    start: line.start, end: line.end, text: wrapText(text, S.max_chars_per_line).join("\n"),
    words: wordLines ? words : [], word_lines: wordLines || [],
  };
}
