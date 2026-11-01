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

const PROJECT_KEY = 'vibecut_project';

export function getProjectSync() {
  try {
    const raw = localStorage.getItem(PROJECT_KEY);
    return raw ? JSON.parse(raw) : { status: 'created' };
  } catch {
    return { status: 'created' };
  }
}

export async function saveProject(data) {
  try {
    localStorage.setItem(PROJECT_KEY, JSON.stringify(data));
  } catch (e) {
    console.warn('[saveProject] localStorage write failed', e);
  }
}
