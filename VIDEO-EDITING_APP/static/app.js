const state = { file: null, sourceFile: null, style: "정석맛", aspectRatio: "16:9", segments: [], selectedIndex: null, objectUrl: null, poller: null };
const $ = (id) => document.getElementById(id);
const player = $("videoPlayer");

function formatTime(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(seconds, 0) : 0;
  const minutes = Math.floor(safe / 60);
  const secs = Math.floor(safe % 60);
  const hundredths = Math.floor((safe % 1) * 10);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${hundredths}`;
}

function parseTime(value) {
  const match = String(value).trim().match(/^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$/);
  if (!match) return NaN;
  return Number(match[1]) * 60 + Number(match[2]) + Number(`0.${match[3] || 0}`);
}

function toast(message, error = false) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.classList.add("show");
  window.clearTimeout(toast.timeout);
  toast.timeout = window.setTimeout(() => node.classList.remove("show"), 3600);
}

function setAnalysisState(title, copy, working = false) {
  const panel = $("analysisState");
  panel.querySelector("strong").textContent = title;
  panel.querySelector("p").textContent = copy;
  panel.querySelector(".state-icon").textContent = working ? "◌" : "◎";
}

function clearObjectUrl() {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = null;
}

function showVideo(url) {
    player.src = url;
    $("videoStage").classList.add("has-video");
    $("videoStage").classList.toggle("portrait-preview", state.aspectRatio === "9:16");
    player.load();
}

function handleFile(file) {
  if (!file || !file.type.startsWith("video/")) return toast("영상 파일을 선택해주세요.", true);
  if (file.size > 500 * 1024 * 1024) return toast("파일 크기는 500MB를 초과할 수 없습니다.", true);
  clearObjectUrl();
  state.file = file;
  state.sourceFile = null;
  state.segments = [];
  state.selectedIndex = null;
  state.objectUrl = URL.createObjectURL(file);
  $("projectName").textContent = file.name;
  showVideo(state.objectUrl);
  $("analyzeButton").disabled = false;
  $("renderButton").disabled = true;
  $("addSegmentButton").disabled = true;
  $("renderResult").hidden = true;
  setAnalysisState("AI 분석 준비 완료", `${(file.size / 1024 / 1024).toFixed(1)}MB · 스타일을 선택해 분석하세요.`);
  renderTimeline();
}

function timelineDuration() {
  const segmentEnd = Math.max(0, ...state.segments.map((segment) => Number(segment.end) || 0));
  return Math.max(segmentEnd, Number.isFinite(player.duration) ? player.duration : 0, 10);
}

function selectSegment(index, focusText = false) {
  state.selectedIndex = index;
  renderTimeline();
  const inspector = $("segmentInspector");
  const segment = state.segments[index];
  if (!segment) { inspector.hidden = true; return; }
  inspector.hidden = false;
  $("selectedSegmentLabel").textContent = `#${String(index + 1).padStart(2, "0")}`;
  $("selectedTextInput").value = segment.text;
  $("selectedTimeRange").textContent = `${formatTime(segment.start)} — ${formatTime(segment.end)}`;
  $("selectedCutButton").textContent = segment.cut ? "컷 편집 해제" : "컷 편집 켜기";
  $("selectedCutButton").classList.toggle("active", Boolean(segment.cut));
  if (focusText) $("selectedTextInput").focus();
}

function toggleCut(index) {
  const segment = state.segments[index];
  if (!segment) return;
  segment.cut = !segment.cut;
  selectSegment(index);
}

