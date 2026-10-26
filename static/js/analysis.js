/* AI 분석 → 검토 → 수정 요청.
   분석은 타임라인의 클립 전체를 한 번에 한다 (받아쓰기 ∥ 장면 분석 → 컷 판단 → 4단 트리 → 편집 계획).
   진행률은 서버 작업(job)을 물어서 보여 주고, 새로고침해도 진행 중인 분석을 이어서 따라간다.
   검토 목록의 남김/자름·자막 수정은 바로 편집 계획에 반영된다 (실행취소 가능). */

import { api, pollJob } from "./api.js";
import { analysisReady, clipById, decisionOf, mutatePlan, on, pid, setAnalysis, setPlanView, setProject, state,
         timelineClips } from "./store.js";
import { loadProfile } from "./profile.js";
import { showSource } from "./preview.js";
import { el, fmt, toast } from "./util.js";

const STAGES = ["idle", "analyzing", "setup", "review", "chat"];
let trackedJob = null;
let reviewFilter = "all";

export function setAiStage(stage) {
  state.ui.aiStage = stage;
  STAGES.forEach(s => document.getElementById(`ai-${s}`).classList.toggle("hidden", s !== stage));
  document.getElementById("btn-ai-reset").classList.toggle("hidden", stage === "idle" || stage === "setup");
  if (stage === "review") renderReview();
  updateAnalyzeButton();
}

export function updateAnalyzeButton() {
  const btn = document.getElementById("btn-analyze");
  const hint = document.getElementById("analyze-hint");
  const clips = timelineClips();
  const status = state.project?.analysis?.status;
  hint.textContent = "";
  if (trackedJob) { btn.disabled = true; btn.textContent = "분석 중..."; return; }
  if (state.pendingUploads.length) { btn.disabled = true; btn.textContent = "업로드 중... (끝나면 켜집니다)"; return; }
  if (!clips.length) { btn.disabled = true; btn.textContent = "타임라인에 클립을 올리세요"; return; }
  btn.disabled = false;
  if (status === "done" && !state.project.analysis_stale) {
    btn.textContent = "다시 분석";
    hint.textContent = "분석 결과가 있습니다. 같은 클립은 저장해 둔 결과를 다시 써서 빠릅니다.";
  } else if (status === "done") {
    btn.textContent = `다시 분석 (타임라인 바뀜 · 클립 ${clips.length}개)`;
    hint.textContent = "타임라인이 분석 때와 달라졌습니다. 새 클립은 다시 분석해야 자막·컷이 생깁니다.";
  } else {
    btn.textContent = `AI 분석 시작 (클립 ${clips.length}개)`;
    if (status === "failed") hint.textContent = (state.project.analysis.warnings || []).join("\n");
  }
  const mode = state.config?.ai_mode === "live" ? "Gemini 받아쓰기·장면 분석" : "오프라인 모드 (규칙·로컬 엔진)";
  hint.textContent = `${hint.textContent}${hint.textContent ? "\n" : ""}${mode}`;
}

/* ---------------------------------------------------------------- 분석 */

export async function loadAnalysisAndPlan() {
  const status = state.project?.analysis?.status;
  let analysis = null;
  if (status === "done" || status === "failed") {      // 분석한 적이 없으면 묻지 않는다 (불필요한 404)
    analysis = await api.getAnalysis(pid()).catch(() => null);
  }
  setAnalysis(analysis);
  setPlanView(await api.getPlan(pid()));
}

async function startAnalysis() {
  try {
    const job = await api.analyze(pid(), loadProfile());
    trackAnalysis(job);
  } catch (err) {
    toast(err.message, "error");
  }
}

