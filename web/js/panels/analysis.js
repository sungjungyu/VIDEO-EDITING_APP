/* ② AI 분석 · ④ 확인·수정 (결과 카드 · 문장 목록 · AI에게 수정 요청).
   분석은 타임라인의 클립 전체를 한 번에 한다 (받아쓰기 ∥ 장면 분석 → 컷 판단 → 장면 나누기(비트) → 편집 결과).
   진행률은 서버 작업(job)을 물어서 단계 목록에 보여 주고, 새로고침해도 진행 중인 분석을 이어서 따라간다.
   문장 목록의 살림/뺌·자막 글자 수정은 바로 편집 결과에 반영된다 (되돌리기 가능).
   수정 요청 뒤에는 무엇이 바뀌었는지(뺀 문장·살린 문장·글자 수정) 보여 주고, 바뀐 문장을 잠깐 반짝인다.
   결과 카드 맨 아래 '평가용 정답': 문장을 다 검수한 뒤 지금 살림/뺌을 정답으로 저장한다 (vibecut bench가 채점에 쓴다). */

import { api, pollJob } from "../core/api.js";
import { $, el, toast } from "../core/dom.js";
import { fmt } from "../core/format.js";
import { CUT_LABEL, cutReason, KEEP_LABEL, REASON_HELP, reasonLabel, SOURCE_LABEL } from "../core/labels.js";
import { analysisReady, clipById, decisionOf, emit, mutatePlan, on, pid, selectLine, setAnalysis, setPlanView,
         setProject, sourceDuration, state, timelineClips } from "../core/store.js";
import { showSource } from "./preview.js";
import { loadProfile } from "./profile.js";
import { goStep } from "./steps.js";

let trackedJob = null;
let reviewFilter = "all";        // all | cut | emph | user | reason:<이유>
let reviewTab = "lines";
let benchInfo = { project: null, saved: false };   // 이 프로젝트를 평가용 정답으로 저장했는지

/* ---------------------------------------------------------------- ② 분석 */

/* 서버 진행률 구간 (services/analysis.py): 소리 0~8 · 받아쓰기·장면 8~75 · 컷 판단 76 · 장면 나누기 91 · 편집 결과 96 */
function pipelineIndex(progress) {
  if (progress < 8) return 0;
  if (progress < 76) return 1;
  if (progress < 91) return 2;
  if (progress < 96) return 3;
  return 4;
}

function renderPipeline() {
  const running = state.ui.analyzing;
  const finished = analysisReady() && !state.project?.analysis_stale;
  const now = running ? pipelineIndex(running.progress) : -1;
  document.querySelectorAll("#pipeline li").forEach(li => {
    const i = Number(li.dataset.stage);
    li.classList.toggle("now", running && i === now);
    li.classList.toggle("done", running ? i < now : finished);
  });
  $("analyze-progress").classList.toggle("hidden", !running);
}

export function updateAnalyzeButton() {
  const btn = $("btn-analyze");
  const next = $("btn-step2-next");
  const hint = $("analyze-hint");
  const clips = timelineClips();
  const status = state.project?.analysis?.status;
  const fresh = status === "done" && !state.project.analysis_stale;
  const mode = state.config?.ai_mode === "live" ? "Gemini로 받아쓰기·장면 이해" : "오프라인 모드 (규칙 판단·로컬 엔진)";
  btn.className = fresh ? "btn-ghost btn-block" : "btn-next";
  next.classList.toggle("hidden", !fresh || !!trackedJob);
  $("btn-analyze-cancel").classList.toggle("hidden", !trackedJob);
  btn.classList.toggle("hidden", !!trackedJob);
  renderPipeline();
  if (trackedJob) { hint.textContent = "분석하는 동안 다른 단계를 둘러봐도 괜찮아요."; return; }
  if (state.pendingUploads.length) {
    btn.disabled = true; btn.textContent = "영상 올리는 중… 끝나면 시작할 수 있어요"; hint.textContent = ""; return;
  }
  if (!clips.length) {
    btn.disabled = true; btn.textContent = "먼저 영상을 올려 주세요"; hint.textContent = "① 영상 올리기에서 영상을 넣으면 시작할 수 있어요."; return;
  }
  btn.disabled = false;
  if (fresh) {
    btn.textContent = "다시 분석하기";
    hint.textContent = `분석이 끝났어요. 같은 영상은 저장해 둔 결과를 다시 써서 빨라요.\n${mode}`;
  } else if (status === "done") {
    btn.textContent = `다시 분석하기 (영상 ${clips.length}개)`;
    hint.textContent = "타임라인이 분석 때와 달라졌어요. 새로 넣은 영상은 다시 분석해야 자막과 컷이 생깁니다.";
  } else {
    btn.textContent = `AI 분석 시작 (영상 ${clips.length}개)`;
    const failed = status === "failed" ? `지난 분석 실패: ${(state.project.analysis.warnings || []).join(" ")}\n` : "";
    hint.textContent = `${failed}${mode}`;
  }
}