function renderTimeline() {
  const canvas = $("timelineCanvas");
  const empty = $("timelineEmpty");
  $("segmentCount").textContent = `${state.segments.length} segment${state.segments.length === 1 ? "" : "s"}`;
  if (!state.segments.length) {
    canvas.hidden = true; empty.hidden = false; $("segmentInspector").hidden = true;
    return;
  }
  canvas.hidden = false; empty.hidden = true;
  const duration = timelineDuration();
  const pixelsPerSecond = Math.max(72, Math.min(110, 1600 / duration));
  const canvasWidth = Math.max(920, Math.ceil(duration * pixelsPerSecond) + 120);
  canvas.style.width = `${canvasWidth}px`;
  $("sourceClip").style.width = `${duration * pixelsPerSecond}px`;
  const ruler = $("timelineRuler");
  const subtitleTrack = $("subtitleTrack");
  ruler.replaceChildren(); subtitleTrack.replaceChildren();
  const tickStep = duration > 90 ? 15 : duration > 35 ? 10 : 5;
  for (let time = 0; time <= duration; time += tickStep) {
    const tick = document.createElement("span");
    tick.className = "ruler-tick"; tick.style.left = `${time * pixelsPerSecond}px`; tick.textContent = formatTime(time).slice(0, 5); ruler.append(tick);
  }
  state.segments.forEach((segment, index) => {
    const clip = document.createElement("article");
    clip.className = `subtitle-clip${segment.cut ? " is-cut" : ""}${state.selectedIndex === index ? " selected" : ""}`;
    clip.style.left = `${segment.start * pixelsPerSecond}px`;
    clip.style.width = `${Math.max(82, (segment.end - segment.start) * pixelsPerSecond)}px`;
    clip.tabIndex = 0; clip.setAttribute("aria-label", `${index + 1}번 자막: ${segment.text}`);
    const copy = document.createElement("div"); copy.className = "clip-copy";
    const title = document.createElement("strong"); title.textContent = segment.text;
    const range = document.createElement("span"); range.textContent = `${formatTime(segment.start)} — ${formatTime(segment.end)}`;
    copy.append(title, range);
    const cutButton = document.createElement("button"); cutButton.type = "button"; cutButton.className = "clip-cut-button"; cutButton.textContent = segment.cut ? "↶" : "✕"; cutButton.title = "컷 편집 토글";
    cutButton.addEventListener("click", (event) => { event.stopPropagation(); toggleCut(index); });
    clip.append(copy, cutButton);
    clip.addEventListener("click", () => { player.currentTime = segment.start; selectSegment(index); });
    clip.addEventListener("dblclick", () => { player.currentTime = segment.start; selectSegment(index, true); });
    clip.addEventListener("contextmenu", (event) => { event.preventDefault(); toggleCut(index); });
    clip.addEventListener("keydown", (event) => { if (event.key === "Enter") selectSegment(index, true); if (event.key === "Delete") toggleCut(index); });
    subtitleTrack.append(clip);
  });
}

async function analyze() {
  if (!state.file) return;
  const button = $("analyzeButton");
  button.disabled = true; button.textContent = "AI가 영상 분석 중…";
  setAnalysisState("AI 편집안 생성 중", "음성 인식, 자막 교정, 컷 포인트를 분석하고 있습니다.", true);
  try {
    const form = new FormData(); form.append("file", state.file); form.append("style", state.style);
    const response = await fetch("/analyze", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "AI 분석에 실패했습니다.");
    state.sourceFile = data.source_file;
    state.segments = data.segments.map((segment) => ({ ...segment, cut: Boolean(segment.cut), subtitle_color: segment.subtitle_color || "white", fontsize: segment.fontsize || 32 }));
    showVideo(data.source_url);
    renderTimeline();
    $("renderButton").disabled = state.segments.length === 0;
    $("addSegmentButton").disabled = false;
    $("timelineDescription").textContent = "텍스트, 시작·종료 시간, 컷 편집을 직접 조정한 뒤 최종 렌더링하세요.";
    setAnalysisState("AI 편집안 생성 완료", `${state.segments.length}개의 수정 가능한 세그먼트를 만들었습니다.`);
    toast("AI 편집안을 타임라인에 채웠습니다.");
  } catch (error) {
    setAnalysisState("AI 분석에 실패했습니다", error.message, false);
    toast(error.message, true);
  } finally { button.disabled = false; button.innerHTML = "<span>✦</span> AI 편집안 생성"; }
}

