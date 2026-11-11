import { useEffect, useRef, useState } from 'react';
import { fmtGlobal, fmtDuration } from '../../utils/format.js';
import { USE_MOCK, clipProxyUrl } from '../../api/index.js';

const LEVEL_NAMES = { topic: '장소·사건', task: '일', situation: '상황', scene: '장면' };
const PROXY_RETRIES = 40;        // 3초 × 40 = 2분까지 proxy가 만들어지기를 기다린다
const PROXY_RETRY_MS = 3000;

function scenesOf(node) {
  if (!node) return [];
  if (node.level === 'scene') return [node];
  return (node.children ?? []).flatMap(scenesOf);
}

/** 재생 구간: 노드의 첫 장면 클립에서, 같은 클립 안의 마지막 장면 끝까지 (전체 타임라인 초 + 클립 안 초 변환값) */
export function playRange(node) {
  const scenes = scenesOf(node);
  const first = scenes[0];
  if (!first || first.clip_start == null) return null;
  const sameClip = scenes.filter(s => s.clip_id === first.clip_id);
  const offset = first.start - first.clip_start;            // 전체 타임라인 초 = 클립 안 초 + offset
  return { clipId: first.clip_id, offset, start: first.start, end: sameClip[sameClip.length - 1].end };
}

/** 클립 proxy 영상을 [from, to] (클립 안 초) 구간만 재생한다. 끝에 닿으면 멈추고, 다시 누르면 구간 처음부터 */
function ScenePlayer({ src, from, to, seekTo, onTime, onError }) {
  const ref = useRef(null);

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const go = () => { v.currentTime = from; v.play().catch(() => {}); };
    if (v.readyState >= 1) go(); else v.addEventListener('loadedmetadata', go, { once: true });
    return () => v.removeEventListener('loadedmetadata', go);
  }, [src, from, to]);

  useEffect(() => {
    const v = ref.current;
    if (!v || seekTo == null) return;
    v.currentTime = seekTo.t;
    v.play().catch(() => {});
  }, [seekTo]);

  return (
    <video
      ref={ref}
      src={src}
      controls
      playsInline
      preload="metadata"
      onError={onError}
      onPlay={(e) => { if (e.currentTarget.currentTime >= to - 0.05 || e.currentTarget.currentTime < from - 0.5) e.currentTarget.currentTime = from; }}
      onTimeUpdate={(e) => {
        const t = e.currentTarget.currentTime;
        if (t >= to) e.currentTarget.pause();
        onTime(t);
      }}
      style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block', background: 'var(--color-video)' }}
    />
  );
}

function Placeholder({ caption }) {
  return (
    <div className="video" style={{ height: 150 }}>
      <div className="floor" />
      <div className="p1" style={{ left: 90, top: 42, width: 40, height: 40 }} />
      <div className="p2" style={{ left: 170, top: 48, width: 34, height: 34 }} />
      {caption && <span className="sub" style={{ bottom: 12, fontSize: 12 }}>{caption}</span>}
    </div>
  );
}

