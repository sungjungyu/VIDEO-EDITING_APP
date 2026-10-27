/* 자막 편집 (영상 편집 프로그램 방식)
     클릭: 선택 · Shift+클릭: 범위 선택 · Ctrl+클릭: 하나씩 더하기 · 더블클릭/Enter: 자막 글자 고치기
     Delete·Backspace: 자르기 · Shift+E: 사용/사용 안 함 전환 (Premiere의 Enable) · 오른쪽 클릭: 메뉴
   그 밖의 단축키: 재생(J·K·L), 프레임 이동(←/→), 1초(Shift+←/→), Home/End, 잘린 곳 이동([ ]), 확대(+ - \), 붙기(S) */

import { api } from "../../core/api.js";
import { $, el, toast } from "../../core/dom.js";
import { clipById, decisionOf, emit, mutatePlan, pid, state } from "../../core/store.js";
import { removeFromTimeline } from "../media.js";
import { showSource, togglePlay } from "../preview.js";
import { attachPane } from "../style-panel.js";
import { joins, SEQUENCE } from "./model.js";
import { fps, isLocked, segments, tl, total } from "./state.js";
import { captionItems } from "./tracks/captions.js";
import { cutRegions } from "./tracks/video.js";

let app;

const lineOf = segId => (state.analysis?.lines || []).find(l => l.seg_id === segId);

/* ---------------------------------------------------------------- 선택 */

export function pruneSelection() {
  const known = new Set((state.analysis?.lines || []).map(l => l.seg_id));
  for (const id of tl.selected) if (!known.has(id)) tl.selected.delete(id);
}

/* 선택 표시만 바꾼다 (자막 칸을 다시 만들지 않는다 → 더블클릭이 이어진다) */
function refreshSelection() {
  for (const chip of app.lanes.C1.layer.querySelectorAll(".tl-cap")) {
    const on = tl.selected.has(chip.dataset.seg);
    chip.classList.toggle("selected", on);
    chip.setAttribute("aria-pressed", String(on));
  }
}

function orderedIds() {
  return [...new Set(captionItems(segments()).map(c => c.segId))];
}

function captionDown(e, item) {
  if (e.button !== 0) return;
  e.stopPropagation();
  if (e.shiftKey && tl.anchor) {
    const ids = orderedIds();
    const a = ids.indexOf(tl.anchor), b = ids.indexOf(item.segId);
    if (a >= 0 && b >= 0) {
      if (!e.ctrlKey && !e.metaKey) tl.selected.clear();
      for (const id of ids.slice(Math.min(a, b), Math.max(a, b) + 1)) tl.selected.add(id);
    }
  } else if (e.ctrlKey || e.metaKey) {
    if (tl.selected.has(item.segId)) tl.selected.delete(item.segId); else tl.selected.add(item.segId);
    tl.anchor = item.segId;
  } else {
    tl.selected.clear();
    tl.selected.add(item.segId);
    tl.anchor = item.segId;
  }
  if (state.ui.selectedClipId) {
    state.ui.selectedClipId = null;
    app.lanes.V1.layer.querySelectorAll(".tl-clip.selected").forEach(b => b.classList.remove("selected"));
  }
  emit("selection");
  refreshSelection();
}

function clearSelection() {
  if (!tl.selected.size) return;
  tl.selected.clear();
  refreshSelection();
}

export function selectClip(clipId) {
  state.ui.selectedClipId = clipId;
  tl.selected.clear();
  refreshSelection();
  for (const block of app.lanes.V1.layer.querySelectorAll(".tl-clip")) {
    block.classList.toggle("selected", block.dataset.clip === clipId);
  }
  emit("selection");
}

/* ---------------------------------------------------------------- 고치기 (모두 실행취소 가능) */

async function patch(changes, message) {
  if (!changes.length) return;
  if (isLocked("C1")) { toast("자막 트랙이 잠겨 있습니다 (트랙 머리의 자물쇠).", "error"); return; }
  try {
    await mutatePlan(() => api.patchLines(pid(), changes));
    if (message) toast(message, "ok", 2200);
  } catch (err) {
    toast(err.message, "error");
  }
}

const selectedIds = () => [...tl.selected];

function setKeep(keep) {
  const ids = selectedIds().filter(id => decisionOf(id).keep !== keep);
  return patch(ids.map(seg_id => ({ seg_id, keep })),
               ids.length ? `문장 ${ids.length}개를 ${keep ? "살렸습니다" : "잘랐습니다"} (Ctrl+Z로 되돌리기)` : "");
}

