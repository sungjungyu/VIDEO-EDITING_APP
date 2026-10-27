/* 화면에 보이는 폭만큼만 그리는 캔버스 (긴 영상을 크게 확대해도 캔버스 크기가 일정하다).
   캔버스는 가로 스크롤 위치(scrollLeft)를 따라 옮겨 놓고, 그릴 때는 타임라인 x에서 scrollLeft를 뺀다. */

export function prepareCanvas(canvas, scrollLeft, width, height) {
  const ratio = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.ceil(width)), h = Math.max(1, Math.ceil(height));
  if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
    canvas.width = Math.round(w * ratio);
    canvas.height = Math.round(h * ratio);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
  }
  canvas.style.transform = `translateX(${scrollLeft}px)`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.translate(-scrollLeft, 0);
  return ctx;
}

export function roundRect(ctx, x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/* 잘린 곳 빗금 (45°) */
export function hatch(ctx, x, y, w, h, color = "rgba(0,0,0,.55)", stripe = "rgba(255,255,255,.07)") {
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = stripe;
  ctx.lineWidth = 3;
  const start = Math.floor((x - h) / 9) * 9;
  ctx.beginPath();
  for (let sx = start; sx < x + w; sx += 9) {
    ctx.moveTo(sx, y + h);
    ctx.lineTo(sx + h, y);
  }
  ctx.stroke();
  ctx.restore();
}

/* CSS 변수 값 (색 토큰을 캔버스에서도 같이 쓴다) */
const cache = new Map();
export function token(name) {
  if (!cache.has(name)) {
    cache.set(name, getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888");
  }
  return cache.get(name);
}