async function renderFinal() {
  if (!state.sourceFile || !state.segments.length) return;
  $("renderButton").disabled = true; $("renderProgress").hidden = false; $("renderResult").hidden = true;
  try {
    const response = await fetch("/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_file: state.sourceFile, segments: state.segments, aspect_ratio: state.aspectRatio }) });
    const job = await response.json(); if (!response.ok) throw new Error(job.detail || "렌더링 작업을 시작하지 못했습니다.");
    pollRender(job.job_id);
  } catch (error) { toast(error.message, true); $("renderButton").disabled = false; }
}

function pollRender(jobId) {
  window.clearInterval(state.poller);
  const update = async () => {
    try {
      const response = await fetch(`/jobs/${jobId}`); const job = await response.json();
      if (!response.ok) throw new Error(job.detail || "렌더링 상태를 확인하지 못했습니다.");
      $("renderMessage").textContent = job.message; $("renderPercent").textContent = `${job.progress || 0}%`; $("progressFill").style.width = `${job.progress || 0}%`;
      if (job.status === "completed") { window.clearInterval(state.poller); $("downloadLink").href = job.output_url; $("renderResult").hidden = false; $("renderButton").disabled = false; toast("최종 렌더링이 완료되었습니다."); }
      if (job.status === "failed") { window.clearInterval(state.poller); $("renderButton").disabled = false; toast(`렌더링 실패: ${job.message}`, true); }
    } catch (error) { window.clearInterval(state.poller); $("renderButton").disabled = false; toast(error.message, true); }
  };
  update(); state.poller = window.setInterval(update, 1200);
}

$("dropzone").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (event) => handleFile(event.target.files[0]));
$("dropzone").addEventListener("dragover", (event) => { event.preventDefault(); $("dropzone").classList.add("dragover"); });
$("dropzone").addEventListener("dragleave", () => $("dropzone").classList.remove("dragover"));
$("dropzone").addEventListener("drop", (event) => { event.preventDefault(); $("dropzone").classList.remove("dragover"); handleFile(event.dataTransfer.files[0]); });
document.querySelectorAll(".style-card").forEach((button) => button.addEventListener("click", () => { document.querySelectorAll(".style-card").forEach((item) => { item.classList.remove("selected"); item.setAttribute("aria-checked", "false"); }); button.classList.add("selected"); button.setAttribute("aria-checked", "true"); state.style = button.dataset.style; }));
document.querySelectorAll(".format-card").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".format-card").forEach((item) => { item.classList.remove("selected"); item.setAttribute("aria-checked", "false"); });
  button.classList.add("selected"); button.setAttribute("aria-checked", "true"); state.aspectRatio = button.dataset.aspect;
  $("videoFormat").textContent = state.aspectRatio;
  $("videoStage").classList.toggle("portrait-preview", state.aspectRatio === "9:16");
  if (state.file) toast(`${state.aspectRatio} 출력 비율을 선택했습니다.`);
}));
$("analyzeButton").addEventListener("click", analyze); $("renderButton").addEventListener("click", renderFinal);
$("addSegmentButton").addEventListener("click", () => { const start = Number.isFinite(player.currentTime) ? player.currentTime : 0; state.segments.push({ start, end: start + 2, text: "새 자막을 입력하세요", cut: false, subtitle_color: "white", fontsize: 32 }); selectSegment(state.segments.length - 1, true); });
$("selectedTextInput").addEventListener("input", (event) => {
  const segment = state.segments[state.selectedIndex];
  if (!segment) return;
  segment.text = event.target.value;
  renderTimeline();
});
$("selectedCutButton").addEventListener("click", () => toggleCut(state.selectedIndex));
$("playButton").addEventListener("click", () => player.paused ? player.play() : player.pause());
player.addEventListener("play", () => { $("playButton").textContent = "Ⅱ"; }); player.addEventListener("pause", () => { $("playButton").textContent = "▶"; });
player.addEventListener("timeupdate", () => { $("timeDisplay").textContent = `${formatTime(player.currentTime)} / ${formatTime(player.duration)}`; $("scrubber").value = player.duration ? (player.currentTime / player.duration) * 100 : 0; });
$("scrubber").addEventListener("input", (event) => { if (player.duration) player.currentTime = player.duration * (Number(event.target.value) / 100); });
$("resetButton").addEventListener("click", () => window.location.reload());
