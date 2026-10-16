/** 复盘页：棋谱回放 + 胜率曲线 + AI 逐手分析 + 形势回看。 */

import { api, onWs } from "../api";
import { GoBoard } from "../board";
import type { RecordDetail, ReviewAnalysis, WsEvent } from "../types";
import { coordName, showScreen, toast } from "../main";

const BLACK = 1;

let board: GoBoard;
let detail: RecordDetail | null = null;
let curIdx = 0; // 当前展示到第几手（0=空盘）
let analysis: ReviewAnalysis | null = null;

export function initReview(): void {
  const root = document.getElementById("screen-review")!;
  root.innerHTML = `
  <main class="play-main">
    <aside class="panel left" style="padding:14px;gap:12px">
      <div class="player-card">
        <div class="row"><span class="stone-ico b"></span><div><div class="p-name" id="rv-black">黑方</div></div></div>
      </div>
      <div class="player-card">
        <div class="row"><span class="stone-ico w"></span><div><div class="p-name" id="rv-white">白方</div></div></div>
      </div>
      <div class="rules-note" id="rv-meta"></div>
    </aside>
    <section class="board-wrap"><div class="board-frame"><canvas id="rv-canvas"></canvas></div></section>
    <aside class="panel right">
      <div class="sec">
        <h3>胜 率 曲 线</h3>
        <div class="own-canvas-wrap"><canvas id="rv-curve" width="536" height="300"></canvas></div>
        <div class="wr-now"><span>黑优</span><span id="rv-curve-hint">点击曲线跳转 · 点击曲线查看每手</span><span>白优</span></div>
      </div>
      <div class="sec" style="flex:1;overflow-y:auto">
        <h3>本 手 分 析</h3>
        <div id="rv-moveinfo" style="font-size:13px;line-height:2.1">—</div>
      </div>
    </aside>
  </main>
  <footer class="review-bar">
    <button class="nav-btn" id="rv-home" title="回到空盘">⏮</button>
    <button class="nav-btn" id="rv-prev" title="上一手（←）">◀</button>
    <div class="move-label" id="rv-label">0 / 0</div>
    <button class="nav-btn" id="rv-next" title="下一手（→）">▶</button>
    <button class="nav-btn" id="rv-end" title="跳到最后">⏭</button>
    <input type="range" class="move-slider" id="rv-slider" min="0" max="0" value="0">
    <div class="divider"></div>
    <button class="btn toggle" id="rv-terr">⚖ 形势</button>
    <button class="btn primary" id="rv-analyze">AI 深度复盘</button>
    <div class="divider"></div>
    <button class="btn" id="rv-back">主菜单</button>
  </footer>`;

  board = new GoBoard(document.getElementById("rv-canvas") as HTMLCanvasElement, {});
  board.mode = "review";
  board.clickableColor = null;

  const $ = (id: string) => document.getElementById(id)!;
  $("rv-home").addEventListener("click", () => goto(0));
  $("rv-prev").addEventListener("click", () => goto(curIdx - 1));
  $("rv-next").addEventListener("click", () => goto(curIdx + 1));
  $("rv-end").addEventListener("click", () => goto(detail?.moves.length ?? 0));
  $("rv-slider").addEventListener("input", (e) => goto(Number((e.target as HTMLInputElement).value)));
  $("rv-back").addEventListener("click", () => showScreen("menu"));
  $("rv-terr").addEventListener("click", () => {
    $("rv-terr").classList.toggle("on");
    render();
  });
  $("rv-analyze").addEventListener("click", async () => {
    if (!detail) return;
    try {
      await api("/api/review/analyze", { file: detail.file });
      toast("复盘分析已开始，完成后自动展示");
    } catch (e) {
      toast(String(e), true);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (!document.getElementById("screen-review")!.classList.contains("active")) return;
    if (e.key === "ArrowLeft") goto(curIdx - 1);
    if (e.key === "ArrowRight") goto(curIdx + 1);
  });

  const curve = $("rv-curve") as HTMLCanvasElement;
  curve.addEventListener("click", (e) => {
    const r = curve.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * curve.width;
    const n = Math.round(((x - 8) / (curve.width - 16)) * (detail?.moves.length ?? 0));
    goto(Math.max(0, Math.min(detail?.moves.length ?? 0, n)));
  });

  window.addEventListener("open-review", (e) => {
    void load((e as CustomEvent).detail as string);
  });

  onWs((ev: WsEvent) => {
    if (!detail) return;
    if (ev.type === "review_progress" && ev.file === detail.file) {
      toast(`复盘分析中 ${ev.done}/${ev.total}`);
    }
    if (ev.type === "review_done" && ev.file === detail.file) {
      toast("复盘分析完成");
      void reloadAnalysis();
    }
    if (ev.type === "review_error" && ev.file === detail.file) {
      toast(`复盘失败：${ev.error}`, true);
    }
  });
}

export async function activateReview(): Promise<void> {
  if (!detail) {
    const list = await api<{ file: string }[]>("/api/records").catch(() => []);
    if (list.length) await load(list[0].file);
  }
}

async function load(file: string): Promise<void> {
  try {
    detail = await api<RecordDetail>(`/api/records/${encodeURIComponent(file)}`);
    analysis = detail.analysis;
    (document.getElementById("rv-slider") as HTMLInputElement).max = String(detail.moves.length);
    document.getElementById("rv-black")!.textContent = detail.black;
    document.getElementById("rv-white")!.textContent = detail.white;
    document.getElementById("rv-meta")!.innerHTML =
      `${detail.date}<br>贴 ${detail.komi} 目 · ${detail.result || "?"}<br>共 ${detail.moves.length} 手`;
    board.setSize(detail.size);
    goto(0);
  } catch (e) {
    toast(String(e), true);
  }
}

async function reloadAnalysis(): Promise<void> {
  if (!detail) return;
  detail = await api<RecordDetail>(`/api/records/${encodeURIComponent(detail.file)}`);
  analysis = detail.analysis;
  render();
}

function goto(n: number): void {
  if (!detail) return;
  const max = detail.moves.length;
  curIdx = Math.max(0, Math.min(max, n));
  (document.getElementById("rv-slider") as HTMLInputElement).value = String(curIdx);
  document.getElementById("rv-label")!.textContent = `${curIdx} / ${max}`;
  render();
}

/** 评估标签：以行棋方视角的胜率变化 */
function gradeMove(delta: number): { text: string; color: string } {
  if (delta >= 0.08) return { text: "神之一手", color: "#e8c860" };
  if (delta >= 0.03) return { text: "好棋", color: "#9dc98f" };
  if (delta > -0.03) return { text: "普通", color: "var(--ink-dim)" };
  if (delta > -0.08) return { text: "缓手", color: "#e8a04c" };
  if (delta > -0.15) return { text: "恶手", color: "#e07856" };
  return { text: "败着", color: "#e2543e" };
}

function render(): void {
  if (!detail) return;
  const N = detail.size;
  // 重放到 curIdx（SGF 为合法对局，重放需正确处理提子）
  const grid = new Int8Array(N * N);
  replay(grid, detail, curIdx);
  board.setPosition(grid, curIdx > 0 ? pointOf(detail.moves[curIdx - 1]) : null, curIdx % 2 === 0 ? BLACK : 2);

  // 形势热力（后端 ownership 已统一为黑方视角）
  const terrOn = document.getElementById("rv-terr")!.classList.contains("on");
  if (terrOn && analysis && analysis.positions[curIdx]) {
    board.setTerritory(analysis.positions[curIdx].ownership);
  } else {
    board.setTerritory(null);
  }

  // 本手分析
  const info = document.getElementById("rv-moveinfo")!;
  if (!analysis) {
    info.innerHTML = `<span style="color:var(--ink-dim)">尚未分析。点击「AI 深度复盘」生成逐手胜率与推荐。</span>`;
  } else if (curIdx === 0) {
    const p0 = analysis.positions[0];
    info.innerHTML = p0
      ? `初始局面：黑胜率 <b style="color:#9db3e0">${(p0.winrate_black * 100).toFixed(1)}%</b><br>AI 推荐：<b>${p0.best ? coordName(p0.best.point, N) : "—"}</b>`
      : "—";
  } else {
    const before = analysis.positions[curIdx - 1];
    const after = analysis.positions[curIdx];
    const mv = detail.moves[curIdx - 1];
    if (before && after) {
      const mover = mv.color;
      const wrBefore = mover === BLACK ? before.winrate_black : 1 - before.winrate_black;
      const wrAfter = mover === BLACK ? after.winrate_black : 1 - after.winrate_black;
      const delta = wrAfter - wrBefore;
      const g = gradeMove(delta);
      const best = before.best;
      const isBest = best && mv.point === best.point;
      info.innerHTML = `
        第 <b>${curIdx}</b> 手 · ${mover === BLACK ? "黑" : "白"} <b>${mv.point == null ? "停一手" : coordName(mv.point, N)}</b>
        ${isBest ? '<span style="color:#e8c860"> ✓ AI首选</span>' : ""}
        <br>评价：<b style="color:${g.color}">${g.text}</b>（胜率 ${(delta * 100).toFixed(1)}pp）
        <br>局面胜率：黑 <b style="color:#9db3e0">${(after.winrate_black * 100).toFixed(1)}%</b>
        <br>目差：${after.score_lead_black >= 0 ? "黑" : "白"}优 <b>${Math.abs(after.score_lead_black).toFixed(1)}</b> 目
        ${!isBest && best ? `<br>AI 建议：<b style="color:#e8c860">${coordName(best.point, N)}</b>（${(best.winrate_black * 100).toFixed(1)}%）` : ""}`;
    }
  }
  drawCurve();
}

/** 用完整规则重放到第 n 手（结果写入 grid；SGF 为合法对局）。 */
function replay(grid: Int8Array, d: RecordDetail, n: number): void {
  // 提子逻辑：用简化组气计算
  const N = d.size;
  const neighbors = (p: number) => {
    const x = p % N;
    const out: number[] = [];
    if (x > 0) out.push(p - 1);
    if (x < N - 1) out.push(p + 1);
    if (p >= N) out.push(p - N);
    if (p < N * (N - 1)) out.push(p + N);
    return out;
  };
  const tryRemove = (p: number) => {
    const color = grid[p];
    if (!color) return;
    const stack = [p];
    const group = new Set<number>();
    let libs = 0;
    while (stack.length) {
      const q = stack.pop()!;
      if (group.has(q)) continue;
      group.add(q);
      for (const nb of neighbors(q)) {
        if (grid[nb] === 0) libs++;
        else if (grid[nb] === color && !group.has(nb)) stack.push(nb);
      }
    }
    if (libs === 0) for (const s of group) grid[s] = 0;
  };
  for (let i = 0; i < n; i++) {
    const { color, point } = d.moves[i];
    if (point == null) continue;
    grid[point] = color;
    for (const nb of neighbors(point)) if (grid[nb] && grid[nb] !== color) tryRemove(nb);
  }
}

function pointOf(m: { color: number; point: number | null }): number | null {
  return m.point;
}

// ── 胜率曲线（可点击跳转；黑上白下两极 + 50% 基线） ──
function drawCurve(): void {
  const cv = document.getElementById("rv-curve") as HTMLCanvasElement;
  const g = cv.getContext("2d")!;
  const W = cv.width;
  const H = cv.height;
  g.clearRect(0, 0, W, H);
  // 黑优区（上半）淡蓝底 / 白优区（下半）淡红底 —— 两极直接标注
  g.fillStyle = "rgba(79,127,217,.08)";
  g.fillRect(0, 0, W, H / 2);
  g.fillStyle = "rgba(217,106,79,.08)";
  g.fillRect(0, H / 2, W, H / 2);
  g.strokeStyle = "rgba(255,255,255,.14)";
  g.setLineDash([4, 5]);
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(0, H / 2);
  g.lineTo(W, H / 2);
  g.stroke();
  g.setLineDash([]);
  g.font = "600 20px Consolas,monospace";
  g.fillStyle = "rgba(157,179,224,.75)";
  g.fillText("黑", 10, 26);
  g.fillStyle = "rgba(230,178,150,.75)";
  g.fillText("白", 10, H - 12);

  if (!analysis || analysis.positions.length < 2) return;
  const total = analysis.positions.length - 1;
  const px = (n: number) => 8 + (n / total) * (W - 16);
  const py = (v: number) => 8 + (1 - v) * (H - 16);

  // 曲线（金色主线）
  g.strokeStyle = "#d9b96a";
  g.lineWidth = 2;
  g.lineJoin = "round";
  g.beginPath();
  analysis.positions.forEach((p, i) => (i ? g.lineTo(px(p.n), py(p.winrate_black)) : g.moveTo(px(p.n), py(p.winrate_black))));
  g.stroke();

  // 当前手：竖线 + 圆点
  const cx = px(Math.min(curIdx, total));
  g.strokeStyle = "rgba(201,162,39,.5)";
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(cx, 4);
  g.lineTo(cx, H - 4);
  g.stroke();
  const pos = analysis.positions[Math.min(curIdx, total)];
  if (pos) {
    g.fillStyle = "#e8c860";
    g.beginPath();
    g.arc(cx, py(pos.winrate_black), 5, 0, 7);
    g.fill();
    g.strokeStyle = "rgba(0,0,0,.4)";
    g.lineWidth = 1;
    g.stroke();
  }
}
