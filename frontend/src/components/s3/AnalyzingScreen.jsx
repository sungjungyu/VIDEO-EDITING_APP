import { useEffect, useState, useRef } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getProgress } from '../../api/index.js';
import { fmtMinSec } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ProgressBar from '../common/ProgressBar.jsx';
import Chip from '../common/Chip.jsx';
import ClipProgressTable from './ClipProgressTable.jsx';
import AnalysisLogList from './AnalysisLogList.jsx';

function stepStatus(percent, idx) {
  // 받아쓰기(0): done from 30%, 영상분석(1): running 0-80% done after, 맞추기(2): running 80-95%, 구조화(3): running 95-100%
  const thresholds = [30, 80, 95, 100];
  if (percent >= thresholds[idx])      return 'done';
  if (idx === 0 && percent < 30)       return 'running';
  if (idx === 1 && percent < 80)       return 'running';
  if (idx === 2 && percent >= 80 && percent < 95) return 'running';
  if (idx === 3 && percent >= 95)      return 'running';
  return 'waiting';
}

const STEP_LABELS = ['1. 받아쓰기', '2. 영상 분석', '3. 말·장면 맞추기', '4. 4단 구조화'];

export default function AnalyzingScreen() {
  const { setCurrentScreen } = useProject();
  const [percent,   setPercent]   = useState(0);
  const [elapsed,   setElapsed]   = useState(0);
  const [mockData,  setMockData]  = useState(null);
  const startTime = useRef(Date.now());

  useEffect(() => {
    getProgress('analyzing').then(setMockData);
  }, []);

  useEffect(() => {
    if (percent >= 100) return;
    const id = setInterval(() => {
      const secs = Math.floor((Date.now() - startTime.current) / 1000);
      setElapsed(secs);
      setPercent(p => Math.min(p + 1, 100));
    }, 150);
    return () => clearInterval(id);
  }, [percent]);

  const done  = percent >= 100;
  const eta   = done ? 0 : Math.round((100 - percent) * 0.15);
  const curClip = mockData?.current?.label ?? '';

  return (
    <div className="app-shell">
      <TopBar rightContent={`경과 ${fmtMinSec(elapsed)}`} />

      <div className="progress-wrap" style={{ flex: 1, overflowY: 'auto' }}>
        <div className="progress-title">
          ③ 분석 중{!done && <span className="dots">…</span>}
        </div>

        <div className="row" style={{ justifyContent: 'center', flexWrap: 'wrap' }}>
          {STEP_LABELS.map((label, i) => {
            const status = stepStatus(percent, i);
            return (
              <Chip key={i} variant={status === 'done' ? 'done' : status === 'running' ? 'on' : 'default'}>
                {status === 'done' ? '✔ ' : ''}{label}
                {i === 1 && status === 'running' && mockData?.clips && ` · 클립 ${mockData.clips.filter(c => c.vision === 'done').length + 1}/${mockData.clips.length}`}
              </Chip>
            );
          })}
        </div>

        <div className="video" style={{ width: 260, height: 146, marginTop: 4 }}>
          <div className="floor" />
          <div className="p1" style={{ left: 66, top: 40, width: 40, height: 40 }} />
          <div className="p2" style={{ left: 150, top: 46, width: 36, height: 36 }} />
        </div>
        {curClip && <div className="lb">분석 중인 클립: {curClip}</div>}

        <div style={{ width: 'min(540px, 100%)' }}>
          <div className="row lb" style={{ justifyContent: 'space-between' }}>
            <span>전체 진행</span>
            <b style={{ color: 'var(--color-text)' }}>{percent}%</b>
          </div>
          <ProgressBar percent={percent} height={10} />
          <div className="lb" style={{ marginTop: 6, textAlign: 'center' }}>
            {done ? '분석이 완료됐어요!' : `예상 남은 시간 약 ${fmtMinSec(eta)} · 창을 닫아도 분석은 계속돼요`}
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
      </div>

      <BottomBar
        left={
          mockData?.stats && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0,1fr))', gap: 8 }}>
              {[['전체 길이', '60:00'], ['장면', mockData.stats.scenes], ['문장', mockData.stats.sentences], ['화자', mockData.stats.speakers], ['API 비용', `₩${mockData.stats.cost_krw}`]].map(([k, v]) => (
                <div key={k}><div className="lb">{k}</div><div className="num">{v}</div></div>
              ))}
            </div>
          )
        }
        right={
          <button
            className="btn-primary"
            disabled={!done}
            onClick={() => setCurrentScreen('s4')}
          >
            구조 편집 시작 →
          </button>
        }
      />
    </div>
  );
}