export default function DetailPanel({ scene, node, sentences, selectionNodes }) {
  // mock: 장면(L4)만 자리표시 그림으로 / 실제: 고른 노드(L1~L4) 구간의 영상
  const target = USE_MOCK ? scene : (node ?? scene);
  const range = !USE_MOCK && target ? playRange(target) : null;
  const [now, setNow] = useState(null);          // 재생 위치 (전체 타임라인 초)
  const [seekTo, setSeekTo] = useState(null);    // 대사를 눌러 옮길 위치 (클립 안 초)
  const [videoFailed, setVideoFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);      // proxy가 아직 없으면(업로드 직후 만드는 중) 3초마다 다시 시도
  const retryTimer = useRef(null);
  const listRef = useRef(null);

  useEffect(() => { setNow(null); setVideoFailed(false); }, [target?.id]);
  useEffect(() => () => clearTimeout(retryTimer.current), []);
  const onVideoError = () => {
    if (attempt >= PROXY_RETRIES) { setVideoFailed(true); return; }
    clearTimeout(retryTimer.current);
    retryTimer.current = setTimeout(() => setAttempt(a => a + 1), PROXY_RETRY_MS);
  };
  // 재생 중인 대사가 목록에서 보이게
  useEffect(() => {
    listRef.current?.querySelector('[data-current="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [now == null ? null : Math.floor(now)]);

  if (!target) {
    return (
      <div className="pane" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-subtle)' }}>
        왼쪽에서 항목을 선택하세요
      </div>
    );
  }

  const lines = USE_MOCK || target.level === 'scene'
    ? (target.sentence_ids ?? []).map(id => sentences?.find(s => s.id === id)).filter(Boolean)
    : (sentences ?? []).filter(s => s.start >= target.start && s.start < target.end);
  const currentId = now == null ? null
    : [...lines].reverse().find(s => s.start <= now + 0.05 && now < (s.end ?? s.start) + 1.0)?.id ?? null;
  const selState = target.level === 'scene' ? selectionNodes?.[target.id] : null;

  return (
    <div className="pane" style={{ display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="sec" style={{ margin: 0 }}>
          {target.level !== 'scene' && <span className="lb" style={{ marginRight: 6 }}>{LEVEL_NAMES[target.level]}</span>}
          {target.title}
        </div>
        {USE_MOCK && <button style={{ height: 28, fontSize: 12 }}>자막 대상 화자</button>}
      </div>

      {selState?.lock && (
        <div className="card" style={{
          background: selState.lock === 'must_include' ? 'var(--color-success-bg)' : 'var(--color-danger-bg)',
          color: selState.lock === 'must_include' ? 'var(--color-success)' : 'var(--color-danger)',
          fontSize: 12,
          marginBottom: 4,
        }}>
          {selState.lock === 'must_include' ? '꼭 넣기로 잠금' : '꼭 빼기로 잠금'}
        </div>
      )}

      {range && !videoFailed ? (
        <div className="video" style={{ height: 220 }}>
          <ScenePlayer
            key={attempt}
            src={clipProxyUrl(range.clipId) + (attempt ? `?try=${attempt}` : '')}
            from={range.start - range.offset}
            to={range.end - range.offset}
            seekTo={seekTo}
            onTime={(t) => setNow(t + range.offset)}
            onError={onVideoError}
          />
        </div>
      ) : null}
      {range && !videoFailed ? (
        attempt > 0 && now == null && <div className="lb">미리보기 영상을 만드는 중… (영상을 올린 직후에는 1~2분 걸려요)</div>
      ) : (
        <Placeholder caption={videoFailed ? '미리보기 영상을 불러오지 못했어요' : lines[0]?.text} />
      )}

      <div className="lb">
        {target.clip_id ?? range?.clipId} {fmtGlobal(target.start)}~{fmtGlobal(target.end)}
        {target.level !== 'scene' && ` (${fmtDuration(target.end - target.start)}`
          + (range && range.end < target.end ? `, 영상은 같은 클립 ${fmtDuration(range.end - range.start)}까지` : '') + ')'}
        {target.place && ` · ${target.place}`}
        {target.activity && ` · ${target.activity}`}
        {target.people?.length > 0 && ` · ${target.people.join(', ')}`}
      </div>

      {lines.length > 0 && (
        <div ref={listRef}>
          {lines.map(s => {
            const current = s.id === currentId;
            const canSeek = range && s.start >= range.start && s.start < range.end;
            return (
              <div
                key={s.id}
                className="log"
                data-current={current ? 'true' : undefined}
                onClick={canSeek ? () => setSeekTo({ t: s.start - range.offset }) : undefined}
                style={{
                  cursor: canSeek ? 'pointer' : undefined,
                  background: current ? 'var(--color-accent-bg)' : undefined,
                  boxShadow: current ? 'inset 2px 0 0 var(--color-accent)' : undefined,
                  paddingLeft: current ? 6 : undefined,
                }}
                title={canSeek ? '누르면 이 대사로 이동' : undefined}
              >
                <span className="log-time">{fmtGlobal(s.start)}</span>
                {s.speaker && <b>{s.speaker} </b>}{s.text}
              </div>
            );
          })}
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
