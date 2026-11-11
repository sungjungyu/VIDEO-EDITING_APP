import { useCallback, useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getTree, getSelection, autoCompress, saveSelection, USE_MOCK } from '../../api/index.js';
import { RENDER_PLANNED } from '../common/NotConnected.jsx';
import { toggle, setLock, getTotalSec, applyAISelection, findNodePath } from '../../logic/selection.js';
import { fmtDuration } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import MillerColumns from './MillerColumns.jsx';
import DetailPanel from './DetailPanel.jsx';
import EditorTimeline from './EditorTimeline.jsx';

export default function StructureEditor() {
  const { status, selection, setSelection, transition } = useProject();
  const [treeData,     setTreeData]     = useState(null);
  const [selectedPath, setSelectedPath] = useState([null, null, null, null]);
  const [selectedScene, setSelectedScene] = useState(null);
  const [blockedMsg,   setBlockedMsg]   = useState('');
  const [aiLoading,    setAiLoading]    = useState(false);
  const [compressNote, setCompressNote] = useState('');      // 자동 채우기 결과 문구 (화면 임시 계산임을 알린다)
  const [renderNotice, setRenderNotice] = useState(false);   // 실제 모드: 렌더 연결 전 안내

  useEffect(() => {
    getTree().then(setTreeData);
    if (selection == null) {
      getSelection().then(setSelection);
    }
  }, []);

  const sentences  = treeData?.sentences ?? [];
  const selNodes   = selection?.nodes ?? {};
  const targetSec  = selection?.target_sec;
  const targetLabel = targetSec != null ? fmtDuration(targetSec) : '—';
  const onTotal    = getTotalSec(selNodes, treeData ?? { tree: [] });

  const warningColor = targetSec != null && onTotal > 0 && Math.abs(onTotal - targetSec) / targetSec > 0.1
    ? 'var(--color-warning)'
    : undefined;

  const updateNodes = useCallback((newNodes) => {
    const newSel = { ...selection, nodes: newNodes };
    if (status === 'rendered') {
      transition('CHANGE_SELECTION', newSel);
    } else {
      setSelection(newSel);
    }
    saveSelection(newSel);
  }, [selection, status, transition, setSelection]);

  const handleToggle = (nodeId) => {
    setCompressNote('');
    const { nodes: newNodes, blocked, lock } = toggle(selNodes, nodeId, treeData ?? { tree: [] });
    if (blocked) {
      // Determine lock type from the current node's state
      const existingLock = selNodes[nodeId]?.lock;
      const msg = existingLock === 'must_include'
        ? '꼭 넣기로 잠긴 장면이에요'
        : existingLock === 'must_exclude'
          ? '꼭 빼기로 잠긴 장면이에요'
          : '잠긴 장면이에요';
      setBlockedMsg(msg);
      setTimeout(() => setBlockedMsg(''), 2000);
      return;
    }
    updateNodes(newNodes);
  };

  const handleLock = (nodeId, lockType) => {
    setCompressNote('');
    const newNodes = setLock(selNodes, nodeId, lockType, treeData ?? { tree: [] });
    updateNodes(newNodes);
  };

  const handleSelectAt = (colIdx, node) => {
    const newPath = [...selectedPath];
    newPath[colIdx] = node.id;
    for (let i = colIdx + 1; i < 4; i++) newPath[i] = null;
    setSelectedPath(newPath);
    if (node.level === 'scene') setSelectedScene(node);
    else setSelectedScene(null);
  };

  const handleTimelineSceneClick = (sceneId) => {
    if (!treeData) return;
    const path = findNodePath(sceneId, treeData);
    if (!path) return;
    // path is [topicId, taskId?, situationId?, sceneId] (up to 4 levels)
    const newPath = [null, null, null, null];
    path.forEach((id, i) => { if (i < 4) newPath[i] = id; });
    setSelectedPath(newPath);
    // Find the scene node
    function findNode(arr, id) {
      for (const n of arr) {
        if (n.id === id) return n;
        const found = findNode(n.children ?? [], id);
        if (found) return found;
      }
      return null;
    }
    const sceneNode = findNode(treeData.tree ?? [], sceneId);
    setSelectedScene(sceneNode ?? null);
  };

  const handleAICompress = async () => {
    setAiLoading(true);
    try {
      const result = await autoCompress(selection, treeData);
      const newNodes = applyAISelection(selNodes, result);
      updateNodes(newNodes);
      const filled = getTotalSec(newNodes, treeData ?? { tree: [] });
      setCompressNote(`임시 계산(화면 안에서 짧은 장면부터 채움): ${fmtDuration(filled)} / 목표 ${targetLabel} · 서버 계산 연결 예정`);
    } finally {
      setAiLoading(false);
    }
  };

  const breadcrumb = selectedPath.filter(Boolean);
  // 실제 모드에서 규칙 트리를 받았으면 (AI 목차 정리 실패) 안내한다. mock 트리에는 meta가 없다
  const treeNote = treeData?.notes?.[0]
    ?? (treeData?.meta?.source === 'rules' ? 'AI 목차 정리에 실패해 규칙으로 묶은 목차예요. 장소·흐름 이름이 거칠 수 있어요.' : null);

  return (
    <div className="app-shell fill">
      <TopBar
        rightContent={
          <span style={{ color: warningColor }}>
            선택 <b>{fmtDuration(onTotal)}</b> / 목표 {targetLabel}
          </span>
        }
      />

      <div style={{ flex: 1, display: 'grid', gridTemplateRows: '1fr auto', overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '60% 40%', overflow: 'hidden' }}>
          <MillerColumns
            treeData={treeData}
            selectedPath={selectedPath}
            selectionNodes={selNodes}
            onSelectAt={handleSelectAt}
            onToggle={handleToggle}
            onLock={handleLock}
          />
          <DetailPanel
            scene={selectedScene}
            sentences={sentences}
            selectionNodes={selNodes}
          />
        </div>
        <EditorTimeline
          treeData={treeData}
          selectionNodes={selNodes}
          selection={selection}
          selectedScene={selectedScene}
          totalSec={treeData?.duration || 3600}
          onSceneClick={handleTimelineSceneClick}
        />
      </div>

      <BottomBar
        left={
          compressNote
            ? <span className="lb" style={{ color: 'var(--color-warning)' }}>{compressNote}</span>
            : treeNote && breadcrumb.length === 0
            ? <span className="lb" style={{ color: 'var(--color-warning)' }}>{treeNote}</span>
            : breadcrumb.length > 0
            ? <span className="lb">선택: {breadcrumb.join(' › ')}</span>
            : <span className="lb">Space 켜기/끄기 · ↑↓←→ 이동 · 우클릭 꼭 넣기/빼기</span>
        }
        right={
          <div className="row">
            <button onClick={handleAICompress} disabled={aiLoading}>
              {aiLoading ? 'AI 분석 중…' : 'AI로 목표 분량 채우기'}
            </button>
            <button className="btn-primary" onClick={() => (USE_MOCK ? transition('START_RENDER') : setRenderNotice(true))}>렌더 →</button>
          </div>
        }
      />

      {renderNotice && (
        <>
          <div className="modal-dim" onClick={() => setRenderNotice(false)} />
          <div className="modal">
            <div style={{ padding: '16px 16px 12px', fontWeight: 600 }}>{RENDER_PLANNED}</div>
            <div className="lb" style={{ padding: '0 16px 16px', lineHeight: 1.7 }}>
              지금은 구조 편집까지 실제 서버와 연결되어 있어요. 고른 장면으로 영상을 만드는 렌더는 서버 연결 뒤에 열려요.
            </div>
            <div className="bottom-bar">
              <span />
              <button className="btn-primary" onClick={() => setRenderNotice(false)}>확인</button>
            </div>
          </div>
        </>
      )}

      {blockedMsg && (
        <div style={{
          position: 'fixed',
          bottom: 64,
          left: '50%',
          transform: 'translateX(-50%)',
          background: 'var(--color-warning-bg)',
          border: '1px solid var(--color-warning-border)',
          color: 'var(--color-warning)',
          padding: '6px 16px',
          borderRadius: 6,
          fontSize: 13,
          zIndex: 100,
        }}>
          {blockedMsg}
        </div>
      )}
    </div>
  );
}
