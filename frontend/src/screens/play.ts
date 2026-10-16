/** 对局页：棋盘 + 计时 + 操作 + AI推荐/形势判断 + 点目/结果流程。 */

import { api } from "../api";
import { GoBoard } from "../board";
import { sfx } from "../audio";
import type { GameState, HintData, TerritoryData, WsEvent } from "../types";
import { closeDialog, coordName, fmtClock, showDialog, showScreen, toast } from "../main";

const BLACK = 1;

let board: GoBoard;
let state: GameState | null = null;
let hintOn = false;
let terrOn = false;
let hintMoveCount = -1;
let terrMoveCount = -1;
let els: Record<string, HTMLElement> = {};
let winrateHist: { n: number; wr: number }[] = [];

export function initPlay(): void {
  const root = document.getElementById("screen-play")!;
  root.innerHTML = `
  <main class="play-main">
    <aside class="panel left">
      <div class="player-card" id="pc-b">
        <div class="row"><span class="stone-ico b"></span>
          <div><div class="p-name" id="name-b">黑方</div><div class="p-tag" id="tag-b"></div></div></div>
        <div class="meta"><span class="cap-num">提子 <b id="cap-b">0</b></span><span class="byo-chip" id="byo-b" style="display:none">读秒 ×3</span></div>
        <div class="clock" id="clock-b">30:00</div>
      </div>
      <div class="player-card" id="pc-w">
        <div class="row"><span class="stone-ico w"></span>
          <div><div class="p-name" id="name-w">白方</div><div class="p-tag" id="tag-w"></div></div></div>
        <div class="meta"><span class="cap-num">提子 <b id="cap-w">0</b></span><span class="byo-chip" id="byo-w" style="display:none"></span></div>
        <div class="clock" id="clock-w">30:00</div>
      </div>
      <div class="rules-note" id="rules-note"></div>
    </aside>
    <section class="board-wrap"><div class="board-frame"><canvas id="play-canvas"></canvas></div></section>
    <aside class="panel right">
      <div class="sec" style="flex:1;display:flex;flex-direction:column;min-height:0">
        <h3>手 数</h3>
        <div class="movelist" id="movelist"></div>
      </div>
      <div class="sec">
        <h3>局 势</h3>
        <div class="own-canvas-wrap"><canvas id="wr-cv" width="536" height="192"></canvas></div>
        <div class="wr-now"><span>黑 <b id="wr-b">50%</b></span><span id="wr-lead">均势</span><span>白 <b id="wr-w">50%</b></span></div>
        <div class="wr-bar"><i id="wr-fill" style="width:50%"></i></div>
      </div>
      <div class="sec" id="hint-sec">
        <h3>A I 推 荐</h3>
        <div class="hint-box" id="hint-box"><span class="pct">—</span><div id="hint-text">开启下方按钮后显示</div></div>
      </div>
    </aside>
  </main>
  <footer class="controls">
    <button class="btn" id="btn-undo">悔 棋<span class="kbd">Ctrl+Z</span></button>
    <button class="btn" id="btn-pass">停 一 手</button>
    <button class="btn danger" id="btn-resign">认 输</button>
    <div class="divider"></div>
    <button class="btn toggle" id="btn-hint">💡 AI 推荐</button>
    <button class="btn toggle" id="btn-terr">⚖ 形势判断</button>
    <div class="divider"></div>
    <button class="btn" id="btn-menu">主菜单</button>
  </footer>`;

  board = new GoBoard(document.getElementById("play-canvas") as HTMLCanvasElement, {
    onPlay: async (p) => {
      if (!state || state.status !== "playing") return;
      try {
        await api("/api/game/move", { point: p });
      } catch (e) {
        toast(String(e), true);
      }
    },
    onToggleDead: async (p) => {
      if (!state) return;
      const cur = new Set(state.dead_stones);
      if (cur.has(p)) cur.delete(p);
      else cur.add(p);
      try {
        const r = await api<{ score_preview: GameState["score_preview"] }>(
          "/api/game/dead-stones",
          { points: [...cur] },
        );
        if (state) {
          state.dead_stones = [...cur];
          state.score_preview = r.score_preview;
        }
        board.setDeadStones(cur);
        renderScoringDialog();
      } catch (e) {
        toast(String(e), true);
      }
    },
  });

  const $ = (id: string) => document.getElementById(id)! as HTMLElement;
  els = {
    "pc-b": $("pc-b"), "pc-w": $("pc-w"),
    "name-b": $("name-b"), "name-w": $("name-w"),
    "tag-b": $("tag-b"), "tag-w": $("tag-w"),
    "cap-b": $("cap-b"), "cap-w": $("cap-w"),
    "byo-b": $("byo-b"), "byo-w": $("byo-w"),
    "clock-b": $("clock-b"), "clock-w": $("clock-w"),
    rules: $("rules-note"), movelist: $("movelist"),
    wrB: $("wr-b"), wrW: $("wr-w"), wrLead: $("wr-lead"), wrFill: $("wr-fill"),
    hintText: $("hint-text"), hintSec: $("hint-sec"),
    chip: document.getElementById("top-chip")!,
  };

  $("btn-undo").addEventListener("click", doUndo);
  $("btn-pass").addEventListener("click", doPass);
  $("btn-resign").addEventListener("click", doResign);
  $("btn-menu").addEventListener("click", () => showScreen("menu"));
  $("btn-hint").addEventListener("click", () => {
    hintOn = !hintOn;
    $("btn-hint").classList.toggle("on", hintOn);
    if (hintOn) void fetchHint();
    else board.setHints(null);
  });
  $("btn-terr").addEventListener("click", () => {
    terrOn = !terrOn;
    $("btn-terr").classList.toggle("on", terrOn);
    if (terrOn) void fetchTerritory();
    else board.setTerritory(null);
  });

  document.addEventListener("keydown", (e) => {
    if (!document.getElementById("screen-play")!.classList.contains("active")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      void doUndo();
    }
  });
}

