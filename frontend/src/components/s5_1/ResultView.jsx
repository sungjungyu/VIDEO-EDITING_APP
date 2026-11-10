import { useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getResult, getExecutionRules } from '../../api/index.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ResultPlayer from './ResultPlayer.jsx';
import ResultSummary from './ResultSummary.jsx';
import StylePanel from '../s2/StylePanel.jsx';

export default function ResultView() {
  const { navigate, executionRules, setExecutionRules, transition } = useProject();
  const [result,      setResult]      = useState(null);
  const [selectedSeg, setSelectedSeg] = useState(null);
  const [styleOpen,   setStyleOpen]   = useState(false);
  const [localRules,  setLocalRules]  = useState(null);

  useEffect(() => {
    getResult().then(data => {
      setResult(data);
      setSelectedSeg(data.segments?.[0] ?? null);
    });
  }, []);

  // 스타일은 S2에서 받지 않으므로 여기가 처음 바꾸는 곳이다. 아직 없으면(새로고침 등) 기본값을 불러온다
  const openStyle = async () => {
    const rules = executionRules ?? await getExecutionRules();
    if (!executionRules) setExecutionRules(rules);
    setLocalRules(JSON.parse(JSON.stringify(rules)));
    setStyleOpen(true);
  };

  const applyStyle = () => {
    transition('CHANGE_STYLE', localRules);
    transition('START_RENDER');
    setStyleOpen(false);
  };

  if (!result) return null;

  return (
    <div className="app-shell">
      <TopBar rightContent={<span style={{ color: 'var(--color-success)' }}>편집 완료</span>} />

      <div className="split" style={{ gridTemplateColumns: '58% 42%', flex: 1, overflowY: 'auto' }}>
        <ResultPlayer result={result} selectedSeg={selectedSeg} onSelectSeg={setSelectedSeg} />
        <ResultSummary result={result} />
      </div>

      <BottomBar
        left={
          <div className="row">
            <button onClick={() => navigate('s4')}>← 구조 편집으로 돌아가기</button>
            <button onClick={openStyle}>스타일만 바꾸기</button>
          </div>
        }
        right={
          <div className="row">
            <span className="lb">MP4 · 자막 SRT · 편집 지시서 JSON</span>
            <button className="btn-primary">내보내기 ↓</button>
          </div>
        }
      />

      {styleOpen && (
        <>
          <div className="modal-dim" onClick={() => setStyleOpen(false)} />
          <div className="modal" style={{ width: 'min(600px, 95vw)' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--color-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 600, fontSize: 15 }}>스타일 변경 후 다시 렌더</span>
              <button onClick={() => setStyleOpen(false)}>✕</button>
            </div>
            <div style={{ padding: '12px 0' }}>
              <StylePanel rules={localRules} onChange={setLocalRules} />
            </div>
            <div className="bottom-bar">
              <button onClick={() => setStyleOpen(false)}>취소</button>
              <button
                className="btn-primary"
                disabled={!localRules}
                onClick={applyStyle}
              >
                적용하고 다시 렌더 →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
