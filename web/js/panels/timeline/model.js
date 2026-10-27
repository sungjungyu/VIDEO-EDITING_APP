/* 타임라인 계산 (화면·상태를 쓰지 않는 순수 함수 — Node 테스트로 검사한다).

   보기가 둘이다 (영상 편집 프로그램처럼 기본은 '편집본' = 결과 영상의 시간축)
     sequence (편집본) : 남는 구간(plan.keep)을 이어 붙인 결과 초. 잘린 곳은 ✂ 이음매로만 보인다
     source   (원본)   : 타임라인 순서대로 클립을 이어 붙인 원본 초. 잘린 곳은 빗금으로 보인다
   두 보기 모두 '구간(segment)' 목록으로 바꿔 같은 방식으로 그린다:
     { clipId, start(타임라인 초), dur, in(클립 초 시작), first, last } */

export const SEQUENCE = "sequence";
export const SOURCE = "source";

const usableEnd = clip => (clip.out_point ?? clip.duration);

/* ---------------------------------------------------------------- 구간 */

export function sourceSegments(clips) {
  let t = 0;
  return clips.map(clip => {
    const dur = Math.max(0, usableEnd(clip) - clip.in_point);
    const seg = { clipId: clip.clip_id, start: t, dur, in: clip.in_point, first: true, last: true };
    t += dur;
    return seg;
  });
}

export function sequenceSegments(keep) {
  const segs = (keep || []).map(k => ({ clipId: k.clip_id, start: k.out_start, dur: k.end - k.start, in: k.start,
                                        first: false, last: false }));
  const seen = new Set();
  for (const s of segs) { if (!seen.has(s.clipId)) { s.first = true; seen.add(s.clipId); } }
  seen.clear();
  for (let i = segs.length - 1; i >= 0; i--) {
    if (!seen.has(segs[i].clipId)) { segs[i].last = true; seen.add(segs[i].clipId); }
  }
  return segs;
}

export function totalOf(segs) {
  return segs.length ? segs[segs.length - 1].start + segs[segs.length - 1].dur : 0;
}

/* 클립 초 → 타임라인 초 (그 시각이 어느 구간에도 없으면 null) */
export function toTimeline(segs, clipId, time) {
  for (const s of segs) {
    if (s.clipId === clipId && time >= s.in - 1e-6 && time <= s.in + s.dur + 1e-6) return s.start + (time - s.in);
  }
  return null;
}

/* 클립 초 → 타임라인 초. 잘려 없는 시각이면 그 뒤에 처음 남는 곳 (재생 헤드 위치용) */
export function toTimelineNearest(segs, clipId, time) {
  const exact = toTimeline(segs, clipId, time);
  if (exact !== null) return exact;
  const later = segs.filter(s => s.clipId === clipId && s.in >= time);
  if (later.length) return later[0].start;
  const before = segs.filter(s => s.clipId === clipId);
  return before.length ? before[before.length - 1].start + before[before.length - 1].dur : null;
}

/* 타임라인 초 → { segment, clipId, time(클립 초) } */
export function fromTimeline(segs, t) {
  if (!segs.length) return null;
  let seg = segs.find(s => t >= s.start && t < s.start + s.dur);
  if (!seg) seg = t < segs[0].start ? segs[0] : segs[segs.length - 1];
  const offset = Math.min(Math.max(t - seg.start, 0), seg.dur);
  return { segment: seg, clipId: seg.clipId, time: seg.in + offset };
}

/* 클립 초 구간 → 타임라인 조각들 [{start, end}] (편집본에서는 여러 조각으로 나뉠 수 있다) */
export function clipRangeToTimeline(segs, clipId, s, e) {
  const out = [];
  for (const seg of segs) {
    if (seg.clipId !== clipId) continue;
    const a = Math.max(s, seg.in), b = Math.min(e, seg.in + seg.dur);
    if (b > a) out.push({ start: seg.start + (a - seg.in), end: seg.start + (b - seg.in) });
  }
  return out;
}

/* 원본 초(분석 트리의 시각) 구간 → 클립 초 조각들 */
export function globalToClips(spans, s, e) {
  const out = [];
  for (const span of spans || []) {
    const a = Math.max(s, span.offset), b = Math.min(e, span.offset + span.duration);
    if (b > a) out.push({ clipId: span.clip_id, start: a - span.offset, end: b - span.offset });
  }
  return out;
}

