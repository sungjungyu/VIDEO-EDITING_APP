/* ③ 분량·장면 (신정빈 님의 편집 설정 화면을 단계 패널로 옮김).
   - AI 가편집: 목표 길이 + 바라는 점 → 서버가 비트 점수(규칙/Gemini)를 매기고 길이는 동적계획법으로 맞춘다 (목표 ±5%)
   - 장면 직접 고르기: 비트(이어지는 말 묶음 · 말 없는 풍경 2~5초) 목록을 시간순으로, 장소가 바뀌는 곳에 구분선.
     체크하면 그 비트만 쓰는 '직접 고르기'(manual)로 바로 반영 · 📌 고정: AI 가편집이 반드시 넣는 비트
     · 줄을 누르면 그 부분 미리보기
   - 길이 비교: '고른 장면 길이'(비트 구간 합) · '실제 결과 길이'(뺀 문장·쉼을 뺀 길이) · 목표
   - 제목·장소 이름 자막 (영상 비율은 어느 단계에서나 보이게 미리보기 재생 줄에 있다: preview.js) */

import { api } from "../core/api.js";
import { $, el, setToggle, toast } from "../core/dom.js";
import { debounce, fmt } from "../core/format.js";
import { analysisReady, mutatePlan, on, pid, sourceDuration, state } from "../core/store.js";
import { showPlan, showSource } from "./preview.js";
import { loadProfile } from "./profile.js";
import { goStep } from "./steps.js";

const tolerance = () => state.config?.target_tolerance ?? 0.05;   // AI 가편집 목표 길이 허용 오차 (서버 설정)

const setup = { beats: [], checked: new Set(), locked: new Set(), reasons: {}, pending: false, targetFor: null };

const beatDuration = b => Math.max(0, b.end - b.start);

/* ---------------------------------------------------------------- 상태 */

function loadState() {
  setup.beats = analysisReady() ? state.analysis.beats || [] : [];
  const sel = state.plan?.selection;
  setup.checked = new Set(sel?.mode === "all" ? setup.beats.map(b => b.beat_id) : sel?.beat_ids || []);
  setup.locked = new Set(sel?.locked_ids || []);
  setup.reasons = sel?.reasons || {};
}

function selectedDuration() {
  return setup.beats.reduce((sum, b) => sum + (setup.checked.has(b.beat_id) ? beatDuration(b) : 0), 0);
}

function targetMinutes() {
  return Number($("setup-target-minutes").value) || 0;
}

/* 목표 길이 입력: 프로젝트를 처음 볼 때 한 번만 채운다 (저장된 목표 → 원본의 절반) */
function initTarget() {
  const key = `${pid()}|${state.analysis?.created_at}`;
  const sourceMin = sourceDuration() / 60;
  $("setup-target-range").max = String(Math.max(1, Math.ceil(sourceMin)));
  if (setup.targetFor === key) return;
  setup.targetFor = key;
  const sel = state.plan?.selection;
  const minutes = sel?.target_sec ? sel.target_sec / 60 : Math.max(0.5, Math.round(sourceMin / 2 * 2) / 2);
  setTarget(Math.round(minutes * 10) / 10);
  $("setup-user-prompt").value = sel?.user_prompt || "";
}

function setTarget(minutes) {
  $("setup-target-minutes").value = String(minutes);
  $("setup-target-range").value = String(minutes);
}

function setStatus(text, kind = "info") {
  const node = $("setup-status");
  node.textContent = text || "";
  node.className = `setup-status is-${text ? kind : "empty"}`;
}

function renderMeter() {
  const box = $("duration-meter");
  box.innerHTML = "";
  if (!state.plan) return;
  const target = targetMinutes() * 60;
  const actual = state.plan.duration || 0;
  const ok = target > 0 && Math.abs(actual / target - 1) <= tolerance();
  box.append(
    el("div", { class: "dm-row" }, el("span", {}, "원본 전체"), el("b", {}, fmt(sourceDuration()))),
    el("div", { class: "dm-row" }, el("span", {}, "고른 장면"), el("b", {}, fmt(selectedDuration()))),
    el("div", { class: "dm-row", title: "고른 장면에서 뺀 문장과 긴 쉼을 덜어 낸 실제 결과 길이" },
       el("span", {}, "실제 결과 길이"), el("b", { class: target > 0 ? (ok ? "ok" : "off") : "" },
         `${fmt(actual)}${target > 0 ? ` (목표 ${fmt(target)}${ok ? " ✓" : ""})` : ""}`)));
}

/* ---------------------------------------------------------------- 그리기 */

function row(beat) {
  const id = beat.beat_id;
  const check = el("input", { type: "checkbox", class: "scene-row-check", title: "체크: 이 장면을 결과에 넣기" });
  check.checked = setup.checked.has(id);
  check.addEventListener("click", e => e.stopPropagation());
  check.addEventListener("change", () => {
    if (check.checked) setup.checked.add(id);
    else { setup.checked.delete(id); setup.locked.delete(id); }
    changed();
  });
  const pin = el("button", { class: `scene-row-pin${setup.locked.has(id) ? " on" : ""}`,
                             title: "고정: AI 가편집이 반드시 넣는 장면" }, "📌");
  pin.addEventListener("click", e => {
    e.stopPropagation();
    if (setup.locked.has(id)) setup.locked.delete(id);
    else { setup.locked.add(id); setup.checked.add(id); }
    changed();
  });
  const broll = beat.kind === "broll";
  const title = broll ? beat.title : `"${beat.title}"`;
  const items = [check, pin,
                 broll ? el("span", { class: "scene-row-kind", title: "말 없는 장면 (분위기 전환용)" }, "풍경") : null,
                 el("span", { class: "scene-row-title", title: beat.summary || beat.title }, title || "(제목 없음)"),
                 el("span", { class: "scene-row-dur" }, fmt(beatDuration(beat)))];
  if (setup.reasons[id]) items.push(el("div", { class: "scene-row-reason" }, `💡 ${setup.reasons[id]}`));
  const div = el("div", { class: `scene-row${setup.locked.has(id) ? " is-locked" : ""}${broll ? " is-broll" : ""}`,
                          title: "눌러서 이 장면 보기" }, ...items);
  div.addEventListener("click", () => showSource(beat.clip_id, beat.start));
  return div;
}

