/* 공통 도구.
   wrapTokens/wrapText는 서버 vibecut/edit/text.py의 wrap_tokens/wrap_text와 같은 규칙이어야 한다
   (미리보기 자막 줄바꿈 = 렌더 자막 줄바꿈). tests/test_text_and_ass.py의 WRAP_CASES로 같이 확인한다. */

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export function fmt(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function fmtSec(s) {
  return `${(s || 0).toFixed(1)}초`;
}

export function clamp(x, lo, hi) {
  return Math.max(lo, Math.min(hi, x));
}

export function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, ch => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
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

export function squash(text) {
  return String(text || "").replace(/\s+/g, "");
}

// 공백 단위로 이어 붙이다가 maxChars를 넘으면 다음 줄. 단어 하나가 maxChars보다 길면 글자 단위로 자른다.
export function wrapTokens(text, maxChars) {
  maxChars = Math.max(1, Math.floor(maxChars || 1));
  const lines = [];
  let cur = [], curLen = 0;
  for (let token of String(text || "").split(/\s+/).filter(Boolean)) {
    while (token.length > maxChars) {
      if (cur.length) { lines.push(cur); cur = []; curLen = 0; }
      lines.push([token.slice(0, maxChars)]);
      token = token.slice(maxChars);
    }
    if (!token) continue;
    const added = token.length + (cur.length ? 1 : 0);
    if (cur.length && curLen + added > maxChars) {
      lines.push(cur); cur = [token]; curLen = token.length;
    } else {
      cur.push(token); curLen += added;
    }
  }
  if (cur.length) lines.push(cur);
  return lines;
}

export function wrapText(text, maxChars) {
  return wrapTokens(text, maxChars).map(line => line.join(" "));
}

// 작은 DOM 도우미: el("div", {class: "x", onclick: fn}, "글자", child)
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function toast(message, kind = "info", ms = 4500) {
  const area = document.getElementById("toast-area");
  if (!area) return;
  const node = el("div", { class: `toast ${kind}` }, message);
  area.appendChild(node);
  setTimeout(() => node.remove(), ms);
}

export function setToggle(id, on) {
  const node = typeof id === "string" ? document.getElementById(id) : id;
  if (!node) return;
  node.classList.toggle("on", !!on);
  node.classList.toggle("off", !on);
}