export function activatePlay(): void {
  if (state) applyState(state, true);
}
export function deactivatePlay(): void {
  /* 暂无需要 */
}

// ── 操作 ──
async function doUndo(): Promise<void> {
  try {
    const r = await api<{ ok: boolean; undid: number }>("/api/game/undo", {});
    if (!r.ok) toast("无可悔之棋");
    hintMoveCount = -1;
    terrMoveCount = -1;
    board.setHints(null);
    board.setTerritory(null);
  } catch (e) {
    toast(String(e), true);
  }
}

async function doPass(): Promise<void> {
  try {
    await api("/api/game/pass", {});
    toast("停一手");
  } catch (e) {
    toast(String(e), true);
  }
}

async function doResign(): Promise<void> {
  if (!state || state.status === "ended") return;
  const d = showDialog(`
    <h2>认输确认</h2>
    <div class="body">确定中盘认输吗？认输后对局结束并保存棋谱。</div>
    <div class="actions"><button class="btn" id="dlg-cancel">再想想</button>
    <button class="btn primary" id="dlg-yes">认 输</button></div>`);
  d.querySelector("#dlg-cancel")!.addEventListener("click", closeDialog);
  d.querySelector("#dlg-yes")!.addEventListener("click", async () => {
    closeDialog();
    try {
      const myColor = state!.mode === "ai" ? state!.human_color : state!.to_play;
      await api("/api/game/resign", { color: myColor });
    } catch (e) {
      toast(String(e), true);
    }
  });
}

// ── AI 推荐 / 形势判断 ──
/** 是否轮到"人"落子（人机模式下 AI 回合不显示推荐） */
function isHumanTurn(): boolean {
  if (!state || state.status !== "playing") return false;
  return state.mode !== "ai" || state.to_play === state.human_color;
}

function clearHints(): void {
  hintMoveCount = -1;
  board.setHints(null);
  els.hintText.innerHTML = "等待您行棋时显示";
  const pct = els.hintText.parentElement!.querySelector(".pct");
  if (pct) pct.textContent = "—";
}