export async function loadAnalysisAndPlan() {
  const status = state.project?.analysis?.status;
  let analysis = null;
  if (status === "done" || status === "failed") {      // 분석한 적이 없으면 묻지 않는다 (불필요한 404)
    analysis = await api.getAnalysis(pid()).catch(() => null);
  }
  benchInfo = { project: pid(), saved: false };
  if (analysis) benchInfo = { project: pid(), ...(await api.getBenchCase(pid()).catch(() => ({ saved: false }))) };
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
  state.ui.analyzing = { progress: job.progress || 0, stage: job.stage || "" };
  emit("analyzing");
  updateAnalyzeButton();
  let final;
  try {
    final = await pollJob(job.job_id, j => {
      state.ui.analyzing = { progress: j.progress || 0, stage: j.stage || "" };
      $("progress-stage").textContent = `${Math.round(j.progress)}%  ${j.stage || "기다리는 중"}`;
      $("progress-bar-fill").style.width = `${j.progress}%`;
      $("progress-message").textContent = j.message || "";
      renderPipeline();
      emit("analyzing");
    });
  } catch (err) {
    final = { status: "failed", error: err.message };
  }
  trackedJob = null;
  state.ui.analyzing = null;
  setProject(await api.getProject(pid()));
  if (final.status === "done") {
    await loadAnalysisAndPlan();
    const r = final.result || {};
    toast(`분석 완료: 문장 ${r.lines}개 중 ${r.cut_suggested}개를 빼자고 제안해요 · 장면 ${r.scenes}개`, "ok", 6000);
    if (state.ui.step === 2) goStep(3);
  } else if (final.status === "failed") {
    toast(`분석 실패: ${final.error}`, "error", 9000);
  }
  emit("analyzing");
  updateAnalyzeButton();
}

/* ---------------------------------------------------------------- ④ 결과 카드 */

function cutStats() {
  const lines = state.analysis?.lines || [];
  const reasons = {};
  let cut = 0, emph = 0, user = 0;
  for (const l of lines) {
    const d = decisionOf(l.seg_id);
    if (!d.keep) { cut += 1; reasons[cutReason(d)] = (reasons[cutReason(d)] || 0) + 1; }
    else if (d.emphasis) emph += 1;
    if (d.source === "user") user += 1;
  }
  return { total: lines.length, cut, emph, user, reasons };
}

function setFilter(filter) {
  reviewFilter = reviewFilter === filter && filter !== "all" ? "all" : filter;
  if (reviewTab !== "lines") showReviewTab("lines");
  renderResultCard();
  renderReview();
}

