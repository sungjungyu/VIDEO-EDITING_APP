/* ⑤ 내보내기의 '배경음악' 카드 (v4 T5).
   - 없음 / 기본 곡 / 내 음악 중 하나. 기본 곡은 장면 분위기에 맞는 곡에 ⭐추천, ▶로 미리 듣기
   - 내 음악: 파일을 올리면 서버가 프로젝트에 저장하고 배경음악을 '내 음악'으로 바꾼다
   - 음량 · 말할 때 음악 작게 — 크기 규칙은 web/js/core/mix.js (= 서버 domain/mix.py), 미리보기에서도 들린다 */

import { api } from "../core/api.js";
import { $, el, setToggle, toast } from "../core/dom.js";
import { mutatePlan, on, pid, setPlanView, state } from "../core/store.js";

let choices = { tracks: [], recommended: null, user: null, mood: null };
let sample = null;               // 미리 듣기 중인 Audio
let sampleId = null;

const music = () => state.plan?.music || { source: "none", volume: 0.25, duck: true, duck_level: 0.3 };

async function saveMusic(change) {
  try {
    await mutatePlan(() => api.putPlan(pid(), { music: { ...music(), ...change } }));
  } catch (err) { toast(err.message, "error"); }
}

function stopSample() {
  if (sample) sample.pause();
  sample = null;
  sampleId = null;
}

function toggleSample(track) {
  const same = sampleId === track.id;
  stopSample();
  if (same) { renderMusic(); return; }
  sample = new Audio(`/api/music/${encodeURIComponent(track.id)}/file`);
  sampleId = track.id;
  sample.volume = 0.6;
  sample.addEventListener("ended", () => { stopSample(); renderMusic(); });
  sample.play().catch(() => stopSample());
  renderMusic();
}

function renderSource() {
  const box = $("music-source");
  box.innerHTML = "";
  const current = music().source;
  for (const [value, label] of [["none", "없음"], ["library", "기본 곡"], ["user", "내 음악"]]) {
    box.appendChild(el("button", { type: "button", class: current === value ? "active" : "", onclick: () => {
      if (value === current) return;
      if (value === "library") {
        const pick = choices.tracks.find(t => t.id === choices.recommended) || choices.tracks[0];
        if (!pick) { toast("아직 들어 있는 기본 곡이 없어요.", "info"); return; }
        saveMusic({ source: "library", track: pick.id, title: pick.title });
      } else if (value === "user") {
        if (choices.user) saveMusic({ source: "user", title: choices.user });
        else $("music-file").click();
      } else {
        saveMusic({ source: "none" });
      }
    } }, label));
  }
}

function renderLibrary() {
  const list = $("music-library");
  list.innerHTML = "";
  list.classList.toggle("hidden", music().source !== "library");
  if (!choices.tracks.length) {
    list.appendChild(el("div", { class: "music-empty" }, "아직 들어 있는 기본 곡이 없어요."));
    return;
  }
  for (const t of choices.tracks) {
    const chosen = music().source === "library" && music().track === t.id;
    list.appendChild(el("div", { class: `music-row${chosen ? " active" : ""}`,
                                 onclick: () => saveMusic({ source: "library", track: t.id, title: t.title }) },
      el("span", { class: "music-radio" }, chosen ? "●" : "○"),
      el("span", { class: "music-title" }, t.title),
      el("span", { class: "music-mood" }, t.mood),
      t.id === choices.recommended ? el("span", { class: "music-rec", title: `장면 분위기(${choices.mood})에 맞아요` },
                                        "⭐추천") : null,
      el("button", { type: "button", class: "btn-mini", onclick: e => { e.stopPropagation(); toggleSample(t); } },
         sampleId === t.id ? "■ 멈춤" : "▶ 듣기")));
  }
}

function renderUser() {
  const box = $("music-user");
  box.classList.toggle("hidden", music().source !== "user");
  $("music-user-name").textContent = choices.user ? `♪ ${music().title || choices.user}` : "";
}

function renderControls() {
  const m = music();
  const on_ = m.source !== "none";
  $("music-controls").classList.toggle("hidden", !on_);
  const slider = $("music-volume");
  if (document.activeElement !== slider) slider.value = String(m.volume);
  $("music-volume-val").textContent = m.volume < 0.15 ? "작게" : m.volume > 0.35 ? "크게" : "보통";
  setToggle("music-duck", m.duck);
  const track = choices.tracks.find(t => t.id === m.track);
  $("music-credit").textContent = m.source === "library" && track
    ? `출처: ${track.source || "-"}${track.license ? ` (${track.license})` : ""}` : "";
}

export function renderMusic() {
  if (state.ui.step !== 5 || !state.plan) return;
  renderSource();
  renderLibrary();
  renderUser();
  renderControls();
}

async function loadChoices() {
  if (!pid()) return;
  try {
    choices = await api.musicChoices(pid());
  } catch (err) {
    choices = { tracks: [], recommended: null, user: null, mood: null };
  }
  renderMusic();
}

async function uploadMusic(file) {
  try {
    toast(`${file.name} 올리는 중…`, "info");
    const view = await api.uploadMusic(pid(), file);
    setPlanView(view);
    await loadChoices();
    toast("내 음악을 배경음악으로 넣었어요.", "ok");
  } catch (err) { toast(err.message, "error"); }
}

export function initMusic() {
  $("btn-music-upload").addEventListener("click", () => $("music-file").click());
  $("music-file").addEventListener("change", e => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) uploadMusic(file);
  });
  let timer = null;
  $("music-volume").addEventListener("input", e => {
    $("music-volume-val").textContent = Number(e.target.value) < 0.15 ? "작게" : Number(e.target.value) > 0.35 ? "크게" : "보통";
    clearTimeout(timer);
    timer = setTimeout(() => saveMusic({ volume: Number(e.target.value) }), 300);
  });
  $("music-duck").addEventListener("click", () => saveMusic({ duck: !music().duck }));
  on("plan", renderMusic);
  on("step", step => { if (step === 5) loadChoices(); else stopSample(); });
  let lastPid = null;
  on("project", () => {                       // 다른 프로젝트를 열었을 때만 다시 읽는다
    if (pid() === lastPid) return;
    lastPid = pid();
    choices = { tracks: [], recommended: null, user: null, mood: null };
    if (state.ui.step === 5) loadChoices();
  });
}