async function fetchHint(): Promise<void> {
  if (!state || state.status !== "playing" || !isHumanTurn()) return;
  try {
    const h = await api<HintData>("/api/game/hint");
    // 响应到达时局面或轮次已变 → 丢弃
    if (!hintOn || !state || h.move_count !== state.moves.length || !isHumanTurn()) return;
    hintMoveCount = h.move_count;
    board.setHints(h.moves);
    if (h.moves.length) {
      const m = h.moves[0];
      els.hintText.innerHTML = `<b>${coordName(m.point, state.size)}</b> · 胜率 ${(m.winrate_black * 100).toFixed(1)}%<small>由最高棋力引擎实时计算</small>`;
      els.hintText.parentElement!.querySelector(".pct")!.textContent = `${coordName(m.point, state.size)}`;
    }
    updateWinrate(h.winrate_black, h.score_lead_black);
  } catch (e) {
    toast(String(e), true);
  }
}

async function fetchTerritory(): Promise<void> {
  if (!state || state.status !== "playing") return;
  try {
    const t = await api<TerritoryData>("/api/game/territory");
    if (!terrOn || t.move_count !== state.moves.length) return;
    terrMoveCount = t.move_count;
    board.setTerritory(t.ownership);
    updateWinrate(t.winrate_black, t.score_lead_black);
  } catch (e) {
    toast(String(e), true);
  }
}

function updateWinrate(wrBlack: number, lead: number): void {
  const pct = wrBlack * 100;
  els.wrB.textContent = `${pct.toFixed(1)}%`;
  els.wrW.textContent = `${(100 - pct).toFixed(1)}%`;
  els.wrFill.style.width = `${pct}%`;
  els.wrLead.textContent =
    Math.abs(lead) < 1 ? "均势" : lead > 0 ? `黑优 ${lead.toFixed(1)} 目` : `白优 ${(-lead).toFixed(1)} 目`;
  // 每个手数只保留一个点：替换同手数记录，丢弃悔棋后多余的更高手数
  const n = state?.moves.length ?? 0;
  winrateHist = winrateHist.filter((p) => p.n < n);
  winrateHist.push({ n, wr: wrBlack });
  drawWinrateCurve();
}

// ── 胜率迷你曲线 ──
function drawWinrateCurve(): void {
  const cv = document.getElementById("wr-cv") as HTMLCanvasElement;
  const g = cv.getContext("2d")!;
  const W = cv.width, H = cv.height, mid = H / 2;
  g.clearRect(0, 0, W, H);
  g.fillStyle = "rgba(79,127,217,.10)";
  g.fillRect(0, 0, W, mid);
  g.strokeStyle = "rgba(255,255,255,.12)";
  g.setLineDash([4, 5]);
  g.lineWidth = 1;
  g.beginPath(); g.moveTo(0, mid); g.lineTo(W, mid); g.stroke();
  g.setLineDash([]);
  if (winrateHist.length < 2) {
    g.font = "600 22px Consolas,monospace";
    g.fillStyle = "rgba(233,221,196,.5)";
    g.fillText("黑", 14, 26); g.fillText("白", 14, H - 12);
    return;
  }
  const px = (i: number) => 8 + (i * (W - 16)) / (winrateHist.length - 1);
  const py = (v: number) => H - 8 - v * (H - 16);
  g.strokeStyle = "#d9b96a";
  g.lineWidth = 2.4;
  g.lineJoin = "round";
  g.beginPath();
  winrateHist.forEach((p, i) => (i ? g.lineTo(px(i), py(p.wr)) : g.moveTo(px(i), py(p.wr))));
  g.stroke();
  const last = winrateHist[winrateHist.length - 1];
  g.fillStyle = "#e8c860";
  g.beginPath();
  g.arc(px(winrateHist.length - 1), py(last.wr), 4, 0, 7);
  g.fill();
  g.font = "600 22px Consolas,monospace";
  g.fillStyle = "rgba(233,221,196,.6)";
  g.fillText("黑", 14, 26); g.fillText("白", 14, H - 12);
}

// ── 状态应用 ──
let gameId: string | null = null;