function renderResultCard() {
  const card = $("result-card");
  card.innerHTML = "";
  const a = state.analysis, plan = state.plan;
  if (!a || !plan) return;
  const source = sourceDuration();
  const s = cutStats();
  const sel = plan.selection || {};
  const ratio = source ? Math.min(1, plan.duration / source) : 0;

  card.appendChild(el("div", { class: "rc-durations" },
    "원본", el("b", {}, fmt(source)), el("span", { class: "rc-arrow" }, "→"), "결과", el("b", {}, fmt(plan.duration)),
    source ? el("span", {}, `(${Math.round((1 - ratio) * 100)}% 줄임)`) : null));
  card.appendChild(el("div", { class: "rc-bar" }, el("div", { style: { width: `${ratio * 100}%` } })));

  if (sel.mode === "auto" && sel.target_sec) {
    const diff = plan.duration / sel.target_sec - 1;
    const ok = Math.abs(diff) <= (state.config?.target_tolerance ?? 0.05);
    card.appendChild(el("div", { class: "rc-line" }, "AI 가편집 목표 ", el("b", {}, fmt(sel.target_sec)), " · 차이 ",
      el("b", { class: ok ? "ok" : "off" }, `${diff >= 0 ? "+" : ""}${(diff * 100).toFixed(1)}%${ok ? " ✓" : ""}`)));
  } else if (sel.mode === "manual") {
    card.appendChild(el("div", { class: "rc-line" }, `직접 고른 장면 ${(sel.beat_ids || []).length}개로 만들었어요`));
  }

  card.appendChild(el("div", { class: "rc-line" }, `문장 ${s.total}개 중 `, el("b", {}, `${s.cut}개`), "를 뺐어요"));
  const chips = el("div", { class: "rc-chips" });
  for (const [reason, n] of Object.entries(s.reasons).sort((x, y) => y[1] - x[1])) {
    const f = `reason:${reason}`;
    chips.appendChild(el("button", { class: `chip reason-${reason}${reviewFilter === f ? " active" : ""}`,
                                     title: `${REASON_HELP[reason] || ""} · 눌러서 이것만 보기`, onclick: () => setFilter(f) },
                         `${reasonLabel(reason)} ${n}`));
  }
  if (s.emph) {
    chips.appendChild(el("button", { class: `chip reason-강조${reviewFilter === "emph" ? " active" : ""}`,
                                     title: "강조 문장 (내보낼 때 살짝 확대) · 눌러서 이것만 보기", onclick: () => setFilter("emph") },
                         `강조 ${s.emph}`));
  }
  if (chips.children.length) card.appendChild(chips);

  const engines = a.engines || {};
  card.appendChild(el("div", { class: "rc-meta" },
    `받아쓰기 ${engines.stt || "-"} · 장면 ${engines.scenes || "-"} · 컷 판단 ${judgeLabel(engines)}`));
  for (const w of [...(state.project?.analysis?.warnings || []), ...(plan.warnings || [])].slice(0, 3)) {
    card.appendChild(el("div", { class: "rc-warn" }, `! ${w}`));
  }
  card.appendChild(benchBox());
}

function judgeLabel(engines) {
  if (engines.judge === "ai") return "Gemini + 규칙";
  if (engines.judge === "hybrid") return `규칙 + Gemini (애매한 문장 ${engines.judge_asked || ""}만)`;
  return "규칙";
}

/* 평가용 정답 저장 (접어 둔 상자). 정답 = 지금 화면의 살림/뺌 → 모든 문장을 검수한 뒤에 누른다 */
function benchBox() {
  const info = benchInfo.project === pid() ? benchInfo : { saved: false };
  const person = el("input", { class: "bench-input", placeholder: "찍은 사람 (선택)", maxlength: "40", value: info.person || "" });
  const split = el("select", { class: "bench-input" },
    el("option", { value: "test", selected: info.split !== "tune" }, "시험용 (결과 보고)"),
    el("option", { value: "tune", selected: info.split === "tune" }, "조정용 (기준값 맞추기)"));
  const save = el("button", { class: "btn-mini", onclick: async () => {
    save.disabled = true;
    try {
      const out = await api.saveBenchCase(pid(), { name: state.project.name, person: person.value, split: split.value,
                                                   profile: loadProfile() });
      benchInfo = { project: pid(), ...out };
      toast(`평가용 정답으로 저장했어요 (문장 ${out.sentences}개, 뺀 문장 ${out.gold_cut}개)`, "ok");
      renderResultCard();
    } catch (err) {
      toast(err.message, "error");
      save.disabled = false;
    }
  } }, info.saved ? "다시 저장 (덮어쓰기)" : "검수 완료 → 정답으로 저장");
  return el("details", { class: "bench-box" },
    el("summary", {}, info.saved ? `평가용 정답 저장됨 · 문장 ${info.sentences}개` : "평가용 정답 (선택)"),
    el("div", { class: "bench-help" }, "모든 문장의 살림/뺌을 사람이 확인한 뒤 저장하세요. 지금 화면의 살림/뺌이 그대로 정답이 됩니다. " +
       "영상은 저장하지 않고 받아쓰기 문장만 data/bench에 남습니다 (vibecut bench로 채점)."),
    el("div", { class: "bench-row" }, person, split, save));
}

