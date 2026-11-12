import { fmtDuration } from '../../utils/format.js';

// 색은 L2(행동 흐름) 순서대로 4색을 돌려 쓴다 (L1이 하나뿐인 영상도 구간이 구분되게)
const TOPIC_COLORS = ['--topic-1', '--topic-2', '--topic-3', '--topic-4'];
const colorOf = (i) => `var(${TOPIC_COLORS[i % TOPIC_COLORS.length]})`;

// info: 왼쪽 위 (선택 경로·안내), actions: 오른쪽 위 선택 합계 옆 버튼 (S4 하단 바를 없애고 여기로 옮겼다)
export default function EditorTimeline({ treeData, selectionNodes, selection, selectedScene, totalSec, onSceneClick, info, actions }) {
  if (!treeData) return null;

  const topics = treeData.tree ?? [];
  const allSec = totalSec ?? topics.reduce((m, t) => Math.max(m, t.end), 0);

  function collectScenes(node, groupIdx, acc) {
    if (node.level === 'scene') {
      acc.push({ ...node, groupIdx });
    } else {
      (node.children ?? []).forEach(c => collectScenes(c, groupIdx, acc));
    }
  }

  // L2 묶음: L1 아래 자식들을 순서대로 이어 붙인 목록 (L1에 자식이 없으면 L1 자신)
  const groups = topics.flatMap(t => (t.children?.length ? t.children : [t]));
  const allScenes = [];
  groups.forEach((g, i) => collectScenes(g, i, allScenes));

  const selectedTotal = allScenes
    .filter(sc => selectionNodes?.[sc.id]?.state === 'on')
    .reduce((s, sc) => s + (sc.end - sc.start), 0);

  const targetSec = selection?.target_sec;
  if (targetSec == null) console.warn('[EditorTimeline] selection.target_sec missing');
  const targetLabel = targetSec != null ? fmtDuration(targetSec) : '—';

  const ratio = targetSec != null && selectedTotal > 0
    ? Math.abs(selectedTotal - targetSec) / targetSec
    : 0;
  const totalColor = ratio > 0.1 ? 'var(--color-warning)' : undefined;

  return (
    <div style={{ borderTop: '1px solid var(--color-border)', padding: '8px 16px 10px' }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6, flexWrap: 'nowrap' }}>
        <div style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{info}</div>
        <div className="row" style={{ flexWrap: 'nowrap', flexShrink: 0 }}>
          <span className="lb" style={{ color: totalColor, whiteSpace: 'nowrap' }}>
            선택 합계 {fmtDuration(selectedTotal)} / 목표 {targetLabel}
          </span>
          {actions}
        </div>
      </div>
      <div className="row lb" style={{ marginBottom: 4 }}>
        <div className="row" style={{ gap: 8 }}>
          {groups.map((g, i) => (
            <span key={g.id} className="legend">
              <i style={{ background: colorOf(i) }} />
              {g.title}
            </span>
          ))}
          <span className="legend"><i style={{ background: 'var(--color-off)' }} />꺼짐</span>
        </div>
      </div>

      <div style={{ display: 'flex', height: 30, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--color-border)', background: 'var(--color-off)' }}>
        {allScenes.map(sc => {
          const w    = ((sc.end - sc.start) / allSec) * 100;
          const sel  = selectionNodes?.[sc.id];
          const on   = sel?.state === 'on';
          const isSelected = sc.id === selectedScene?.id;
          const color = on ? colorOf(sc.groupIdx) : 'transparent';
          return (
            <div
              key={sc.id}
              className="seg"
              style={{
                width: `${w}%`,
                background: color,
                outline: isSelected ? '2px solid var(--color-text)' : undefined,
                outlineOffset: isSelected ? -2 : undefined,
                cursor: on ? 'pointer' : undefined,
              }}
              title={sc.title}
              onClick={() => onSceneClick?.(sc.id)}
            />
          );
        })}
      </div>

      <div className="row lb" style={{ justifyContent: 'space-between', marginTop: 4 }}>
        <span>00:00</span>
        <span>원본 {fmtDuration(allSec)} 기준 · 회색 = 꺼진 구간</span>
        <span>{fmtDuration(allSec)}</span>
      </div>
    </div>
  );
}
