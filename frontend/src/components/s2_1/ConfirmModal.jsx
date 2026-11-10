import { useState } from 'react';
import Chip from '../common/Chip.jsx';
import RuleBox from './RuleBox.jsx';
import AmbiguityRow from './AmbiguityRow.jsx';

export default function ConfirmModal({ rules, onBack, onConfirm }) {
  const [local, setLocal] = useState(() => JSON.parse(JSON.stringify(rules ?? {})));

  if (!local) return null;

  const updateAmb = (updated) => {
    setLocal(prev => ({
      ...prev,
      ambiguities: prev.ambiguities.map(a => a.id === updated.id ? updated : a),
    }));
  };

  const targetSecVal = local.target_sec;
  if (targetSecVal == null) console.warn('[ConfirmModal] judgment_rules.target_sec missing');
  const totalMin = targetSecVal != null ? Math.floor(targetSecVal / 60) : null;
  const totalSec = targetSecVal != null ? targetSecVal % 60 : null;

  return (
    <>
      <div className="modal-dim" />
      <div className="modal">
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--color-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 600, fontSize: 15 }}>이렇게 이해했어요</span>
          <span className="lb">칩을 눌러 고치거나 ×로 지울 수 있어요</span>
        </div>

        <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="row">
            <span className="lb" style={{ width: 64 }}>영상 성격</span>
            <Chip>{local.purpose}</Chip>
            <span className="lb" style={{ marginLeft: 'auto' }}>
              목표 {totalMin != null ? `${totalMin}:${String(totalSec).padStart(2,'0')}` : '—'}
            </span>
          </div>

          <RuleBox
            title="꼭 지킬 것"
            badgeVariant="danger"
            badgeLabel="코드가 반드시 지킴"
            items={[
              ...(local.must_include ?? []).map(x => `넣기: ${x}`),
              ...(local.must_exclude ?? []).map(x => `빼기: ${x}`),
            ]}
            onRemove={() => {}}
            onAdd={() => {}}
          />

          <RuleBox
            title="참고할 것"
            badgeVariant="accent"
            badgeLabel="AI가 고를 때 참고"
            items={[
              ...(local.focus ?? []).map(x => `강조: ${x}`),
              ...(local.minimize ?? []).map(x => `줄일 것: ${x}`),
            ]}
            onRemove={() => {}}
            onAdd={() => {}}
          />

          <div className="row">
            <span className="lb" style={{ width: 64 }}>등장인물</span>
            {(local.characters ?? []).map((c, i) => (
              <Chip key={i}>{c.label} = {c.name} ×</Chip>
            ))}
            <Chip variant="add">+ 추가</Chip>
          </div>

          {local.ambiguities?.length > 0 && (
            <div className="warn">
              <b>확인이 필요해요 ({local.ambiguities.length})</b>
              {local.ambiguities.map((amb, i) => (
                <div key={amb.id}>
                  <div style={{ marginTop: 6 }}>{i + 1}. {amb.message}</div>
                  <AmbiguityRow item={amb} onChange={updateAmb} />
                </div>
              ))}
            </div>
          )}

          <details>
            <summary>AI가 만든 판단 규칙 보기 (JSON)</summary>
            <pre style={{ fontSize: 10, background: 'var(--color-surface-2)', borderRadius: 6, padding: 8, margin: '6px 0 0', overflow: 'auto', maxHeight: 120 }}>
              {JSON.stringify(local, null, 2)}
            </pre>
          </details>
        </div>

        <div className="bottom-bar">
          <button onClick={onBack}>← 프롬프트 다시 쓰기</button>
          <button className="btn-primary" onClick={() => onConfirm(local)}>확정하고 분석 시작 →</button>
        </div>
      </div>
    </>
  );
}