/* 결과 초 구간 → 클립 초 조각들 (제목·촬영지 자막을 원본 보기에 놓을 때) */
export function outputToClips(keep, s, e) {
  const out = [];
  for (const k of keep || []) {
    const a = Math.max(s, k.out_start), b = Math.min(e, k.out_start + (k.end - k.start));
    if (b > a) out.push({ clipId: k.clip_id, start: k.start + (a - k.out_start), end: k.start + (b - k.out_start) });
  }
  return out;
}

/* ---------------------------------------------------------------- 잘린 곳 */

/* 클립마다 사용 범위 안에서 남는 구간에 들지 않는 곳 = 잘린 곳 (클립 초) */
export function cutRanges(clips, keep) {
  const out = [];
  for (const clip of clips) {
    const kept = (keep || []).filter(k => k.clip_id === clip.clip_id).sort((a, b) => a.start - b.start);
    let cursor = clip.in_point;
    for (const k of kept) {
      if (k.start - cursor > 0.02) out.push({ clipId: clip.clip_id, start: cursor, end: k.start });
      cursor = Math.max(cursor, k.end);
    }
    if (usableEnd(clip) - cursor > 0.02) out.push({ clipId: clip.clip_id, start: cursor, end: usableEnd(clip) });
  }
  return out;
}

/* 잘린 곳의 이유: 그 안의 자른 문장 이유(가장 많이 겹치는 것) → 고르지 않은 장면 → 쉼 */
export function cutReason(range, lines, decisionOf, selectionMode) {
  let best = null, bestOverlap = 0;
  for (const line of lines) {
    if (line.clip_id !== range.clipId) continue;
    const overlap = Math.min(line.end, range.end) - Math.max(line.start, range.start);
    const d = decisionOf(line.seg_id);
    if (overlap > bestOverlap && !d.keep) { best = d.reason; bestOverlap = overlap; }
  }
  if (best) return best;
  return selectionMode && selectionMode !== "all" && range.end - range.start > 2.5 ? "고르지 않음" : "쉼";
}

/* 편집본의 이음매: 같은 클립 안에서 잘라 낸 곳 (앞 구간 끝 = 뒤 구간 시작) */
export function joins(segs) {
  const out = [];
  for (let i = 0; i + 1 < segs.length; i++) {
    const a = segs[i], b = segs[i + 1];
    if (a.clipId === b.clipId && b.in - (a.in + a.dur) > 0.02) {
      out.push({ t: b.start, clipId: a.clipId, start: a.in + a.dur, end: b.in });
    }
  }
  return out;
}

/* ---------------------------------------------------------------- 눈금·시각 */

const STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];

/* 큰 눈금 간격(초)과 작은 눈금 수. 프레임이 보일 만큼 확대하면 프레임 단위 */
export function tickSpacing(pxPerSec, fps = 30, minLabelPx = 84) {
  const frame = 1 / fps;
  for (const n of [1, 2, 5, 10, 15]) {
    if (n * frame * pxPerSec >= minLabelPx) return { major: n * frame, minor: n === 1 ? 1 : n, frames: true };
  }
  const major = STEPS.find(s => s * pxPerSec >= minLabelPx) || 3600;
  const minor = major >= 60 ? 6 : major === 15 ? 3 : major === 2 ? 4 : 5;
  return { major, minor, frames: false };
}

export function timecode(t, fps = 30) {
  const frames = Math.round(Math.max(0, t || 0) * fps);      // 가장 가까운 프레임
  const total = Math.floor(frames / fps);
  const f = frames % fps;
  const pad = n => String(n).padStart(2, "0");
  return `${pad(Math.floor(total / 3600))}:${pad(Math.floor(total / 60) % 60)}:${pad(total % 60)}:${pad(f)}`;
}

export function rulerLabel(t, frames, fps = 30) {
  const total = Math.floor(t + 1e-6);
  const m = Math.floor(total / 60), s = total % 60;
  const base = total >= 3600 ? `${Math.floor(total / 3600)}:${String(m % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
  if (!frames) return base;
  return timecode(t, fps);                    // 프레임이 보일 만큼 확대하면 00:00:01:15처럼 프레임까지
}

/* ---------------------------------------------------------------- 붙기 */

/* 가장 가까운 붙기 지점 (threshold 초 이내). 없으면 null */
export function snapTo(t, targets, threshold) {
  let best = null, bestDist = threshold;
  for (const target of targets) {
    const d = Math.abs(target - t);
    if (d <= bestDist) { best = target; bestDist = d; }
  }
  return best;
}
