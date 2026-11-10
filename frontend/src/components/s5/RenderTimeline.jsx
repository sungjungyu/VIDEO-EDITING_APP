const TOPIC_COLORS = { t1: '--topic-1', t2: '--topic-1', t3: '--topic-2', t4: '--topic-3', t5: '--topic-4' };

export default function RenderTimeline({ segments, currentLabel, renderPercent }) {
  if (!segments) return null;

  const filled = segments.filter(s => (s.pct_end / 100) * 100 <= renderPercent);

  return (
    <div style={{ width: 'min(580px, 100%)' }}>
      <div className="row lb" style={{ justifyContent: 'space-between' }}>
        <span>결과 영상 타임라인 (선택한 구간 {segments.length}개)</span>
        <span>10:04 / 목표 10:00</span>
      </div>
      <div style={{ display: 'flex', height: 34, borderRadius: 6, overflow: 'hidden', marginTop: 4, border: '1px solid var(--color-border)', background: 'var(--color-surface-2)' }}>
        {segments.map((seg, i) => {
          const w    = seg.pct_end - seg.pct_start;
          const done = seg.pct_end <= renderPercent;
          const now  = !done && seg.pct_start <= renderPercent;
          const color = done
            ? `var(${TOPIC_COLORS[seg.topic_id] ?? '--topic-1'})`
            : now
              ? 'var(--color-text-muted)'
              : 'transparent';
          return (
            <div
              key={i}
              className={`seg${now ? ' now' : ''}`}
              style={{ width: `${w}%`, background: color }}
            />
          );
        })}
      </div>
      {currentLabel && (
        <div className="row lb legend" style={{ marginTop: 5, justifyContent: 'flex-end' }}>
          지금: {currentLabel}
        </div>
      )}
    </div>
  );
}