/* ---------------------------------------------------------------- ④ 문장 목록 */

function renderFilters() {
  const box = $("review-filters");
  box.innerHTML = "";
  const s = cutStats();
  const items = [["all", `전체 ${s.total}`], ["cut", `뺀 문장 ${s.cut}`], ["emph", `강조 ${s.emph}`], ["user", `내가 바꾼 것 ${s.user}`]];
  if (reviewFilter.startsWith("reason:")) items.push([reviewFilter, `${reasonLabel(reviewFilter.slice(7))}만 ×`]);
  for (const [key, label] of items) {
    box.appendChild(el("button", { class: reviewFilter === key ? "active" : "", onclick: () => setFilter(key) }, label));
  }
}

function lineItem(line) {
  const d = decisionOf(line.seg_id);
  const toggle = el("button", { class: `seg-toggle ${d.keep ? "seg-keep" : "seg-cut"}`,
                                title: d.keep ? "누르면 이 문장을 뺍니다" : "누르면 이 문장을 살립니다" }, d.keep ? KEEP_LABEL : CUT_LABEL);
  toggle.addEventListener("click", () => setLine(line.seg_id, { keep: !d.keep }));
  const clip = clipById(line.clip_id);
  const time = el("span", { class: "seg-time", title: `${clip?.filename || ""} · 눌러서 이 문장 듣기` },
                  `▶ ${fmt(line.start)}`);
  time.addEventListener("click", () => showSource(line.clip_id, Math.max(0, line.start - 0.3), true));
  const text = el("textarea", { class: "seg-text", rows: "1", placeholder: "(받아쓰기 없음)", title: "눌러서 자막 글자 고치기" });
  text.value = d.text || line.text;
  text.addEventListener("input", function () { this.style.height = "auto"; this.style.height = `${this.scrollHeight}px`; });
  text.addEventListener("focus", () => { if (state.ui.selectedLineId !== line.seg_id) selectLine(line, "list"); });
  text.addEventListener("change", () => {
    const value = text.value.trim();
    if (value === (d.text || line.text)) return;
    setLine(line.seg_id, { text: value === line.text ? "" : value });
  });
  const reason = cutReason(d);
  const tag = !d.keep ? el("span", { class: `seg-reason reason-${reason}` }, reasonLabel(reason))
    : d.emphasis ? el("span", { class: "seg-reason reason-강조" }, "강조") : null;
  const note = !d.keep ? (reason === "직접" ? REASON_HELP.직접 : d.note || REASON_HELP[reason] || "") : "";
  const sub = el("div", { class: "seg-sub" }, time, tag, note ? el("span", { class: "seg-note", title: note }, note) : null,
                 el("span", {}, `· ${SOURCE_LABEL[d.source] || d.source}`));
  const row = el("div", { class: `seg-item${d.keep ? "" : " is-cut"}${state.ui.flash.has(line.seg_id) ? " flash" : ""}`
                                 + `${state.ui.selectedLineId === line.seg_id ? " selected" : ""}`,
                          dataset: { seg: line.seg_id } }, toggle, el("div", { class: "seg-main" }, text, sub));
  row.addEventListener("click", e => {          // 줄의 빈 곳을 누르면 고르기 (버튼·글자 칸은 각자 동작)
    if (!e.target.closest("button, textarea, .seg-time")) selectLine(line, "list");
  });
  return row;
}

/* 고른 문장이 목록에 보이게: ④ 문장 목록 탭으로, 필터에 걸려 안 보이면 '전체'로 */
function showLineInList(line, edit = false) {
  if (!analysisReady()) return;
  if (state.ui.step !== 4) goStep(4);
  if (reviewTab !== "lines") showReviewTab("lines");
  if (!matches(line)) { reviewFilter = "all"; renderResultCard(); }
  renderReview();
  markSelectedRow();
  const row = $("review-segs-list").querySelector(`.seg-item[data-seg="${CSS.escape(line.seg_id)}"]`);
  if (!row) return;
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  if (edit) {
    const text = row.querySelector(".seg-text");
    text.focus();
    text.setSelectionRange(text.value.length, text.value.length);
  }
}

