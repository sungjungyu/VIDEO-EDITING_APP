// 타임라인 계산(web/js/panels/timeline/model.js) 테스트. 실행: node tests/js/timeline-model.test.mjs
// 브라우저에서도 같은 검사를 돌릴 수 있게 검사 목록을 export한다.

import * as m from "../../web/js/panels/timeline/model.js";

const clips = [
  { clip_id: "c01", duration: 20, in_point: 0, out_point: null },
  { clip_id: "c02", duration: 10, in_point: 1, out_point: 9 },
];
const keep = [
  { clip_id: "c01", start: 1, end: 5, out_start: 0 },
  { clip_id: "c01", start: 8, end: 12, out_start: 4 },
  { clip_id: "c02", start: 2, end: 6, out_start: 8 },
];

export const CHECKS = [
  ["원본 구간: 사용 범위대로 이어 붙임", () => {
    const s = m.sourceSegments(clips);
    return s[1].start === 20 && s[1].dur === 8 && s[1].in === 1 && m.totalOf(s) === 28;
  }],
  ["편집본 구간: 클립의 첫·마지막 조각 표시", () => {
    const s = m.sequenceSegments(keep);
    return s[0].first && !s[0].last && !s[1].first && s[1].last && s[2].first && s[2].last && m.totalOf(s) === 12;
  }],
  ["클립 초 ↔ 편집본 초", () => {
    const s = m.sequenceSegments(keep);
    const at = m.fromTimeline(s, 5);
    return m.toTimeline(s, "c01", 9) === 5 && at.clipId === "c01" && at.time === 9 && m.toTimeline(s, "c01", 6) === null;
  }],
  ["잘린 시각은 다음에 남는 곳으로", () => m.toTimelineNearest(m.sequenceSegments(keep), "c01", 6) === 4],
  ["클립 구간이 편집본에서 두 조각으로", () => {
    const pieces = m.clipRangeToTimeline(m.sequenceSegments(keep), "c01", 4, 9);
    return pieces.length === 2 && pieces[0].start === 3 && pieces[0].end === 4 && pieces[1].start === 4 && pieces[1].end === 5;
  }],
  ["잘린 곳: 앞·가운데·뒤", () => {
    const cuts = m.cutRanges(clips, keep);
    const c01 = cuts.filter(c => c.clipId === "c01").map(c => [c.start, c.end]);
    const c02 = cuts.filter(c => c.clipId === "c02").map(c => [c.start, c.end]);
    return JSON.stringify(c01) === "[[0,1],[5,8],[12,20]]" && JSON.stringify(c02) === "[[1,2],[6,9]]";
  }],
  ["편집본 이음매는 같은 클립 안에서만", () => {
    const j = m.joins(m.sequenceSegments(keep));
    return j.length === 1 && j[0].t === 4 && j[0].start === 5 && j[0].end === 8;
  }],
  ["잘린 이유: 자른 문장 → 고르지 않음 → 쉼", () => {
    const lines = [{ seg_id: "t1", clip_id: "c01", start: 5.2, end: 7.5 }];
    const dec = id => (id === "t1" ? { keep: false, reason: "NG" } : { keep: true });
    return m.cutReason({ clipId: "c01", start: 5, end: 8 }, lines, dec, "all") === "NG"
      && m.cutReason({ clipId: "c01", start: 12, end: 20 }, lines, dec, "manual") === "고르지 않음"
      && m.cutReason({ clipId: "c01", start: 0, end: 1 }, lines, dec, "manual") === "쉼";
  }],
  ["결과 초 → 클립 초 (제목 자막을 원본에 놓기)", () => {
    const p = m.outputToClips(keep, 3, 5);
    return p.length === 2 && p[0].start === 4 && p[0].end === 5 && p[1].start === 8 && p[1].end === 9;
  }],
  ["원본 초(트리) → 클립 초", () => {
    const p = m.globalToClips([{ clip_id: "c01", offset: 0, duration: 20 }, { clip_id: "c02", offset: 20, duration: 10 }], 18, 23);
    return p.length === 2 && p[1].clipId === "c02" && p[1].start === 0 && p[1].end === 3;
  }],
  ["눈금: 확대하면 프레임 단위", () => m.tickSpacing(40).major === 5 && !m.tickSpacing(40).frames && m.tickSpacing(3000).frames],
  ["시각 표시", () => m.timecode(83.5, 30) === "00:01:23:15" && m.rulerLabel(65, false) === "1:05"],
  ["붙기: 가까운 지점만", () => m.snapTo(4.98, [0, 5, 10], 0.1) === 5 && m.snapTo(4.5, [0, 5, 10], 0.1) === null],
];

if (typeof process !== "undefined" && process.argv?.[1]?.endsWith("timeline-model.test.mjs")) {
  const failed = CHECKS.filter(([, check]) => !check());
  for (const [name] of failed) console.error("실패:", name);
  if (failed.length) process.exit(1);
  console.log(`통과: 타임라인 계산 ${CHECKS.length}건`);
}
