/* 화면 상태 한 곳 + 간단한 이벤트 + 실행취소/다시실행.

   state.project   서버 프로젝트 (클립·타임라인 순서·분석 상태·렌더 목록)
   state.analysis  받아쓰기 문장·장면·트리·AI 판단 (분석 전엔 null)
   state.plan      편집 계획 (서버가 계산한 keep·events·duration 포함)
   state.issues    렌더 전 검사 결과
   state.media     clip_id → 브라우저 쪽 정보 (로컬 blob 주소, 썸네일)

   편집 계획을 바꾸는 동작은 mutatePlan()을 거친다 → 성공하면 이전 값을 실행취소 기록에 쌓는다. */

import { api } from "./api.js";

const listeners = {};

export function on(event, fn) {
  (listeners[event] ||= []).push(fn);
}

export function emit(event, data) {
  for (const fn of listeners[event] || []) {
    try { fn(data); } catch (err) { console.error(`[${event}]`, err); }
  }
}

export const state = {
  config: null,
  project: null,
  analysis: null,
  plan: null,
  issues: [],
  media: new Map(),
  pendingUploads: [],
  ui: {
    selectedClipId: null,
    aiStage: "idle",
    pxPerSec: 40,
    previewMode: "source",
    previewClipId: null,
  },
};

export const pid = () => state.project?.project_id;

export function setProject(project) {
  state.project = project;
  emit("project", project);
}

export function setPlanView(view) {
  state.plan = view.plan;
  state.issues = view.issues || [];
  emit("plan", state.plan);
}

let lineIndex = new Map();
let linesByClip = new Map();

export function setAnalysis(analysis) {
  state.analysis = analysis;
  lineIndex = new Map();
  linesByClip = new Map();
  for (const line of analysis?.lines || []) {
    lineIndex.set(line.seg_id, line);
    if (!linesByClip.has(line.clip_id)) linesByClip.set(line.clip_id, []);
    linesByClip.get(line.clip_id).push(line);
  }
  for (const list of linesByClip.values()) list.sort((a, b) => a.start - b.start);
  emit("analysis", analysis);
}

export const lineById = id => lineIndex.get(id);
export const linesOfClip = cid => linesByClip.get(cid) || [];

/* 문장 하나의 최종 판단: 사용자 결정 > AI·규칙 판단 > 남김 */
export function decisionOf(segId) {
  return state.plan?.lines?.[segId] || state.analysis?.judgments?.[segId]
    || { seg_id: segId, keep: true, reason: "일반", source: "rule", emphasis: false };
}

export function clipById(cid) {
  return state.project?.clips.find(c => c.clip_id === cid) || null;
}

export function timelineClips() {
  if (!state.project) return [];
  return state.project.timeline.map(clipById).filter(Boolean);
}

export const usableEnd = clip => (clip.out_point ?? clip.duration);

/* 타임라인 배치 (자석식: 순서대로 붙여 놓는다). [{clip, start, dur}] */
export function timelineLayout() {
  let t = 0;
  return timelineClips().map(clip => {
    const dur = Math.max(0, usableEnd(clip) - clip.in_point);
    const item = { clip, start: t, dur };
    t += dur;
    return item;
  });
}

export function analysisReady() {
  return !!state.analysis && state.project?.analysis?.status === "done";
}

/* 분석용 원본 시각(트리 노드) → (clip_id, 클립 초) */
export function globalToClip(t) {
  for (const span of state.analysis?.clips || []) {
    if (t >= span.offset && t < span.offset + span.duration) return { clipId: span.clip_id, time: t - span.offset };
  }
  return null;
}

/* 클립 초 → 결과 초 (잘린 곳이면 null) */
export function clipToOutput(clipId, t) {
  for (const k of state.plan?.keep || []) {
    if (k.clip_id === clipId && t >= k.start && t < k.end) return k.out_start + (t - k.start);
  }
  return null;
}

/* ---------------------------------------------------------------- 실행취소 */

const undoStack = [];
const redoStack = [];
const MAX_HISTORY = 50;

function snapshot() {
  const p = state.plan;
  return p ? structuredClone({ selection: p.selection, lines: p.lines, styles: p.styles, output: p.output,
                               options: p.options }) : null;
}

export const canUndo = () => undoStack.length > 0;
export const canRedo = () => redoStack.length > 0;

export function clearHistory() {
  undoStack.length = 0;
  redoStack.length = 0;
  emit("history");
}

/* change: async () => 서버 응답(plan view). 성공하면 이전 상태를 기록하고 화면을 갱신한다. */
export async function mutatePlan(change, { record = true } = {}) {
  const before = snapshot();
  const view = await change();
  if (record && before) {
    undoStack.push(before);
    if (undoStack.length > MAX_HISTORY) undoStack.shift();
    redoStack.length = 0;
  }
  setPlanView(view);
  emit("history");
  return view;
}

export async function undo() {
  if (!undoStack.length) return;
  const target = undoStack.pop();
  redoStack.push(snapshot());
  setPlanView(await api.putPlan(pid(), target));
  emit("history");
}

export async function redo() {
  if (!redoStack.length) return;
  const target = redoStack.pop();
  undoStack.push(snapshot());
  setPlanView(await api.putPlan(pid(), target));
  emit("history");
}
