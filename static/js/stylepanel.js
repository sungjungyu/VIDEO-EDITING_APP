/* 자막 스타일 폼 (#sub-style-pane).
   - 평상시: 타임라인 '자막' 라벨을 누르면 오른쪽 객체 패널에서 '자막' 스타일을 편집
   - 편집 설정: 스타일 목록(자막/제목/촬영지 자막)의 항목을 펼치면 그 안으로 폼을 옮겨 그 항목을 편집
   바꾼 값은 바로 미리보기에 보이고(draft), 0.4초 뒤 서버 편집 계획(styles)에 저장한다 (실행취소 가능). */

import { api } from "./api.js";
import { emit, mutatePlan, pid, state } from "./store.js";
import { PRESETS, STYLE_DEFAULTS, drawEvent } from "./style.js";
import { debounce, setToggle, toast, wrapText } from "./util.js";

export const STYLE_ITEMS = [
  { key: "subtitle", name: "자막", sample: "예시 자막입니다. 이렇게 보여요." },
  { key: "title", name: "제목", sample: "큰 제목 글자" },
  { key: "location", name: "촬영지 자막", sample: "성수동 카페거리" },
];

/* 서버 vibecut/models.py default_styles와 같은 기본값 */
const ITEM_DEFAULTS = {
  subtitle: { ...STYLE_DEFAULTS },
  title: { ...STYLE_DEFAULTS, preset: "제목", size: 84, weight: "bold", position: "top", bottom_margin: 80,
           max_chars_per_line: 18, fade: true },
  location: { ...STYLE_DEFAULTS, preset: "촬영지", size: 44, position: "top", bottom_margin: 50,
              background_box: true, bg_opacity: 55, outline: false, fade: true },
};

let activeKey = "subtitle";
let drafts = {};

export function styleOf(key) {
  return { ...STYLE_DEFAULTS, ...(state.plan?.styles?.[key] || {}) };
}

/* 미리보기에 쓸 스타일 (저장 전 편집 중인 값 포함) */
export function effectiveStyle(key) {
  return drafts[key] || styleOf(key);
}

const save = debounce(async () => {
  if (!state.plan || !Object.keys(drafts).length) return;
  const styles = { ...state.plan.styles, ...drafts };
  try {
    await mutatePlan(() => api.putPlan(pid(), { styles }));
    drafts = {};
  } catch (err) {
    toast(`스타일 저장 실패: ${err.message}`, "error");
  }
}, 400);

function update(changes) {
  drafts[activeKey] = { ...effectiveStyle(activeKey), ...changes };
  syncForm();
  emit("style-draft");
  save();
}

export function setActiveStyle(key) {
  activeKey = key;
  syncForm();
}

/* 폼을 parent 안으로 옮긴다 (스타일 목록 항목 / 객체 패널) */
export function attachPane(parent, key) {
  const pane = document.getElementById("sub-style-pane");
  if (pane.parentNode !== parent) parent.appendChild(pane);
  pane.style.display = "block";
  setActiveStyle(key);
}

export function detachPane() {
  const pane = document.getElementById("sub-style-pane");
  const objPanel = document.getElementById("obj-panel");
  if (pane.parentNode !== objPanel) objPanel.appendChild(pane);
  pane.style.display = "none";
  activeKey = "subtitle";
}

export function renderStylePreview() {
  const stage = document.getElementById("ss-preview-stage");
  if (!stage || !stage.isConnected || stage.offsetParent === null) return;
  const vertical = state.plan?.output?.aspect === "9:16";
  const w = stage.clientWidth || 200;
  const h = vertical ? w * 16 / 9 : w * 9 / 16;
  stage.style.height = `${h}px`;
  stage.style.padding = "0";
  stage.style.display = "block";
  stage.innerHTML = "";
  const S = effectiveStyle(activeKey);
  const sample = STYLE_ITEMS.find(i => i.key === activeKey)?.sample || "예시";
  drawEvent(stage, { start: 0, end: 10, text: wrapText(sample, S.max_chars_per_line).join("\n") }, S, w, h, 1);
}

