/* 편집 설정 화면 (신정빈 화면을 모듈로 옮기고 서버 편집 계획에 연결).
   - 장면 트리(장소/일/상황/대사 탭)에서 체크 → 그 장면만 쓰는 '직접 고르기'(manual)로 바로 반영
   - 📌 고정: AI 가편집이 반드시 넣는 장면
   - AI 가편집: 목표 분량 + 요청 → 서버가 장면 점수(Gemini/규칙)로 고르고 분량은 코드가 맞춘다
   - 요약: '고른 장면 길이'(트리 구간 합)와 '실제 결과 길이'(자른 문장·쉼을 뺀 편집 계획 길이)를 함께 보여 준다
   - 분석 전에는 예시 트리를 보여 준다 (서버에 보내지 않음) */

import { api } from "./api.js";
import { setAiStage } from "./analysis.js";
import { loadProfile } from "./profile.js";
import { showSource } from "./preview.js";
import { analysisReady, globalToClip, mutatePlan, on, pid, state } from "./store.js";
import { STYLE_ITEMS, attachPane, detachPane } from "./stylepanel.js";
import { debounce, el, setToggle, toast } from "./util.js";

const DEPTH_LABELS = ["장소", "일", "상황", "대사"];

/* 분석 전 화면 확인용 예시 트리 (test_prompt_builder.py의 RAW_TREE와 같은 내용) */
const EXAMPLE_TREE = [
  { id: "intro", title: "오프닝", start: 0, end: 30, children: [
    { id: "intro-hook", title: "훅 멘트", start: 0, end: 10, children: [] },
    { id: "intro-topic", title: "오늘 주제", start: 10, end: 30, children: [] }] },
  { id: "body", title: "본론: 영상편집 꿀팁 3가지", start: 30, end: 330, children: [
    { id: "tip-1", title: "꿀팁 1 - 컷편집", start: 30, end: 120, children: [
      { id: "tip-1-demo", title: "데모", start: 60, end: 100, children: [] }] },
    { id: "tip-2", title: "꿀팁 2 - 자막", start: 120, end: 220, children: [] },
    { id: "tip-3", title: "꿀팁 3 - 색보정", start: 220, end: 330, children: [] }] },
  { id: "outro", title: "엔딩", start: 330, end: 390, children: [
    { id: "outro-cta", title: "구독 유도", start: 330, end: 360, children: [] },
    { id: "outro-next", title: "다음 영상 예고", start: 360, end: 390, children: [] }] },
];

const setup = { open: false, example: true, tree: [], checked: new Set(), locked: new Set(), reasons: {}, depth: 0,
                prevStage: "idle", expandedStyle: null, pending: false };

/* ---------------------------------------------------------------- 트리 도구 */

function walk(nodes, fn, depth = 0) {
  for (const n of nodes) { fn(n, depth); walk(n.children || [], fn, depth + 1); }
}

function allIds(nodes) {
  const out = [];
  walk(nodes, n => out.push(n.id));
  return out;
}

const nodeDuration = n => Math.max(0, n.end - n.start);

/* 부모와 자식이 함께 체크되면 부모 길이만 센다 (prompt_builder.calc_duration과 같은 규칙) */
function selectedDuration(nodes) {
  let total = 0;
  for (const n of nodes) total += setup.checked.has(n.id) ? nodeDuration(n) : selectedDuration(n.children || []);
  return total;
}

function hasCheckedDescendant(node) {
  return (node.children || []).some(c => setup.checked.has(c.id) || hasCheckedDescendant(c));
}

function checkState(node) {
  if (setup.checked.has(node.id)) return "checked";
  return hasCheckedDescendant(node) ? "indeterminate" : "unchecked";
}

function cascade(node, on) {
  if (on) setup.checked.add(node.id); else setup.checked.delete(node.id);
  for (const c of node.children || []) cascade(c, on);
}

