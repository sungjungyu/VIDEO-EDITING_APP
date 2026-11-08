/* ④ 확인·수정의 '자막 모양' 탭 (#sub-style-pane). 자막 모양은 여기 한 곳에서만 바꾼다.
   - 위 버튼으로 무엇을 꾸밀지 고른다: 자막 / 제목 / 장소 이름
   - 빠른 모양(프리셋) 세 가지, 나머지는 '자세히 바꾸기' 안에
   바꾼 값은 바로 미리보기에 보이고(draft), 0.4초 뒤 서버 편집 결과(styles)에 저장한다 (되돌리기 가능). */

import { api } from "../core/api.js";
import { $, el, setToggle, toast } from "../core/dom.js";
import { debounce } from "../core/format.js";
import { emit, mutatePlan, on, pid, state } from "../core/store.js";
import { drawEvent } from "../subtitle/draw.js";
import { defaultStyle, PRESETS } from "../subtitle/presets.js";
import { wrapText } from "../subtitle/wrap.js";
import { saveDefaultStyle } from "./profile.js";

export const STYLE_ITEMS = [
  { key: "subtitle", name: "자막", sample: "예시 자막입니다. 이렇게 보여요." },
  { key: "title", name: "제목", sample: "큰 제목 글자" },
  { key: "location", name: "장소 이름", sample: "성수동 카페거리" },
];

let activeKey = "subtitle";
let drafts = {};

function styleOf(key) {
  return { ...defaultStyle(key), ...(state.plan?.styles?.[key] || {}) };
}

/* 미리보기에 쓸 스타일 (저장 전 편집 중인 값 포함) */
export function effectiveStyle(key) {
  return drafts[key] || styleOf(key);
}

const save = debounce(async () => {
  if (!state.plan || !Object.keys(drafts).length) return;
  const sent = { ...drafts };
  try {
    await mutatePlan(() => api.putPlan(pid(), { styles: { ...state.plan.styles, ...sent } }));
    // 응답을 기다리는 사이 또 바꾼 값은 남겨 둔다 (그 값은 이미 예약된 다음 save가 보낸다)
    for (const key of Object.keys(sent)) if (drafts[key] === sent[key]) delete drafts[key];
  } catch (err) {
    toast(`자막 모양을 저장하지 못했어요: ${err.message}`, "error");
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
  renderTargets();
  syncForm();
}

function renderTargets() {
  const box = $("style-target");
  box.innerHTML = "";
  for (const item of STYLE_ITEMS) {
    box.appendChild(el("button", { type: "button", class: item.key === activeKey ? "active" : "",
                                   onclick: () => setActiveStyle(item.key) }, item.name));
  }
}

function renderStylePreview() {
  const stage = $("ss-preview-stage");
  if (!stage || stage.offsetParent === null) return;          // 탭이 숨어 있으면 그리지 않는다
  const vertical = state.plan?.output?.aspect === "9:16";
  const w = stage.parentNode.clientWidth || 200;
  const h = Math.min(vertical ? w * 16 / 9 : w * 9 / 16, window.innerHeight < 820 ? 150 : 220);
  const width = vertical ? h * 9 / 16 : h * 16 / 9;
  stage.style.height = `${h}px`;
  stage.style.width = `${width}px`;
  stage.style.margin = "0 auto";
  stage.innerHTML = "";
  const S = effectiveStyle(activeKey);
  const sample = STYLE_ITEMS.find(i => i.key === activeKey)?.sample || "예시";
  drawEvent(stage, { start: 0, end: 10, text: wrapText(sample, S.max_chars_per_line).join("\n") }, S, width, h, 1);
}

function syncForm() {
  const S = effectiveStyle(activeKey);
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
  $("btn-ss-reset").addEventListener("click", () => update(defaultStyle(activeKey)));
  $("btn-ss-save-default").addEventListener("click", () => {
    const ok = saveDefaultStyle(effectiveStyle("subtitle"));
    toast(ok ? "이 자막 모양으로 새 프로젝트를 시작해요." : "이 브라우저에는 저장할 수 없어요.", ok ? "ok" : "error");
  });
  window.addEventListener("resize", renderStylePreview);
  renderTargets();
  on("plan", syncForm);
  on("review-tab", tab => { if (tab === "style") syncForm(); });
  on("step", step => { if (step === 4) requestAnimationFrame(renderStylePreview); });
}
