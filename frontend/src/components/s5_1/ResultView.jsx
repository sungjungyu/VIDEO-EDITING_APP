import { useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getResult } from '../../api/index.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ResultPlayer from './ResultPlayer.jsx';
import ResultSummary from './ResultSummary.jsx';

export default function ResultView() {
  const { navigate } = useProject();
  const [result,      setResult]      = useState(null);
  const [selectedSeg, setSelectedSeg] = useState(null);

  useEffect(() => {
    getResult().then(data => {
      setResult(data);
      setSelectedSeg(data.segments?.[0] ?? null);
    });
  }, []);

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
            <button onClick={() => navigate('s2')}>스타일만 바꾸기</button>
          </div>
        }
        right={
          <div className="row">
            <span className="lb">MP4 · 자막 SRT · 편집 지시서 JSON</span>
            <button className="btn-primary">내보내기 ↓</button>
          </div>
        }
      />
    </div>
  );
}
