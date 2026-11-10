import Badge from '../common/Badge.jsx';
import { fmtDuration } from '../../utils/format.js';

const TYPE_BADGE = {
  boundary: { variant: 'accent',  label: '장면 경계' },
  merge:    { variant: 'warning', label: '합침'      },
  person:   { variant: 'accent',  label: '인물'      },
  stt:      { variant: 'success', label: '받아쓰기'  },
};

export default function AnalysisLogList({ logs, stats }) {
  return (
    <div>
      {logs?.map((log, i) => (
        <div key={i} className="log">
          <span className="log-time">{log.t != null ? fmtDuration(log.t) : '—'}</span>
          <Badge variant={TYPE_BADGE[log.type]?.variant ?? 'accent'}>
            {TYPE_BADGE[log.type]?.label ?? log.type}
          </Badge>
          {' '}{log.text}
        </div>
      ))}
      {stats && (
        <div className="lb" style={{ marginTop: 6 }}>
          총 {stats.scenes}개 장면 · {stats.sentences}개 문장 · 화자 {stats.speakers}명 · API ₩{stats.cost_krw}
        </div>
      )}
      <div className="lb" style={{ marginTop: 4 }}>
        시각은 전체 타임라인 기준 · scene_analyzer 실제 처리 기록만 표시
      </div>
    </div>
  );
}
