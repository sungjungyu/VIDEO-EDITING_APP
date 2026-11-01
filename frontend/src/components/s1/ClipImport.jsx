import { useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getClips } from '../../api/index.js';
import { fmtDuration, fmtAspect } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ClipCard from './ClipCard.jsx';

export default function ClipImport() {
  const { status, clips, setClips, transition, navigate } = useProject();
  const [pendingClips, setPendingClips] = useState(null); // awaiting CHANGE_CLIPS confirm

  useEffect(() => {
    getClips().then(setClips);
  }, []);

  const totalSec = clips.reduce((s, c) => s + c.duration, 0);
  const canNext  = clips.length > 0;

  const aspectSummary = () => {
    const counts = {};
    clips.forEach(c => {
      const a = fmtAspect(c.width, c.height);
      counts[a] = (counts[a] ?? 0) + 1;
    });
    return Object.entries(counts).map(([a, n]) => `${a} ×${n}`).join(', ');
  };

  const handleRemove = (id) => {
    const next = clips.filter(c => c.id !== id);
    if (status === 'analyzed' || status === 'rendered') {
      setPendingClips(next);
    } else {
      setClips(next);
    }
  };

  const handleNext = () => {
    if (status === 'analyzed' || status === 'rendered') {
      navigate('s2');
    } else {
      transition('ADD_CLIPS', clips);
    }
  };

  return (
    <div className="app-shell">
      <TopBar rightContent="프로젝트: 밤 브이로그" />

      <div style={{ padding: 16, flex: 1, overflowY: 'auto' }}>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
          <div className="sec" style={{ margin: 0 }}>촬영 클립</div>
          <div className="row">
            <span className="lb">드래그해서 순서를 바꿀 수 있어요</span>
            <button>촬영 시각순 정렬</button>
          </div>
        </div>

        <div className="grid2">
          {clips.map(clip => (
            <ClipCard key={clip.id} clip={clip} onRemove={handleRemove} />
          ))}
          <div className="clip-card add-card">
            + 영상 추가 (클릭 또는 끌어다 놓기)
          </div>
        </div>
      </div>

      <BottomBar
        left={<span className="lb">클립 {clips.length}개 · 총 {fmtDuration(totalSec)} · {aspectSummary()}</span>}
        right={
          <button className="btn-primary" disabled={!canNext} onClick={handleNext}>
            {status === 'analyzed' || status === 'rendered' ? '요청 화면으로 →' : '다음: 요청 →'}
          </button>
        }
      />

      {pendingClips && (
        <>
          <div className="modal-dim" />
          <div className="modal">
            <div style={{ padding: '16px 16px 12px', fontWeight: 600 }}>분석을 다시 해야 해요</div>
            <div className="lb" style={{ padding: '0 16px 16px' }}>
              클립을 바꾸면 분석 결과와 편집 선택이 초기화돼요. 계속할까요?
            </div>
            <div className="bottom-bar">
              <button onClick={() => setPendingClips(null)}>취소</button>
              <button className="btn-primary" onClick={() => { transition('CHANGE_CLIPS', pendingClips); setPendingClips(null); }}>
                초기화하고 계속
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