function toggleEnable() {
  const ids = selectedIds();
  if (!ids.length) return;
  return setKeep(!ids.every(id => decisionOf(id).keep));
}

function resetSelected() {
  return patch(selectedIds().filter(id => state.plan?.lines?.[id]).map(seg_id => ({ seg_id, reset: true })),
               "AI·규칙 판단으로 되돌렸습니다.");
}

function playLine(segId) {
  const line = lineOf(segId);
  if (!line) return;
  if (tl.view === SEQUENCE) {
    const item = captionItems(segments()).find(c => c.segId === segId);
    if (item) app.seek(item.start, { play: true });
    else showSource(line.clip_id, Math.max(0, line.start - 0.2), true);
  } else {
    showSource(line.clip_id, Math.max(0, line.start - 0.2), true);
  }
}

/* 더블클릭·Enter: 자막 칸 위에서 바로 글자 고치기 */
function captionEdit(e, item, chip) {
  e?.stopPropagation();
  if (isLocked("C1")) return;
  const line = lineOf(item.segId);
  if (!line) return;
  const d = decisionOf(item.segId);
  const input = el("input", { class: "tl-cap-input", value: d.text || line.text, "aria-label": "자막 글자" });
  const layer = chip?.parentNode || app.lanes.C1.layer;
  input.style.left = chip ? chip.style.left : "0px";
  input.style.minWidth = `${Math.max(220, parseFloat(chip?.style.width || 0))}px`;
  layer.appendChild(input);
  input.focus();
  input.select();
  let done = false;
  const finish = save => {
    if (done) return;
    done = true;
    const value = input.value.trim();
    input.remove();
    if (save && value !== (d.text || line.text)) {
      patch([{ seg_id: item.segId, text: value === line.text ? "" : value }], "자막 글자를 고쳤습니다.");
    }
  };
  input.addEventListener("keydown", ev => {
    ev.stopPropagation();
    if (ev.key === "Enter") finish(true);
    if (ev.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
  input.addEventListener("mousedown", ev => ev.stopPropagation());
}

/* ---------------------------------------------------------------- 메뉴 */

function showMenu(e, items) {
  e.preventDefault();
  e.stopPropagation();
  const menu = $("tl-menu");
  menu.innerHTML = "";
  for (const item of items) {
    if (item === "-") { menu.appendChild(el("div", { class: "tl-menu-sep" })); continue; }
    const node = el("button", { class: `tl-menu-item${item.danger ? " danger" : ""}`, type: "button", role: "menuitem",
                                disabled: item.disabled ? true : undefined },
      el("span", {}, item.label), item.key ? el("kbd", {}, item.key) : null);
    node.addEventListener("click", () => { closeMenu(); item.action(); });
    menu.appendChild(node);
  }
  menu.classList.remove("hidden");
  const { innerWidth, innerHeight } = window;
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(e.clientX, innerWidth - rect.width - 8)}px`;
  menu.style.top = `${Math.min(e.clientY, innerHeight - rect.height - 8)}px`;
  menu.querySelector("button:not([disabled])")?.focus();
}

function closeMenu() { $("tl-menu").classList.add("hidden"); }

function captionMenu(e, item) {
  if (!tl.selected.has(item.segId)) {
    tl.selected.clear();
    tl.selected.add(item.segId);
    tl.anchor = item.segId;
    refreshSelection();
  }
  const n = tl.selected.size;
  const allKept = selectedIds().every(id => decisionOf(id).keep);
  const someUser = selectedIds().some(id => state.plan?.lines?.[id]);
  const locked = isLocked("C1");
  showMenu(e, [
    { label: "▶ 이 문장 재생", action: () => playLine(item.segId) },
    "-",
    { label: n > 1 ? `문장 ${n}개 자르기` : "자르기", key: "Delete", action: () => setKeep(false), danger: true,
      disabled: locked || selectedIds().every(id => !decisionOf(id).keep) },
    { label: n > 1 ? `문장 ${n}개 살리기` : "살리기", action: () => setKeep(true),
      disabled: locked || allKept },
    { label: "사용 / 사용 안 함", key: "Shift+E", action: toggleEnable, disabled: locked },
    { label: "자막 글자 고치기", key: "Enter", disabled: locked || n !== 1,
      action: () => captionEdit(null, item, app.lanes.C1.layer.querySelector(`[data-seg="${item.segId}"]`)) },
    { label: "AI·규칙 판단으로 되돌리기", action: resetSelected, disabled: locked || !someUser },
    "-",
    { label: "선택 해제", key: "Esc", action: clearSelection },
  ]);
}

function clipMenu(e, seg) {
  const clip = clipById(seg.clipId);
  if (!clip) return;
  selectClip(clip.clip_id);
  showMenu(e, [
    { label: "▶ 원본으로 처음부터 보기", action: () => showSource(clip.clip_id, clip.in_point, true) },
    { label: "클립 정보", action: () => emit("selection") },
    "-",
    { label: "타임라인에서 빼기", danger: true, disabled: isLocked("V1"), action: () => removeFromTimeline(clip.clip_id) },
  ]);
}

/* 편집본의 ✂ 이음매: 그 자리에서 잘린 문장을 보고 바로 살리기 */
function openJoin(e, join) {
  const pop = $("tl-popover");
  const lines = (state.analysis?.lines || []).filter(l => l.clip_id === join.clipId && l.end > join.start
                                                          && l.start < join.end);
  pop.dataset.kind = "join";
  pop.innerHTML = "";
  pop.appendChild(el("div", { class: "tl-pop-title" }, `잘린 곳 · ${(join.end - join.start).toFixed(1)}초`));
  if (!lines.length) pop.appendChild(el("div", { class: "tl-pop-empty" }, "말 없는 쉼을 줄인 곳입니다."));
  for (const line of lines) {
    const d = decisionOf(line.seg_id);
    const row = el("div", { class: "tl-pop-row" },
      el("span", { class: `tl-pop-reason${d.keep ? " keep" : ""}` }, d.keep ? "쉼" : d.reason),
      el("span", { class: "tl-pop-text", title: line.text }, line.text || "(말소리)"),
      !d.keep ? el("button", { class: "tl-pop-btn", type: "button" }, "살리기") : null);
    row.querySelector("button")?.addEventListener("click", () => {
      pop.classList.add("hidden");
      patch([{ seg_id: line.seg_id, keep: true }], "문장을 살렸습니다.");
    });
    pop.appendChild(row);
  }
  const cut = lines.filter(l => !decisionOf(l.seg_id).keep);
  if (cut.length > 1) {
    const all = el("button", { class: "tl-pop-btn wide", type: "button" }, `모두 살리기 (${cut.length})`);
    all.addEventListener("click", () => {
      pop.classList.add("hidden");
      patch(cut.map(l => ({ seg_id: l.seg_id, keep: true })), `문장 ${cut.length}개를 살렸습니다.`);
    });
    pop.appendChild(all);
  }
  pop.classList.remove("hidden");
  const rect = pop.getBoundingClientRect();
  pop.style.left = `${Math.min(e.clientX - rect.width / 2, window.innerWidth - rect.width - 8)}px`;
  pop.style.top = `${e.clientY - rect.height - 14}px`;
}

/* ---------------------------------------------------------------- 잘린 곳 이동 · 도움말 */

function cutTimes() {
  if (tl.view === SEQUENCE) return joins(segments()).map(j => j.t);
  return cutRegions(segments()).map(c => c.start);
}

function nextCut(dir) {
  const now = app.currentTime();
  const times = cutTimes().sort((a, b) => a - b);
  const target = dir > 0 ? times.find(t => t > now + 0.05) : times.reverse().find(t => t < now - 0.05);
  if (target !== undefined) app.seek(target);
}

const SHORTCUTS = [
  ["Space", "재생 / 정지"], ["J · K · L", "1초 뒤로 · 정지 · 재생(누를수록 빠르게)"], ["← / →", "1프레임"],
  ["Shift + ← / →", "1초"], ["Home / End", "처음 / 끝"], ["[ / ]", "이전 / 다음 잘린 곳"],
  ["+ / -  ·  \\", "확대 / 축소  ·  전체 보기"], ["Ctrl + 휠", "마우스 위치 기준 확대"], ["Shift + 휠", "트랙 위아래 이동"],
  ["S", "붙기 켜기 / 끄기 (Alt: 끌 때만 잠깐 끄기)"], ["클릭 · Shift · Ctrl", "자막 선택 · 범위 · 하나씩 더하기"],
  ["더블클릭 · Enter", "자막 글자 고치기"], ["Delete · Backspace", "고른 문장 자르기"], ["Shift + E", "사용 / 사용 안 함"],
  ["Esc", "선택 해제"], ["Ctrl + Z / Shift + Z", "실행취소 / 다시실행"],
];

function toggleHelp() {
  const pop = $("tl-popover");
  if (!pop.classList.contains("hidden") && pop.dataset.kind === "help") { pop.classList.add("hidden"); return; }
  pop.dataset.kind = "help";
  pop.innerHTML = "";
  pop.appendChild(el("div", { class: "tl-pop-title" }, "타임라인 단축키"));
  for (const [key, what] of SHORTCUTS) pop.appendChild(el("div", { class: "tl-help-row" }, el("kbd", {}, key), el("span", {}, what)));
  pop.classList.remove("hidden");
  const btn = $("tl-help").getBoundingClientRect();
  const rect = pop.getBoundingClientRect();
  pop.style.left = `${btn.right - rect.width}px`;
  pop.style.top = `${btn.top - rect.height - 8}px`;
}

/* ---------------------------------------------------------------- 단축키 */

let speed = 1;

function onKey(e) {
  const tag = document.activeElement?.tagName;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || document.querySelector(".modal:not(.hidden)")) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const key = e.key;
  const video = $("video");
  const handled = () => e.preventDefault();
  if (key === "Delete" || key === "Backspace") { if (tl.selected.size) { handled(); setKeep(false); } return; }
  if (key === "E" && e.shiftKey) { handled(); toggleEnable(); return; }
  if (key === "Enter" && tl.selected.size === 1) {
    handled();
    const id = selectedIds()[0];
    const item = captionItems(segments()).find(c => c.segId === id);
    if (item) captionEdit(null, item, app.lanes.C1.layer.querySelector(`[data-seg="${id}"]`));
    return;
  }
  if (key === "Escape") { closeMenu(); $("tl-popover").classList.add("hidden"); clearSelection(); return; }
  if (key === "ArrowLeft" || key === "ArrowRight") {
    handled();
    const dir = key === "ArrowLeft" ? -1 : 1;
    video.pause();
    app.seek(app.currentTime() + dir * (e.shiftKey ? 1 : 1 / fps()), { play: false });
    return;
  }
  if (key === "Home") { handled(); app.seek(0); return; }
  if (key === "End") { handled(); app.seek(total()); return; }
  if (key === "[" || key === "]") { handled(); nextCut(key === "]" ? 1 : -1); return; }
  const lower = key.toLowerCase();
  if (lower === "k") { handled(); video.pause(); speed = 1; video.playbackRate = 1; return; }
  if (lower === "l") {
    handled();
    speed = video.paused ? 1 : Math.min(4, speed * 2);
    video.playbackRate = speed;
    if (video.paused) togglePlay();
    return;
  }
  if (lower === "j") { handled(); video.pause(); speed = 1; video.playbackRate = 1; app.seek(app.currentTime() - 1, { play: false }); return; }
  if (lower === "s" && !e.shiftKey) { handled(); $("tl-snap").click(); return; }
  if (key === "+" || key === "=") { handled(); $("tl-zoom-in").click(); return; }
  if (key === "-") { handled(); $("tl-zoom-out").click(); return; }
  if (key === "\\") { handled(); $("tl-zoom-fit").click(); return; }
  if (key === "?") { handled(); toggleHelp(); }
}

/* ---------------------------------------------------------------- 초기화 */

export function initEdit(context) {
  app = context;
  document.addEventListener("keydown", onKey);
  document.addEventListener("mousedown", e => {
    if (!e.target.closest("#tl-menu")) closeMenu();
    if (!e.target.closest("#tl-popover") && !e.target.closest(".tl-join") && !e.target.closest("#tl-help")) {
      $("tl-popover").classList.add("hidden");
    }
  });
  $("tl-scroll").addEventListener("scroll", closeMenu);
  for (const id of ["C1", "T1", "V1", "A1"]) {
    app.lanes[id].lane.addEventListener("mousedown", e => {
      if (e.target === app.lanes[id].lane || e.target === app.lanes[id].layer || e.target.tagName === "CANVAS") clearSelection();
    });
  }
  return {
    captionDown, captionEdit, captionMenu, clipMenu, openJoin, nextCut, toggleHelp,
    removeClip: id => removeFromTimeline(id),
    openTextStyle: style => {
      const panel = $("obj-panel");
      panel.dataset.mode = "style";
      panel.classList.remove("hidden");
      $("obj-panel-name").textContent = style === "title" ? "제목 스타일" : "촬영지 자막 스타일";
      $("obj-tab-body").style.display = "none";
      attachPane(panel, style);
    },
  };
}
