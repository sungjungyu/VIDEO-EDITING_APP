/* 내 편집 스타일 (브라우저 localStorage). ② 분석 단계에서 고르고, 분석·AI 가편집·수정 요청에 함께 보낸다.
     컷 빠르기      → 한 컷 평균 길이 성향 (서버는 앞 글자 '느림/보통/빠름'으로 남기는 문장 사이 쉼을 정한다)
     군말 빼기 강도 → 규칙·AI 컷 판단의 기준 (앞 글자 '약/중/강')
     자주 쓰는 단어 → 받아쓰기 고유명사 힌트 + 강조(줌인) 후보
   바꾸면 바로 저장한다. 자막 모양은 ④ '내 기본 모양으로 저장'으로 넣어 두고, 새 프로젝트를 그 모양으로 시작한다. */

import { $ } from "../core/dom.js";
import { migrateStyle } from "../subtitle/presets.js";

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
  try { localStorage.setItem(KEY, JSON.stringify(profile)); return true; } catch (err) { return false; }
}

export function saveDefaultStyle(style) {
  return saveProfile({ ...loadProfile(), subtitle_style: style || null });
}

function parseCommaList(text) {
  return text.split(",").map(s => s.trim()).filter(Boolean);
}

function fill() {
  const p = loadProfile();
  $("profile-cut-tempo").value = p.cut_tempo;
  $("profile-filler-removal").value = p.filler_removal;
  $("profile-frequent-words").value = p.frequent_words.join(", ");
  $("profile-box").open = !!(p.cut_tempo || p.filler_removal || p.frequent_words.length);
}

function save() {
  const ok = saveProfile({
    ...loadProfile(),
    cut_tempo: $("profile-cut-tempo").value,
    filler_removal: $("profile-filler-removal").value,
    frequent_words: parseCommaList($("profile-frequent-words").value),
  });
  const status = $("profile-save-status");
  status.textContent = ok ? "저장했어요. 다음 분석·AI 가편집부터 반영됩니다." : "이 브라우저에는 저장할 수 없어요.";
  status.className = `field-note${ok ? " ok" : ""}`;
}

export function initProfile() {
  fill();
  $("profile-cut-tempo").addEventListener("change", save);
  $("profile-filler-removal").addEventListener("change", save);
  $("profile-frequent-words").addEventListener("change", save);
}
