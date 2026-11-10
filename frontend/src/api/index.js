// API 진입점: VITE_USE_MOCK=false 이면 실제 서버(real.js), 그 외(기본)는 mock.js.
//   mock:  npm run dev
//   실제:  npm run dev:real   (서버: vibecut serve, Vite가 /api를 8000번으로 넘긴다)
import * as mock from './mock.js';
import * as real from './real.js';

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';
const api = USE_MOCK ? mock : real;

export { ProjectGoneError } from './real.js';

export const getClips          = (...a) => api.getClips(...a);
export const getJudgmentRules  = (...a) => api.getJudgmentRules(...a);
export const getExecutionRules = (...a) => api.getExecutionRules(...a);
export const getTree           = (...a) => api.getTree(...a);
export const getResult         = (...a) => api.getResult(...a);
export const getProgress       = (...a) => api.getProgress(...a);
export const getSelection      = (...a) => api.getSelection(...a);
export const saveSelection     = (...a) => api.saveSelection(...a);
export const autoCompress      = (...a) => api.autoCompress(...a);

export const ensureProject     = (...a) => api.ensureProject(...a);
export const checkProject      = (...a) => api.checkProject(...a);
export const deleteProject     = (...a) => api.deleteProject(...a);
export const uploadClips       = (...a) => api.uploadClips(...a);
export const removeClip        = (...a) => api.removeClip(...a);
export const reorderClips      = (...a) => api.reorderClips(...a);
export const startAnalysis     = (...a) => api.startAnalysis(...a);
export const getJob            = (...a) => api.getJob(...a);
export const getAnalysis       = (...a) => api.getAnalysis(...a);

// 화면 상태(상태 머신)는 어느 모드든 브라우저에 저장한다
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