/* Delete 키: 고른 문장 빼기/살리기 */
export function toggleSelectedLine() {
  const id = state.ui.selectedLineId;
  if (!id || !analysisReady()) return false;
  setLine(id, { keep: !decisionOf(id).keep });
  return true;
}

/* 같은 문장들이 그대로 보이는 중이면(필터·분석이 그대로) 판단이 바뀐 줄만 바꿔 끼운다
   (문장 하나를 바꿀 때마다 600줄을 다시 만들고 줄마다 높이를 다시 재지 않게) */
const MAX_REVIEW_ROWS = 600;
const shown = { key: "", rows: new Map(), signatures: new Map() };

function decisionSignature(line) {
  const d = decisionOf(line.seg_id);
  return [d.keep, d.reason, d.emphasis, d.source, d.text || "", d.note || "", state.ui.flash.has(line.seg_id)].join("|");
}

/* 고른 줄 표시만 옮긴다 (줄을 다시 만들면 글자 칸 커서가 사라진다) */
function markSelectedRow() {
  const list = $("review-segs-list");
  list.querySelectorAll(".seg-item.selected").forEach(n => n.classList.remove("selected"));
  const id = state.ui.selectedLineId;
  if (id) list.querySelector(`.seg-item[data-seg="${CSS.escape(id)}"]`)?.classList.add("selected");
}

