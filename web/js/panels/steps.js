/* 단계 표시줄: ① 영상 올리기 → ② AI 분석 → ③ 분량·장면 → ④ 확인·수정 → ⑤ 내보내기.
   - 오른쪽 패널에는 지금 단계의 내용만 보인다 (왼쪽 영상·가운데 미리보기·아래 타임라인은 늘 그대로)
   - 순서를 강제하지 않는다: 아무 단계나 눌러서 갈 수 있고, 준비가 덜 된 단계는 무엇을 먼저 할지 안내한다
   - 끝낸 단계에는 체크 표시, 분석이 도는 동안은 ② 옆에 진행률 */

import { $, el } from "../core/dom.js";
import { analysisReady, emit, on, state, timelineClips } from "../core/store.js";

export const STEPS = ["영상 올리기", "AI 분석", "분량·장면", "확인·수정", "내보내기"];

function isDone(n) {
  const p = state.project;
  if (!p) return false;
  const fresh = analysisReady() && !p.analysis_stale;
  switch (n) {
    case 1: return timelineClips().length > 0;
    case 2: return fresh;
    case 3: return fresh && !!state.plan && state.plan.selection?.mode !== "all";
    case 4: return fresh && (p.renders || []).length > 0;
    case 5: return (p.renders || []).some(r => r.quality === "final");
    default: return false;
  }
}

/* 프로젝트를 열었을 때 보여 줄 단계 */
export function suggestedStep() {
  if (state.ui.analyzing) return 2;
  if (!timelineClips().length) return 1;
  if (!analysisReady()) return 2;
  return 4;
}

function renderStepper() {
  const nav = $("stepper");
  nav.innerHTML = "";
  STEPS.forEach((name, i) => {
    const n = i + 1;
    const done = isDone(n);
    if (i) nav.appendChild(el("span", { class: `step-line${isDone(n - 1) ? " done" : ""}` }));
    const extra = n === 2 && state.ui.analyzing ? el("span", { class: "step-extra" }, `${Math.round(state.ui.analyzing.progress)}%`) : null;
    nav.appendChild(el("button", {
      class: `step-btn${n === state.ui.step ? " active" : ""}${done ? " done" : ""}`,
      title: `${n}. ${name}`, onclick: () => goStep(n),
    }, el("span", { class: "step-num" }, done && n !== state.ui.step ? "✓" : String(n)),
       el("span", { class: "step-name" }, name), extra));
  });
}

/* 분석이 필요한 내용(data-when="analysis")과 그 대신 보일 안내(data-needs="analysis") */
function renderAvailability() {
  const ready = analysisReady();
  document.querySelectorAll('[data-when="analysis"]').forEach(node => node.classList.toggle("unavailable", !ready));
  document.querySelectorAll('[data-needs="analysis"]').forEach(node => node.classList.toggle("hidden", ready));
}

function renderNotice() {
  const box = $("side-notice");
  const stale = state.project?.analysis?.status === "done" && state.project.analysis_stale;
  box.classList.toggle("hidden", !(stale && state.ui.step >= 3));
  if (!stale) return;
  box.innerHTML = "";
  box.append(el("span", {}, "타임라인이 분석했을 때와 달라졌어요. 새로 넣은 영상은 다시 분석해야 자막과 컷이 생깁니다."),
             el("button", { class: "btn-ghost", onclick: () => goStep(2) }, "② AI 분석으로"));
}

export function renderSteps() {
  renderStepper();
  renderAvailability();
  renderNotice();
  document.querySelectorAll(".step-pane").forEach(pane => {
    pane.classList.toggle("hidden", Number(pane.dataset.step) !== state.ui.step);
  });
}

export function goStep(n) {
  state.ui.step = Math.min(5, Math.max(1, n));
  renderSteps();
  emit("step", state.ui.step);
}

export function initSteps() {
  document.addEventListener("click", e => {
    const go = e.target.closest("[data-go]");
    if (go) goStep(Number(go.dataset.go));
  });
  on("project", renderSteps);
  on("plan", renderStepper);
  on("analysis", renderSteps);
  on("analyzing", renderStepper);
}
