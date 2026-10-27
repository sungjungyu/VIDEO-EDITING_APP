/* 도구 막대: 재생 묶음 · 시각(눌러서 입력) · 편집본/원본 · 붙기 · 확대 · 잘린 곳 · 단축키 도움말 */

import { $, el } from "../../core/dom.js";
import { fmt } from "../../core/format.js";
import { state } from "../../core/store.js";
import { ICONS } from "./icons.js";
import { SEQUENCE, SOURCE, timecode } from "./model.js";
import { fps, MAX_PX, MIN_PX, tl, total } from "./state.js";

const button = (id, icon, title, extra = {}) => {
  const node = el("button", { class: "tl-tool", id, type: "button", title, "aria-label": title, ...extra });
  node.innerHTML = icon;
  return node;
};

/* 확대 슬라이더는 로그 눈금 (2px/초 ~ 480px/초) */
export const sliderToPx = v => MIN_PX * (MAX_PX / MIN_PX) ** (v / 1000);
export const pxToSlider = px => Math.round(1000 * Math.log(px / MIN_PX) / Math.log(MAX_PX / MIN_PX));

export function buildToolbar(actions) {
  const bar = $("tl-toolbar");
  bar.innerHTML = "";
  const transport = el("div", { class: "tl-group" },
    button("tl-go-start", ICONS.start, "맨 앞으로 (Home)"),
    button("tl-prev-frame", ICONS.prevFrame, "이전 프레임 (←)"),
    button("tl-play", ICONS.play, "재생/정지 (Space)", { class: "tl-tool tl-tool-play" }),
    button("tl-next-frame", ICONS.nextFrame, "다음 프레임 (→)"),
    button("tl-go-end", ICONS.end, "맨 끝으로 (End)"));
  const time = el("div", { class: "tl-timecode", title: "눌러서 시각 입력 (예: 1:23, 00:01:23:10)" },
    el("button", { class: "tl-timecode-now", id: "tl-time-now", type: "button" }, "00:00:00:00"),
    el("span", { class: "tl-timecode-sep" }, "/"),
    el("span", { class: "tl-timecode-total", id: "tl-time-total" }, "00:00:00:00"));
  const views = el("div", { class: "tl-segmented", role: "tablist", "aria-label": "타임라인 보기" },
    el("button", { type: "button", class: "tl-seg-btn", id: "tl-view-sequence", role: "tab",
                   title: "결과 영상 기준 (잘린 곳을 붙여서 보기)" }, "편집본"),
    el("button", { type: "button", class: "tl-seg-btn", id: "tl-view-source", role: "tab",
                   title: "원본 기준 (잘린 곳을 빗금으로 보기, 클립 앞뒤 자르기)" }, "원본"));
  const snap = button("tl-snap", ICONS.magnet, "붙기 (S)", { class: "tl-tool tl-toggle" });
  const zoom = el("div", { class: "tl-group tl-zoom" },
    button("tl-zoom-out", ICONS.zoomOut, "축소 (-)"),
    el("input", { type: "range", id: "tl-zoom-slider", min: "0", max: "1000", step: "1", "aria-label": "확대" }),
    button("tl-zoom-in", ICONS.zoomIn, "확대 (+)"),
    button("tl-zoom-fit", ICONS.fit, "전체 보기 (\\)"));
  const cuts = el("button", { type: "button", class: "tl-cut-badge", id: "tl-cut-badge", title: "다음 잘린 곳으로 (])" });
  const help = button("tl-help", ICONS.help, "단축키 (?)");
  bar.append(transport, time, views, snap, zoom, el("div", { class: "tl-spacer" }), cuts, help);

  $("tl-go-start").addEventListener("click", () => actions.seek(0));
  $("tl-go-end").addEventListener("click", () => actions.seek(total()));
  $("tl-prev-frame").addEventListener("click", () => actions.step(-1 / fps()));
  $("tl-next-frame").addEventListener("click", () => actions.step(1 / fps()));
  $("tl-play").addEventListener("click", actions.togglePlay);
  $("tl-view-sequence").addEventListener("click", () => actions.setView(SEQUENCE));
  $("tl-view-source").addEventListener("click", () => actions.setView(SOURCE));
  snap.addEventListener("click", actions.toggleSnap);
  $("tl-zoom-out").addEventListener("click", () => actions.zoomBy(1 / 1.5));
  $("tl-zoom-in").addEventListener("click", () => actions.zoomBy(1.5));
  $("tl-zoom-fit").addEventListener("click", actions.fit);
  $("tl-zoom-slider").addEventListener("input", e => actions.zoomTo(sliderToPx(Number(e.target.value))));
  cuts.addEventListener("click", () => actions.nextCut(1));
  help.addEventListener("click", actions.toggleHelp);
  $("tl-time-now").addEventListener("click", () => editTimecode(actions));
}

function parseTime(text) {
  const parts = text.trim().split(":").map(Number);
  if (!parts.length || parts.some(Number.isNaN)) return null;
  if (parts.length === 4) return parts[0] * 3600 + parts[1] * 60 + parts[2] + parts[3] / fps();
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

function editTimecode(actions) {
  const now = $("tl-time-now");
  const input = el("input", { class: "tl-timecode-input", value: now.textContent, "aria-label": "이동할 시각" });
  now.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = apply => {
    if (done) return;
    done = true;
    input.replaceWith(now);
    const t = apply ? parseTime(input.value) : null;
    if (t !== null) actions.seek(t);
  };
  input.addEventListener("keydown", e => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

export function updateToolbar(t, playing, cutCount) {
  const now = $("tl-time-now");
  if (now) now.textContent = timecode(t, fps());
  $("tl-time-total").textContent = timecode(total(), fps());
  $("tl-play").innerHTML = playing ? ICONS.pause : ICONS.play;
  $("tl-view-sequence").classList.toggle("active", tl.view === SEQUENCE);
  $("tl-view-source").classList.toggle("active", tl.view === SOURCE);
  $("tl-view-sequence").setAttribute("aria-selected", String(tl.view === SEQUENCE));
  $("tl-view-source").setAttribute("aria-selected", String(tl.view === SOURCE));
  $("tl-snap").classList.toggle("on", tl.prefs.snap);
  $("tl-zoom-slider").value = String(pxToSlider(tl.px));
  const badge = $("tl-cut-badge");
  badge.innerHTML = "";
  badge.append(el("span", { class: "tl-cut-icon" }), `잘린 곳 ${cutCount}`,
               el("span", { class: "tl-cut-result" }, `결과 ${fmt(state.plan?.duration || 0)}`));
  badge.querySelector(".tl-cut-icon").innerHTML = ICONS.scissors;
  badge.disabled = !cutCount;
}
