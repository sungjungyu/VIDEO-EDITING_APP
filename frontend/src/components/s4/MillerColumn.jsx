import { fmtDuration } from '../../utils/format.js';
import { getNodeState } from '../../logic/selection.js';

const LEVEL_LABELS = { topic: '장소·사건', task: '일', situation: '상황', scene: '장면' };

function nodeState(node, selectionNodes, treeData) {
  if (node.level === 'scene') {
    const s = selectionNodes?.[node.id];
    if (!s) return 'default';
    if (s.state === 'off') return 'off';
    if (s.by === 'ai') return 'ai';
    return 'on';
  }
  // Group node: use getNodeState for on/off/partial
  const state = getNodeState(selectionNodes ?? {}, node.id, treeData ?? { tree: [] });
  if (state === 'on') return 'on';
  if (state === 'off') return 'off';
  return 'part';
}

export default function MillerColumn({ level, nodes, selectedId, selectionNodes, treeData, onSelect, onToggle, onContextMenu }) {
  const sec = (node) => node.end - node.start;

  return (
    <div className="miller-col">
      <div className="miller-colh">{LEVEL_LABELS[level] ?? level}</div>
      {nodes.map(node => {
        const state = nodeState(node, selectionNodes, treeData);
        const isOff = state === 'off';
        const cls   = ['miller-item', selectedId === node.id ? 'sel' : '', isOff ? 'off' : ''].filter(Boolean).join(' ');
        const dotCls = ['st', state === 'part' ? 'part' : state === 'ai' ? 'ai' : ''].filter(Boolean).join(' ');
        const lock = node.level === 'scene' ? selectionNodes?.[node.id]?.lock : null;

        return (
          <div
            key={node.id}
            className={cls}
            onClick={() => onSelect(node)}
            onContextMenu={(e) => onContextMenu?.(e, node)}
          >
            <span
              className="st-btn"
              title="클릭하여 켜기/끄기"
              onClick={(e) => { e.stopPropagation(); onToggle?.(node); }}
            >
              <span className={dotCls} />
            </span>
            {node.title}
            {lock === 'must_include' && <span className="lock-tag in" title="꼭 넣기 잠금">꼭 넣기</span>}
            {lock === 'must_exclude' && <span className="lock-tag out" title="꼭 빼기 잠금">꼭 빼기</span>}
            <span className="d">{fmtDuration(sec(node))}</span>
          </div>
        );
      })}
    </div>
  );
}
