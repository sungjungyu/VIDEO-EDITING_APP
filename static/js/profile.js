/* 제작자 프로필 (브라우저 localStorage). 분석·AI 가편집·수정 요청에 함께 보낸다.
     컷 템포        → 남기는 문장 사이 쉼을 얼마나 줄일지 (느림 1.5초 / 보통 0.8초 / 빠름 0.4초)
     군말 제거 강도 → 규칙·AI 컷 판단의 기준
     자주 쓰는 단어 → 받아쓰기 고유명사 힌트 + 강조(줌인) 후보
   저장할 때 지금 자막 스타일도 함께 넣어 두고, 새 프로젝트를 만들면 그 스타일로 시작한다. */

import { migrateStyle } from "./style.js";
import { state } from "./store.js";

const KEY = "video_editor_profile_v1";
const DEFAULT = { cut_tempo: "", filler_removal: "", frequent_words: [], subtitle_style: null };

export function loadProfile() {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || "{}");
    return {
      cut_tempo: parsed.cut_tempo ?? "",
      filler_removal: parsed.filler_removal ?? "",
      frequent_words: Array.isArray(parsed.frequent_words) ? parsed.frequent_words : [],
      subtitle_style: migrateStyle(parsed.subtitle_style),
    };
  } catch (err) {
    return { ...DEFAULT };
  }
}

function saveProfile(profile) {
  try { localStorage.setItem(KEY, JSON.stringify(profile)); } catch (err) { /* 저장 공간 없음 */ }
}

function parseCommaList(text) {
  return text.split(",").map(s => s.trim()).filter(Boolean);
}

function open() {
  const p = loadProfile();
  document.getElementById("profile-cut-tempo").value = p.cut_tempo;
  document.getElementById("profile-filler-removal").value = p.filler_removal;
  document.getElementById("profile-frequent-words").value = p.frequent_words.join(", ");
  document.getElementById("profile-save-status").textContent = "";
  document.getElementById("profile-modal").classList.remove("hidden");
}

function close() {
  document.getElementById("profile-modal").classList.add("hidden");
}

export function initProfile() {
  document.getElementById("btn-profile").addEventListener("click", open);
  document.getElementById("profile-modal-close").addEventListener("click", close);
  document.getElementById("profile-modal-backdrop").addEventListener("click", close);
  document.getElementById("btn-profile-cancel").addEventListener("click", close);
  document.getElementById("btn-profile-save").addEventListener("click", () => {
    saveProfile({
      cut_tempo: document.getElementById("profile-cut-tempo").value,
      filler_removal: document.getElementById("profile-filler-removal").value,
      frequent_words: parseCommaList(document.getElementById("profile-frequent-words").value),
      subtitle_style: state.plan?.styles?.subtitle || null,
    });
    const status = document.getElementById("profile-save-status");
    status.textContent = "저장했습니다. 다음 분석·AI 가편집부터 반영됩니다.";
    status.className = "modal-status ok";
  });
}
