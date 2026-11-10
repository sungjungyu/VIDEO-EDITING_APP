import { useEffect, useState, useRef } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getProgress, getSelection, startAnalysis, getJob, USE_MOCK } from '../../api/index.js';
import { fmtMinSec, fmtDuration } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ProgressBar from '../common/ProgressBar.jsx';
import Chip from '../common/Chip.jsx';
import ClipProgressTable from './ClipProgressTable.jsx';
import AnalysisLogList from './AnalysisLogList.jsx';

// ── mock: 애니메이션으로 진행을 흉내 낸다 ──
const MOCK_STEPS = ['1. 받아쓰기', '2. 영상 분석', '3. 말·장면 맞추기', '4. 4단 구조화'];
const MOCK_THRESHOLDS = [30, 80, 95, 100];

function mockStepIndex(percent) {
  if (percent < 30) return 0;   // 받아쓰기·영상 분석은 동시에 돈다
  if (percent < 80) return 1;
  if (percent < 95) return 2;
  return 3;
}

// ── 실제: 서버 분석 작업의 stage(진행 문구) 순서. src/vibecut/services/analysis.py 와 맞춘다 ──
const REAL_STEPS = [
  { stage: '오디오 추출',        label: '1. 오디오 추출' },
  { stage: '받아쓰기·영상 분석', label: '2. 받아쓰기·영상 분석' },
  { stage: '컷 판단',            label: '3. 컷 판단' },
  { stage: '장면 나누기',        label: '4. 장면 나누기' },
  { stage: '편집 계획',          label: '5. 편집 계획' },
];
const REAL_START = [0, 8, 76, 91, 96];   // 각 단계가 시작하는 진행률 (stage 문구가 없을 때 대신 쓴다)
const POLL_MS = 2000;

function realStepIndex(job) {
  const byStage = REAL_STEPS.findIndex(s => s.stage === job?.stage);
  if (byStage >= 0) return byStage;
  const p = job?.progress ?? 0;
  let idx = 0;
  REAL_START.forEach((start, i) => { if (p >= start) idx = i; });
  return idx;
}

function useMockProgress(status, transition) {
  const [percent,  setPercent]  = useState(0);
  const [elapsed,  setElapsed]  = useState(0);
  const [mockData, setMockData] = useState(null);
  const startTime     = useRef(Date.now());
  const didTransition = useRef(false);

  useEffect(() => { getProgress('analyzing').then(setMockData); }, []);

  useEffect(() => {
    if (status !== 'analyzing' || percent >= 100) return;
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000));
      setPercent(p => Math.min(p + 1, 100));
    }, 150);
    return () => clearInterval(id);
  }, [percent, status]);

  useEffect(() => {
    if (status !== 'analyzing' || percent < 100 || didTransition.current) return;
    didTransition.current = true;
    getSelection().then(sel => transition('ANALYZE_SUCCESS', { selection: sel }));
  }, [percent, status, transition]);

  const displayPercent = status === 'analyzed' ? 100 : percent;
  const cur = mockStepIndex(displayPercent);
  return {
    percent: displayPercent,
    elapsed,
    steps: MOCK_STEPS.map((label, i) => ({
      label: i === 1 && i === cur && mockData?.clips
        ? `${label} · 클립 ${mockData.clips.filter(c => c.vision === 'done').length + 1}/${mockData.clips.length}`
        : label,
      state: displayPercent >= MOCK_THRESHOLDS[i] ? 'done' : i === cur ? 'running' : 'waiting',
    })),
    message: mockData?.current?.label ? `분석 중인 클립: ${mockData.current.label}` : '',
    remaining: `예상 남은 시간 약 ${fmtMinSec(Math.round((100 - displayPercent) * 0.15))}`,
    mockData,
  };
}