export async function trackAnalysis(job) {
  if (trackedJob === job.job_id) return;
  trackedJob = job.job_id;
  setAiStage("analyzing");
  const stageEl = document.getElementById("progress-stage");
  const bar = document.getElementById("progress-bar-fill");
  const msg = document.getElementById("progress-message");
  let final;
  try {
    final = await pollJob(job.job_id, j => {
      stageEl.textContent = `${Math.round(j.progress)}%  ${j.stage || "대기 중"}`;
      bar.style.width = `${j.progress}%`;
      msg.textContent = j.message || "";
    });
  } catch (err) {
    final = { status: "failed", error: err.message };
  }
  trackedJob = null;
  setProject(await api.getProject(pid()));
  if (final.status === "done") {
    await loadAnalysisAndPlan();
    const r = final.result || {};
    toast(`분석 완료: 문장 ${r.lines}개 (자름 제안 ${r.cut_suggested}개), 장면 ${r.scenes}개`, "ok");
    setAiStage("review");
  } else {
    if (final.status === "failed") toast(`분석 실패: ${final.error}`, "error", 9000);
    setAiStage(analysisReady() ? "review" : "idle");
  }
}

/* ---------------------------------------------------------------- 검토 */

const SOURCE_LABEL = { ai: "AI", rule: "규칙", user: "내가 바꿈" };

