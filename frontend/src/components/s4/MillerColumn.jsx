import { fmtDuration } from '../../utils/format.js';

const LEVEL_LABELS = { topic: '장소·사건', task: '일', situation: '상황', scene: '장면' };

function nodeState(node, selectionNodes) {
  if (node.level !== 'scene') return 'part';
  const s = selectionNodes?.[node.id];
  if (!s) return 'default';
  if (s.state === 'off') return 'off';
  if (s.by === 'ai') return 'ai';
  return 'on';
}

export default function MillerColumn({ level, nodes, selectedId, selectionNodes, onSelect }) {
  const sec = (node) => node.end - node.start;

  return (
    <div className="miller-col">
      <div className="miller-colh">{LEVEL_LABELS[level] ?? level}</div>
      {nodes.map(node => {
        const state = nodeState(node, selectionNodes);
        const isOff = state === 'off';
        const cls   = ['miller-item', selectedId === node.id ? 'sel' : '', isOff ? 'off' : ''].filter(Boolean).join(' ');
        const dotCls = ['st', state === 'part' ? 'part' : state === 'ai' ? 'ai' : ''].filter(Boolean).join(' ');

        return (
          <div key={node.id} className={cls} onClick={() => onSelect(node)}>
            <span className={dotCls} />
            {node.title}
            {node.level === 'scene' && selectionNodes?.[node.id]?.lock === 'must_include' && (
              <span style={{ fontSize: 10, marginLeft: 2 }}>📌</span>
            )}
            <span className="d">{fmtDuration(sec(node))}</span>
          </div>
        );
      })}
    </div>
  );
}
