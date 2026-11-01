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

export default function MillerColumns({ treeData, selectedPath, selectionNodes, onSelectAt }) {
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

  return (
    <div className="miller" style={{ height: '100%' }}>
      {columns.map(({ level, nodes }, i) => (
        <MillerColumn
          key={level}
          level={level}
          nodes={nodes}
          selectedId={selectedPath[i]}
          selectionNodes={selectionNodes}
          onSelect={(node) => onSelectAt(i, node)}
        />
      ))}
    </div>
  );
}
