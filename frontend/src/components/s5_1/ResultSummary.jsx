import { fmtDuration, fmtMinSec } from '../../utils/format.js';

const TOPIC_COLORS_CSS = ['var(--topic-1)', 'var(--topic-2)', 'var(--topic-3)', 'var(--topic-4)'];

export default function ResultSummary({ result }) {
  const { duration, source_duration, target_sec, topic_ratio, requests, fixes, timing } = result;
  const diff     = duration - target_sec;
  const diffStr  = diff >= 0 ? `+${diff}초` : `${diff}초`;
  const totalTime = (timing?.analyze ?? 0) + (timing?.edit ?? 0) + (timing?.render ?? 0);

  return (
    <div className="pane" style={{ display: 'flex', flexDirection: 'column', gap: 12, overflowY: 'auto' }}>
      <div>
        <div className="sec">결과 요약</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          <div><div className="lb">원본</div><div className="num">{fmtDuration(source_duration)}</div></div>
          <div><div className="lb">결과</div><div className="num">{fmtDuration(duration)}</div></div>
          <div><div className="lb">목표 대비</div><div className="num">{diffStr}</div></div>
        </div>
      </div>

      <div>
        <div className="lb" style={{ marginBottom: 4 }}>장소·사건별 비율</div>
        {Object.entries(topic_ratio).map(([name, ratio], i) => (
          <div key={name}>
            <div className="row lb" style={{ justifyContent: 'space-between', marginTop: i > 0 ? 4 : 0 }}>
              <span>{name}</span><span>{Math.round(ratio * 100)}%</span>
            </div>
            <div className="bar">
              <i style={{ width: `${ratio * 100}%`, background: TOPIC_COLORS_CSS[i] ?? 'var(--color-accent)' }} />
            </div>
          </div>
        ))}
      </div>

      <div>
        <div className="lb" style={{ marginBottom: 4 }}>요청 반영</div>
        {requests?.map((req, i) => (
          <div key={i} className="log row" style={{ justifyContent: 'space-between' }}>
            <span>
              {req.type === 'must_include' ? '꼭 넣기' : '줄일 것'}: {req.text}
            </span>
            {req.type === 'must_include' && (
              <span style={{ color: req.ok ? 'var(--color-success)' : 'var(--color-danger)' }}>
                {req.ok ? '✔ 포함' : '✗ 미포함'}
              </span>
            )}
            {req.type === 'minimize' && (
              <span>{fmtDuration(req.before)} → {fmtDuration(req.after)}</span>
            )}
          </div>
        ))}
        {fixes && (
          <div className="log row" style={{ justifyContent: 'space-between' }}>
            <span>검수 보정</span>
            <span>컷 {fixes.word_boundary}곳 · 페이드 {fixes.fades}곳</span>
          </div>
        )}
      </div>

      <div className="card">
        <div className="lb">작업 시간</div>
        <div style={{ marginTop: 2 }}>
          분석 {fmtMinSec(timing?.analyze ?? 0)} · 구조 편집 {fmtMinSec(timing?.edit ?? 0)} · 렌더 {fmtMinSec(timing?.render ?? 0)} = <b>{fmtMinSec(totalTime)}</b>
        </div>
      </div>
    </div>
  );
}
