/* 값 다루기: 시간 표시, 범위 제한, 입력이 멈춘 뒤 한 번만 실행. */

export function fmt(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function clamp(x, lo, hi) {
  return Math.max(lo, Math.min(hi, x));
}

export function debounce(fn, ms) {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.flush = (...args) => { clearTimeout(timer); return fn(...args); };
  return wrapped;
}
