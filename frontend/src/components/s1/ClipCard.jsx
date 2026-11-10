import { fmtDuration, fmtAspect } from '../../utils/format.js';

export default function ClipCard({ clip, onRemove }) {
  const aspect = clip.width && clip.height ? fmtAspect(clip.width, clip.height) : '';
  const shotAt = clip.shot_at
    ? `${new Date(clip.shot_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })} 촬영`
    : '촬영 시각 없음';

  return (
    <div className="clip-card">
      <div className="clip-thumb">
        <span className="num-badge">{clip.order}</span>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {clip.file}
        </div>
        <div className="lb">
          {fmtDuration(clip.duration)} · {shotAt} · {clip.width}×{clip.height} · {aspect}
        </div>
      </div>
      <span
        className="lb"
        style={{ marginLeft: 'auto', cursor: 'pointer', flexShrink: 0 }}
        onClick={() => onRemove?.(clip.id)}
      >
        ×
      </span>
    </div>
  );
}