/* 서버로 보낼 때는 가장 위쪽의 체크된 노드만 (자식은 부모 구간에 이미 들어 있다) */
function topMostChecked(nodes, out = []) {
  for (const n of nodes) {
    if (setup.checked.has(n.id)) out.push(n.id);
    else topMostChecked(n.children || [], out);
  }
  return out;
}

function expandDown(nodes, ids) {
  const want = new Set(ids), out = new Set();
  walk(nodes, n => { if (want.has(n.id)) walk([n], m => out.add(m.id)); });
  return out;
}

/* ---------------------------------------------------------------- 상태 */

function loadState() {
  const real = analysisReady() && state.analysis.tree.length;
  setup.example = !real;
  setup.tree = real ? state.analysis.tree : EXAMPLE_TREE;
  const sel = state.plan?.selection;
  if (!real) {
    setup.checked = new Set();
    setup.locked = new Set();
    setup.reasons = {};
    return;
  }
  setup.checked = sel?.mode === "all" ? new Set(allIds(setup.tree)) : expandDown(setup.tree, sel?.node_ids || []);
  setup.locked = new Set(sel?.locked_ids || []);
  setup.reasons = sel?.reasons || {};
}

function totalSeconds() {
  return setup.tree.reduce((a, n) => a + nodeDuration(n), 0);
}

function targetMinutes() {
  return Number(document.getElementById("setup-target-minutes").value) || 0;
}

function setStatus(text, kind = "info") {
  const node = document.getElementById("setup-status");
  node.textContent = text || "";
  node.className = `setup-status is-${text ? kind : "empty"}`;
}

function updateSummary() {
  const selected = selectedDuration(setup.tree);
  const target = targetMinutes() * 60;
  const selEl = document.getElementById("setup-selected-duration");
  const planEl = document.getElementById("setup-plan-duration");
  selEl.textContent = `${selected.toFixed(1)}초`;
  const actual = setup.example ? selected : (state.plan?.duration || 0);
  planEl.textContent = setup.example ? "(예시 트리)" : `${actual.toFixed(1)}초`;
  document.getElementById("setup-target-display").textContent = `${targetMinutes()}분 (${target.toFixed(1)}초)`;
  planEl.className = "";
  if (target > 0 && !setup.example) {
    const r = actual / target;
    planEl.className = r >= 0.95 && r <= 1.05 ? "duration-ok" : "duration-off";
  }
}

/* ---------------------------------------------------------------- 그리기 */

function renderTabs() {
  const tabs = document.getElementById("scene-tabs");
  tabs.innerHTML = "";
  DEPTH_LABELS.forEach((label, depth) => {
    tabs.appendChild(el("button", { type: "button", class: `scene-tab${depth === setup.depth ? " active" : ""}`,
                                    onclick: () => { setup.depth = depth; renderTabs(); renderList(); } },
                        `${depth + 1}. ${label}`));
  });
}

function nodesAtDepth(depth) {
  const out = [];
  walk(setup.tree, (n, d) => { if (d === depth) out.push(n); });
  return out;
}

function row(node) {
  const check = el("input", { type: "checkbox", class: "scene-row-check" });
  const s = checkState(node);
  check.checked = s === "checked";
  check.indeterminate = s === "indeterminate";
  check.addEventListener("click", e => e.stopPropagation());
  check.addEventListener("change", () => {
    cascade(node, check.checked);
    if (!check.checked) setup.locked.delete(node.id);
    changed();
  });
  const pin = el("button", { class: `scene-row-pin${setup.locked.has(node.id) ? " on" : ""}`,
                             title: "고정: AI 가편집이 반드시 넣는 장면" }, "📌");
  pin.addEventListener("click", e => {
    e.stopPropagation();
    if (setup.locked.has(node.id)) setup.locked.delete(node.id);
    else { setup.locked.add(node.id); cascade(node, true); }
    changed();
  });
  const items = [check, pin, el("span", { class: "scene-row-title", title: node.summary || node.title }, node.title || "(제목 없음)"),
                 el("span", { class: "scene-row-dur" }, `${nodeDuration(node).toFixed(1)}초`)];
  if (setup.reasons[node.id]) items.push(el("div", { class: "scene-row-reason" }, `💡 ${setup.reasons[node.id]}`));
  const div = el("div", { class: `scene-row${setup.locked.has(node.id) ? " is-locked" : ""}` }, ...items);
  div.addEventListener("click", () => {
    if (setup.example) return;
    const pos = globalToClip(node.start);
    if (pos) showSource(pos.clipId, pos.time);
  });
  return div;
}

