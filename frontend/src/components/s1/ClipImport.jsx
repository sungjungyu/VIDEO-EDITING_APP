import { useEffect, useRef, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getClips, uploadClips, removeClip, reorderClips, ProjectGoneError, USE_MOCK } from '../../api/index.js';
import { fmtDuration, fmtAspect } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import ProgressBar from '../common/ProgressBar.jsx';
import ClipCard from './ClipCard.jsx';

const NEEDS_CONFIRM = (status) => status === 'analyzed' || status === 'rendered';
const ACCEPT = '.mp4,.mov,.m4v,.avi,.mkv,.webm,.3gp,video/*';

export default function ClipImport() {
  const { status, clips, setClips, transition, navigate, notice, setNotice } = useProject();
  // pending: 분석 결과가 있을 때 클립을 바꾸기 전 확인받을 작업 () => Promise<clips>
  const [pending,   setPending]   = useState(null);
  const [uploadPct, setUploadPct] = useState(null);   // null = 업로드 중 아님
  const [busy,      setBusy]      = useState(false);
  const [error,     setError]     = useState(null);
  const [dragOver,  setDragOver]  = useState(false);
  const fileInput = useRef(null);

  const handleError = (e) => {
    if (e instanceof ProjectGoneError) {
      transition('RESET', { keepServer: true });
      setNotice(e.message);
      setClips([]);
    } else {
      setError(e.message ?? String(e));
    }
  };

  useEffect(() => {
    getClips().then(setClips).catch(handleError);
  }, []);

  const totalSec = clips.reduce((s, c) => s + c.duration, 0);
  const canNext  = clips.length > 0 && uploadPct === null && !busy;

  const aspectSummary = () => {
    const counts = {};
    clips.forEach(c => {
      if (!c.width || !c.height) return;
      const a = fmtAspect(c.width, c.height);
      counts[a] = (counts[a] ?? 0) + 1;
    });
    return Object.entries(counts).map(([a, n]) => `${a} ×${n}`).join(', ');
  };

  // 클립 목록을 바꾸는 작업. 분석 결과가 있으면 먼저 확인받고, 확인 후 CHANGE_CLIPS로 분석을 초기화한다
  const runChange = async (work) => {
    setError(null);
    setBusy(true);
    try {
      const next = await work();
      if (NEEDS_CONFIRM(status)) transition('CHANGE_CLIPS', next);
      else setClips(next);
    } catch (e) {
      handleError(e);
    } finally {
      setBusy(false);
      setUploadPct(null);
    }
  };
  const applyOrConfirm = (work) => (NEEDS_CONFIRM(status) ? setPending(() => work) : runChange(work));

  const handleRemove = (id) => {
    const remaining = clips.filter(c => c.id !== id);
    applyOrConfirm(() => removeClip(id, remaining));
  };

  const handleSort = () => {
    const key = (c) => c.shot_at ?? c.file;
    const sorted = [...clips].sort((a, b) => (key(a) < key(b) ? -1 : 1));
    applyOrConfirm(() => reorderClips(sorted));
  };

  const handleFiles = (fileList) => {
    const files = [...(fileList ?? [])];
    if (files.length === 0) return;
    applyOrConfirm(() => {
      setUploadPct(0);
      return uploadClips(files, setUploadPct);
    });
  };

  const handleAddClick = () => {
    if (USE_MOCK) {
      // mock에서는 실제 파일을 못 올리므로, 분석이 있으면 초기화 확인만 띄운다
      if (NEEDS_CONFIRM(status)) setPending(() => async () => clips);
      return;
    }
    fileInput.current?.click();
  };

  const handleNext = () => {
    if (NEEDS_CONFIRM(status)) {
      navigate('s2');
    } else {
      transition('ADD_CLIPS', clips);
    }
  };

  const confirmChange = () => {
    const work = pending;
    setPending(null);
    runChange(work);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (!USE_MOCK) handleFiles(e.dataTransfer.files);
  };

  return (
    <div className="app-shell">
      <TopBar rightContent={USE_MOCK ? '프로젝트: 밤 브이로그' : 'VIBE CUT'} />

      <div
        style={{ padding: 16, flex: 1, overflowY: 'auto' }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        {notice && (
          <div className="warn row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
            <span>{notice}</span>
            <button onClick={() => setNotice(null)}>닫기</button>
          </div>
        )}
        {error && (
          <div className="warn row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
            <span>{error}</span>
            <button onClick={() => setError(null)}>닫기</button>
          </div>
        )}

        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
          <div className="sec" style={{ margin: 0 }}>촬영 클립</div>
          <div className="row">
            <span className="lb">편집에 쓰는 순서대로 보여요</span>
            <button onClick={handleSort} disabled={busy || clips.length < 2}>촬영 시각순 정렬</button>
          </div>
        </div>

        {uploadPct !== null && (
          <div style={{ marginBottom: 12 }}>
            <div className="row lb" style={{ justifyContent: 'space-between' }}>
              <span>{uploadPct < 100 ? '영상 올리는 중…' : '서버에서 영상 정보를 읽는 중…'}</span>
              <b>{uploadPct}%</b>
            </div>
            <ProgressBar percent={uploadPct} height={6} />
          </div>
        )}

        <div className="grid2">
          {clips.map(clip => (
            <ClipCard key={clip.id} clip={clip} onRemove={busy ? undefined : handleRemove} />
          ))}
          <div
            className="clip-card add-card"
            onClick={busy ? undefined : handleAddClick}
            style={dragOver ? { outline: '2px dashed var(--color-accent)' } : undefined}
          >
            + 영상 추가 (클릭 또는 끌어다 놓기)
          </div>
        </div>
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => { handleFiles(e.target.files); e.target.value = ''; }}
        />
      </div>

      <BottomBar
        left={<span className="lb">클립 {clips.length}개 · 총 {fmtDuration(totalSec)}{clips.length > 0 && ` · ${aspectSummary()}`}</span>}
        right={
          <button className="btn-primary" disabled={!canNext} onClick={handleNext}>
            {NEEDS_CONFIRM(status) ? '요청 화면으로 →' : '다음: 요청 →'}
          </button>
        }
      />

      {pending && (
        <>
          <div className="modal-dim" />
          <div className="modal">
            <div style={{ padding: '16px 16px 12px', fontWeight: 600 }}>분석을 다시 해야 해요</div>
            <div className="lb" style={{ padding: '0 16px 16px' }}>
              클립을 바꾸면 분석 결과와 편집 선택이 초기화돼요. 계속할까요?
            </div>
            <div className="bottom-bar">
              <button onClick={() => setPending(null)}>취소</button>
              <button className="btn-primary" onClick={confirmChange}>초기화하고 계속</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
