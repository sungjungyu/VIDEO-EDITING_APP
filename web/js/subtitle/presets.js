/* 자막 스타일 기본값·프리셋.
   기본값은 서버(src/vibecut/domain/models/plan.py default_styles)가 /api/config로 내려준 것을 쓴다 → 한 곳에서 정한다. */

import { state } from "../core/store.js";

/* 항목(subtitle | title | location)의 기본 스타일 */
export function defaultStyle(key = "subtitle") {
  const defaults = state.config?.style_defaults || {};
  return { ...(defaults[key] || defaults.subtitle || {}) };
}

export const PRESETS = {
  "매운맛": { font: "Malgun Gothic", color: "#ffe600", size: 64, weight: "bold", italic: false,
              outline: true, outline_color: "#000000", outline_width: 5, shadow: true, shadow_distance: 6,
              background_box: true, bg_color: "#000000", bg_opacity: 70, position: "bottom", bottom_margin: 70,
              max_chars_per_line: 16, karaoke: true, fade: true },
  "순한맛": { font: "Malgun Gothic", color: "#ffffff", size: 50, weight: "normal", italic: false,
              outline: true, outline_color: "#000000", outline_width: 4, shadow: false, shadow_distance: 4,
              background_box: false, bg_color: "#000000", bg_opacity: 50, position: "bottom", bottom_margin: 50,
              max_chars_per_line: 22, karaoke: true, fade: true },
  "정석맛": { font: "Malgun Gothic", color: "#ffffff", size: 54, weight: "normal", italic: false,
              outline: true, outline_color: "#000000", outline_width: 3, shadow: false, shadow_distance: 4,
              background_box: false, bg_color: "#000000", bg_opacity: 60, position: "bottom", bottom_margin: 60,
              max_chars_per_line: 20, karaoke: false, fade: false },
};

/* 브라우저에 저장된 예전(v1) 스타일: 값이 미리보기 화면 px라 1080 기준으로 약 2.25배 */
export function migrateStyle(s) {
  if (!s || typeof s !== "object") return null;
  if ((s.version || 1) >= 2) return { ...defaultStyle(), ...s };
  const k = 2.25;
  return {
    ...defaultStyle(), ...s, version: 2,
    size: Math.round((s.size ?? 24) * k),
    outline_width: Math.round((s.outline_width ?? 1) * k * 2) / 2,
    shadow_distance: Math.round((s.shadow_distance ?? 2) * k),
    bottom_margin: Math.round((s.bottom_margin ?? 10) * k),
  };
}
