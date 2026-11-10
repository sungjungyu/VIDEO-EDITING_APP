import { useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getClips } from '../../api/index.js';
import { fmtDuration, fmtAspect } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ClipCard from './ClipCard.jsx';

const NEEDS_CONFIRM = (status) => status === 'analyzed' || status === 'rendered';

export default function ClipImport() {
  const { status, clips, setClips, transition, navigate } = useProject();
  // pendingClips: new clip list waiting for user confirm before CHANGE_CLIPS
  const [pendingClips, setPendingClips] = useState(null);

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

  // Any clip-list change while analyzed/rendered: show confirm first
  const applyOrConfirm = (newClips) => {
    if (NEEDS_CONFIRM(status)) {
      setPendingClips(newClips);
    } else {
      setClips(newClips);
    }
  };

  const handleRemove = (id) => applyOrConfirm(clips.filter(c => c.id !== id));

  const handleSort = () => {
    const sorted = [...clips].sort((a, b) => (a.recorded_at ?? a.file) < (b.recorded_at ?? b.file) ? -1 : 1);
    applyOrConfirm(sorted);
  };

  const handleAddClick = () => {
    if (NEEDS_CONFIRM(status)) {
      // In mock mode we can't add real files; show confirm so analysis is reset first
      setPendingClips(clips);
    }
    // else: no-op in mock (file picker not implemented)
  };

  const handleNext = () => {
    if (NEEDS_CONFIRM(status)) {
      navigate('s2');
    } else {
      transition('ADD_CLIPS', clips);
    }
  };

  const confirmChange = () => {
    transition('CHANGE_CLIPS', pendingClips);
    setPendingClips(null);
  };

  return (
    <div className="app-shell">
      <TopBar rightContent="프로젝트: 밤 브이로그" />

      <div style={{ padding: 16, flex: 1, overflowY: 'auto' }}>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
          <div className="sec" style={{ margin: 0 }}>촬영 클립</div>
          <div className="row">
            <span className="lb">드래그해서 순서를 바꿀 수 있어요</span>
            <button onClick={handleSort}>촬영 시각순 정렬</button>
          </div>
        </div>

        <div className="grid2">
          {clips.map(clip => (
            <ClipCard key={clip.id} clip={clip} onRemove={handleRemove} />
          ))}
          <div className="clip-card add-card" onClick={handleAddClick}>
            + 영상 추가 (클릭 또는 끌어다 놓기)
          </div>
        </div>
      </div>

      <BottomBar
        left={<span className="lb">클립 {clips.length}개 · 총 {fmtDuration(totalSec)} · {aspectSummary()}</span>}
        right={
          <button className="btn-primary" disabled={!canNext} onClick={handleNext}>
            {NEEDS_CONFIRM(status) ? '요청 화면으로 →' : '다음: 요청 →'}
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
              <button className="btn-primary" onClick={confirmChange}>초기화하고 계속</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
