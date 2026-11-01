import { useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getJudgmentRules, getExecutionRules } from '../../api/index.js';
import { fmtDuration } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import StylePanel from './StylePanel.jsx';
import ConfirmModal from '../s2_1/ConfirmModal.jsx';

export default function RequestScreen() {
  const { status, clips, judgmentRules, setJudgmentRules, executionRules, setExecutionRules, transition, navigate } = useProject();

  const [oneLine,    setOneLine]    = useState('친구랑 편의점 갔다가 집에서 먹방하는 밤 브이로그');
  const [targetMin,  setTargetMin]  = useState(10);
  const [targetSec,  setTargetSec]  = useState(0);
  const [intentText, setIntentText] = useState('과자 고르는 장면이랑 먹방 위주로 해줘. 걸어서 이동하는 건 짧게. 빨간 후드 입은 애가 민수야. 한강 도착하는 장면은 꼭 넣고.');
  const [showModal,  setShowModal]  = useState(false);

  useEffect(() => {
    getJudgmentRules().then(setJudgmentRules);
    getExecutionRules().then(setExecutionRules);
  }, []);

  const canNext = oneLine.trim().length > 0 && (targetMin > 0 || targetSec > 0);

  const totalSec = clips.reduce((s, c) => s + c.duration, 0);

  const handleConfirm = (confirmedRules) => {
    setShowModal(false);
    if (status === 'analyzed' || status === 'rendered') {
      transition('CHANGE_REQUEST', confirmedRules);
      navigate('s4');
    } else {
      transition('CONFIRM_REQUEST', confirmedRules);
    }
  };

  return (
    <div className="app-shell" style={{ position: 'relative' }}>
      <TopBar rightContent={`클립 ${clips.length}개 · ${fmtDuration(totalSec)}`} />

      <div className="split" style={{ gridTemplateColumns: '52% 48%', flex: 1, overflowY: 'auto' }}>
        {/* 왼쪽: 기획 */}
        <div className="pane" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div className="sec">기획</div>
            <div className="lb">AI가 무엇을 남길지 고를 때 기준이 돼요</div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 8 }}>
            <div>
              <div className="lb">목표 분량 *</div>
              <div className="row">
                <input
                  className="fld"
                  type="number"
                  min={0}
                  value={targetMin}
                  onChange={e => setTargetMin(Number(e.target.value))}
                  style={{ width: 48 }}
                />
                <span className="lb">분</span>
                <input
                  className="fld"
                  type="number"
                  min={0}
                  max={59}
                  value={targetSec}
                  onChange={e => setTargetSec(Number(e.target.value))}
                  style={{ width: 40 }}
                />
                <span className="lb">초</span>
              </div>
            </div>
            <div>
              <div className="lb">영상 한 줄 설명 *</div>
              <input
                className="fld"
                value={oneLine}
                onChange={e => setOneLine(e.target.value)}
                style={{ width: '100%' }}
                placeholder="예: 친구랑 편의점 갔다가 집에서 먹방하는 밤 브이로그"
              />
            </div>
          </div>

          <div>
            <div className="lb">편집 의도 (자유롭게, 선택)</div>
            <textarea
              className="fld"
              value={intentText}
              onChange={e => setIntentText(e.target.value)}
              style={{ width: '100%', minHeight: 120, resize: 'vertical', lineHeight: 1.6 }}
              placeholder="예: 강조할 장면, 줄일 장면, 꼭 넣을·뺄 장면, 등장인물"
            />
            <div className="lb" style={{ marginTop: 4 }}>예: 강조할 장면, 줄일 장면, 꼭 넣을·뺄 장면, 등장인물</div>
          </div>

          <div className="card lb" style={{ marginTop: 'auto' }}>
            다음을 누르면 AI가 이해한 내용을 항목으로 보여드려요. 거기서 고친 뒤 확정하면 분석이 시작돼요.
          </div>
        </div>

        {/* 오른쪽: 스타일 */}
        <StylePanel rules={executionRules} onChange={setExecutionRules} />
      </div>

      {showModal && (
        <ConfirmModal
          rules={judgmentRules}
          onBack={() => setShowModal(false)}
          onConfirm={handleConfirm}
        />
      )}

      <BottomBar
        left={<button onClick={() => navigate('s1')}>← 가져오기</button>}
        right={
          <button
            className="btn-primary"
            disabled={!canNext}
            onClick={() => setShowModal(true)}
          >
            다음: AI가 이해한 내용 확인 →
          </button>
        }
      />
    </div>
  );
}
