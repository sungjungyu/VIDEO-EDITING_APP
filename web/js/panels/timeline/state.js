/* 타임라인이 함께 쓰는 상태와 설정.
   트랙 구성은 영상 편집 프로그램(Premiere)과 같은 순서: 위에서부터 자막(C1) · 텍스트(T1) · 영상(V1) · 소리(A1).
   장면(장소·활동)은 트랙 대신 눈금 위 '구간 마커'로 보인다 (Premiere·Resolve의 시퀀스 마커처럼). */

import { state, timelineClips } from "../../core/store.js";
import { SEQUENCE, SOURCE, sequenceSegments, sourceSegments, totalOf } from "./model.js";

export const HEADER_W = 156;          // 트랙 머리 폭 (px)
export const RULER_H = 34;            // 눈금 높이: 시각 22px + 장면 마커 12px
export const MIN_PX = 2, MAX_PX = 480; // 1초당 px

export const TRACKS = [
  { id: "C1", kind: "captions", name: "자막", sizes: [26, 34, 48], lockable: true },
  { id: "T1", kind: "overlay", name: "텍스트", sizes: [22, 28, 36], lockable: false },
  { id: "V1", kind: "video", name: "영상", sizes: [40, 56, 80], lockable: true },
  { id: "A1", kind: "audio", name: "소리", sizes: [28, 44, 64], lockable: false },
];

const PREFS_KEY = "vibecut_timeline_v1";
const DEFAULT_PREFS = { height: 268, snap: true, tracks: { C1: { size: 1 }, T1: { size: 0 }, V1: { size: 1 }, A1: { size: 1 } } };

function loadPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    return { ...DEFAULT_PREFS, ...saved, tracks: { ...DEFAULT_PREFS.tracks, ...(saved.tracks || {}) } };
  } catch (err) {
    return structuredClone(DEFAULT_PREFS);
  }
}

export function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(tl.prefs)); } catch (err) { /* 저장 공간 없음 */ }
}

export const tl = {
  view: SEQUENCE,         // 처음 보기는 편집본 (영상 편집 프로그램의 타임라인 = 결과 영상)
  px: 40,
  fitted: true,           // '전체 보기' 상태 (보기를 바꾸거나 클립이 바뀌면 다시 맞춘다)
  prefs: loadPrefs(),
  selected: new Set(),    // 고른 자막 문장 (seg_id)
  anchor: null,           // Shift 범위 선택의 기준 문장
  drag: null,             // 진행 중인 끌기 { kind, … }
  waveforms: new Map(),   // clip_id → { rate, peaks } | "loading"
};

export const trackPref = id => (tl.prefs.tracks[id] ||= { size: 1 });
export const trackHeight = track => (trackPref(track.id).hidden ? 14 : track.sizes[trackPref(track.id).size ?? 1]);
export const isLocked = id => !!trackPref(id).locked;

export function segments(view = tl.view) {
  return view === SOURCE ? sourceSegments(timelineClips()) : sequenceSegments(state.plan?.keep);
}

export const total = () => totalOf(segments());
export const xOf = t => t * tl.px;
export const tOf = x => x / tl.px;
export const fps = () => state.plan?.output?.fps || 30;
