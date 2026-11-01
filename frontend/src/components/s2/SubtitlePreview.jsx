export default function SubtitlePreview({ rules }) {
  if (!rules) return null;
  const { subtitle, output } = rules;
  const is916 = output?.aspect === '9:16';

  const previewW = is916 ? 100 : 178;
  const previewH = is916 ? 178 : 100;

  return (
    <div
      className="video"
      style={{ width: previewW, height: previewH, flexShrink: 0 }}
    >
      <div className="floor" />
      <div className="p1" style={{ left: '30%', top: '28%', width: 28, height: 28 }} />
      <div className="p2" style={{ left: '55%', top: '32%', width: 24, height: 24 }} />
      {subtitle?.enabled && (
        <span
          className="sub"
          style={{
            bottom: is916 ? 48 : 12,
            fontSize: 11,
            ...(subtitle.outline?.enabled
              ? { textShadow: `0 0 2px ${subtitle.outline.color}, 0 0 2px ${subtitle.outline.color}` }
              : {}),
          }}
        >
          칼로리 보소
        </span>
      )}
    </div>
  );
}
