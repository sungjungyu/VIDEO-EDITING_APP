/** 초 → MM:SS */
export function fmtDuration(sec) {
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

/** 화면 비율 (width / height) → "16:9" 등 */
export function fmtAspect(w, h) {
  const gcd = (a, b) => (b === 0 ? a : gcd(b, a % b));
  const g = gcd(w, h);
  return `${w / g}:${h / g}`;
}

/** 초 → "분 초" 표시 (예: "10분 4초") */
export function fmtMinSec(sec) {
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m === 0) return `${r}초`;
  if (r === 0) return `${m}분`;
  return `${m}분 ${r}초`;
}

/** 전체 타임라인 기준 시각 → "MM:SS" */
export function fmtGlobal(sec) {
  return fmtDuration(sec);
}