function useJobProgress(status, transition, jobId, setJobId) {
  const [job,   setJob]   = useState(null);
  const [now,   setNow]   = useState(Date.now());
  const [error, setError] = useState(null);   // 폴링 자체의 오류 (서버 연결 끊김 등)
  const starting = useRef(false);

  // 분석 시작: 작업 id가 없을 때 한 번 (다시 시도 시 RETRY_ANALYZE가 id를 비운다)
  useEffect(() => {
    if (status !== 'analyzing' || jobId || starting.current) return;
    starting.current = true;
    startAnalysis({})
      .then(j => { setJob(j); setJobId(j.job_id); })
      .catch(e => transition('ANALYZE_FAIL', { message: e.message }))
      .finally(() => { starting.current = false; });
  }, [status, jobId]);

  // 2초마다 작업 상태 확인. 분석 완료 뒤에도 결과 숫자를 보여 주려고 한 번은 읽는다
  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timer;
    const tick = async () => {
      try {
        const j = await getJob(jobId);
        if (stopped) return;
        setJob(j);
        setError(null);
        if (j.status === 'done') {
          if (status === 'analyzing') {
            // S4는 아직 mock 트리를 쓴다 (Phase 2에서 서버 트리로 교체)
            const sel = await getSelection();
            transition('ANALYZE_SUCCESS', { selection: sel });
          }
          return;
        }
        if (j.status === 'failed' || j.status === 'canceled') {
          if (status === 'analyzing') {
            transition('ANALYZE_FAIL', { message: j.error || (j.status === 'canceled' ? '분석이 취소됐어요.' : '분석에 실패했어요.') });
          }
          return;
        }
      } catch (e) {
        if (stopped) return;
        // 404: 서버가 다시 켜져 작업이 사라짐 → 새로고침 복원 로직이 S1로 보낸다. 그 외는 잠시 후 다시 시도
        setError(e.status === 404 ? '분석 작업을 찾을 수 없어요. 서버가 다시 시작됐을 수 있어요.' : `서버 연결 확인 중… (${e.message})`);
      }
      if (!stopped && status === 'analyzing') timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, [jobId, status]);

  useEffect(() => {
    if (status !== 'analyzing') return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [status]);

  const done = status === 'analyzed' || job?.status === 'done';
  const percent = done ? 100 : Math.floor(job?.progress ?? 0);
  const started = job?.started_at ? Date.parse(job.started_at) : null;
  const finished = job?.finished_at ? Date.parse(job.finished_at) : null;
  const elapsed = job?.metrics?.elapsed_sec
    ?? (started ? Math.max(0, Math.floor(((finished ?? now) - started) / 1000)) : 0);
  const cur = done ? REAL_STEPS.length : realStepIndex(job);

  return {
    percent,
    elapsed,
    steps: REAL_STEPS.map((s, i) => ({ label: s.label, state: i < cur ? 'done' : i === cur ? 'running' : 'waiting' })),
    message: error ?? (job?.status === 'queued' ? '다른 작업이 끝나기를 기다리는 중…' : job?.message || ''),
    remaining: '창을 닫아도 분석은 서버에서 계속돼요',
    job,
  };
}

export default function AnalyzingScreen() {
  const { status, clips, analyzeError, analyzeJobId, setAnalyzeJobId, transition, navigate } = useProject();
  const progress = USE_MOCK
    ? useMockProgress(status, transition)                                  // eslint-disable-line react-hooks/rules-of-hooks
    : useJobProgress(status, transition, analyzeJobId, setAnalyzeJobId);   // eslint-disable-line react-hooks/rules-of-hooks
  const { percent, elapsed, steps, message, remaining, mockData, job } = progress;

  const retry = () => {
    setAnalyzeJobId(null);
    transition('RETRY_ANALYZE');
  };

  if (status === 'analyze_failed') {
    const failedClips = analyzeError?.failedClips ?? [];
    return (
      <div className="app-shell">
        <TopBar />
        <div className="progress-wrap" style={{ flex: 1, overflowY: 'auto' }}>
          <div className="progress-title" style={{ color: 'var(--color-danger)' }}>분석 실패</div>
          <div className="lb" style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}>
            {analyzeError?.message ?? '일부 클립 분석 중 오류가 발생했어요.'}
          </div>
          {failedClips.length > 0 ? failedClips.map(c => (
            <div key={c.id} className="warn row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
              <span>{c.file}</span>
              <div className="row" style={{ gap: 6 }}>
                <button onClick={() => transition('SKIP_CLIP', { clipId: c.id })}>이 클립 빼고 진행</button>
                <button className="btn-primary" onClick={retry}>다시 시도</button>
              </div>
            </div>
          )) : (
            <div className="row" style={{ gap: 6 }}>
              {!USE_MOCK && <button onClick={() => transition('RESET')}>처음으로</button>}
              <button className="btn-primary" onClick={retry}>다시 시도</button>
            </div>
          )}
        </div>
        <BottomBar left={null} right={null} />
      </div>
    );
  }

  const result = job?.result;
  const usage  = job?.metrics?.ai_usage;
  const totalSec = clips.reduce((s, c) => s + c.duration, 0);

  return (
    <div className="app-shell">
      <TopBar rightContent={`경과 ${fmtMinSec(elapsed)}`} />

      <div className="progress-wrap" style={{ flex: 1, overflowY: 'auto' }}>
        <div className="progress-title">
          ③ 분석 중{status !== 'analyzed' && <span className="dots">…</span>}
        </div>

        <div className="row" style={{ justifyContent: 'center', flexWrap: 'wrap' }}>
          {steps.map((s, i) => (
            <Chip key={i} variant={s.state === 'done' ? 'done' : s.state === 'running' ? 'on' : 'default'}>
              {s.state === 'done' ? '✓ ' : ''}{s.label}
            </Chip>
          ))}
        </div>

        <div className="video" style={{ width: 260, height: 146, marginTop: 4 }}>
          <div className="floor" />
          <div className="p1" style={{ left: 66, top: 40, width: 40, height: 40 }} />
          <div className="p2" style={{ left: 150, top: 46, width: 36, height: 36 }} />
        </div>
        {message && status !== 'analyzed' && <div className="lb">{message}</div>}

        <div style={{ width: 'min(540px, 100%)' }}>
          <div className="row lb" style={{ justifyContent: 'space-between' }}>
            <span>전체 진행</span>
            <b style={{ color: 'var(--color-text)' }}>{percent}%</b>
          </div>
          <ProgressBar percent={percent} height={10} />
          <div className="lb" style={{ marginTop: 6, textAlign: 'center' }}>
            {status === 'analyzed' ? '분석이 완료됐어요!' : `${remaining}`}
          </div>
        </div>

        {mockData && (
          <details style={{ width: '100%', borderTop: '1px solid var(--color-border)', padding: '10px 0' }}>
            <summary>자세히 보기 (클립별 진행 · AI가 발견한 것)</summary>
            <div className="split" style={{ gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 10 }}>
              <ClipProgressTable clipProgress={mockData.clips} />
              <AnalysisLogList logs={mockData.logs} stats={mockData.stats} />
            </div>
          </details>
        )}
        {!USE_MOCK && result?.warnings?.length > 0 && (
          <details open={result.warnings.some(w => w.startsWith('받아쓰기 실패'))}
            style={{ width: '100%', borderTop: '1px solid var(--color-border)', padding: '10px 0' }}>
            <summary>분석 경고 {result.warnings.length}개</summary>
            <ul className="lb">{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </details>
        )}
      </div>

      <BottomBar
        left={
          USE_MOCK ? mockData?.stats && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0,1fr))', gap: 8 }}>
              {[['전체 길이', '60:00'], ['장면', mockData.stats.scenes], ['문장', mockData.stats.sentences], ['화자', mockData.stats.speakers], ['API 비용', `₩${mockData.stats.cost_krw}`]].map(([k, v]) => (
                <div key={k}><div className="lb">{k}</div><div className="num">{v}</div></div>
              ))}
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0,1fr))', gap: 8 }}>
              {[
                ['전체 길이', fmtDuration(totalSec)],
                ['장면', result?.scenes ?? '–'],
                ['문장', result?.lines ?? '–'],
                ['자름 제안', result?.cut_suggested ?? '–'],
                ['AI 요청', usage ? `${usage.requests}회${usage.cache_hits ? ` (캐시 ${usage.cache_hits})` : ''}` : '–'],
              ].map(([k, v]) => (
                <div key={k}><div className="lb">{k}</div><div className="num">{v}</div></div>
              ))}
            </div>
          )
        }
        right={
          <button
            className="btn-primary"
            disabled={status !== 'analyzed'}
            onClick={() => navigate('s4')}
          >
            구조 편집 시작 →
          </button>
        }
      />
    </div>
  );
}
