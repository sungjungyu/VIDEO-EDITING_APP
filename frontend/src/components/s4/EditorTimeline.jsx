import { fmtDuration } from '../../utils/format.js';

const TOPIC_COLORS = ['--topic-1', '--topic-2', '--topic-3', '--topic-4', '--topic-1'];

export default function EditorTimeline({ treeData, selectionNodes, selection, selectedScene, totalSec }) {
  if (!treeData) return null;

  const topics = treeData.tree ?? [];
  const allSec = totalSec ?? topics.reduce((m, t) => Math.max(m, t.end), 0);

  function collectScenes(node, topicIdx, acc) {
    if (node.level === 'scene') {
      acc.push({ ...node, topicIdx });
    } else {
      (node.children ?? []).forEach(c => collectScenes(c, topicIdx, acc));
    }
  }

  const allScenes = [];
  topics.forEach((t, i) => collectScenes(t, i, allScenes));

  const selectedTotal = allScenes
    .filter(sc => selectionNodes?.[sc.id]?.state === 'on')
    .reduce((s, sc) => s + (sc.end - sc.start), 0);

  const targetSec = selection?.target_sec;
  if (targetSec == null) console.warn('[EditorTimeline] selection.target_sec missing');
  const targetLabel = targetSec != null ? fmtDuration(targetSec) : '—';

  return (
    <div style={{ borderTop: '1px solid var(--color-border)', padding: '10px 16px' }}>
      <div className="row lb" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
        <div className="row" style={{ gap: 8 }}>
          {topics.map((t, i) => (
            <span key={t.id} className="legend">
              <i style={{ background: `var(${TOPIC_COLORS[i] ?? '--topic-1'})` }} />
              {t.title}
            </span>
          ))}
          <span className="legend"><i style={{ background: 'var(--color-off)' }} />꺼짐</span>
        </div>
        <span>선택 합계 {fmtDuration(selectedTotal)} / 목표 {targetLabel}</span>
      </div>

      <div style={{ display: 'flex', height: 30, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--color-border)', background: 'var(--color-off)' }}>
        {allScenes.map(sc => {
          const w    = ((sc.end - sc.start) / allSec) * 100;
          const sel  = selectionNodes?.[sc.id];
          const on   = sel?.state === 'on';
          const isSelected = sc.id === selectedScene?.id;
          const color = on ? `var(${TOPIC_COLORS[sc.topicIdx] ?? '--topic-1'})` : 'transparent';
          return (
            <div
              key={sc.id}
              className="seg"
              style={{
                width: `${w}%`,
                background: color,
                outline: isSelected ? '2px solid var(--color-text)' : undefined,
                outlineOffset: isSelected ? -2 : undefined,
              }}
              title={sc.title}
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
