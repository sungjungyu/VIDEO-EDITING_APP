import { useEffect, useState, useRef } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getProgress } from '../../api/index.js';
import { fmtMinSec } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ProgressBar from '../common/ProgressBar.jsx';
import Chip from '../common/Chip.jsx';
import Badge from '../common/Badge.jsx';
import RenderTimeline from './RenderTimeline.jsx';

const STEP_LABELS = [
  { key: 'edl',      label: '1. 편집 지시서' },
  { key: 'review',   label: '2. 렌더 전 검수' },
  { key: 'cut',      label: '3. 자르기·이어붙이기' },
  { key: 'subtitle', label: '4. 자막 입히기' },
  { key: 'io',       label: '5. 인트로·아웃트로' },
];

function stepStatus(percent, idx) {
  const thresholds = [15, 25, 80, 95, 100];
  if (percent >= thresholds[idx])   return 'done';
  const prevDone = idx === 0 ? true : percent >= thresholds[idx - 1];
  if (prevDone && percent < thresholds[idx]) return 'running';
  return 'waiting';
}

const REVIEW_BADGE = { fix: 'success', warn: 'warning', ok: 'success' };

export default function RenderingScreen() {
  const { status, renderError, transition, navigate } = useProject();
  const [percent,    setPercent]   = useState(0);
  const [elapsed,    setElapsed]   = useState(0);
  const [mockData,   setMockData]  = useState(null);
  const [showCancel, setShowCancel] = useState(false);
  const startTime     = useRef(Date.now());
  const didTransition = useRef(false);

  useEffect(() => {
    getProgress('rendering').then(setMockData);
  }, []);

  // Animate only while rendering
  useEffect(() => {
    if (status !== 'rendering') return;
    if (percent >= 100) return;
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000));
      setPercent(p => Math.min(p + 2, 100));
    }, 100);
    return () => clearInterval(id);
  }, [percent, status]);

  // Auto-transition on completion
  useEffect(() => {
    if (status !== 'rendering') return;
    if (percent < 100) return;
    if (didTransition.current) return;
    didTransition.current = true;
    transition('RENDER_SUCCESS');
  }, [percent, status, transition]);

  const displayPercent = status === 'rendered' ? 100 : percent;
  const cur = mockData?.current;
  const currentLabel = cur ? `${cur.label} (${cur.clip_label})` : '';
  const done = status === 'rendered';

  if (status === 'render_failed') {
    return (
      <div className="app-shell">
        <TopBar />
        <div className="progress-wrap" style={{ flex: 1, overflowY: 'auto' }}>
          <div className="progress-title" style={{ color: 'var(--color-danger)' }}>렌더 실패</div>
          <div className="lb">{renderError?.message ?? '렌더 중 오류가 발생했어요.'}</div>
        </div>
        <BottomBar
          left={null}
          right={
            <button className="btn-primary" onClick={() => transition('BACK_TO_EDITOR')}>
              구조 편집으로 →
            </button>
          }
        />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <TopBar rightContent={`경과 ${fmtMinSec(elapsed)}`} />

      <div className="progress-wrap" style={{ flex: 1, overflowY: 'auto' }}>
        <div className="progress-title">
          ⑤ 편집 중{!done && <span className="dots">…</span>}
        </div>

        <div className="row" style={{ justifyContent: 'center', flexWrap: 'wrap' }}>
          {STEP_LABELS.map(({ key, label }, i) => {
            const st     = stepStatus(displayPercent, i);
            const detail = key === 'cut' && mockData?.current ? ` · ${mockData.current.label}` : '';
            return (
              <Chip key={key} variant={st === 'done' ? 'done' : st === 'running' ? 'on' : 'default'}>
                {st === 'done' ? '✓ ' : ''}{label}{detail}
              </Chip>
            );
          })}
        </div>

        <RenderTimeline
          segments={mockData?.segments}
          currentLabel={currentLabel}
          renderPercent={displayPercent}
        />

        <div style={{ width: 'min(580px, 100%)' }}>
          <div className="row lb" style={{ justifyContent: 'space-between' }}>
            <span>전체 진행</span>
            <b style={{ color: 'var(--color-text)' }}>{displayPercent}%</b>
          </div>
          <ProgressBar percent={displayPercent} height={10} />
          <div className="lb" style={{ marginTop: 6, textAlign: 'center' }}>
            {done ? '렌더가 완료됐어요!' : `예상 남은 시간 약 ${fmtMinSec(Math.round((100 - displayPercent) * 0.05))}`}
          </div>
        </div>

        {mockData && (
          <details style={{ width: '100%', borderTop: '1px solid var(--color-border)', padding: '10px 0' }}>
            <summary>자세히 보기 (검수 결과 · 적용 설정)</summary>
            <div className="split" style={{ gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 10 }}>
              <div>
                <div className="lb" style={{ marginBottom: 4 }}>렌더 전 검수</div>
                {mockData.review_logs?.map((log, i) => (
                  <div key={i} className="log">
                    <Badge variant={REVIEW_BADGE[log.type] ?? 'accent'}>
                      {log.type === 'fix' ? '보정' : log.type === 'warn' ? '확인' : '통과'}
                    </Badge>
                    {' '}{log.text}
                  </div>
                ))}
              </div>
              <div>
                <div className="lb" style={{ marginBottom: 4 }}>적용 설정</div>
                <div className="log">화면 비율 자동 (클립 방향에 맞춤) · 가운데 자르기</div>
                <div className="log">자막 Pretendard 48pt · #FFFFFF · 외곽선 3 · 아래</div>
                <div className="log">자막 대상: 민수, 경우 (화자 2명)</div>
                <div className="log">인트로 없음 · 아웃트로 outro.mp4 (5초)</div>
              </div>
            </div>
          </details>
        )}
      </div>

      <BottomBar
        left={
          <button onClick={() => setShowCancel(true)} disabled={done}>
            취소하고 구조 편집으로
          </button>
        }
        right={
          <button
            className="btn-primary"
            disabled={!done}
            onClick={() => navigate('s51')}
          >
            결과 보기 →
          </button>
        }
      />

      {showCancel && (
        <>
          <div className="modal-dim" />
          <div className="modal">
            <div style={{ padding: '16px 16px 12px', fontWeight: 600 }}>렌더를 취소할까요?</div>
            <div className="lb" style={{ padding: '0 16px 16px' }}>
              지금까지의 렌더 진행이 취소되고 구조 편집으로 돌아가요.
            </div>
            <div className="bottom-bar">
              <button onClick={() => setShowCancel(false)}>계속 렌더</button>
              <button className="btn-primary" onClick={() => { transition('CANCEL_RENDER'); setShowCancel(false); }}>
                취소하고 구조 편집으로
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
