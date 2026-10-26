/* 내보내기: 렌더 전 검사 → 설정 → 렌더(진행률·취소) → 결과 다운로드 → 평가 지표.
   렌더는 서버 작업이라 창을 닫거나 새로고침해도 계속되고, 다시 열면 이어서 진행률을 보여 준다. */

import { api, pollJob } from "./api.js";
import { mutatePlan, on, pid, setProject, state } from "./store.js";
import { el, fmt, setToggle, toast } from "./util.js";

let renderJob = null;

const $ = id => document.getElementById(id);

function setHidden(hidden) {
  $("export-modal").classList.toggle("hidden", hidden);
}

function renderIssues() {
  const box = $("export-issues");
  box.innerHTML = "";
  if (!state.issues.length) {
    box.appendChild(el("div", { class: "issue warning", style: { color: "#5ca85c", background: "rgba(92,168,92,.1)" } },
                       "문제 없음"));
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
  $("modal-sub").textContent = `${state.project.name} · 결과 ${fmt(plan.duration)} · 구간 ${plan.keep.length}개 · `
    + `자막 ${plan.events.length}개 · ${plan.output.aspect}`;
  $("plan-json").textContent = JSON.stringify(plan, null, 2);
  const blocked = state.issues.some(i => i.level === "error") || !plan.keep.length;
  $("btn-render").disabled = blocked || !!renderJob;
  $("btn-render-preview").disabled = blocked || !!renderJob;
}

function renderRenders() {
  const list = $("render-list");
  list.innerHTML = "";
  const renders = state.project?.renders || [];
  if (!renders.length) {
    list.appendChild(el("div", { class: "analysis-hint", style: { textAlign: "left" } }, "아직 렌더한 결과가 없습니다."));
    return;
  }
  for (const r of renders) {
    list.appendChild(el("div", { class: "render-item" },
      el("span", {}, r.quality === "final" ? "최종" : "미리보기"),
      el("span", { class: "meta" }, `${r.width}x${r.height} · ${fmt(r.duration)} · 계획과 차이 ${r.error_ms >= 0 ? "+" : ""}${r.error_ms}ms`
        + ` · ${r.elapsed_sec}초 걸림 · ${(r.size_bytes / 1048576).toFixed(1)}MB`),
      el("a", { href: r.url, download: "" }, "다운로드")));
  }
}

async function renderMetrics() {
  const table = $("metrics-table");
  table.innerHTML = "";
  let m;
  try { m = await api.metrics(pid()); } catch (err) { return; }
  const pct = v => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`);
  const rows = [
    ["원본 → 결과", `${fmt(m.source_sec)} → ${fmt(m.output_sec)} (압축률 ${pct(m.compression)})`],
    m.target_ratio !== undefined ? ["분량 정확도 (결과/목표)", pct(m.target_ratio)] : null,
    m.lines !== undefined ? ["문장 / 자른 문장", `${m.lines} / ${m.lines_cut}`] : null,
    m.decision_acceptance !== undefined ? ["AI 판단 채택률 (안 뒤집은 비율)", pct(m.decision_acceptance)] : null,
    m.selection_retention !== undefined ? ["AI 장면 선택 유지율", pct(m.selection_retention)] : null,
    m.word_cuts !== undefined ? ["단어 중간 컷", `${m.word_cuts}곳`] : null,
    m.render ? ["최종 렌더 길이 오차", `${m.render.error_ms}ms (렌더 ${m.render.x_realtime}배속)`] : null,
    m.analysis ? ["분석 시간", `${m.analysis.elapsed_sec}초 (원본 1분당 ${m.analysis.sec_per_source_min}초)`] : null,
    m.analysis ? ["AI 요청 / 캐시 재사용", `${m.analysis.ai_usage?.requests ?? 0} / ${m.analysis.ai_usage?.cache_hits ?? 0}`] : null,
  ].filter(Boolean);
  for (const [k, v] of rows) table.appendChild(el("tr", {}, el("td", {}, k), el("td", {}, v)));
}

export async function openExportModal() {
  setHidden(false);
  try {
    const view = await api.getPlan(pid());
    state.plan = view.plan;
    state.issues = view.issues;
  } catch (err) { toast(err.message, "error"); }
  renderIssues();
  renderSettings();
  renderSummary();
  renderRenders();
  renderMetrics();
}

async function savePlan(body) {
  try {
    await mutatePlan(() => api.putPlan(pid(), body));
    renderIssues();
    renderSummary();
  } catch (err) { toast(err.message, "error"); }
}

export async function trackRender(job) {
  if (renderJob === job.job_id) return;
  renderJob = job.job_id;
  $("render-progress").style.display = "";
  renderSummary();
  const status = $("modal-status");
  let final;
  try {
    final = await pollJob(job.job_id, j => {
      $("render-stage").textContent = `${j.stage || "대기 중"} ${Math.round(j.progress)}%`;
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
    status.textContent = `렌더 완료: ${fmt(r.duration)} (계획과 차이 ${r.error_ms}ms)`;
    status.className = "modal-status ok";
    toast("렌더가 끝났습니다. 내보내기 창에서 다운로드하세요.", "ok");
  } else if (final.status === "failed") {
    status.textContent = `렌더 실패: ${final.error}`;
    status.className = "modal-status err";
    toast(`렌더 실패: ${final.error}`, "error", 9000);
  } else {
    status.textContent = "렌더를 취소했습니다.";
    status.className = "modal-status";
  }
  renderSummary();
  renderRenders();
  renderMetrics();
}

async function startRender(quality) {
  try {
    trackRender(await api.render(pid(), quality));
  } catch (err) {
    toast(err.message, "error");
  }
}

export function initExport() {
  $("btn-export").addEventListener("click", openExportModal);
  for (const id of ["modal-close", "modal-backdrop"]) $(id).addEventListener("click", () => setHidden(true));
  $("btn-render").addEventListener("click", () => startRender("final"));
  $("btn-render-preview").addEventListener("click", () => startRender("preview"));
  $("btn-render-cancel").addEventListener("click", () => { if (renderJob) api.cancelJob(renderJob); });
  $("btn-copy-json").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(state.plan, null, 2)); toast("편집 계획 JSON을 복사했습니다.", "ok"); }
    catch (err) { toast("복사하지 못했습니다.", "error"); }
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
  on("plan", () => {
    $("btn-export").disabled = !state.plan?.keep?.length;
    if (!$("export-modal").classList.contains("hidden")) { renderIssues(); renderSettings(); renderSummary(); }
  });
}