function renderList() {
  const list = document.getElementById("scene-list");
  list.innerHTML = "";
  const nodes = nodesAtDepth(setup.depth);
  if (!nodes.length) {
    list.appendChild(el("div", { class: "scene-list-empty" }, "이 단계의 장면이 없습니다"));
    return;
  }
  for (const n of nodes) list.appendChild(row(n));
}

function renderStyleList() {
  const list = document.getElementById("style-list");
  detachPane();
  list.innerHTML = "";
  STYLE_ITEMS.forEach((item, i) => {
    const open = setup.expandedStyle === item.key;
    const head = el("div", { class: "style-item-head" },
      el("span", { class: "style-item-caret" }, open ? "▼" : "▶"),
      el("span", { class: "style-item-num" }, `${i + 1}.`),
      el("span", { class: "style-item-name" }, item.name));
    head.addEventListener("click", () => {
      setup.expandedStyle = open ? null : item.key;
      renderStyleList();
    });
    const node = el("div", { class: `style-item${open ? " open" : ""}` }, head);
    if (open) {
      const body = el("div", { class: "style-item-body" });
      node.appendChild(body);
      list.appendChild(node);
      attachPane(body, item.key);
    } else {
      list.appendChild(node);
    }
  });
}

function renderExtras() {
  const options = state.plan?.options || {};
  const input = document.getElementById("setup-title-text");
  if (document.activeElement !== input) input.value = options.title_text || "";
  setToggle("setup-location-toggle", options.location_captions);
}

function renderAll() {
  renderTabs();
  renderList();
  updateSummary();
  renderExtras();
}

/* ---------------------------------------------------------------- 서버 반영 */

const applyManual = debounce(async () => {
  setup.pending = false;
  if (setup.example) { setStatus("예시 트리입니다. 영상을 AI 분석하면 실제 장면으로 바뀝니다.", "info"); return; }
  try {
    await mutatePlan(() => api.select(pid(), {
      mode: "manual", node_ids: topMostChecked(setup.tree), locked_ids: [...setup.locked],
      target_sec: targetMinutes() * 60 || null, user_prompt: document.getElementById("setup-user-prompt").value,
    }));
    setStatus(`직접 고른 장면으로 편집 계획을 바꿨습니다 (결과 ${state.plan.duration.toFixed(1)}초).`, "ok");
  } catch (err) {
    setStatus(`반영 실패: ${err.message}`, "error");
  }
}, 500);

function changed() {
  setup.pending = true;
  renderList();
  updateSummary();
  applyManual();
}

