/* 배경음악 크기 규칙 — 서버 src/vibecut/domain/mix.py gain_at과 같은 식 (렌더 = 미리보기).
   숫자를 바꾸면 두 곳을 함께 바꾼다. 같은 사례 파일 tests/fixtures/mix_cases.json으로 양쪽을 검사한다.
   spans: 결과 영상에서 말하는 구간 [[시작, 끝], …] (서버가 합쳐서 plan.speech로 준다) */

export const LEAD = 0.4;
export const RELEASE = 0.6;
export const FADE_IN = 1.5;
export const FADE_OUT = 2.5;

const clip01 = x => (x < 0 ? 0 : x > 1 ? 1 : x);

export function duckAmount(t, spans) {
  let sum = 0;
  for (const [a, b] of spans) sum += clip01((t - (a - LEAD)) / LEAD) * clip01((b + RELEASE - t) / RELEASE);
  return Math.min(1, sum);
}

export function gainAt(t, spans, volume, duckLevel, duck, duration) {
  const fade = clip01(t / FADE_IN) * clip01((duration - t) / FADE_OUT);
  const ducked = duck ? 1 - (1 - duckLevel) * duckAmount(t, spans) : 1;
  return volume * fade * ducked;
}
