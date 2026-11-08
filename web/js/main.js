/* 시작점: 설정을 읽고, 마지막에 열었던 프로젝트를 다시 열고, 각 화면 모듈을 연결한다.
   프로젝트(영상)는 서버가 켜져 있는 동안에만 남는다 — 서버를 켜거나 끄면 서버가 모두 지운다. */

import { api } from "./core/api.js";
import { $, el, toast } from "./core/dom.js";
import { canRedo, canUndo, clearHistory, mutatePlan, on, pid, redo, selectLine, setProject, state, timelineClips,
         undo } from "./core/store.js";
import { initAnalysis, loadAnalysisAndPlan, showReviewTab, toggleSelectedLine, trackAnalysis,
         updateAnalyzeButton } from "./panels/analysis.js";
import { initExport, trackRender } from "./panels/export.js";
import { initMedia, resetMedia } from "./panels/media.js";
import { initMusic } from "./panels/music.js";
import { initPreview, togglePlay } from "./panels/preview.js";
import { initProfile, loadProfile } from "./panels/profile.js";
import { initSetup } from "./panels/setup.js";
import { goStep, initSteps, suggestedStep } from "./panels/steps.js";
import { initStylePanel, setActiveStyle } from "./panels/style-panel.js";
import { initTimeline, zoomToFit } from "./panels/timeline.js";

const PROJECT_KEY = "vibecut_project_id";

/* ---------------------------------------------------------------- 프로젝트 */

async function openProject(project) {
  try { localStorage.setItem(PROJECT_KEY, project.project_id); } catch (err) { /* 무시 */ }
  if (project.project_id !== pid()) resetMedia();
  clearHistory();
  state.analysis = null;
  state.ui.selectedClipId = null;
  state.ui.selectedLineId = null;
  setProject(project);
  await loadAnalysisAndPlan();
  zoomToFit();
  if (timelineClips()[0]) $("preview-empty").classList.add("hidden");
  for (const job of project.active_jobs || []) {
    if (job.kind === "analyze") trackAnalysis(job);
    if (job.kind === "render") trackRender(job);
  }
  goStep(suggestedStep());
  watchProject();
}

async function newProject() {
  const name = window.prompt("새 프로젝트 이름", "새 프로젝트");
  if (name === null) return;
  const project = await api.createProject(name.trim() || "새 프로젝트");
  const style = loadProfile().subtitle_style;
  await openProject(project);
  if (style) {
    await mutatePlan(() => api.putPlan(pid(), { styles: { ...state.plan.styles, subtitle: style } }), { record: false });
  }
}

async function toggleProjectMenu() {
  const menu = $("project-menu");
  if (!menu.classList.contains("hidden")) { menu.classList.add("hidden"); return; }
  menu.innerHTML = "";
  menu.appendChild(el("button", { class: "btn-primary project-menu-new",
                                  onclick: () => { menu.classList.add("hidden"); newProject().catch(e => toast(e.message, "error")); } },
                      "+ 새 프로젝트"));
  const projects = await api.listProjects().catch(() => []);
  for (const p of projects) {
    menu.appendChild(el("div", {
      class: `project-menu-item${p.project_id === pid() ? " current" : ""}`,
      onclick: async () => { menu.classList.add("hidden"); openProject(await api.getProject(p.project_id)); },
    }, el("span", {}, p.name), el("span", { class: "project-menu-meta" },
      `영상 ${p.clips}개 · ${p.analysis === "done" ? "분석함" : "분석 전"} · ${p.updated_at.slice(5, 16).replace("T", " ")}`)));
  }
  menu.classList.remove("hidden");
}

