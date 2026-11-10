import { useState } from 'react';
import Chip from '../common/Chip.jsx';
import SubtitlePreview from './SubtitlePreview.jsx';

const PRESETS = ['기본', '강조', '깔끔'];
// auto: 서버 auto_aspect (클립 방향으로 정함, 기본값)
const ASPECTS = [['auto', '자동'], ['16:9', '16:9'], ['9:16', '9:16'], ['1:1', '1:1']];
const FITS    = ['가운데 자르기', '여백 채우기'];
const POSITIONS = ['아래', '위'];

export default function StylePanel({ rules, onChange }) {
  const [preset, setPreset] = useState('기본');

  if (!rules) return <div className="pane" style={{ flex: 1 }}><div className="lb">로딩 중…</div></div>;

  const { subtitle, output } = rules;

  const set = (path, value) => {
    const updated = JSON.parse(JSON.stringify(rules));
    const parts = path.split('.');
    let obj = updated;
    parts.slice(0, -1).forEach(p => { obj = obj[p]; });
    obj[parts[parts.length - 1]] = value;
    onChange?.(updated);
  };

  return (
    <div className="pane" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <div className="sec">스타일</div>
        <div className="row">
          {PRESETS.map(p => (
            <Chip key={p} variant={preset === p ? 'on' : 'default'} onClick={() => setPreset(p)}>{p}</Chip>
          ))}
          <span className="lb">프리셋은 시작값</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div>
          <div className="lb">화면 비율</div>
          <div className="row">
            {ASPECTS.map(([value, label]) => (
              <Chip key={value} variant={(output?.aspect ?? 'auto') === value ? 'on' : 'default'} onClick={() => set('output.aspect', value)}>{label}</Chip>
            ))}
          </div>
        </div>
        <div>
          <div className="lb">비율 다른 영상</div>
          <div className="row">
            {FITS.map(f => (
              <Chip key={f} variant={(output?.fit === 'crop' ? '가운데 자르기' : '여백 채우기') === f ? 'on' : 'default'} onClick={() => set('output.fit', f === '가운데 자르기' ? 'crop' : 'letterbox')}>{f}</Chip>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr', gap: 12, alignItems: 'start' }}>
        <SubtitlePreview rules={rules} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          <div className="row">
            <span className="lb" style={{ width: 44 }}>자막</span>
            <Chip variant={subtitle?.enabled ? 'on' : 'default'} onClick={() => set('subtitle.enabled', !subtitle?.enabled)}>켜기</Chip>
            <Chip variant={subtitle?.speakers_only ? 'on' : 'default'} onClick={() => set('subtitle.speakers_only', !subtitle?.speakers_only)}>등장인물 말만</Chip>
          </div>
          <div className="lb" style={{ marginLeft: 50 }}>누구 말인지는 ④ 구조 편집에서 골라요</div>
          <div className="row">
            <span className="lb" style={{ width: 44 }}>글꼴</span>
            <input className="fld" defaultValue={subtitle?.font} style={{ width: 100 }} readOnly />
            <input className="fld" defaultValue={subtitle?.size} style={{ width: 40 }} readOnly />
            <span className="lb">pt</span>
          </div>
          <div className="row">
            <span className="lb" style={{ width: 44 }}>색</span>
            <span style={{ width: 16, height: 16, borderRadius: 4, border: '1px solid var(--color-border-strong)', background: subtitle?.color ?? '#fff', flexShrink: 0 }} />
            <input className="fld" defaultValue={subtitle?.color} style={{ width: 80 }} readOnly />
          </div>
          <div className="row">
            <span className="lb" style={{ width: 44 }}>외곽선</span>
            <Chip variant={subtitle?.outline?.enabled ? 'on' : 'default'} onClick={() => set('subtitle.outline.enabled', !subtitle?.outline?.enabled)}>켜기</Chip>
            <input className="fld" defaultValue={subtitle?.outline?.width} style={{ width: 32 }} readOnly />
            <span style={{ width: 16, height: 16, borderRadius: 4, background: subtitle?.outline?.color ?? '#000', flexShrink: 0 }} />
          </div>
          <div className="row">
            <span className="lb" style={{ width: 44 }}>위치</span>
            {POSITIONS.map(p => (
              <Chip key={p} variant={subtitle?.position === (p === '아래' ? 'bottom' : 'top') ? 'on' : 'default'} onClick={() => set('subtitle.position', p === '아래' ? 'bottom' : 'top')}>{p}</Chip>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div>
          <div className="lb">인트로 (선택)</div>
          <div className="card lb" style={{ textAlign: 'center', borderStyle: 'dashed', cursor: 'pointer' }}>+ 영상 올리기</div>
        </div>
        <div>
          <div className="lb">아웃트로 (선택)</div>
          <div className="card lb" style={{ textAlign: 'center', borderStyle: 'dashed', cursor: 'pointer' }}>
            {rules.outro?.file ?? '+ 영상 올리기'}
          </div>
        </div>
      </div>

      <label className="lb">
        <input type="checkbox" defaultChecked={rules.save_profile} style={{ marginRight: 6 }} />
        이 스타일을 내 프로필로 저장
      </label>
    </div>
  );
}
