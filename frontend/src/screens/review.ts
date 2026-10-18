/** 复盘页：棋谱回放 + 胜率曲线 + AI 逐手分析 + 形势回看 + AI 推荐/接管试下。 */

import { api, onWs } from "../api";
import { GoBoard } from "../board";
import { errPayloadText, errText, t } from "../i18n";
import type { MsgKey } from "../i18n";
import type { GameState, HintData, RecordDetail, ReviewAnalysis, WsEvent } from "../types";
import { coordName, showScreen, toast } from "../main";
import { onGameEvent } from "./play";

const BLACK = 1;

let board: GoBoard;
let detail: RecordDetail | null = null;
let curIdx = 0; // 当前展示到第几手（0=空盘）
let analysis: ReviewAnalysis | null = null;
let terrToggle = false;
let hintToggle = false;
let hintData: HintData | null = null; // 当前局面（= curIdx）的复盘推荐
let hintRequest = 0;
let loadRequest = 0;
let loading = false;
let takeoverPending = false;
let hintStatus: "loading" | "error" | null = null;

export function initReview(): void {
  const root = document.getElementById("screen-review")!;
  root.innerHTML = `
  <main class="play-main">
    <aside class="panel left" style="padding:14px;gap:12px">
      <div class="player-card">
        <div class="row"><span class="stone-ico b"></span><div><div class="p-name" id="rv-black"></div></div></div>
      </div>
      <div class="player-card">
        <div class="row"><span class="stone-ico w"></span><div><div class="p-name" id="rv-white"></div></div></div>
      </div>
      <div class="rules-note" id="rv-meta"></div>
    </aside>
    <section class="board-wrap"><div class="board-frame"><canvas id="rv-canvas"></canvas></div></section>
    <aside class="panel right">
      <div class="sec">
        <h3>${t("rv.curve_title")}</h3>
        <div class="own-canvas-wrap"><canvas id="rv-curve" width="536" height="300"></canvas></div>
        <div class="wr-now"><span>${t("rv.black_lead")}</span><span id="rv-curve-hint">${t("rv.curve_tip")}</span><span>${t("rv.white_lead")}</span></div>
      </div>
      <div class="sec" style="flex:1;overflow-y:auto">
        <h3>${t("rv.analysis_title")}</h3>
        <div id="rv-moveinfo" style="font-size:13px;line-height:2.1">—</div>
      </div>
    </aside>
  </main>
  <footer class="review-bar">
    <button class="nav-btn" id="rv-home" title="${t("rv.first")}">⏮</button>
    <button class="nav-btn" id="rv-prev" title="${t("rv.prev")}">◀</button>
    <div class="move-label" id="rv-label">0 / 0</div>
    <button class="nav-btn" id="rv-next" title="${t("rv.next")}">▶</button>
    <button class="nav-btn" id="rv-end" title="${t("rv.last")}">⏭</button>
    <input type="range" class="move-slider" id="rv-slider" min="0" max="0" value="0">
    <div class="divider"></div>
    <button class="btn toggle" id="rv-terr">${t("rv.terr")}</button>
    <button class="btn toggle" id="rv-hint">${t("play.hint_toggle")}</button>
    <button class="btn primary" id="rv-analyze">${t("rv.analyze")}</button>
    <div class="divider"></div>
    <button class="btn" id="rv-takeover">${t("rv.takeover")}</button>
    <button class="btn" id="rv-back">${t("rv.menu")}</button>
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
  const terrBtn = $("rv-terr");
  terrBtn.classList.toggle("on", terrToggle);
  terrBtn.addEventListener("click", () => {
    terrToggle = !terrToggle;
    terrBtn.classList.toggle("on", terrToggle);
    render();
  });
  const hintBtn = $("rv-hint");
  hintBtn.classList.toggle("on", hintToggle);
  hintBtn.addEventListener("click", () => {
    hintRequest++; // 关闭再开启时也不能接收上一次请求
    hintToggle = !hintToggle;
    hintBtn.classList.toggle("on", hintToggle);
    if (hintToggle) void fetchHint();
    else {
      hintData = null;
      hintStatus = null;
      board.setHints(null);
      render();
    }
  });
  $("rv-takeover").addEventListener("click", doTakeover);
  $("rv-analyze").addEventListener("click", async () => {
    if (!detail) return;
    try {
      await api("/api/review/analyze", { file: detail.file });
      toast(t("rv.started"));
    } catch (e) {
      toast(errText(e), true);
    }
  });

  const curve = $("rv-curve") as HTMLCanvasElement;
  curve.addEventListener("click", (e) => {
    const r = curve.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * curve.width;
    const n = Math.round(((x - 8) / (curve.width - 16)) * (detail?.moves.length ?? 0));
    goto(Math.max(0, Math.min(detail?.moves.length ?? 0, n)));
  });

  // 已载入棋谱时恢复显示（首帧或语言切换后）
  if (detail) reapplyReview();
  updateButtons();
}

// document/window/bus 级监听只挂一次（initReview 可重复调用于语言切换重建）
document.addEventListener("keydown", (e) => {
  if (!document.getElementById("screen-review")?.classList.contains("active")) return;
  if (e.key === "ArrowLeft") goto(curIdx - 1);
  if (e.key === "ArrowRight") goto(curIdx + 1);
});

window.addEventListener("open-review", (e) => {
  const source = (e as CustomEvent<string | { file: string; moves: number }>).detail;
  if (typeof source === "string") void load(source);
  else if (detail?.file === source.file && !loading) goto(source.moves);
  else void load(source.file, source.moves);
});

onWs((ev: WsEvent) => {
  if (!detail) return;
  if (ev.type === "review_progress" && ev.file === detail.file) {
    toast(t("rv.progress", { done: ev.done, total: ev.total }));
  }
  if (ev.type === "review_done" && ev.file === detail.file) {
    toast(t("rv.done"));
    void reloadAnalysis();
  }
  if (ev.type === "review_error" && ev.file === detail.file) {
    toast(t("rv.failed", { msg: errPayloadText(ev.error) }), true);
  }
});

export async function activateReview(): Promise<void> {
  if (!detail && !loading) {
    const request = loadRequest;
    const list = await api<{ file: string }[]>("/api/records").catch(() => []);
    if (list.length && !detail && !loading && request === loadRequest) await load(list[0].file);
  }
}

/** 语言切换后恢复复盘页显示（名称/meta/游标/曲线）。 */
export function reapplyReview(): void {
  if (!detail) return;
  if (board.size !== detail.size) board.setSize(detail.size);
  (document.getElementById("rv-slider") as HTMLInputElement).max = String(detail.moves.length);
  document.getElementById("rv-black")!.textContent = detail.black;
  document.getElementById("rv-white")!.textContent = detail.white;
  document.getElementById("rv-meta")!.innerHTML =
    `${detail.date}<br>${t("rv.komi", { komi: detail.komi, result: detail.result || "?" })}<br>${t("rv.total_moves", { n: detail.moves.length })}`;
  goto(curIdx);
}

function updateButtons(): void {
  for (const id of ["rv-hint", "rv-terr", "rv-analyze", "rv-takeover"]) {
    (document.getElementById(id) as HTMLButtonElement).disabled = !detail || loading || takeoverPending;
  }
}

async function load(file: string, moves = 0): Promise<void> {
  const request = ++loadRequest;
  loading = true;
  hintRequest++;
  hintData = null;
  hintStatus = null;
  board.setHints(null);
  updateButtons();
  try {
    const loaded = await api<RecordDetail>(`/api/records/${encodeURIComponent(file)}`);
    if (request !== loadRequest) return;
    detail = loaded;
    analysis = detail.analysis;
    curIdx = moves;
    loading = false;
    reapplyReview();
  } catch (e) {
    if (request !== loadRequest) return;
    toast(errText(e), true);
  } finally {
    if (request === loadRequest) {
      loading = false;
      updateButtons();
    }
  }
}

async function reloadAnalysis(): Promise<void> {
  if (!detail) return;
  const current = detail;
  try {
    const loaded = await api<RecordDetail>(`/api/records/${encodeURIComponent(current.file)}`);
    if (detail !== current || loading) return;
    detail = loaded;
    analysis = loaded.analysis;
    render();
  } catch (e) {
    if (detail === current && !loading) toast(errText(e), true);
  }
}

function goto(n: number): void {
  if (!detail || loading) return;
  const max = detail.moves.length;
  curIdx = Math.max(0, Math.min(max, n));
  (document.getElementById("rv-slider") as HTMLInputElement).value = String(curIdx);
  document.getElementById("rv-label")!.textContent = `${curIdx} / ${max}`;
  render();
  syncHints();
}

// ── 复盘 AI 推荐：对照"我下的"与"AI 正着"（独立于整谱深度复盘） ──
async function fetchHint(): Promise<void> {
  if (!detail || loading || !hintToggle) return;
  const file = detail.file;
  const moves = curIdx;
  const request = ++hintRequest;
  const isCurrent = () => request === hintRequest && hintToggle && !loading
    && detail?.file === file && curIdx === moves;
  hintStatus = "loading";
  render();
  try {
    const h = await api<HintData>(
      `/api/review/hint?file=${encodeURIComponent(file)}&moves=${moves}`,
    );
    // 响应到达时已导航离开该局面 → 丢弃
    if (!isCurrent() || h.move_count !== moves) return;
    hintStatus = null;
    hintData = h;
    board.setHints(h.moves);
    render();
  } catch (e) {
    if (!isCurrent()) return;
    hintStatus = "error";
    toast(errText(e), true);
    render();
  }
}

/** 导航后同步推荐覆盖层：命中缓存直接上，否则清掉并按需拉取。 */
function syncHints(): void {
  if (!hintToggle) return;
  if (hintData && hintData.move_count === curIdx) board.setHints(hintData.moves);
  else {
    hintData = null;
    board.setHints(null);
    void fetchHint();
  }
}

/** 接管试下：从当前局面起开一盘黑白皆由玩家执的对局（不限时、不存谱）。 */
async function doTakeover(): Promise<void> {
  if (!detail || loading || takeoverPending) return;
  takeoverPending = true;
  updateButtons();
  try {
    const snap = await api<GameState>("/api/review/takeover", {
      file: detail.file,
      moves: curIdx,
    });
    toast(t("rv.takeover_toast"));
    onGameEvent({ type: "state", game: snap }); // 直接套用对局页渲染，不等 WS
    showScreen("play");
  } catch (e) {
    toast(errText(e), true);
  } finally {
    takeoverPending = false;
    updateButtons();
  }
}

/** 评估标签：以行棋方视角的胜率变化 */
function gradeMove(delta: number): { textKey: MsgKey; color: string } {
  if (delta >= 0.08) return { textKey: "rv.grade_brilliant", color: "#e8c860" };
  if (delta >= 0.03) return { textKey: "rv.grade_good", color: "#9dc98f" };
  if (delta > -0.03) return { textKey: "rv.grade_plain", color: "var(--ink-dim)" };
  if (delta > -0.08) return { textKey: "rv.grade_slow", color: "#e8a04c" };
  if (delta > -0.15) return { textKey: "rv.grade_bad", color: "#e07856" };
  return { textKey: "rv.grade_blunder", color: "#e2543e" };
}

function render(): void {
  if (!detail) return;
  const N = detail.size;
  // 重放到 curIdx（SGF 为合法对局，重放需正确处理提子）
  const grid = new Int8Array(N * N);
  replay(grid, detail, curIdx);
  const last = detail.moves[curIdx - 1];
  board.setPosition(grid, last?.point ?? null, last ? 3 - last.color : BLACK);

  // 形势热力（后端 ownership 已统一为黑方视角）
  if (terrToggle && analysis && analysis.positions[curIdx]) {
    board.setTerritory(analysis.positions[curIdx].ownership);
  } else {
    board.setTerritory(null);
  }

  // 本手分析
  const info = document.getElementById("rv-moveinfo")!;
  if (!analysis) {
    info.innerHTML = `<span style="color:var(--ink-dim)">${t("rv.not_analyzed")}</span>`;
  } else if (curIdx === 0) {
    const p0 = analysis.positions[0];
    info.innerHTML = p0
      ? `${t("rv.initial", { p: (p0.winrate_black * 100).toFixed(1) })}<br>${t("rv.ai_best")}<b>${p0.best ? coordName(p0.best.point, N) : "—"}</b>`
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
        ${t("rv.move_n_color", { n: curIdx, color: t(mover === BLACK ? "stone.black" : "stone.white") })} <b>${mv.point == null ? t("rv.pass_move") : coordName(mv.point, N)}</b>
        ${isBest ? `<span style="color:#e8c860"> ${t("rv.ai_pick")}</span>` : ""}
        <br>${t("rv.grade")}<b style="color:${g.color}">${t(g.textKey)}</b>${t("rv.winrate_drop", { p: (delta * 100).toFixed(1) })}
        <br>${t("rv.pos_winrate", { p: (after.winrate_black * 100).toFixed(1) })}
        <br>${t("rv.lead", {
          who: t(after.score_lead_black >= 0 ? "stone.black" : "stone.white"),
          x: Math.abs(after.score_lead_black).toFixed(1),
        })}
        ${!isBest && best ? `<br>${t("rv.suggest")}<b style="color:#e8c860">${coordName(best.point, N)}</b>（${(best.winrate_black * 100).toFixed(1)}%）` : ""}`;
    }
  }
  // 复盘推荐（开启且数据对应当前局面时）：首选点 + 行棋方视角胜率
  if (hintToggle && hintData && hintData.move_count === curIdx && hintData.moves.length) {
    const m = hintData.moves[0];
    const wr = hintData.to_play === BLACK ? m.winrate_black : 1 - m.winrate_black;
    info.innerHTML += `<br>${t("rv.hint_line", {
      coord: coordName(m.point, N),
      p: (wr * 100).toFixed(1),
    })}`;
  } else if (hintToggle) {
    const key = hintStatus === "error" ? "rv.hint_failed"
      : hintStatus === "loading" ? "rv.hint_loading" : "rv.hint_empty";
    info.innerHTML += `<br>${t(key)}`;
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

// ── 胜率曲线（可点击跳转；黑上白下两极 + 50% 基线） ──
function drawCurve(): void {
  const cv = document.getElementById("rv-curve") as HTMLCanvasElement;
  if (!cv) return;
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
  g.fillText(t("stone.black"), 10, 26);
  g.fillStyle = "rgba(230,178,150,.75)";
  g.fillText(t("stone.white"), 10, H - 12);

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