/* 시간순 목록 하나. 장소가 바뀌는 곳에만 얇은 구분선 */
function renderList() {
  const list = $("scene-list");
  list.innerHTML = "";
  if (!setup.beats.length) {
    list.appendChild(el("div", { class: "scene-list-empty" }, "고를 장면이 없어요"));
    return;
  }
  let place = null;
  for (const b of setup.beats) {
    if (b.place !== place) {
      place = b.place;
      list.appendChild(el("div", { class: "scene-divider" }, el("span", {}, place || "장소 모름")));
    }
    list.appendChild(row(b));
  }
}

function renderExtras() {
  const options = state.plan?.options || {};
  const input = $("setup-title-text");
  if (document.activeElement !== input) input.value = options.title_text || "";
  setToggle("setup-location-toggle", options.location_captions);
}

function renderAll() {
  if (state.ui.step !== 3) return;
  if (!analysisReady()) { renderExtras(); return; }
  initTarget();
  if (!setup.pending) loadState();
  renderList();
  renderMeter();
  renderExtras();
}

/* ---------------------------------------------------------------- 서버 반영 */

const applyManual = debounce(async () => {
  setup.pending = false;
  try {
    await mutatePlan(() => api.select(pid(), {
      mode: "manual", beat_ids: setup.beats.map(b => b.beat_id).filter(i => setup.checked.has(i)),
      locked_ids: [...setup.locked],
      target_sec: targetMinutes() * 60 || null, user_prompt: $("setup-user-prompt").value,
    }));
    setStatus(`고른 장면으로 바꿨어요 (결과 ${fmt(state.plan.duration)}).`, "ok");
  } catch (err) {
    setStatus(`반영하지 못했어요: ${err.message}`, "error");
  }
}, 500);

function changed() {
  setup.pending = true;
  renderList();
  renderMeter();
  applyManual();
}

async function runAiAutoEdit() {
  if (!analysisReady()) { goStep(2); return; }
  const target = targetMinutes() * 60;
  if (target <= 0) { setStatus("목표 길이를 넣어 주세요.", "error"); return; }
  const btn = $("btn-start-edit");
  btn.disabled = true;
  btn.textContent = "AI가 장면을 고르는 중…";
  setStatus("장면마다 점수를 매기고 목표 길이에 맞추는 중이에요…", "info");
  try {
    const view = await mutatePlan(() => api.select(pid(), {
      mode: "auto", target_sec: target, user_prompt: $("setup-user-prompt").value.trim(),
      locked_ids: [...setup.locked], profile: loadProfile(),
    }));
    loadState();
    renderAll();
    const diff = view.plan.duration / target - 1;
    const ok = Math.abs(diff) <= tolerance();
    const lines = [`${view.engine === "ai" ? "Gemini" : "규칙(오프라인)"} 점수로 장면 ${view.plan.selection.beat_ids.length}개를 골랐어요.`,
                   `결과 ${fmt(view.plan.duration)} / 목표 ${fmt(target)} (차이 ${diff >= 0 ? "+" : ""}${(diff * 100).toFixed(1)}%)`,
                   ...(view.warnings || []).map(w => `! ${w}`)];
    setStatus(lines.join("\n"), ok ? "ok" : "info");
    toast(`AI 가편집 완료: ${fmt(view.plan.duration)} (목표 ${fmt(target)})`, "ok");
    goStep(4);
    showPlan(0, false);
  } catch (err) {
    setStatus(`AI 가편집에 실패했어요: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "AI로 목표 길이 맞추기";
  }
}

/* 0.5초 안에 여러 옵션을 바꾸면 모아서 한 번에 보낸다 */
let pendingOptions = {};
const flushOptions = debounce(async () => {
  const changes = pendingOptions;
  pendingOptions = {};
  try {
    await mutatePlan(() => api.putPlan(pid(), { options: { ...state.plan.options, ...changes } }));
  } catch (err) {
    toast(err.message, "error");
  }
}, 500);
const saveOptions = changes => { Object.assign(pendingOptions, changes); flushOptions(); };

export function initSetup() {
  $("setup-target-minutes").addEventListener("input", e => { $("setup-target-range").value = e.target.value; renderMeter(); });
  $("setup-target-range").addEventListener("input", e => { $("setup-target-minutes").value = e.target.value; renderMeter(); });
  $("btn-start-edit").addEventListener("click", runAiAutoEdit);
  $("btn-select-all").addEventListener("click", async () => {
    try {
      await mutatePlan(() => api.select(pid(), { mode: "all" }));
      loadState();
      renderAll();
      setStatus("전체 장면을 써요.", "ok");
    } catch (err) { setStatus(err.message, "error"); }
  });
  $("setup-title-text").addEventListener("input", e => saveOptions({ title_text: e.target.value }));
  $("setup-location-toggle").addEventListener("click", () => {
    const on = !state.plan?.options?.location_captions;
    setToggle("setup-location-toggle", on);
    saveOptions({ location_captions: on });
  });
  on("plan", renderAll);
  on("analysis", () => { setup.targetFor = null; renderAll(); });
  on("step", renderAll);
}
