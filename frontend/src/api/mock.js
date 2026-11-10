// mock API — 서버 없이 화면 흐름을 확인할 때 쓴다 (VITE_USE_MOCK=true, 기본값).
// 실제 API(real.js)와 함수 이름·반환 모양을 맞춘다.
import clipsData           from '../mock/clips.json';
import judgmentRulesData   from '../mock/judgment_rules.json';
import executionRulesData  from '../mock/execution_rules.json';
import treeData            from '../mock/tree.json';
import selectionData       from '../mock/selection.json';
import progressAnalyzing   from '../mock/progress_analyzing.json';
import progressRendering   from '../mock/progress_rendering.json';
import resultData          from '../mock/result.json';
import { computeAutoCompress } from '../logic/selection.js';

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

export async function getClips()          { await delay(50); return clipsData; }
export async function getJudgmentRules()  { await delay(50); return judgmentRulesData; }
export async function getExecutionRules() { await delay(50); return executionRulesData; }
export async function getTree()           { await delay(50); return treeData; }
export async function getResult()         { await delay(50); return resultData; }

export async function getProgress(stage = 'analyzing') {
  await delay(50);
  return stage === 'rendering' ? progressRendering : progressAnalyzing;
}

const SELECTION_KEY = 'vibecut_selection';

export async function getSelection() {
  await delay(50);
  try {
    const raw = localStorage.getItem(SELECTION_KEY);
    if (raw) return JSON.parse(raw);
  } catch {}
  return selectionData;
}

export async function saveSelection(data) {
  try {
    localStorage.setItem(SELECTION_KEY, JSON.stringify(data));
  } catch (e) {
    console.warn('[saveSelection] failed', e);
  }
}

export async function autoCompress(selection, treeData) {
  await delay(400);
  return computeAutoCompress(selection, treeData);
}

// ── 실제 API에만 의미가 있는 함수들: mock에서는 화면이 깨지지 않을 만큼만 흉내 낸다 ──

export async function ensureProject()          { return { project_id: 'mock' }; }
export async function checkProject()           { return true; }
export async function deleteProject()          {}
export async function uploadClips(_files, onProgress) { onProgress?.(100); await delay(50); return clipsData; }
export async function removeClip(_id, remaining)      { return remaining; }
export async function reorderClips(clips)             { return clips; }
export async function startAnalysis()          { return { job_id: 'mock' }; }
export async function getJob()                 { return { status: 'done', progress: 100 }; }
export async function getAnalysis()            { return null; }   // mock S3는 progress 데이터의 stats를 쓴다