function reviewCard() {
  const card = document.getElementById("review-card");
  card.innerHTML = "";
  const a = state.analysis, plan = state.plan;
  if (!a || !plan) return;
  const lines = a.lines;
  const cut = lines.filter(l => !decisionOf(l.seg_id).keep);
  const reasons = {};
  for (const l of cut) { const r = decisionOf(l.seg_id).reason; reasons[r] = (reasons[r] || 0) + 1; }
  const source = timelineClips().reduce((s, c) => s + ((c.out_point ?? c.duration) - c.in_point), 0);
  const engines = a.engines || {};
  card.append(
    el("div", {}, "원본 ", el("b", {}, fmt(source)), " → 결과 ", el("b", {}, fmt(plan.duration)),
       ` (구간 ${plan.keep.length}개, 자막 ${plan.events.length}개)`),
    el("div", {}, `문장 ${lines.length}개 중 자름 ${cut.length}개`,
       Object.keys(reasons).length ? ` — ${Object.entries(reasons).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""),
    el("div", { style: { color: "var(--muted)", fontSize: "10px" } },
       `받아쓰기 ${engines.stt || "-"} · 장면 ${engines.scenes || "-"} · 컷 판단 ${engines.judge === "ai" ? "Gemini+규칙" : "규칙"}`),
  );
  for (const w of [...(state.project?.analysis?.warnings || []), ...(plan.warnings || [])].slice(0, 4)) {
    card.appendChild(el("div", { class: "warn" }, `! ${w}`));
  }
}

function lineItem(line) {
  const d = decisionOf(line.seg_id);
  const toggle = el("button", { class: `seg-toggle ${d.keep ? "seg-keep" : "seg-cut"}`,
                                title: d.keep ? "자르기" : "남기기" }, d.keep ? "남김" : "자름");
  toggle.addEventListener("click", () => setLine(line.seg_id, { keep: !d.keep }));
  const clip = clipById(line.clip_id);
  const time = el("span", { class: "seg-time", title: "클릭: 이 문장 재생" }, `${fmt(line.start)}\n${fmt(line.end)}`);
  time.addEventListener("click", () => showSource(line.clip_id, Math.max(0, line.start - 0.3), true));
  const text = el("textarea", { class: "seg-text", rows: "1", placeholder: "(받아쓰기 없음)" });
  text.value = d.text || line.text;
  text.addEventListener("input", function () { this.style.height = "auto"; this.style.height = `${this.scrollHeight}px`; });
  text.addEventListener("change", () => {
    const value = text.value.trim();
    if (value === (d.text || line.text)) return;
    setLine(line.seg_id, { text: value === line.text ? "" : value });
  });
  // 배지: [색 종류, 글자]. 남긴 문장은 강조·핵심·일반, 자른 문장은 자른 이유
  const [kind, label] = !d.keep ? [d.reason, d.reason]
    : d.emphasis ? ["핵심", "강조"] : [d.reason === "핵심" ? "핵심" : "일반", d.reason];
  const side = el("div", { class: "seg-side" },
    el("span", { class: `seg-reason reason-${kind}`, title: d.note || "" }, label),
    el("span", { class: "seg-source", title: clip?.filename || "" }, SOURCE_LABEL[d.source] || d.source));
  return el("div", { class: `seg-item${d.keep ? "" : " is-cut"}`, dataset: { seg: line.seg_id } }, toggle, time, text, side);
}

export function renderReview() {
  reviewCard();
  const list = document.getElementById("review-segs-list");
  list.innerHTML = "";
  const lines = state.analysis?.lines || [];
  document.getElementById("review-seg-count").textContent = String(lines.length);
  const filtered = lines.filter(l => {
    const d = decisionOf(l.seg_id);
    if (reviewFilter === "cut") return !d.keep;
    if (reviewFilter === "emph") return d.keep && d.emphasis;
    if (reviewFilter === "user") return d.source === "user";
    return true;
  });
  for (const line of filtered.slice(0, 600)) list.appendChild(lineItem(line));
  if (filtered.length > 600) list.appendChild(el("div", { class: "analysis-hint" }, `… ${filtered.length - 600}개 더 있음 (필터로 좁히세요)`));
  requestAnimationFrame(() => list.querySelectorAll(".seg-text").forEach(t => { t.style.height = `${t.scrollHeight}px`; }));
}

async function setLine(segId, change) {
  try {
    await mutatePlan(() => api.patchLines(pid(), [{ seg_id: segId, ...change }]));
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ---------------------------------------------------------------- 수정 요청 (채팅) */

function addChatMsg(role, text) {
  const box = document.getElementById("chat-messages");
  const node = el("div", { class: `msg msg-${role}` }, text);
  box.appendChild(node);
  box.scrollTop = box.scrollHeight;
  return node;
}

async function sendRevise(instruction) {
  if (!analysisReady()) { addChatMsg("err", "먼저 AI 분석을 해 주세요."); return; }
  addChatMsg("user", instruction);
  const thinking = addChatMsg("ai", "처리 중...");
  try {
    const view = await mutatePlan(() => api.revise(pid(), { instruction, profile: loadProfile() }));
    thinking.textContent = `${view.message} (문장 ${view.changed}개 바뀜 · 결과 ${fmt(view.plan.duration)})`;
  } catch (err) {
    thinking.className = "msg msg-err";
    thinking.textContent = `수정 실패: ${err.message}`;
  }
}

/* ---------------------------------------------------------------- 초기화 */

export function initAnalysis() {
  document.getElementById("btn-analyze").addEventListener("click", startAnalysis);
  document.getElementById("btn-analyze-cancel").addEventListener("click", async () => {
    if (trackedJob) await api.cancelJob(trackedJob).catch(err => toast(err.message, "error"));
  });
  document.getElementById("btn-ai-reset").addEventListener("click", () => setAiStage("idle"));
  document.getElementById("btn-apply").addEventListener("click", () => setAiStage("chat"));
  document.querySelectorAll("#review-filters button").forEach(btn => btn.addEventListener("click", () => {
    reviewFilter = btn.dataset.filter;
    document.querySelectorAll("#review-filters button").forEach(b => b.classList.toggle("active", b === btn));
    renderReview();
  }));
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  form.addEventListener("submit", e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    sendRevise(text);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  document.querySelectorAll(".btn-quick").forEach(btn => btn.addEventListener("click", () => {
    if (btn.dataset.review) setAiStage("review");
    else sendRevise(btn.dataset.cmd);
  }));
  on("project", updateAnalyzeButton);
  on("uploads", updateAnalyzeButton);
  on("plan", () => { if (state.ui.aiStage === "review") renderReview(); });
  on("timeline-changed", async () => {
    try { setPlanView(await api.getPlan(pid())); } catch (err) { toast(err.message, "error"); }
  });
}
