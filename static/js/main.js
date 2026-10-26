/* 시작점: 설정을 읽고, 마지막에 열었던 프로젝트를 다시 열고(서버에 저장돼 있음), 각 화면 모듈을 연결한다. */

import { api } from "./api.js";
import { initAnalysis, loadAnalysisAndPlan, setAiStage, trackAnalysis, updateAnalyzeButton } from "./analysis.js";
import { initExport, trackRender } from "./exporter.js";
import { initMedia } from "./media.js";
import { initPreview, togglePlay } from "./preview.js";
import { initProfile, loadProfile } from "./profile.js";
import { closeEditSetup, initSetup } from "./setup.js";
import { analysisReady, canRedo, canUndo, clearHistory, clipById, mutatePlan, on, pid, redo, setProject, state,
         timelineClips, undo } from "./store.js";
import { attachPane, detachPane, initStylePanel } from "./stylepanel.js";
import { initTimeline, zoomToFit } from "./timeline.js";
import { el, fmt, toast } from "./util.js";

const PROJECT_KEY = "vibecut_project_id";

/* ---------------------------------------------------------------- 프로젝트 */

async function openProject(project) {
  try { localStorage.setItem(PROJECT_KEY, project.project_id); } catch (err) { /* 무시 */ }
  clearHistory();
  state.analysis = null;
  setProject(project);
  await loadAnalysisAndPlan();
  setAiStage(analysisReady() ? "review" : "idle");
  zoomToFit();
  const first = timelineClips()[0];
  if (first) document.getElementById("preview-empty").classList.add("hidden");
  for (const job of project.active_jobs || []) {
    if (job.kind === "analyze") trackAnalysis(job);
    if (job.kind === "render") trackRender(job);
  }
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
  const menu = document.getElementById("project-menu");
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
      `클립 ${p.clips} · ${p.analysis === "done" ? "분석됨" : "분석 전"} · ${p.updated_at.slice(5, 16).replace("T", " ")}`)));
  }
  menu.classList.remove("hidden");
}

function renameProject() {
  const button = document.getElementById("project-name");
  const input = el("input", { class: "project-name-input", value: state.project.name, maxlength: "80" });
  button.replaceWith(input);
  input.focus();
  input.select();
  const done = async save => {
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

/* ---------------------------------------------------------------- 상단 바·객체 패널 */

function renderTopbar() {
  const p = state.project;
  if (!p) return;
  document.getElementById("project-name").textContent = p.name;
  const clips = timelineClips();
  const status = document.getElementById("topbar-status");
  if (!clips.length) status.textContent = "타임라인에 영상을 추가하세요";
  else if (state.plan) status.textContent = `클립 ${clips.length}개 · 결과 ${fmt(state.plan.duration)}`
    + (p.analysis.status === "done" ? (p.analysis_stale ? " · 타임라인이 바뀌어 다시 분석이 필요합니다" : " · 분석 완료") : " · 분석 전");
  const badge = document.getElementById("ai-badge");
  const live = state.config?.ai_mode === "live";
  badge.className = `ai-badge ${live ? "live" : "offline"}`;
  badge.textContent = live ? "AI: Gemini" : "AI: 오프라인";
  badge.title = live ? `글 판단 ${state.config.models.text} · 받아쓰기 ${state.config.models.stt}`
    : "Gemini 키가 없거나 VIBECUT_AI_MODE=offline — 규칙 판단과 로컬 엔진, 저장해 둔 AI 응답만 씁니다";
}

function renderHistoryButtons() {
  document.getElementById("btn-undo").disabled = !canUndo();
  document.getElementById("btn-redo").disabled = !canRedo();
}

function showClipPanel() {
  const panel = document.getElementById("obj-panel");
  const clip = clipById(state.ui.selectedClipId);
  if (!clip || document.body.classList.contains("setup-active")) {
    if (!document.getElementById("sub-style-pane").closest(".style-item-body")) detachPane();
    if (panel.dataset.mode !== "style") panel.classList.add("hidden");
    return;
  }
  detachPane();
  panel.dataset.mode = "clip";
  panel.classList.remove("hidden");
  document.getElementById("obj-tab-body").style.display = "";
  document.getElementById("obj-panel-name").textContent = clip.filename;
  const kept = (state.plan?.keep || []).filter(k => k.clip_id === clip.clip_id).reduce((a, k) => a + k.end - k.start, 0);
  const created = clip.created_at ? new Date(clip.created_at * 1000).toLocaleString("ko-KR") : "메타데이터 없음";
  const rows = [["길이", fmt(clip.duration)], ["사용 범위", `${fmt(clip.in_point)} ~ ${fmt(clip.out_point ?? clip.duration)}`],
                ["결과에 남는 길이", fmt(kept)], ["해상도", `${clip.width}x${clip.height} · ${clip.fps}fps`],
                ["소리", clip.has_audio ? "있음" : "없음"], ["촬영 시각", created], ["파일", clip.filename]];
  const box = document.getElementById("obj-tab-basic");
  box.innerHTML = "";
  for (const [k, v] of rows) box.appendChild(el("div", { class: "obj-prop" }, el("span", { class: "obj-prop-label" }, k),
                                               el("span", { class: "obj-prop-value" }, v)));
}

function showStylePanel() {
  if (document.body.classList.contains("setup-active")) return;
  const panel = document.getElementById("obj-panel");
  panel.dataset.mode = "style";
  panel.classList.remove("hidden");
  document.getElementById("obj-panel-name").textContent = "자막 스타일";
  document.getElementById("obj-tab-body").style.display = "none";
  attachPane(panel, "subtitle");
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

  initMedia();
  initTimeline();
  initPreview();
  initStylePanel();
  initAnalysis();
  initSetup();
  initProfile();
  initExport();

  on("project", renderTopbar);
  on("plan", renderTopbar);
  on("plan", showClipPanel);
  on("selection", showClipPanel);
  on("history", renderHistoryButtons);
  on("project", () => { if (state.project?.active_jobs?.some(j => j.kind === "proxy")) watchProject(); });

  document.getElementById("btn-project-menu").addEventListener("click", () => toggleProjectMenu().catch(e => toast(e.message, "error")));
  document.getElementById("project-name").addEventListener("click", renameProject);
  document.getElementById("btn-undo").addEventListener("click", () => undo().catch(e => toast(e.message, "error")));
  document.getElementById("btn-redo").addEventListener("click", () => redo().catch(e => toast(e.message, "error")));
  document.getElementById("sub-track-label").addEventListener("click", showStylePanel);
  document.addEventListener("click", e => {
    const menu = document.getElementById("project-menu");
    if (!menu.classList.contains("hidden") && !e.target.closest("#project-menu") && !e.target.closest("#btn-project-menu")) {
      menu.classList.add("hidden");
    }
  });
  document.addEventListener("keydown", e => {
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
    if (e.key === "Escape") {
      document.querySelectorAll(".modal").forEach(m => m.classList.add("hidden"));
      document.getElementById("project-menu").classList.add("hidden");
      return;
    }
    if (typing) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      (e.shiftKey ? redo() : undo()).catch(err => toast(err.message, "error"));
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); redo().catch(err => toast(err.message, "error")); }
  });

  let project = null;
  const saved = (() => { try { return localStorage.getItem(PROJECT_KEY); } catch (err) { return null; } })();
  if (saved) project = await api.getProject(saved).catch(() => null);
  if (!project) {
    const list = await api.listProjects().catch(() => []);
    project = list.length ? await api.getProject(list[0].project_id) : await api.createProject("새 프로젝트");
  }
  await openProject(project);
  updateAnalyzeButton();
  closeEditSetup();
}

boot();
