/**
 * API 레이어 — 지금은 mock JSON을 돌려준다.
 * 나중에 이 파일만 fetch로 교체하면 된다.
 */
import clipsData           from '../mock/clips.json';
import judgmentRulesData   from '../mock/judgment_rules.json';
import executionRulesData  from '../mock/execution_rules.json';
import treeData            from '../mock/tree.json';
import selectionData       from '../mock/selection.json';
import progressAnalyzing   from '../mock/progress_analyzing.json';
import progressRendering   from '../mock/progress_rendering.json';
import resultData          from '../mock/result.json';

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

export async function getClips()          { await delay(50); return clipsData; }
export async function getJudgmentRules()  { await delay(50); return judgmentRulesData; }
export async function getExecutionRules() { await delay(50); return executionRulesData; }
export async function getTree()           { await delay(50); return treeData; }
export async function getSelection()      { await delay(50); return selectionData; }
export async function getResult()         { await delay(50); return resultData; }

export async function getProgress(stage = 'analyzing') {
  await delay(50);
  return stage === 'rendering' ? progressRendering : progressAnalyzing;
}
