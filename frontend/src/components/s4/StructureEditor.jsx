import { useEffect, useState } from 'react';
import { useProject } from '../../state/ProjectContext.jsx';
import { getTree, getSelection } from '../../api/index.js';
import { fmtDuration } from '../../utils/format.js';
import TopBar from '../common/TopBar.jsx';
import BottomBar from '../common/BottomBar.jsx';
import MillerColumns from './MillerColumns.jsx';
import DetailPanel from './DetailPanel.jsx';
import EditorTimeline from './EditorTimeline.jsx';

export default function StructureEditor() {
  const { selection, setSelection, transition } = useProject();
  const [treeData,     setTreeData]     = useState(null);
  const [selectedPath, setSelectedPath] = useState([null, null, null, null]);
  const [selectedScene, setSelectedScene] = useState(null);

  useEffect(() => {
    getTree().then(setTreeData);
    getSelection().then(setSelection);
  }, []);

  const handleSelectAt = (colIdx, node) => {
    const newPath = [...selectedPath];
    newPath[colIdx] = node.id;
    for (let i = colIdx + 1; i < 4; i++) newPath[i] = null;
    setSelectedPath(newPath);
    if (node.level === 'scene') setSelectedScene(node);
    else setSelectedScene(null);
  };

  const sentences = treeData?.sentences ?? [];
  const selNodes  = selection?.nodes ?? {};
  const onTotal   = Object.entries(selNodes)
    .filter(([, v]) => v.state === 'on')
    .reduce((sum, [id]) => {
      function findSec(list) {
        for (const n of list) {
          if (n.id === id) return n.end - n.start;
          const r = findSec(n.children ?? []);
          if (r != null) return r;
        }
        return null;
      }
      const s = findSec(treeData?.tree ?? []);
      return sum + (s ?? 0);
    }, 0);

  const breadcrumb = selectedPath.filter(Boolean);

  const targetSec = selection?.target_sec;
  if (targetSec == null && selection != null) console.warn('[StructureEditor] selection.target_sec missing');
  const targetLabel = targetSec != null ? fmtDuration(targetSec) : '—';

  return (
    <div className="app-shell" style={{ height: '100vh', maxHeight: '100vh' }}>
      <TopBar
        rightContent={
          <span>선택 <b>{fmtDuration(onTotal)}</b> / 목표 {targetLabel}</span>
        }
      />

      <div style={{ flex: 1, display: 'grid', gridTemplateRows: '1fr auto', overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '60% 40%', overflow: 'hidden' }}>
          <MillerColumns
            treeData={treeData}
            selectedPath={selectedPath}
            selectionNodes={selNodes}
            onSelectAt={handleSelectAt}
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
          totalSec={3600}
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
            <button>AI로 목표 분량 채우기</button>
            <button className="btn-primary" onClick={() => transition('START_RENDER')}>렌더 →</button>
          </div>
        }
      />
    </div>
  );
}
