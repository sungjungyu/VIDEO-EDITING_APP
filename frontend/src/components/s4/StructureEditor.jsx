import { useCallback, useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getTree, getSelection, autoCompress, saveSelection } from '../../api/index.js';
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
    } finally {
      setAiLoading(false);
    }
  };

  const breadcrumb = selectedPath.filter(Boolean);

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
          breadcrumb.length > 0
            ? <span className="lb">선택: {breadcrumb.join(' › ')}</span>
            : <span className="lb">Space 켜기/끄기 · ↑↓←→ 이동 · 우클릭 꼭 넣기/빼기</span>
        }
        right={
          <div className="row">
            <button onClick={handleAICompress} disabled={aiLoading}>
              {aiLoading ? 'AI 분석 중…' : 'AI로 목표 분량 채우기'}
            </button>
            <button className="btn-primary" onClick={() => transition('START_RENDER')}>렌더 →</button>
          </div>
        }
      />

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
