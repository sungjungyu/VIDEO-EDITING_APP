import { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react';
import { getProjectSync, saveProject } from '../api/index.js';

const ProjectContext = createContext(null);

export const STATUS_TO_SCREEN = {
  created:        's1',
  clips_ready:    's2',
  analyzing:      's3',
  analyze_failed: 's3',
  analyzed:       's4',
  rendering:      's5',
  render_failed:  's5',
  rendered:       's51',
};

const ALLOWED_SCREENS = {
  created:        ['s1'],
  clips_ready:    ['s1', 's2'],
  analyzing:      ['s3'],
  analyze_failed: ['s3'],
  analyzed:       ['s1', 's2', 's3', 's4'],  // s3: 분석 완료 후 화면에 머물 수 있음
  rendering:      ['s5'],
  render_failed:  ['s5'],
  rendered:       ['s1', 's2', 's4', 's5', 's51'],  // s5: 렌더 완료 후 화면에 머물 수 있음
};

// state × action → next state
const VALID_TRANSITIONS = {
  created:        { ADD_CLIPS: 'clips_ready', RESET: 'created' },
  clips_ready:    { ADD_CLIPS: 'clips_ready', CLEAR_CLIPS: 'created', CONFIRM_REQUEST: 'analyzing', RESET: 'created' },
  analyzing:      { ANALYZE_SUCCESS: 'analyzed', ANALYZE_FAIL: 'analyze_failed', RESET: 'created' },
  analyze_failed: { RETRY_ANALYZE: 'analyzing', SKIP_CLIP: 'analyzing', RESET: 'created' },
  analyzed: {
    CHANGE_CLIPS:     'clips_ready',
    CHANGE_REQUEST:   'analyzed',
    CHANGE_STYLE:     'analyzed',
    CHANGE_SELECTION: 'analyzed',
    START_RENDER:     'rendering',
    RESET:            'created',
  },
  rendering: {
    RENDER_SUCCESS: 'rendered',
    RENDER_FAIL:    'render_failed',
    CANCEL_RENDER:  'analyzed',
    RESET:          'created',
  },
  render_failed: { BACK_TO_EDITOR: 'analyzed', RESET: 'created' },
  rendered: {
    CHANGE_CLIPS:     'clips_ready',
    CHANGE_REQUEST:   'analyzed',
    CHANGE_STYLE:     'rendered',
    CHANGE_SELECTION: 'analyzed',
    START_RENDER:     'rendering',
    RESET:            'created',
  },
};

// screen to navigate to after each action; omitted = screen stays as-is
// ANALYZE_SUCCESS / RENDER_SUCCESS intentionally omitted:
// status changes but the progress screen stays visible until the user clicks the button.
const ACTION_SCREEN = {
  ADD_CLIPS:        's2',
  CLEAR_CLIPS:      's1',
  CONFIRM_REQUEST:  's3',
  ANALYZE_FAIL:     's3',
  RETRY_ANALYZE:    's3',
  SKIP_CLIP:        's3',
  CHANGE_CLIPS:     's1',
  START_RENDER:     's5',
  RENDER_FAIL:      's5',
  CANCEL_RENDER:    's4',
  BACK_TO_EDITOR:   's4',
  RESET:            's1',
};

export function ProjectProvider({ children }) {
  const stored     = getProjectSync();
  const initStatus = stored.status ?? 'created';
  const initScreen = (() => {
    const hash    = window.location.hash.slice(1);
    const allowed = ALLOWED_SCREENS[initStatus] ?? ['s1'];
    return allowed.includes(hash) ? hash : (STATUS_TO_SCREEN[initStatus] ?? 's1');
  })();

  const [status,         setStatus]         = useState(initStatus);
  const [currentScreen,  setCurrentScreen]  = useState(initScreen);
  const [clips,          setClips]          = useState(stored.clips ?? []);
  const [judgmentRules,  setJudgmentRules]  = useState(stored.judgmentRules ?? null);
  const [executionRules, setExecutionRules] = useState(stored.executionRules ?? null);
  const [selection,      setSelection]      = useState(stored.selection ?? null);
  const [analyzeError,   setAnalyzeError]   = useState(null);
  const [renderError,    setRenderError]    = useState(null);

  const statusRef = useRef(initStatus);
  useEffect(() => { statusRef.current = status; }, [status]);

  // Keep URL hash in sync with current screen
  useEffect(() => {
    if (window.location.hash.slice(1) !== currentScreen) {
      window.location.hash = currentScreen;
    }
  }, [currentScreen]);

  // Handle hash changes: browser back/forward AND manual URL-bar edits
  useEffect(() => {
    const onHash = () => {
      const hash    = window.location.hash.slice(1);
      const allowed = ALLOWED_SCREENS[statusRef.current] ?? ['s1'];
      if (allowed.includes(hash)) {
        setCurrentScreen(hash);
      } else {
        // redirect to the canonical screen for this status
        window.location.hash = STATUS_TO_SCREEN[statusRef.current] ?? 's1';
      }
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // Persist status (+ clips for restart continuity) on every change
  useEffect(() => {
    saveProject({ status, clips });
  }, [status, clips]);

  // navigate: moves to a screen without changing status (must be in ALLOWED_SCREENS)
  const navigate = useCallback((screen) => {
    const allowed = ALLOWED_SCREENS[statusRef.current] ?? ['s1'];
    if (!allowed.includes(screen)) {
      console.warn(`[navigate] screen "${screen}" not allowed in status "${statusRef.current}"`);
      return;
    }
    setCurrentScreen(screen);
  }, []);

  // transition: the single entry point for all status changes
  const transition = useCallback((action, payload) => {
    const curStatus = statusRef.current;
    const allowed   = VALID_TRANSITIONS[curStatus];
    if (!allowed?.[action]) {
      console.warn(`[transition] invalid: ${curStatus} + ${action}`);
      return;
    }
    const nextStatus = allowed[action];

    // Data side effects
    switch (action) {
      case 'ADD_CLIPS':
        if (payload) setClips(payload);
        break;
      case 'CLEAR_CLIPS':
      case 'CHANGE_CLIPS':
        setClips(payload ?? []);
        setSelection(null);
        break;
      case 'CONFIRM_REQUEST':
        if (payload) setJudgmentRules(payload);
        break;
      case 'ANALYZE_SUCCESS':
        if (payload?.selection) setSelection(payload.selection);
        setAnalyzeError(null);
        break;
      case 'ANALYZE_FAIL':
        setAnalyzeError(payload ?? null);
        break;
      case 'RETRY_ANALYZE':
        setAnalyzeError(null);
        break;
      case 'SKIP_CLIP':
        setAnalyzeError(null);
        if (payload?.clipId) setClips(prev => prev.filter(c => c.id !== payload.clipId));
        break;
      case 'CHANGE_REQUEST':
        if (payload) setJudgmentRules(payload);
        break;
      case 'CHANGE_STYLE':
        if (payload) setExecutionRules(payload);
        break;
      case 'CHANGE_SELECTION':
        if (payload) setSelection(payload);
        break;
      case 'RENDER_SUCCESS':
        setRenderError(null);
        break;
      case 'RENDER_FAIL':
        setRenderError(payload ?? null);
        break;
      case 'CANCEL_RENDER':
      case 'BACK_TO_EDITOR':
        setRenderError(null);
        break;
      case 'RESET':
        setClips([]);
        setSelection(null);
        setJudgmentRules(null);
        setExecutionRules(null);
        setAnalyzeError(null);
        setRenderError(null);
        break;
      default: break;
    }

    setStatus(nextStatus);
    if (ACTION_SCREEN[action]) setCurrentScreen(ACTION_SCREEN[action]);
  }, []);

  return (
    <ProjectContext.Provider value={{
      status, currentScreen,
      clips, setClips,
      judgmentRules, setJudgmentRules,
      executionRules, setExecutionRules,
      selection, setSelection,
      analyzeError, renderError,
      transition, navigate,
    }}>
      {children}
    </ProjectContext.Provider>
  );
}

export const useProject = () => useContext(ProjectContext);