function fitHeight(textarea) {
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function matches(line) {
  const d = decisionOf(line.seg_id);
  if (reviewFilter === "cut") return !d.keep;
  if (reviewFilter === "emph") return d.keep && d.emphasis;
  if (reviewFilter === "user") return d.source === "user";
  if (reviewFilter.startsWith("reason:")) return !d.keep && cutReason(d) === reviewFilter.slice(7);
  return true;
}

function renderReview() {
  if (state.ui.step !== 4 || !analysisReady()) return;
  renderFilters();
  const list = $("review-segs-list");
  const filtered = (state.analysis?.lines || []).filter(matches);
  const visible = filtered.slice(0, MAX_REVIEW_ROWS);
  const key = `${state.analysis?.created_at}|${reviewFilter}|${visible.map(l => l.seg_id).join(",")}|${filtered.length}`;
  if (key === shown.key) {
    for (const line of visible) {
      const signature = decisionSignature(line);
      if (shown.signatures.get(line.seg_id) === signature) continue;
      const row = lineItem(line);
      shown.rows.get(line.seg_id).replaceWith(row);
      shown.rows.set(line.seg_id, row);
      shown.signatures.set(line.seg_id, signature);
      requestAnimationFrame(() => fitHeight(row.querySelector(".seg-text")));
    }
    return;
  }
  shown.key = key;
  shown.rows.clear();
  shown.signatures.clear();
  list.innerHTML = "";
  if (!filtered.length) list.appendChild(el("div", { class: "list-more" }, "해당하는 문장이 없어요"));
  for (const line of visible) {
    const row = lineItem(line);
    shown.rows.set(line.seg_id, row);
    shown.signatures.set(line.seg_id, decisionSignature(line));
    list.appendChild(row);
  }
  if (filtered.length > MAX_REVIEW_ROWS) {
    list.appendChild(el("div", { class: "list-more" }, `… ${filtered.length - MAX_REVIEW_ROWS}개 더 있어요 (위 필터로 좁혀 보세요)`));
  }
  requestAnimationFrame(() => list.querySelectorAll(".seg-text").forEach(fitHeight));
}

async function setLine(segId, change) {
  try {
    await mutatePlan(() => api.patchLines(pid(), [{ seg_id: segId, ...change }]));
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ---------------------------------------------------------------- ④ 탭 */

export function showReviewTab(name) {
  reviewTab = name;
  document.querySelectorAll("#review-tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll("[data-tab-body]").forEach(b => b.classList.toggle("hidden", b.dataset.tabBody !== name));
  if (name === "lines") renderReview();
  emit("review-tab", name);
}

export const currentReviewTab = () => reviewTab;

/* ---------------------------------------------------------------- ④ 수정 요청 (채팅) */

function addChatMsg(role, ...content) {
  const box = $("chat-messages");
  const node = el("div", { class: `msg msg-${role}` }, ...content);
  box.appendChild(node);
  box.scrollTop = box.scrollHeight;
  return node;
}

function decisionsNow() {
  const out = new Map();
  for (const l of state.analysis?.lines || []) {
    const d = decisionOf(l.seg_id);
    out.set(l.seg_id, { keep: d.keep, text: d.text || "" });
  }
  return out;
}

let flashTimer = null;

function flashLines(ids) {
  state.ui.flash = new Set(ids);
  emit("flash");
  renderReview();
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { state.ui.flash = new Set(); emit("flash"); renderReview(); }, 4000);
}

async function sendRevise(instruction) {
  if (!analysisReady()) { addChatMsg("err", "먼저 AI 분석을 해 주세요."); return; }
  addChatMsg("user", instruction);
  const thinking = addChatMsg("ai", "생각하는 중…");
  const before = decisionsNow();
  try {
    const view = await mutatePlan(() => api.revise(pid(), { instruction, profile: loadProfile() }));
    const cut = [], kept = [], edited = [];
    for (const [id, now] of decisionsNow()) {
      const was = before.get(id);
      if (!was) continue;
      if (was.keep && !now.keep) cut.push(id);
      else if (!was.keep && now.keep) kept.push(id);
      else if (was.text !== now.text) edited.push(id);
    }
    thinking.textContent = `${view.message} · 결과 ${fmt(view.plan.duration)}`;
    const diff = el("div", { class: "msg-diff" });
    if (cut.length) diff.appendChild(el("span", { class: "d-cut" }, `${cut.length}문장 뺌`));
    if (kept.length) diff.appendChild(el("span", { class: "d-keep" }, `${kept.length}문장 살림`));
    if (edited.length) diff.appendChild(el("span", { class: "d-text" }, `글자 ${edited.length}곳 고침`));
    if (!diff.children.length) diff.appendChild(el("span", { class: "d-text" }, "바뀐 문장 없음"));
    thinking.appendChild(diff);
    const changed = [...cut, ...kept, ...edited];
    if (changed.length) {
      flashLines(changed);
      const first = state.analysis.lines.find(l => l.seg_id === changed[0]);
      if (first) emit("reveal-line", first);
    }
  } catch (err) {
    thinking.className = "msg msg-err";
    thinking.textContent = `수정하지 못했어요: ${err.message}`;
  }
}

/* ---------------------------------------------------------------- 초기화 */

function refreshStep4() {
  if (state.ui.step !== 4) return;
  renderResultCard();
  renderReview();
}

export function initAnalysis() {
  $("btn-analyze").addEventListener("click", startAnalysis);
  $("btn-analyze-cancel").addEventListener("click", async () => {
    if (trackedJob) await api.cancelJob(trackedJob).catch(err => toast(err.message, "error"));
  });
  document.querySelectorAll("#review-tabs button").forEach(btn => btn.addEventListener("click", () => showReviewTab(btn.dataset.tab)));
  const form = $("chat-form");
  const input = $("chat-input");
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
  document.querySelectorAll(".btn-quick").forEach(btn => btn.addEventListener("click", () => sendRevise(btn.dataset.cmd)));
  on("project", updateAnalyzeButton);
  on("uploads", updateAnalyzeButton);
  on("analysis", () => { updateAnalyzeButton(); refreshStep4(); });
  on("plan", refreshStep4);
  on("step", step => { if (step === 2) updateAnalyzeButton(); refreshStep4(); });
  on("line-selected", ({ line, from }) => {
    if (from === "timeline" && line) showLineInList(line);
    else markSelectedRow();
  });
  on("edit-line", line => showLineInList(line, true));
  on("timeline-changed", async () => {
    try { setPlanView(await api.getPlan(pid())); } catch (err) { toast(err.message, "error"); }
  });
}
