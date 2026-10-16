/** 入口：页面骨架、简单路由、共享 UI 工具。 */

import "./style.css";
import { api, connectWs, onWs } from "./api";
import type { EngineStatus, WsEvent } from "./types";
import { initMenu, refreshMenu } from "./screens/menu";
import { initPlay, activatePlay, deactivatePlay, onGameEvent } from "./screens/play";
import { initReview, activateReview } from "./screens/review";

// ── 骨架 ──
const app = document.getElementById("app")!;
app.innerHTML = `
  <header>
    <div class="logo" id="nav-home"><span class="badge">弈</span><span class="name">PLAYGO</span><span class="sub">本地围棋对弈</span></div>
    <div class="spacer"></div>
    <span class="mode-chip" id="top-chip" style="display:none"></span>
    <button class="icon-btn" id="nav-records" title="棋谱库">📖</button>
  </header>
  <section class="screen" id="screen-menu"></section>
  <section class="screen" id="screen-play"></section>
  <section class="screen" id="screen-review"></section>
  <div class="overlay" id="overlay"><div class="dialog" id="dialog"></div></div>
  <div id="toast"></div>
`;

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

export function showScreen(name: "menu" | "play" | "review"): void {
  document.querySelectorAll<HTMLElement>(".screen").forEach((s) => s.classList.remove("active"));
  document.getElementById(`screen-${name}`)!.classList.add("active");
  if (name === "play") activatePlay();
  else deactivatePlay();
  if (name === "review") activateReview();
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
  refreshMenu();
});
document.getElementById("nav-records")!.addEventListener("click", () => {
  showScreen("menu");
  refreshMenu("records");
});

// ── 引擎状态（顶栏角标 + 全局事件） ──
export let engineStatus: EngineStatus | null = null;

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

// 初始拉取
void api<EngineStatus>("/api/engines/status").then((s) => {
  engineStatus = s;
});

initMenu();
initPlay();
initReview();
connectWs();
showScreen("menu");