export function syncForm() {
  const S = effectiveStyle(activeKey);
  const $ = id => document.getElementById(id);
  $("ss-font").value = S.font;
  $("ss-color").value = S.color;
  $("ss-size").value = S.size;
  $("ss-size-val").textContent = String(Math.round(S.size));
  $("ss-weight").value = S.weight;
  setToggle("ss-italic", S.italic);
  setToggle("ss-outline", S.outline);
  $("ss-outline-color").value = S.outline_color;
  $("ss-outline-w").value = S.outline_width;
  $("ss-outline-w-val").textContent = String(S.outline_width);
  $("ss-outline-row").style.display = S.outline ? "" : "none";
  $("ss-outline-color-row").style.display = S.outline ? "" : "none";
  setToggle("ss-shadow", S.shadow);
  $("ss-shadow-dist").value = S.shadow_distance;
  $("ss-shadow-dist-val").textContent = String(S.shadow_distance);
  $("ss-shadow-dist-row").style.display = S.shadow && !S.background_box ? "" : "none";
  setToggle("ss-bg-box", S.background_box);
  $("ss-bg-color").value = S.bg_color;
  $("ss-bg-opacity").value = S.bg_opacity;
  $("ss-bg-opacity-val").textContent = `${S.bg_opacity}%`;
  $("ss-bg-color-row").style.display = S.background_box ? "" : "none";
  $("ss-bg-opacity-row").style.display = S.background_box ? "" : "none";
  $("ss-position").value = S.position;
  $("ss-bottom-margin").value = S.bottom_margin;
  $("ss-bottom-margin-val").textContent = String(S.bottom_margin);
  $("ss-max-chars").value = S.max_chars_per_line;
  $("ss-max-chars-val").textContent = String(S.max_chars_per_line);
  setToggle("ss-karaoke", S.karaoke);
  setToggle("ss-fade", S.fade);
  document.querySelectorAll(".ss-preset-btn").forEach(b => b.classList.toggle("active", b.dataset.preset === S.preset));
  renderStylePreview();
}

export function initStylePanel() {
  const $ = id => document.getElementById(id);
  const num = (id, key) => $(id).addEventListener("input", e => update({ [key]: Number(e.target.value) }));
  const text = (id, key, ev = "input") => $(id).addEventListener(ev, e => update({ [key]: e.target.value }));
  const toggle = (id, key) => $(id).addEventListener("click", () => update({ [key]: !effectiveStyle(activeKey)[key] }));

  document.querySelectorAll(".ss-preset-btn").forEach(btn => btn.addEventListener("click", () => {
    update({ ...PRESETS[btn.dataset.preset], preset: btn.dataset.preset });
  }));
  text("ss-font", "font", "change");
  text("ss-color", "color");
  num("ss-size", "size");
  text("ss-weight", "weight", "change");
  toggle("ss-italic", "italic");
  toggle("ss-outline", "outline");
  text("ss-outline-color", "outline_color");
  num("ss-outline-w", "outline_width");
  toggle("ss-shadow", "shadow");
  num("ss-shadow-dist", "shadow_distance");
  toggle("ss-bg-box", "background_box");
  text("ss-bg-color", "bg_color");
  num("ss-bg-opacity", "bg_opacity");
  text("ss-position", "position", "change");
  num("ss-bottom-margin", "bottom_margin");
  num("ss-max-chars", "max_chars_per_line");
  toggle("ss-karaoke", "karaoke");
  toggle("ss-fade", "fade");
  $("btn-ss-reset").addEventListener("click", () => update({ ...(ITEM_DEFAULTS[activeKey] || STYLE_DEFAULTS) }));
  window.addEventListener("resize", renderStylePreview);
}