async function runAiAutoEdit() {
  if (setup.example) { setStatus("먼저 영상을 AI 분석하세요. 지금은 예시 트리입니다.", "error"); return; }
  const target = targetMinutes() * 60;
  if (target <= 0) { setStatus("목표 분량을 입력하세요.", "error"); return; }
  const btn = document.getElementById("btn-start-edit");
  btn.disabled = true;
  btn.textContent = "AI가 장면을 고르는 중...";
  setStatus("장면 점수를 매기고 목표 분량에 맞추는 중...", "info");
  try {
    const view = await mutatePlan(() => api.select(pid(), {
      mode: "auto", target_sec: target, user_prompt: document.getElementById("setup-user-prompt").value.trim(),
      locked_ids: [...setup.locked], profile: loadProfile(),
    }));
    loadState();
    renderAll();
    const ratio = view.plan.duration / target;
    const lines = [`${view.engine === "ai" ? "Gemini" : "규칙(오프라인)"} 점수로 ${view.plan.selection.node_ids.length}개 장면을 골랐습니다.`,
                   `결과 ${view.plan.duration.toFixed(1)}초 / 목표 ${target.toFixed(0)}초 (${(ratio * 100).toFixed(0)}%)`,
                   ...(view.warnings || []).map(w => `! ${w}`)];
    setStatus(lines.join("\n"), Math.abs(ratio - 1) <= 0.05 ? "ok" : "info");
  } catch (err) {
    setStatus(`AI 가편집 실패: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "AI 가편집하기";
  }
}

const saveOptions = debounce(async changes => {
  try {
    await mutatePlan(() => api.putPlan(pid(), { options: { ...state.plan.options, ...changes } }));
  } catch (err) {
    toast(err.message, "error");
  }
}, 500);

/* ---------------------------------------------------------------- 열기·닫기 */

export function openEditSetup() {
  if (setup.open) return;
  setup.open = true;
  setup.prevStage = state.ui.aiStage === "setup" ? "idle" : state.ui.aiStage;
  document.querySelectorAll(".icon-btn").forEach(b => b.classList.remove("icon-active"));
  document.getElementById("btn-editsetup-icon").classList.add("icon-active");
  document.body.classList.add("setup-active");
  loadState();
  const sel = state.plan?.selection;
  const minutes = sel?.target_sec ? sel.target_sec / 60 : setup.example ? 3 : Math.max(0.1, totalSeconds() / 2 / 60);
  document.getElementById("setup-target-minutes").value = String(Math.round(minutes * 10) / 10);
  document.getElementById("setup-user-prompt").value = sel?.user_prompt || "";
  setup.depth = 0;
  setStatus(setup.example ? "아직 분석한 영상이 없어 예시 트리를 보여 줍니다. 영상을 AI 분석하면 실제 장면 트리로 바뀝니다."
    : `${sel?.mode === "all" ? "지금은 전체 장면을 씁니다." : sel?.mode === "auto" ? "AI 가편집 결과입니다." : "직접 고른 장면입니다."}`
      + " 체크를 바꾸면 바로 반영됩니다.", "info");
  setup.expandedStyle = null;
  renderAll();
  renderStyleList();
  setAiStage("setup");
}

export function closeEditSetup() {
  if (!setup.open) return;
  setup.open = false;
  document.body.classList.remove("setup-active");
  document.querySelectorAll(".icon-btn").forEach(b => b.classList.remove("icon-active"));
  document.querySelector('.icon-btn[data-panel="media"]').classList.add("icon-active");
  setup.expandedStyle = null;
  detachPane();
  setAiStage(setup.prevStage || "idle");
}

export function initSetup() {
  document.getElementById("btn-editsetup-icon").addEventListener("click", () => (setup.open ? closeEditSetup() : openEditSetup()));
  document.querySelector('.icon-btn[data-panel="media"]').addEventListener("click", closeEditSetup);
  document.getElementById("setup-target-minutes").addEventListener("input", updateSummary);
  document.getElementById("btn-start-edit").addEventListener("click", runAiAutoEdit);
  document.getElementById("btn-select-all").addEventListener("click", async () => {
    if (setup.example) return;
    try {
      await mutatePlan(() => api.select(pid(), { mode: "all" }));
      loadState();
      renderAll();
      setStatus("전체 장면을 씁니다.", "ok");
    } catch (err) { setStatus(err.message, "error"); }
  });
  document.getElementById("setup-title-text").addEventListener("input", e => saveOptions({ title_text: e.target.value }));
  document.getElementById("setup-location-toggle").addEventListener("click", () => {
    const on = !state.plan?.options?.location_captions;
    setToggle("setup-location-toggle", on);
    saveOptions({ location_captions: on });
  });
  on("plan", () => {
    if (!setup.open) return;
    if (!setup.pending) { loadState(); renderList(); }
    updateSummary();
    renderExtras();
  });
  on("analysis", () => { if (setup.open) { loadState(); renderAll(); } });
}
