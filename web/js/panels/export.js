/* ⑤ 내보내기: 만들기 전 확인 → 영상 설정 → 만들기(진행률·멈추기) → 내려받기 · 결과 리포트(평가 지표).
   렌더는 서버 작업이라 다른 단계로 가거나 새로고침해도 계속되고, 돌아오면 이어서 진행률을 보여 준다.
   결과 리포트: 압축률·분량 정확도·AI 판단 채택률 등. 편집 결과 원본 데이터(JSON)는 리포트 안 '개발자 정보'에. */

import { api, pollJob } from "../core/api.js";
import { $, el, setToggle, toast } from "../core/dom.js";
import { fmt } from "../core/format.js";
import { mutatePlan, on, pid, setProject, state } from "../core/store.js";

let renderJob = null;

function renderIssues() {
  const box = $("export-issues");
  box.innerHTML = "";
  if (!state.plan?.keep?.length) {
    box.appendChild(el("div", { class: "issue error" }, "결과에 남은 부분이 없어요. ②~④ 단계를 먼저 해 주세요."));
    return;
  }
  if (!state.issues.length) {
    box.appendChild(el("div", { class: "issue ok" }, "✓ 문제없어요. 바로 만들 수 있어요."));
    return;
  }
  for (const issue of state.issues) box.appendChild(el("div", { class: `issue ${issue.level}` }, issue.message));
}

function renderSettings() {
  const plan = state.plan;
  if (!plan) return;
  $("exp-resolution").value = String(plan.output.resolution >= 1080 ? 1080 : 720);
  $("exp-fps").value = String(plan.output.fps);
  $("exp-tempo").value = plan.options.max_pause === null ? "" : String(plan.options.max_pause);
  setToggle("exp-loudness", plan.options.loudness);
  setToggle("exp-punch", plan.options.punch_in);
  setToggle("exp-subtitles", plan.options.subtitles);
}

function renderSummary() {
  const plan = state.plan;
  if (!plan) return;
  $("export-summary").textContent = `${state.project.name} · 결과 ${fmt(plan.duration)} · ${plan.output.aspect === "9:16" ? "세로" : "가로"} `
    + `${plan.output.aspect} · 자막 ${plan.events.length}개`;
  const blocked = state.issues.some(i => i.level === "error") || !plan.keep.length;
  $("btn-render").disabled = blocked || !!renderJob;
  $("btn-render-preview").disabled = blocked || !!renderJob;
}

function renderRenders() {
  const list = $("render-list");
  list.innerHTML = "";
  for (const r of [...(state.project?.renders || [])].reverse()) {
    list.appendChild(el("div", { class: "render-item" },
      el("div", { class: "render-item-info" },
        el("b", {}, `${r.quality === "final" ? "최종 영상" : "빠른 확인용"} · ${fmt(r.duration)}`),
        el("span", {}, `${r.width}x${r.height} · ${(r.size_bytes / 1048576).toFixed(1)}MB · ${r.elapsed_sec}초 걸림`)),
      el("a", { href: r.url, download: "" }, "내려받기")));
  }
}

function refresh() {
  if (state.ui.step !== 5) return;
  renderIssues();
  renderSettings();
  renderSummary();
  renderRenders();
}

async function savePlan(body) {
  try {
    await mutatePlan(() => api.putPlan(pid(), body));
  } catch (err) { toast(err.message, "error"); }
}

export async function trackRender(job) {
  if (renderJob === job.job_id) return;
  renderJob = job.job_id;
  $("render-progress").style.display = "";
  renderSummary();
  const status = $("modal-status");
  status.textContent = "";
  let final;
  try {
    final = await pollJob(job.job_id, j => {
      $("render-stage").textContent = `${j.stage || "기다리는 중"} ${Math.round(j.progress)}%`;
      $("render-bar").style.width = `${j.progress}%`;
    });
  } catch (err) {
    final = { status: "failed", error: err.message };
  }
  renderJob = null;
  $("render-progress").style.display = "none";
  setProject(await api.getProject(pid()));
  if (final.status === "done") {
    const r = final.result.render;
    status.textContent = `다 만들었어요: ${fmt(r.duration)} (계획과 차이 ${r.error_ms}ms). 아래에서 내려받으세요.`;
    status.className = "modal-status ok";
    toast("영상을 다 만들었어요. ⑤ 내보내기에서 내려받으세요.", "ok");
  } else if (final.status === "failed") {
    status.textContent = `만들지 못했어요: ${final.error}`;
    status.className = "modal-status err";
    toast(`영상 만들기 실패: ${final.error}`, "error", 9000);
  } else {
    status.textContent = "멈췄어요.";
    status.className = "modal-status";
  }
  refresh();
}

async function startRender(quality) {
  $("btn-render").disabled = $("btn-render-preview").disabled = true;     // 응답 전 두 번 누르기 방지
  try {
    trackRender(await api.render(pid(), quality));
  } catch (err) {
    toast(err.message, "error");
    renderSummary();
  }
}

/* ---------------------------------------------------------------- 결과 리포트 */

