import { fmtDuration } from '../../utils/format.js';

const TOPIC_COLORS = { t2: '--topic-1', t3: '--topic-2', t4: '--topic-3', t5: '--topic-4' };

export default function ResultPlayer({ result, selectedSeg, onSelectSeg }) {
  const { segments, duration } = result;

  const playPercent = selectedSeg
    ? (selectedSeg.pct_start / 100) * duration
    : 0;

  return (
    <div className="pane" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
      {/* 비율 9:16 플레이어 */}
      <div className="video" style={{ width: 176, height: 313 }}>
        <div className="floor" />
        <div className="p1" style={{ left: 46, top: 100, width: 42, height: 42 }} />
        <div className="p2" style={{ left: 100, top: 108, width: 36, height: 36 }} />
        {selectedSeg && (
          <span className="sub" style={{ bottom: 48, fontSize: 12 }}>
            {selectedSeg.scene_title}
          </span>
        )}
        <div style={{ position: 'absolute', left: 8, right: 8, bottom: 10, display: 'flex', alignItems: 'center', gap: 6, color: 'var(--color-text)', fontSize: 10 }}>
          <span>▶</span>
          <div style={{ flex: 1, height: 3, background: 'var(--color-border-strong)', borderRadius: 2 }}>
            <div style={{ width: `${selectedSeg?.pct_start ?? 0}%`, height: '100%', background: 'var(--color-text)' }} />
          </div>
          <span>{fmtDuration(playPercent)}</span>
        </div>
      </div>

      <div style={{ width: '100%' }}>
        <div className="row lb" style={{ justifyContent: 'space-between' }}>
          <span>구간 {segments.length}개 · 누르면 그 위치로 이동</span>
          <span>{fmtDuration(playPercent)} / {fmtDuration(duration)}</span>
        </div>
        <div style={{ display: 'flex', height: 28, borderRadius: 6, overflow: 'hidden', marginTop: 4, border: '1px solid var(--color-border)', position: 'relative', cursor: 'pointer' }}>
          {segments.map(seg => {
            const w   = seg.pct_end - seg.pct_start;
            const sel = seg.id === selectedSeg?.id;
            return (
              <div
                key={seg.id}
                className="seg"
                style={{
                  width: `${w}%`,
                  background: `var(${TOPIC_COLORS[seg.topic_id] ?? '--topic-1'})`,
                  outline: sel ? '2px solid var(--color-text)' : undefined,
                  outlineOffset: sel ? -2 : undefined,
                }}
                onClick={() => onSelectSeg(seg)}
                title={seg.scene_title}
              />
            );
          })}
          <div style={{ position: 'absolute', left: `${selectedSeg?.pct_start ?? 0}%`, top: -2, bottom: -2, width: 2, background: 'var(--color-text)' }} />
        </div>

        {selectedSeg && (
          <div className="card" style={{ marginTop: 8 }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <b>{selectedSeg.scene_title}</b>
              <span className="lb">원본 {selectedSeg.original_clip} {fmtDuration(selectedSeg.original_start)}~{fmtDuration(selectedSeg.original_end)}</span>
            </div>
            {selectedSeg.ai_reason && (
              <div className="lb" style={{ marginTop: 3, lineHeight: 1.5 }}>AI가 남긴 이유: {selectedSeg.ai_reason}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
