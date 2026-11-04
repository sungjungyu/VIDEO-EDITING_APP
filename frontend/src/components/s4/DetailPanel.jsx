import { fmtGlobal } from '../../utils/format.js';

export default function DetailPanel({ scene, sentences, selectionNodes }) {
  if (!scene) {
    return (
      <div className="pane" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-subtle)' }}>
        왼쪽에서 항목을 선택하세요
      </div>
    );
  }

  const sceneSentences = (scene.sentence_ids ?? [])
    .map(id => sentences?.find(s => s.id === id))
    .filter(Boolean);

  const selState = selectionNodes?.[scene.id];

  return (
    <div className="pane" style={{ display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="sec" style={{ margin: 0 }}>{scene.title}</div>
        <button style={{ height: 28, fontSize: 11 }}>자막 대상 화자 ⚙</button>
      </div>

      {selState?.lock && (
        <div className="card" style={{
          background: selState.lock === 'must_include' ? 'var(--color-success-bg)' : 'var(--color-danger-bg)',
          color: selState.lock === 'must_include' ? 'var(--color-success)' : 'var(--color-danger)',
          fontSize: 12,
          marginBottom: 4,
        }}>
          {selState.lock === 'must_include' ? '📌 꼭 넣기 잠금' : '🚫 꼭 빼기 잠금'}
        </div>
      )}

      <div className="video" style={{ height: 150 }}>
        <div className="floor" />
        <div className="p1" style={{ left: 90, top: 42, width: 40, height: 40 }} />
        <div className="p2" style={{ left: 170, top: 48, width: 34, height: 34 }} />
        {sceneSentences[0] && (
          <span className="sub" style={{ bottom: 12, fontSize: 12 }}>{sceneSentences[0].text}</span>
        )}
      </div>

      <div className="lb">
        {scene.clip_id} {fmtGlobal(scene.start)}~{fmtGlobal(scene.end)}
        {scene.place && ` · ${scene.place}`}
        {scene.activity && ` · ${scene.activity}`}
        {scene.people?.length > 0 && ` · ${scene.people.join(', ')}`}
      </div>

      {sceneSentences.length > 0 && (
        <div>
          {sceneSentences.map(s => (
            <div key={s.id} className="log">
              <span className="log-time">{fmtGlobal(s.start)}</span>
              <b>{s.speaker}</b> {s.text}
            </div>
          ))}
        </div>
      )}

      {selState?.by === 'ai' && selState?.reason && (
        <div className="card">
          <div className="lb">AI 선택 이유</div>
          <div style={{ fontSize: 12, marginTop: 2 }}>{selState.reason}</div>
        </div>
      )}
    </div>
  );
}