function applyState(s: GameState, force = false): void {
  const prev = state;
  state = s;

  // 换了新对局：清空全部派生数据（胜率历史/覆盖层）
  if (s.id !== gameId) {
    gameId = s.id;
    winrateHist = [];
    hintMoveCount = -1;
    terrMoveCount = -1;
    board.setHints(null);
    board.setTerritory(null);
    drawWinrateCurve();
  }

  if (board.size !== s.size) board.setSize(s.size); // 仅尺寸变化时重置

  // 落子动画：对比新手
  if (
    prev &&
    s.moves.length > prev.moves.length &&
    s.moves.length - prev.moves.length === 1 &&
    !force
  ) {
    const m = s.moves[s.moves.length - 1];
    const captured = m.captured.map((p) => ({ point: p, color: m.color === BLACK ? 2 : 1 }));
    board.playMove(s.board, m.point, m.color, captured);
    sfx.stone();
    if (captured.length) setTimeout(() => sfx.capture(), 120);
  } else {
    board.setPosition(s.board, s.last_move, s.to_play);
  }

  board.setDeadStones(s.dead_stones);
  board.mode = s.status === "scoring" ? "scoring" : "play";
  board.clickableColor =
    s.status === "playing" ? (s.mode === "ai" ? s.human_color : s.to_play) : null;

  // 左侧卡片
  els["name-b"].textContent = s.names.black;
  els["name-w"].textContent = s.names.white;
  els["tag-b"].textContent = s.mode === "ai" && s.human_color === BLACK ? "您 · 先手" : "先手";
  els["tag-w"].textContent = s.mode === "ai" && s.human_color === 2 ? "您" : "";
  els["cap-b"].textContent = String(s.captures.black);
  els["cap-w"].textContent = String(s.captures.white);
  updateClocks(s.clocks);

  // 顶栏角标
  const diff = { easy: "简单", medium: "中等", hard: "困难" }[s.difficulty] ?? s.difficulty;
  els.chip.style.display = "";
  els.chip.textContent =
    s.mode === "ai"
      ? `人机对局 · ${diff} · ${s.human_color === BLACK ? "执黑" : "执白"}`
      : "双人对弈";

  // 手数列表
  const list = els.movelist;
  list.innerHTML = "";
  const LETN = 19;
  for (let i = 0; i < s.moves.length; i += 2) {
    const row = document.createElement("div");
    row.className = "mv-row";
    const b = s.moves[i];
    let html = `<span><i class="n">${b.n}.</i><b class="b">● ${b.point == null ? "停" : coordName(b.point, LETN)}</b></span>`;
    if (s.moves[i + 1]) {
      const w = s.moves[i + 1];
      html += `<span><i class="n">${w.n}.</i><b class="w">○ ${w.point == null ? "停" : coordName(w.point, LETN)}</b></span>`;
    }
    row.innerHTML = html;
    list.appendChild(row);
  }
  list.scrollTop = list.scrollHeight;

  // 用时说明
  const t = s.time;
  els.rules.innerHTML = t.main
    ? `<b>用时规则</b><br>主用时 ${fmtClock(t.main, false)}，耗尽后进入<br>${t.byo}s 读秒 ×${t.periods}，用尽判负。<br>中国规则 · 贴 ${s.komi} 目 · 第 <b>${s.moves.length + 1}</b> 手`
    : `<b>不限时</b><br>中国规则 · 贴 ${s.komi} 目<br>第 <b>${s.moves.length + 1}</b> 手`;

  // 按钮状态
  setBtn("btn-undo", s.status === "playing" || s.status === "scoring");
  setBtn("btn-pass", s.status === "playing");
  setBtn("btn-resign", s.status === "playing");

  // AI 推荐/形势：局面一变立即撤下旧覆盖层（避免标记落在对方新子上），再按需刷新
  if (s.status === "playing") {
    const humanTurn = isHumanTurn();
    if (hintOn) {
      if (!humanTurn || hintMoveCount !== s.moves.length) {
        clearHints(); // AI 回合或局面已变：先清掉旧推荐
      }
      if (humanTurn && hintOn && hintMoveCount !== s.moves.length) void fetchHint();
    }
    if (terrOn && terrMoveCount !== s.moves.length) {
      board.setTerritory(null);
      terrMoveCount = -1;
      void fetchTerritory();
    }
  } else {
    // 点目/终局阶段撤下推荐
    if (hintMoveCount !== -1) clearHints();
  }

  // 点目 / 结果流程
  if (s.status === "scoring") showScoringDialog();
  else closeDialog();
  if (s.status === "ended" && s.result) showResultDialog(s);
}

function setBtn(id: string, enabled: boolean): void {
  const b = document.getElementById(id) as HTMLButtonElement | null;
  if (b) b.disabled = !enabled;
}

