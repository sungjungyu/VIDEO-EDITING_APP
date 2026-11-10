import { useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getJudgmentRules, getExecutionRules, USE_MOCK } from '../../api/index.js';
import { fmtDuration, fmtMinSec } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ConfirmModal from '../s2_1/ConfirmModal.jsx';

const MOCK_ONE_LINE = '친구랑 편의점 갔다가 집에서 먹방하는 밤 브이로그';
const MOCK_INTENT   = '과자 고르는 장면이랑 먹방 위주로 해줘. 걸어서 이동하는 건 짧게. 빨간 후드 입은 애가 민수야. 한강 도착하는 장면은 꼭 넣고.';

export default function RequestScreen() {
  const { status, clips, judgmentRules, setJudgmentRules, executionRules, setExecutionRules,
          request, setRequest, transition, navigate } = useProject();

  // 실제 API 모드: 이전에 확정한 요청이 있으면 그 값으로, 없으면 빈 칸에서 시작
  const initTarget = request?.target_sec ?? (USE_MOCK ? 600 : 60);
  const [oneLine,    setOneLine]    = useState(request?.one_line ?? (USE_MOCK ? MOCK_ONE_LINE : ''));
  const [targetMin,  setTargetMin]  = useState(Math.floor(initTarget / 60));
  const [targetSec,  setTargetSec]  = useState(initTarget % 60);
  const [intentText, setIntentText] = useState(request?.intent ?? (USE_MOCK ? MOCK_INTENT : ''));
  const [showModal,  setShowModal]  = useState(false);

  useEffect(() => {
    // 스타일(자막·비율·인트로)은 S2에서 받지 않는다 (교수님 피드백). 기본값으로 렌더하고 S5-1 "스타일만 바꾸기"에서 바꾼다
    if (!executionRules) getExecutionRules().then(setExecutionRules);
    if (!USE_MOCK) return;   // 실제 API에는 아직 규칙 해석(S2-1) API가 없다 (Phase 3)
    getJudgmentRules().then(setJudgmentRules);
  }, []);

  const canNext = oneLine.trim().length > 0 && (targetMin > 0 || targetSec > 0);

  const totalSec = clips.reduce((s, c) => s + c.duration, 0);
  const goalSec  = targetMin * 60 + targetSec;

  const handleConfirm = (confirmedRules) => {
    setShowModal(false);
    if (!USE_MOCK) {
      setRequest({ one_line: oneLine.trim(), intent: intentText.trim(), target_sec: goalSec });
    }
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

      <div className="split" style={{ gridTemplateColumns: 'min(720px, 100%)', justifyContent: 'center', flex: 1, overflowY: 'auto' }}>
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
            {USE_MOCK
              ? '다음을 누르면 AI가 이해한 내용을 항목으로 보여드려요. 거기서 고친 뒤 확정하면 분석이 시작돼요.'
              : '다음을 누르면 요청을 한 번 더 확인한 뒤 분석이 시작돼요. 한 줄 설명과 편집 의도는 구조 편집에서 AI가 장면을 고를 때 쓰여요.'}
          </div>
        </div>

      </div>

      {showModal && USE_MOCK && (
        <ConfirmModal
          rules={judgmentRules}
          onBack={() => setShowModal(false)}
          onConfirm={handleConfirm}
        />
      )}
      {showModal && !USE_MOCK && (
        <>
          <div className="modal-dim" />
          <div className="modal">
            <div style={{ padding: '16px 16px 12px', fontWeight: 600 }}>요청 확인</div>
            <div style={{ padding: '0 16px 16px', display: 'grid', gridTemplateColumns: '90px 1fr', gap: '6px 12px' }}>
              <span className="lb">한 줄 설명</span><span>{oneLine.trim()}</span>
              <span className="lb">목표 분량</span>
              <span>{fmtMinSec(goalSec)} <span className="lb">(원본 {fmtMinSec(totalSec)})</span></span>
              <span className="lb">편집 의도</span><span>{intentText.trim() || <span className="lb">없음</span>}</span>
              <span className="lb">클립</span><span>{clips.length}개</span>
            </div>
            <div className="bottom-bar">
              <button onClick={() => setShowModal(false)}>고치기</button>
              <button className="btn-primary" onClick={() => handleConfirm(null)}>
                {status === 'analyzed' || status === 'rendered' ? '확정' : '확정하고 분석 시작 →'}
              </button>
            </div>
          </div>
        </>
      )}

      <BottomBar
        left={<button onClick={() => navigate('s1')}>← 가져오기</button>}
        right={
          <button
            className="btn-primary"
            disabled={!canNext}
            onClick={() => setShowModal(true)}
          >
            {USE_MOCK ? '다음: AI가 이해한 내용 확인 →' : '다음: 요청 확인 →'}
          </button>
        }
      />
    </div>
  );
}