function reportCard(label, value, desc, { unit = "", ok = false, wide = false } = {}) {
  return el("div", { class: `report-card${wide ? " wide" : ""}` },
    el("div", { class: "report-label" }, label),
    el("div", { class: `report-value${ok ? " ok" : ""}` }, value, unit ? el("small", {}, unit) : null),
    desc ? el("div", { class: "report-desc" }, desc) : null);
}

async function openReport() {
  $("report-modal").classList.remove("hidden");
  $("report-sub").textContent = state.project?.name || "";
  $("plan-json").textContent = JSON.stringify(state.plan, null, 2);
  const grid = $("report-grid");
  grid.innerHTML = "";
  let m;
  try { m = await api.metrics(pid()); } catch (err) {
    grid.appendChild(el("div", { class: "report-empty" }, `지표를 불러오지 못했어요: ${err.message}`));
    return;
  }
  const pct = v => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}`);
  grid.appendChild(reportCard("원본 → 결과", `${fmt(m.source_sec)} → ${fmt(m.output_sec)}`,
    m.compression !== undefined ? `결과가 원본의 ${pct(m.compression)}% 길이 (${100 - Number(pct(m.compression))}% 줄임)` : "", { wide: true }));
  if (m.target_ratio !== undefined && m.target_ratio !== null) {
    const ok = Math.abs(m.target_ratio - 1) <= (state.config?.target_tolerance ?? 0.05);
    grid.appendChild(reportCard("목표 길이 정확도", pct(m.target_ratio), "결과 길이 ÷ AI 가편집 목표 (100%가 정확)", { unit: "%", ok }));
  }
  if (m.lines !== undefined) grid.appendChild(reportCard("뺀 문장", `${m.lines_cut}`, `전체 ${m.lines}문장 중`, { unit: "개" }));
  if (m.decision_acceptance !== undefined && m.decision_acceptance !== null) {
    grid.appendChild(reportCard("AI 판단 채택률", pct(m.decision_acceptance), "AI·규칙 판단 중 사람이 뒤집지 않은 비율", { unit: "%" }));
  }
  if (m.selection_retention !== undefined && m.selection_retention !== null) {
    grid.appendChild(reportCard("AI 장면 선택 유지율", pct(m.selection_retention), "AI가 고른 장면 중 그대로 둔 비율", { unit: "%" }));
  }
  if (m.word_cuts !== undefined) {
    grid.appendChild(reportCard("단어 중간 컷", `${m.word_cuts}`, "말하는 단어 중간을 자른 곳 (0이 정상)", { unit: "곳", ok: m.word_cuts === 0 }));
  }
  if (m.render) {
    grid.appendChild(reportCard("렌더 길이 오차", `${m.render.error_ms}`, `계획과 실제 영상 길이 차이 · ${m.render.x_realtime}배속으로 만듦`,
      { unit: "ms", ok: Math.abs(m.render.error_ms) <= 34 }));
  }
  if (m.analysis) {
    grid.appendChild(reportCard("분석 시간", `${m.analysis.elapsed_sec}`, `원본 1분당 ${m.analysis.sec_per_source_min}초`, { unit: "초" }));
    grid.appendChild(reportCard("AI 요청 / 캐시 재사용", `${m.analysis.ai_usage?.requests ?? 0} / ${m.analysis.ai_usage?.cache_hits ?? 0}`,
      "같은 영상은 저장해 둔 결과를 다시 씀"));
  }
}

export function initExport() {
  $("btn-render").addEventListener("click", () => startRender("final"));
  $("btn-render-preview").addEventListener("click", () => startRender("preview"));
  $("btn-render-cancel").addEventListener("click", () => { if (renderJob) api.cancelJob(renderJob); });
  $("btn-report").addEventListener("click", () => openReport().catch(err => toast(err.message, "error")));
  document.querySelectorAll('[data-close="report-modal"]').forEach(n => n.addEventListener("click", () => $("report-modal").classList.add("hidden")));
  $("btn-copy-json").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(state.plan, null, 2)); toast("편집 결과 JSON을 복사했어요.", "ok"); }
    catch (err) { toast("복사하지 못했어요.", "error"); }
  });
  $("exp-resolution").addEventListener("change", e => savePlan({ output: { ...state.plan.output, resolution: Number(e.target.value) } }));
  $("exp-fps").addEventListener("change", e => savePlan({ output: { ...state.plan.output, fps: Number(e.target.value) } }));
  $("exp-tempo").addEventListener("change", e => savePlan({ options: { ...state.plan.options,
                                                                     max_pause: e.target.value === "" ? null : Number(e.target.value) } }));
  for (const [id, key] of [["exp-loudness", "loudness"], ["exp-punch", "punch_in"], ["exp-subtitles", "subtitles"]]) {
    $(id).addEventListener("click", () => {
      const value = !state.plan.options[key];
      setToggle(id, value);
      savePlan({ options: { ...state.plan.options, [key]: value } });
    });
  }
  on("plan", refresh);
  on("project", () => { if (state.ui.step === 5) renderRenders(); });
  on("step", async step => {
    if (step !== 5 || !pid()) return;
    try { const view = await api.getPlan(pid()); state.plan = view.plan; state.issues = view.issues; } catch (err) { /* 그대로 */ }
    refresh();
  });
}
