/** 对局页：棋盘 + 计时 + 操作 + AI推荐/形势判断 + 点目/结果流程。 */

import { api } from "../api";
import { GoBoard } from "../board";
import { sfx } from "../audio";
import { errPayloadText, errText, t } from "../i18n";
import type { MsgKey } from "../i18n";
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

const DIFF_KEY: Record<string, MsgKey> = {
  easy: "diff.easy",
  medium: "diff.medium",
  hard: "diff.hard",
};

export function initPlay(): void {
  const root = document.getElementById("screen-play")!;
  root.innerHTML = `
  <main class="play-main">
    <aside class="panel left">
      <div class="player-card" id="pc-b">
        <div class="row"><span class="stone-ico b"></span>
          <div><div class="p-name" id="name-b">${t("play.default_black")}</div><div class="p-tag" id="tag-b"></div></div></div>
        <div class="meta"><span class="cap-num">${t("play.captures")} <b id="cap-b">0</b></span><span class="byo-chip" id="byo-b" style="display:none"></span></div>
        <div class="clock" id="clock-b">30:00</div>
      </div>
      <div class="player-card" id="pc-w">
        <div class="row"><span class="stone-ico w"></span>
          <div><div class="p-name" id="name-w">${t("play.default_white")}</div><div class="p-tag" id="tag-w"></div></div></div>
        <div class="meta"><span class="cap-num">${t("play.captures")} <b id="cap-w">0</b></span><span class="byo-chip" id="byo-w" style="display:none"></span></div>
        <div class="clock" id="clock-w">30:00</div>
      </div>
      <div class="rules-note" id="rules-note"></div>
    </aside>
    <section class="board-wrap"><div class="board-frame"><canvas id="play-canvas"></canvas></div></section>
    <aside class="panel right">
      <div class="sec" style="flex:1;display:flex;flex-direction:column;min-height:0">
        <h3>${t("play.moves")}</h3>
        <div class="movelist" id="movelist"></div>
      </div>
      <div class="sec">
        <h3>${t("play.trend")}</h3>
        <div class="own-canvas-wrap"><canvas id="wr-cv" width="536" height="192"></canvas></div>
        <div class="wr-now"><span>${t("stone.black")} <b id="wr-b">50%</b></span><span id="wr-lead">${t("play.balanced")}</span><span>${t("stone.white")} <b id="wr-w">50%</b></span></div>
        <div class="wr-bar"><i id="wr-fill" style="width:50%"></i></div>
      </div>
      <div class="sec" id="hint-sec">
        <h3>${t("play.hint_title")}</h3>
        <div class="hint-box" id="hint-box"><span class="pct">—</span><div id="hint-text">${t("play.hint_off")}</div></div>
      </div>
    </aside>
  </main>
  <footer class="controls">
    <button class="btn" id="btn-undo">${t("play.undo")}<span class="kbd">Ctrl+Z</span></button>
    <button class="btn" id="btn-pass">${t("play.pass")}</button>
    <button class="btn" id="btn-score">${t("play.score_btn")}</button>
    <button class="btn danger" id="btn-resign">${t("play.resign")}</button>
    <div class="divider"></div>
    <button class="btn toggle" id="btn-hint">${t("play.hint_toggle")}</button>
    <button class="btn toggle" id="btn-terr">${t("play.terr_toggle")}</button>
    <div class="divider"></div>
    <button class="btn" id="btn-menu">${t("play.menu")}</button>
  </footer>`;

  board = new GoBoard(document.getElementById("play-canvas") as HTMLCanvasElement, {
    onPlay: async (p) => {
      if (!state || state.status !== "playing") return;
      try {
        await api("/api/game/move", { point: p });
      } catch (e) {
        toast(errText(e), true);
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
        toast(errText(e), true);
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
  $("btn-score").addEventListener("click", doScore);
  $("btn-resign").addEventListener("click", doResign);
  $("btn-menu").addEventListener("click", () => showScreen("menu"));
  const btnHint = $("btn-hint");
  const btnTerr = $("btn-terr");
  btnHint.classList.toggle("on", hintOn);
  btnTerr.classList.toggle("on", terrOn);
  btnHint.addEventListener("click", () => {
    hintOn = !hintOn;
    btnHint.classList.toggle("on", hintOn);
    if (hintOn) void fetchHint();
    else board.setHints(null);
  });
  btnTerr.addEventListener("click", () => {
    terrOn = !terrOn;
    btnTerr.classList.toggle("on", terrOn);
    if (terrOn) void fetchTerritory();
    else board.setTerritory(null);
  });
}

// document 级监听只挂一次（initPlay 可重复调用于语言切换重建）
document.addEventListener("keydown", (e) => {
  if (!document.getElementById("screen-play")?.classList.contains("active")) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    void doUndo();
  }
});

export function activatePlay(): void {
  if (state) applyState(state, true);
}
export function deactivatePlay(): void {
  /* 暂无需要 */
}

/** 语言切换后按当前状态与语言重渲染（棋盘/曲线/覆盖层全部恢复）。 */
export function reapplyPlay(): void {
  hintMoveCount = -1;
  terrMoveCount = -1;
  if (state) applyState(state, true);
  drawWinrateCurve();
}

// ── 操作 ──
async function doUndo(): Promise<void> {
  try {
    const r = await api<{ ok: boolean; undid: number }>("/api/game/undo", {});
    if (!r.ok) toast(t("play.no_undo"));
    hintMoveCount = -1;
    terrMoveCount = -1;
    board.setHints(null);
    board.setTerritory(null);
  } catch (e) {
    toast(errText(e), true);
  }
}

async function doPass(): Promise<void> {
  try {
    await api("/api/game/pass", {});
    toast(t("play.passed"));
  } catch (e) {
    toast(errText(e), true);
  }
}

/** 主动点目：交给引擎判定死活并预览结果，接受与否在点目弹层中选择。 */
async function doScore(): Promise<void> {
  if (!state || state.status !== "playing") return;
  try {
    toast(t("play.scoring_toast"));
    await api("/api/game/score", {});
  } catch (e) {
    toast(errText(e), true);
  }
}

async function doResign(): Promise<void> {
  if (!state || state.status === "ended") return;
  const d = showDialog(`
    <h2>${t("play.resign_title")}</h2>
    <div class="body">${t("play.resign_body")}</div>
    <div class="actions"><button class="btn" id="dlg-cancel">${t("play.resign_cancel")}</button>
    <button class="btn primary" id="dlg-yes">${t("play.resign_ok")}</button></div>`);
  d.querySelector("#dlg-cancel")!.addEventListener("click", closeDialog);
  d.querySelector("#dlg-yes")!.addEventListener("click", async () => {
    closeDialog();
    try {
      const myColor = state!.mode === "ai" ? state!.human_color : state!.to_play;
      await api("/api/game/resign", { color: myColor });
    } catch (e) {
      toast(errText(e), true);
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
  els.hintText.innerHTML = t("play.hint_wait");
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
      const coord = coordName(m.point, state.size);
      // 胜率按玩家棋色显示：推荐只在轮到该玩家时出现，视角即推荐局面的行棋方
      const myWr = h.to_play === BLACK ? m.winrate_black : 1 - m.winrate_black;
      els.hintText.innerHTML = t("play.hint_item", {
        coord,
        p: (myWr * 100).toFixed(1),
      });
      els.hintText.parentElement!.querySelector(".pct")!.textContent = coord;
    }
    updateWinrate(h.winrate_black, h.score_lead_black);
  } catch (e) {
    toast(errText(e), true);
  }
}

async function fetchTerritory(): Promise<void> {
  if (!state || state.status !== "playing") return;
  try {
    const t0 = await api<TerritoryData>("/api/game/territory");
    if (!terrOn || t0.move_count !== state.moves.length) return;
    terrMoveCount = t0.move_count;
    board.setTerritory(t0.ownership);
    updateWinrate(t0.winrate_black, t0.score_lead_black);
  } catch (e) {
    toast(errText(e), true);
  }
}

function updateWinrate(wrBlack: number, lead: number): void {
  const pct = wrBlack * 100;
  els.wrB.textContent = `${pct.toFixed(1)}%`;
  els.wrW.textContent = `${(100 - pct).toFixed(1)}%`;
  els.wrFill.style.width = `${pct}%`;
  els.wrLead.textContent =
    Math.abs(lead) < 1
      ? t("play.balanced")
      : lead > 0
        ? t("play.black_lead", { x: lead.toFixed(1) })
        : t("play.white_lead", { x: (-lead).toFixed(1) });
  // 每个手数只保留一个点：替换同手数记录，丢弃悔棋后多余的更高手数
  const n = state?.moves.length ?? 0;
  winrateHist = winrateHist.filter((p) => p.n < n);
  winrateHist.push({ n, wr: wrBlack });
  drawWinrateCurve();
}

// ── 胜率迷你曲线 ──
function drawWinrateCurve(): void {
  const cv = document.getElementById("wr-cv") as HTMLCanvasElement;
  if (!cv) return;
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
    g.fillText(t("stone.black"), 14, 26); g.fillText(t("stone.white"), 14, H - 12);
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
  g.fillText(t("stone.black"), 14, 26); g.fillText(t("stone.white"), 14, H - 12);
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
  els["tag-b"].textContent = s.mode === "ai" && s.human_color === BLACK ? t("play.you_first") : t("play.first");
  els["tag-w"].textContent = s.mode === "ai" && s.human_color === 2 ? t("play.you") : "";
  els["cap-b"].textContent = String(s.captures.black);
  els["cap-w"].textContent = String(s.captures.white);
  updateClocks(s.clocks);

  // 顶栏角标
  const diff = t(DIFF_KEY[s.difficulty] ?? "diff.medium");
  els.chip.style.display = "";
  els.chip.textContent =
    s.mode === "ai"
      ? t("play.chip_ai", {
          diff,
          color: t(s.human_color === BLACK ? "common.black_stone" : "common.white_stone"),
        })
      : t("play.chip_pvp");

  // 手数列表
  const list = els.movelist;
  list.innerHTML = "";
  const LETN = 19;
  for (let i = 0; i < s.moves.length; i += 2) {
    const row = document.createElement("div");
    row.className = "mv-row";
    const b = s.moves[i];
    let html = `<span><i class="n">${b.n}.</i><b class="b">● ${b.point == null ? t("play.pass_mark") : coordName(b.point, LETN)}</b></span>`;
    if (s.moves[i + 1]) {
      const w = s.moves[i + 1];
      html += `<span><i class="n">${w.n}.</i><b class="w">○ ${w.point == null ? t("play.pass_mark") : coordName(w.point, LETN)}</b></span>`;
    }
    row.innerHTML = html;
    list.appendChild(row);
  }
  list.scrollTop = list.scrollHeight;

  // 用时说明
  const tm = s.time;
  els.rules.innerHTML = tm.main
    ? `<b>${t("play.rules_title")}</b><br>${t("play.rules_timed", {
        main: fmtClock(tm.main, false),
        byo: tm.byo,
        periods: tm.periods,
      })}<br>${t("play.rules_komi_move", { komi: s.komi, n: s.moves.length + 1 })}`
    : `<b>${t("play.rules_free")}</b><br>${t("play.rules_komi", {
        komi: s.komi,
      })}<br>${t("play.rules_move", { n: s.moves.length + 1 })}`;

  // 按钮状态（点目阶段的出口在点目弹层：确认结果 / 继续对弈）
  setBtn("btn-undo", s.status === "playing");
  setBtn("btn-pass", s.status === "playing");
  setBtn("btn-score", s.status === "playing");
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
  else if (!s.result) closeDialog();
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
      byoEl.textContent = t("play.byo_n", { n: view.byo_periods });
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
      think.textContent = t("play.thinking");
    } else if (state.ai_thinking && state.ai_color === BLACK) {
      const tb = els["byo-b"];
      tb.style.display = "";
      tb.className = "byo-chip think";
      tb.textContent = t("play.thinking");
    }
  }
}

/** 点目/终局结果文案（由 winner/margin/子数组合，语言相关）。 */
function scoreText(winner: number, margin: number, b: number, w: number): string {
  return !winner
    ? t("play.draw_text")
    : t("play.score_text", {
        who: t(winner === BLACK ? "stone.black" : "stone.white"),
        margin,
        b,
        w,
      });
}

// ── 点目弹层 ──
function showScoringDialog(): void {
  // 引擎死活判定完成前无预览：先给"等待 + 继续对弈"出口，判定到达后整层重渲染
  if (!state?.score_preview) {
    const wait = showDialog(`
      <h2>${t("play.score_title")}</h2>
      <div class="body">${t("play.scoring_wait")}</div>
      <div class="actions">
        <button class="btn" id="dlg-continue">${t("play.score_resume")}</button>
      </div>`);
    wait.querySelector("#dlg-continue")!.addEventListener("click", doResume);
    return;
  }
  const sp = state.score_preview;
  const d = showDialog(`
    <h2>${t("play.score_title")}</h2>
    <div class="body">
      ${t("play.score_desc")}
      <div class="score-line">
        <span>${t("play.black_area", { b: sp.black_area })}</span>
        <span style="color:var(--gold-soft)">${scoreText(sp.winner, sp.margin, sp.black_area, sp.white_area)}</span>
        <span>${t("play.white_area", { w: sp.white_area })}</span>
      </div>
    </div>
    <div class="actions">
      <button class="btn" id="dlg-continue">${t("play.score_resume")}</button>
      <button class="btn primary" id="dlg-confirm">${t("play.score_confirm")}</button>
    </div>`);
  d.querySelector("#dlg-confirm")!.addEventListener("click", async () => {
    closeDialog();
    try {
      await api("/api/game/confirm-score", {});
    } catch (e) {
      toast(errText(e), true);
    }
  });
  d.querySelector("#dlg-continue")!.addEventListener("click", doResume);
}

/** 拒绝点目结果：不撤手数，返回对弈继续下。 */
async function doResume(): Promise<void> {
  closeDialog();
  try {
    await api("/api/game/resume", {});
  } catch (e) {
    toast(errText(e), true);
  }
}

function renderScoringDialog(): void {
  if (state?.status === "scoring") showScoringDialog();
}

// ── 结果弹层 ──
function showResultDialog(s: GameState): void {
  const r = s.result!;
  const who = r.winner == null ? t("play.draw") : r.winner === BLACK ? t("play.black_win") : t("play.white_win");
  let line: string;
  if (r.reason === "timeout") {
    line = t("play.reason_timeout");
  } else if (r.reason === "resign") {
    const loser = 3 - (r.winner ?? 1); // 认输方
    line = t("play.reason_resign", {
      who: t(loser === BLACK ? "play.default_black" : "play.default_white"),
    });
  } else {
    const sp = s.score_preview;
    line = sp
      ? scoreText(r.winner ?? 0, r.margin, sp.black_area, sp.white_area)
      : t("play.draw_text");
  }
  const d = showDialog(`
    <h2>${t("play.result_title")}</h2>
    <div class="body" style="text-align:center">
      <div style="font-family:var(--kai);font-size:44px;color:var(--gold);margin:8px 0">${who}</div>
      <div>${line}</div>
      <div style="color:var(--ink-dim);font-size:12px;margin-top:10px">${t("play.saved_note")}</div>
    </div>
    <div class="actions">
      <button class="btn" id="dlg-close">${t("play.stay")}</button>
      <button class="btn" id="dlg-menu2">${t("play.back_menu")}</button>
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
      toast(t("play.saved_toast", { path: ev.path }));
      break;
    case "error":
      toast(errPayloadText(ev.error), true);
      break;
    default:
      break;
  }
}