function updateClocks(clocks: Record<string, { display: number; in_byo: boolean; byo_periods: number; unlimited: boolean }>): void {
  for (const [c, view] of Object.entries(clocks)) {
    const el = els[`clock-${c === "1" ? "b" : "w"}`];
    const byoEl = els[`byo-${c === "1" ? "b" : "w"}`];
    el.textContent = view.unlimited ? "∞" : fmtClock(view.display, view.in_byo);
    el.classList.toggle("warn", view.in_byo && view.display <= 15);
    if (view.unlimited) {
      byoEl.style.display = "none";
    } else if (view.in_byo) {
      byoEl.style.display = "";
      byoEl.textContent = `读秒 ×${view.byo_periods}`;
    } else {
      byoEl.style.display = "none";
    }
  }
  if (state) {
    els["pc-b"].classList.toggle("active", state.to_play === BLACK && state.status === "playing");
    els["pc-w"].classList.toggle("active", state.to_play === 2 && state.status === "playing");
    const think = els["byo-w"];
    if (state.ai_thinking && state.ai_color === 2) {
      think.style.display = "";
      think.className = "byo-chip think";
      think.textContent = "思考中…";
    } else if (state.ai_thinking && state.ai_color === BLACK) {
      const tb = els["byo-b"];
      tb.style.display = "";
      tb.className = "byo-chip think";
      tb.textContent = "思考中…";
    }
  }
}

// ── 点目弹层 ──
function showScoringDialog(): void {
  if (!state?.score_preview) return;
  const d = showDialog(`
    <h2>终局点目</h2>
    <div class="body">
      双方连续停一手，进入点目。<b>点击棋盘上的死子</b>可手动调整死活（已自动用 AI 判定）。
      <div class="score-line">
        <span>黑 <b>${state.score_preview.black_area}</b> 子</span>
        <span style="color:var(--gold-soft)">${state.score_preview.text}</span>
        <span>白 <b>${state.score_preview.white_area}</b> 子（含贴目）</span>
      </div>
    </div>
    <div class="actions">
      <button class="btn" id="dlg-continue">继续下（撤销停一手）</button>
      <button class="btn primary" id="dlg-confirm">确认结果</button>
    </div>`);
  d.querySelector("#dlg-confirm")!.addEventListener("click", async () => {
    closeDialog();
    try {
      await api("/api/game/confirm-score", {});
    } catch (e) {
      toast(String(e), true);
    }
  });
  d.querySelector("#dlg-continue")!.addEventListener("click", async () => {
    closeDialog();
    await api("/api/game/undo", {});
  });
}

function renderScoringDialog(): void {
  if (state?.status === "scoring") showScoringDialog();
}

// ── 结果弹层 ──
function showResultDialog(s: GameState): void {
  const r = s.result!;
  const who = r.winner == null ? "和棋" : r.winner === BLACK ? "黑方胜" : "白方胜";
  const d = showDialog(`
    <h2>对局结束</h2>
    <div class="body" style="text-align:center">
      <div style="font-family:var(--kai);font-size:44px;color:var(--gold);margin:8px 0">${who}</div>
      <div>${r.detail}</div>
      <div style="color:var(--ink-dim);font-size:12px;margin-top:10px">棋谱已自动保存，可到棋谱库复盘</div>
    </div>
    <div class="actions">
      <button class="btn" id="dlg-close">留在此页</button>
      <button class="btn" id="dlg-menu2">回主菜单</button>
    </div>`);
  d.querySelector("#dlg-close")!.addEventListener("click", closeDialog);
  d.querySelector("#dlg-menu2")!.addEventListener("click", () => {
    closeDialog();
    showScreen("menu");
  });
}

// ── WS 事件入口（由 main 转发） ──
export function onGameEvent(ev: WsEvent): void {
  switch (ev.type) {
    case "state":
      applyState(ev.game);
      break;
    case "clocks":
      if (state) {
        state.clocks = ev.clocks;
        state.to_play = ev.to_play;
        updateClocks(ev.clocks);
      }
      break;
    case "saved":
      toast(`棋谱已保存：${ev.path}`);
      break;
    case "error":
      toast(ev.message, true);
      break;
    default:
      break;
  }
}
