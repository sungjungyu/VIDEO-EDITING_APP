/* 화면 도우미: 요소 찾기·만들기, 알림, 켜기/끄기 버튼. */

export const $ = id => document.getElementById(id);

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
  const area = $("toast-area");
  if (!area) return;
  const node = el("div", { class: `toast ${kind}` }, message);
  area.appendChild(node);
  setTimeout(() => node.remove(), ms);
}

export function setToggle(id, on) {
  const node = typeof id === "string" ? $(id) : id;
  if (!node) return;
  node.classList.toggle("on", !!on);
  node.classList.toggle("off", !on);
}

/* 같은 화면 갱신 주기 안에 여러 번 불러도 한 번만 실행한다 (끌기처럼 이벤트가 몰릴 때) */
export function perFrame(fn) {
  let queued = false;
  return () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; fn(); });
  };
}