function renameProject() {
  const button = $("project-name");
  const input = el("input", { class: "project-name-input", value: state.project.name, maxlength: "80" });
  button.replaceWith(input);
  input.focus();
  input.select();
  let finished = false;
  const done = async save => {
    if (finished) return;
    finished = true;
    input.replaceWith(button);
    const name = input.value.trim();
    if (save && name && name !== state.project.name) {
      try { setProject(await api.patchProject(pid(), { name })); } catch (err) { toast(err.message, "error"); }
    }
  };
  input.addEventListener("keydown", e => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
  input.addEventListener("blur", () => done(true));
}

/* 프록시(미리보기 사본)·분석 같은 서버 작업이 도는 동안 프로젝트 상태를 가끔 다시 읽는다 */
let watching = false;
async function watchProject() {
  if (watching) return;
  watching = true;
  try {
    while (state.project && (state.project.active_jobs || []).some(j => j.kind === "proxy")) {
      await new Promise(r => setTimeout(r, 3000));
      setProject(await api.getProject(pid()));
    }
  } catch (err) {
    console.warn("[watch]", err);
  } finally {
    watching = false;
  }
}

/* ---------------------------------------------------------------- 상단 바 */

function renderTopbar() {
  const p = state.project;
  if (!p) return;
  $("project-name").textContent = p.name;
  const badge = $("ai-badge");
  const live = state.config?.ai_mode === "live";
  badge.className = `ai-badge ${live ? "live" : "offline"}`;
  badge.textContent = live ? "AI 연결됨" : "오프라인 모드";
  badge.title = live ? `Gemini · 글 판단 ${state.config.models.text} · 받아쓰기 ${state.config.models.stt}`
    : "Gemini 키가 없거나 VIBECUT_AI_MODE=offline — 규칙 판단과 로컬 엔진, 저장해 둔 AI 응답만 씁니다";
}

function renderHistoryButtons() {
  $("btn-undo").disabled = !canUndo();
  $("btn-redo").disabled = !canRedo();
}

/* 타임라인 '자막' 이름표 → ④ 확인·수정의 자막 모양 탭 */
function openSubtitleStyle() {
  goStep(4);
  if (!state.analysis) return;
  showReviewTab("style");
  setActiveStyle("subtitle");
}

/* ---------------------------------------------------------------- 시작 */

async function boot() {
  try {
    state.config = await api.config();
  } catch (err) {
    toast(err.message, "error", 15000);
    return;
  }
  if (!state.config.ffmpeg?.ok) toast(`ffmpeg 문제: ${state.config.ffmpeg?.error}`, "error", 15000);

  initSteps();
  initMedia();
  initTimeline();
  initPreview();
  initStylePanel();
  initAnalysis();
  initSetup();
  initProfile();
  initExport();
  initMusic();

  on("project", renderTopbar);
  on("history", renderHistoryButtons);
  on("project", () => { if (state.project?.active_jobs?.some(j => j.kind === "proxy")) watchProject(); });
  on("project", renderStep1);
  on("uploads", renderStep1);

  $("btn-project-menu").addEventListener("click", () => toggleProjectMenu().catch(e => toast(e.message, "error")));
  $("project-name").addEventListener("click", renameProject);
  $("btn-undo").addEventListener("click", () => undo().catch(e => toast(e.message, "error")));
  $("btn-redo").addEventListener("click", () => redo().catch(e => toast(e.message, "error")));
  $("sub-track-label").addEventListener("click", openSubtitleStyle);
  $("btn-step1-next").addEventListener("click", () => goStep(2));
  document.addEventListener("click", e => {
    const menu = $("project-menu");
    if (!menu.classList.contains("hidden") && !e.target.closest("#project-menu") && !e.target.closest("#btn-project-menu")) {
      menu.classList.add("hidden");
    }
  });
  document.addEventListener("keydown", e => {
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
    if (e.key === "Escape") {
      document.querySelectorAll(".modal").forEach(m => m.classList.add("hidden"));
      $("project-menu").classList.add("hidden");
      if (!typing && state.ui.selectedLineId) selectLine(null);
      return;
    }
    if (typing) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if ((e.key === "Delete" || e.key === "Backspace") && toggleSelectedLine()) e.preventDefault();
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      (e.shiftKey ? redo() : undo()).catch(err => toast(err.message, "error"));
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); redo().catch(err => toast(err.message, "error")); }
  });

  let project = null;                  // 새로고침: 열던 프로젝트 → 가장 최근 프로젝트 → 새 프로젝트
  const saved = (() => { try { return localStorage.getItem(PROJECT_KEY); } catch (err) { return null; } })();
  if (saved) project = await api.getProject(saved).catch(() => null);
  if (!project) {
    const list = await api.listProjects().catch(() => []);
    project = list.length ? await api.getProject(list[0].project_id) : await api.createProject("새 프로젝트");
  }
  await openProject(project);
  updateAnalyzeButton();
}

/* ① 영상 올리기: 지금 상태 한 줄 + '다음' 버튼 */
function renderStep1() {
  const clips = timelineClips();
  const box = $("step1-summary");
  const uploading = state.pendingUploads.length;
  box.textContent = uploading ? `영상 ${uploading}개를 올리는 중이에요…`
    : clips.length ? `타임라인에 영상 ${clips.length}개가 있어요. 순서가 맞으면 다음으로 넘어가세요.` : "";
  $("btn-step1-next").disabled = !clips.length || !!uploading;
}

boot();
