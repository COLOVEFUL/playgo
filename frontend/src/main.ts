/** 入口：页面骨架、简单路由、共享 UI 工具、语言切换编排。 */

import "./style.css";
import { api, connectWs, onWs } from "./api";
import { initLang, lang, onLangChange, setLang, t } from "./i18n";
import type { EngineStatus, WsEvent } from "./types";
import { initMenu, refreshMenu } from "./screens/menu";
import { initPlay, activatePlay, deactivatePlay, onGameEvent, reapplyPlay } from "./screens/play";
import { initReview, activateReview, deactivateReview, reapplyReview } from "./screens/review";

// 语言须在首次渲染前就位（跟随浏览器 / localStorage）
initLang();

// ── 骨架 ──
const app = document.getElementById("app")!;
app.innerHTML = `
  <header>
    <div class="logo" id="nav-home"><span class="badge">弈</span><span class="name">PLAYGO</span><span class="sub">${t("app.tagline")}</span></div>
    <div class="spacer"></div>
    <span class="mode-chip" id="top-chip" style="display:none"></span>
    <button class="icon-btn" id="nav-lang" title="${t("app.lang_tip")}">EN</button>
    <button class="icon-btn" id="nav-records" title="${t("app.records_tip")}">📖</button>
  </header>
  <section class="screen" id="screen-menu"></section>
  <section class="screen" id="screen-play"></section>
  <section class="screen" id="screen-review"></section>
  <div class="overlay" id="overlay"><div class="dialog" id="dialog"></div></div>
  <div id="toast"></div>
`;

/** 顶栏文案按当前语言刷新（语言切换时只改文本，不重建、监听器不丢）。 */
function updateHeader(): void {
  document.querySelector("#nav-home .sub")!.textContent = t("app.tagline");
  const langBtn = document.getElementById("nav-lang")!;
  langBtn.textContent = lang() === "zh" ? "EN" : "中";
  langBtn.title = t("app.lang_tip");
  document.getElementById("nav-records")!.title = t("app.records_tip");
}

// ── 共享工具 ──
let toastTimer = 0;
export function toast(msg: string, isError = false): void {
  const el = document.getElementById("toast")!;
  el.textContent = msg;
  el.className = `show${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (el.className = ""), isError ? 4200 : 2400);
}

export function showDialog(html: string): HTMLElement {
  document.getElementById("overlay")!.classList.add("show");
  const d = document.getElementById("dialog")!;
  d.innerHTML = html;
  return d;
}
export function closeDialog(): void {
  document.getElementById("overlay")!.classList.remove("show");
}

/** 外部棋谱的姓名/结果只显示为文字，不能成为HTML标签或属性。 */
export function escapeHtml(text: string): string {
  const entities: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return text.replace(/[&<>"']/g, (char) => entities[char]);
}

export function showScreen(name: "menu" | "play" | "review"): void {
  document.querySelectorAll<HTMLElement>(".screen").forEach((s) => s.classList.remove("active"));
  document.getElementById(`screen-${name}`)!.classList.add("active");
  if (name === "play") activatePlay();
  else deactivatePlay();
  if (name === "review") activateReview();
  else deactivateReview();
}

export function fmtClock(sec: number, inByo: boolean): string {
  if (sec < 0) return "∞";
  const s = Math.max(0, Math.ceil(sec));
  if (inByo || s < 60) return `${s}`;
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export const LET = "ABCDEFGHJKLMNOPQRST";
export function coordName(point: number, size = 19): string {
  const x = point % size;
  const y = Math.floor(point / size);
  return `${LET[x]}${size - y}`;
}

// ── 路由 ──
document.getElementById("nav-home")!.addEventListener("click", () => {
  showScreen("menu");
  refreshMenu("engine");
});
document.getElementById("nav-records")!.addEventListener("click", () => {
  showScreen("menu");
  refreshMenu("records");
});
document.getElementById("nav-lang")!.addEventListener("click", () => {
  setLang(lang() === "zh" ? "en" : "zh");
});

// 语言切换：重建三屏并重放当前状态（棋局在后端，曲线历史等模块内保留）
onLangChange(() => {
  updateHeader();
  closeDialog();
  initMenu();
  initPlay();
  initReview();
  void refreshMenu();
  reapplyPlay();
  reapplyReview();
});

// ── 引擎状态（顶栏角标 + 全局事件） ──
export let engineStatus: EngineStatus | null = null;

/** 手动刷新状态后回写全局（import 绑定只读，经此更新） */
export function setEngineStatus(s: EngineStatus): void {
  engineStatus = s;
}

onWs((ev: WsEvent) => {
  switch (ev.type) {
    case "engine":
    case "engine_restarted":
      engineStatus = ev.engine;
      refreshMenu();
      break;
    default:
      break;
  }
  onGameEvent(ev);
});

// 初始拉取（成功后刷新菜单，启动早期没赶上预热广播时引擎面板也能渲染）
void api<EngineStatus>("/api/engines/status").then((s) => {
  engineStatus = s;
  void refreshMenu();
});

updateHeader();
initMenu();
initPlay();
initReview();
connectWs();
showScreen("menu");
