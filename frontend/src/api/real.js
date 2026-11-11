// 실제 API 어댑터 — FastAPI(src/vibecut) /api 에 연결한다 (VITE_USE_MOCK=false).
// 함수 이름과 반환 모양은 mock.js와 같다. S4 트리는 서버 규칙 트리, 선택·렌더는 Phase 2·3에서 연결하고 지금은 화면·mock.
import * as mock from './mock.js';
import { adaptTree, defaultSelection } from '../utils/adaptTree.js';

const BASE = '/api';
const PROJECT_ID_KEY = 'vibecut_server_project_id';

/** 서버가 다시 켜져 프로젝트가 지워졌을 때 (wipe_media) */
export class ProjectGoneError extends Error {
  constructor() {
    super('서버가 다시 시작되어 올린 영상과 프로젝트가 지워졌어요. 영상을 다시 올려 주세요.');
    this.name = 'ProjectGoneError';
  }
}

async function request(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(detailText(data.detail) || `서버 오류 (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function detailText(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(d => d.msg ?? JSON.stringify(d)).join(', ');
  return JSON.stringify(detail);
}

function storedProjectId() {
  try { return localStorage.getItem(PROJECT_ID_KEY); } catch { return null; }
}
function storeProjectId(id) {
  try {
    if (id) localStorage.setItem(PROJECT_ID_KEY, id);
    else localStorage.removeItem(PROJECT_ID_KEY);
  } catch {}
}

/** 서버 ClipInfo → 화면 클립 모양 (mock/clips.json과 같은 필드) */
function toUiClips(project) {
  const byId = Object.fromEntries(project.clips.map(c => [c.clip_id, c]));
  const ordered = [
    ...project.timeline.map(id => byId[id]).filter(Boolean),
    ...project.clips.filter(c => !project.timeline.includes(c.clip_id)),
  ];
  let offset = 0;
  return ordered.map((c, i) => {
    const clip = {
      id: c.clip_id,
      file: c.filename,
      order: i + 1,
      duration: c.duration,
      offset,
      shot_at: c.created_at ? new Date(c.created_at * 1000).toISOString() : null,
      width: c.width,
      height: c.height,
      fps: c.fps,
      proxy_url: c.proxy_url,
      file_url: c.file_url,
    };
    offset += c.duration;
    return clip;
  });
}

async function getProject(id) {
  try {
    return await request('GET', `/projects/${id}`);
  } catch (e) {
    if (e.status === 404) { storeProjectId(null); throw new ProjectGoneError(); }
    throw e;
  }
}

let creating = null;   // 동시에 여러 번 불려도(React StrictMode 등) 프로젝트를 하나만 만든다

/** 저장된 프로젝트가 있으면 그것을, 없으면 새로 만든다. 저장된 것이 서버에서 사라졌으면 ProjectGoneError */
export async function ensureProject() {
  const id = storedProjectId();
  if (id) return getProject(id);
  if (!creating) {
    creating = request('POST', '/projects', { name: 'VIBE CUT 프로젝트' })
      .then((project) => { storeProjectId(project.project_id); return project; })
      .finally(() => { creating = null; });
  }
  return creating;
}

/** 새로고침 복원용: 저장된 프로젝트가 서버에 아직 있으면 true, 없으면 false (404만 false) */
export async function checkProject() {
  const id = storedProjectId();
  if (!id) return false;
  try { await getProject(id); return true; }
  catch (e) { if (e instanceof ProjectGoneError) return false; throw e; }
}

/** 처음으로: 서버 프로젝트를 지우고(실패해도 무시) 다음에 새로 만들게 한다 */
export async function deleteProject() {
  const id = storedProjectId();
  storeProjectId(null);
  if (id) await request('DELETE', `/projects/${id}`).catch(() => {});
}

export async function getClips() {
  return toUiClips(await ensureProject());
}

/**
 * 영상 여러 개를 한 번에 올린다 (필드 이름 files). 진행률은 XMLHttpRequest로 받는다.
 * 올린 클립은 타임라인 끝에 붙인다 (서버는 업로드만으로 타임라인에 넣지 않는다).
 */
export async function uploadClips(files, onProgress) {
  const project = await ensureProject();
  const form = new FormData();
  for (const f of files) form.append('files', f, f.name);

  const data = await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/projects/${project.project_id}/clips`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(Math.round(e.loaded / e.total * 100)); };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else if (xhr.status === 404) { storeProjectId(null); reject(new ProjectGoneError()); }
      else reject(new Error(detailText(body.detail) || `업로드 실패 (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error('업로드 중 연결이 끊겼어요. 서버가 켜져 있는지 확인해 주세요.'));
    xhr.send(form);
  });

  const added = data.clips.map(c => c.clip_id);
  const timeline = [...data.project.timeline, ...added.filter(id => !data.project.timeline.includes(id))];
  const updated = await request('PATCH', `/projects/${project.project_id}`, { timeline });
  return toUiClips(updated);
}

export async function removeClip(clipId) {
  const updated = await request('DELETE', `/projects/${storedProjectId()}/clips/${clipId}`);
  return toUiClips(updated);
}

/** 화면 순서(clips 배열)를 서버 타임라인으로 저장 */
export async function reorderClips(clips) {
  const updated = await request('PATCH', `/projects/${storedProjectId()}`, { timeline: clips.map(c => c.id) });
  return toUiClips(updated);
}

/** 분석 시작 → Job. 이미 돌고 있으면 서버가 그 작업을 돌려준다 */
export async function startAnalysis(profile = {}) {
  const project = await ensureProject();
  return request('POST', `/projects/${project.project_id}/analyze`, { profile });
}

/** Job: status(queued/running/done/failed/canceled), progress, stage, message, error, result, metrics */
export async function getJob(jobId) {
  return request('GET', `/jobs/${jobId}`);
}

/** 분석 결과(Analysis): clips(offset·duration), lines(speaker), scenes, beats, engines, warnings */
export async function getAnalysis() {
  return request('GET', `/projects/${storedProjectId()}/analysis`);
}

// ── 4단 트리 (S4): 서버가 분석 결과로 규칙 트리를 만들어 준다. 선택(켜기·끄기·잠금)은 아직 화면에서만 ──
let treeCache = null;   // { pid, data } — S3 끝과 S4가 같은 트리를 두 번 받지 않게

/** ai: true면 서버가 AI 트리를 만든다(유료, 1시간 영상 1~2분). 기본은 저장된 AI 트리 > 규칙 트리 */
export async function getTree({ ai = false } = {}) {
  const pid = storedProjectId();
  if (treeCache?.pid === pid && (!ai || treeCache.data.meta?.source !== 'rules')) return treeCache.data;
  const data = adaptTree(await request('GET', `/projects/${pid}/tree${ai ? '?ai=true' : ''}`));
  treeCache = { pid, data };
  return data;
}

const selectionKey = () => `vibecut_selection_${storedProjectId()}`;

/** 저장한 선택이 지금 트리와 맞으면 그것, 아니면 모든 장면 켜짐. 목표 분량은 S2 요청 값 */
export async function getSelection() {
  const tree = await getTree();
  let target = null;
  try { target = JSON.parse(localStorage.getItem('vibecut_project') ?? '{}').request?.target_sec ?? null; } catch { /* 없음 */ }
  const fresh = defaultSelection(tree, target);
  try {
    const saved = JSON.parse(localStorage.getItem(selectionKey()) ?? 'null');
    const ids = Object.keys(fresh.nodes);
    if (saved?.nodes && ids.length && ids.every(id => saved.nodes[id])) return { ...saved, target_sec: target ?? saved.target_sec };
  } catch { /* 새로 만든다 */ }
  return fresh;
}

export async function saveSelection(data) {
  try { localStorage.setItem(selectionKey(), JSON.stringify(data)); } catch { /* 저장 못 해도 화면은 계속 */ }
}

export const autoCompress      = mock.autoCompress;   // 화면 안 계산 (greedy). 서버 DP 선택은 다음 단계

// ── Phase 3에서 실제 API로 바꿀 것들: 지금은 mock 그대로 ──
export const getJudgmentRules  = mock.getJudgmentRules;
export const getExecutionRules = mock.getExecutionRules;
export const getResult         = mock.getResult;
export const getProgress       = mock.getProgress;
