import { useEffect, useRef, useState } from 'react';
import MillerColumn from './MillerColumn.jsx';

const LEVELS = ['topic', 'task', 'situation', 'scene'];

function childrenOf(nodes, parentId) {
  function find(list) {
    for (const n of list) {
      if (n.id === parentId) return n.children ?? [];
      const found = find(n.children ?? []);
      if (found) return found;
    }
    return null;
  }
  return find(nodes) ?? [];
}

export default function MillerColumns({ treeData, selectedPath, selectionNodes, onSelectAt, onToggle, onLock }) {
  const [ctxMenu, setCtxMenu] = useState(null);
  const ctxRef = useRef(null);

  if (!treeData) return null;
  const roots = treeData.tree ?? [];

  const columns = LEVELS.map((level, i) => {
    let nodes;
    if (i === 0) {
      nodes = roots;
    } else {
      const parentId = selectedPath[i - 1];
      nodes = parentId ? childrenOf(roots, parentId) : [];
    }
    return { level, nodes };
  });

  // Close context menu when clicking outside
  useEffect(() => {
    const handleMouseDown = (e) => {
      if (ctxRef.current && !ctxRef.current.contains(e.target)) {
        setCtxMenu(null);
      }
    };
    window.addEventListener('mousedown', handleMouseDown);
    return () => window.removeEventListener('mousedown', handleMouseDown);
  }, []);

  const handleContextMenu = (e, nodeId) => {
    e.preventDefault();
    e.stopPropagation();
    const x = Math.min(e.clientX, window.innerWidth - 148);
    const y = Math.min(e.clientY, window.innerHeight - 120);
    setCtxMenu({ nodeId, x, y });
  };

  const handleKeyDown = (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    // Find rightmost non-null column index
    let colIdx = 0;
    for (let i = 3; i >= 0; i--) {
      if (selectedPath[i] != null) { colIdx = i; break; }
    }

    const curNodes = columns[colIdx]?.nodes ?? [];
    const curId = selectedPath[colIdx];
    const curIdx = curNodes.findIndex(n => n.id === curId);

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        if (curIdx < curNodes.length - 1) {
          onSelectAt?.(colIdx, curNodes[curIdx + 1]);
        }
        break;

      case 'ArrowUp':
        e.preventDefault();
        if (curIdx > 0) {
          onSelectAt?.(colIdx, curNodes[curIdx - 1]);
        }
        break;

      case 'ArrowRight': {
        e.preventDefault();
        const nextCol = colIdx + 1;
        if (nextCol < 4 && columns[nextCol]?.nodes.length > 0) {
          const alreadySelected = columns[nextCol].nodes.find(n => n.id === selectedPath[nextCol]);
          onSelectAt?.(nextCol, alreadySelected ?? columns[nextCol].nodes[0]);
        }
        break;
      }

      case 'ArrowLeft': {
        e.preventDefault();
        const prevCol = colIdx - 1;
        if (prevCol >= 0 && selectedPath[prevCol] != null) {
          const parentNode = columns[prevCol]?.nodes.find(n => n.id === selectedPath[prevCol]);
          if (parentNode) onSelectAt?.(prevCol, parentNode);
        }
        break;
      }

      case ' ':
        e.preventDefault();
        if (curId != null) onToggle?.(curId);
        break;

      case 'Escape':
        setCtxMenu(null);
        break;

      default:
        break;
    }
  };

  return (
    <div
      className="miller"
      style={{ height: '100%' }}
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      {columns.map(({ level, nodes }, i) => (
        <MillerColumn
          key={level}
          level={level}
          nodes={nodes}
          selectedId={selectedPath[i]}
          selectionNodes={selectionNodes}
          treeData={treeData}
          onSelect={(node) => onSelectAt(i, node)}
          onToggle={(node) => onToggle?.(node.id)}
          onContextMenu={(e, node) => handleContextMenu(e, node.id)}
        />
      ))}

      {ctxMenu && (
        <div
          ref={ctxRef}
          className="ctx-menu"
          style={{ position: 'fixed', left: ctxMenu.x, top: ctxMenu.y, zIndex: 200 }}
        >
          <div className="ctx-item" onClick={() => { onToggle?.(ctxMenu.nodeId); setCtxMenu(null); }}>
            ◉ 켜기 / 끄기 (Space)
          </div>
          <div className="ctx-item" style={{ height: 1, padding: 0, background: 'var(--color-border)', margin: '2px 0' }} />
          <div className="ctx-item" onClick={() => { onLock?.(ctxMenu.nodeId, 'must_include'); setCtxMenu(null); }}>
            📌 꼭 넣기
          </div>
          <div className="ctx-item" onClick={() => { onLock?.(ctxMenu.nodeId, 'must_exclude'); setCtxMenu(null); }}>
            🚫 꼭 빼기
          </div>
          <div className="ctx-item" onClick={() => { onLock?.(ctxMenu.nodeId, null); setCtxMenu(null); }}>
            🔓 잠금 해제
          </div>
        </div>
      )}
    </div>
  );
}
