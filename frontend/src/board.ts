/** 拟真围棋棋盘 Canvas 组件。

纯色木底、质感棋子（渐变+高光+投影）、落子/提子动画、
悬停幽灵子、AI 推荐标记、形势热力图、死子标记、复盘导航。
*/

import type { HintMove } from "./types";
import { HINT_COLORS, hintBackground, hintWinrate, isPreferredHint, MAX_HINTS } from "./hint-style";
import { t } from "./i18n";

const BLACK = 1;
const WHITE = 2;

export interface BoardCallbacks {
  onPlay?: (point: number) => void;
  onToggleDead?: (point: number) => void;
  onHover?: (point: number | null) => void;
}

interface Anim {
  t0: number; // performance.now()
  dur: number;
  kind: "place" | "capture";
  color: number;
}

export class GoBoard {
  readonly canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private cb: BoardCallbacks;
  private sizeN = 19;
  private board: Int8Array;
  private lastMove: number | null = null;
  private toPlay = BLACK;
  private hints: HintMove[] | null = null;
  private territory: number[] | null = null;
  private dead = new Set<number>();
  private anims = new Map<number, Anim>();
  private hover: number | null = null;
  private raf = 0;
  private cssSize = 0;
  private dpr = 1;

  /** 当前路数（公开只读） */
  get size(): number {
    return this.sizeN;
  }

  /** play: 人落子; scoring: 点死子; review: 仅展示 */
  mode: "play" | "scoring" | "review" = "play";
  /** 哪一方的轮次允许点击落子（null=不可落子） */
  clickableColor: number | null = BLACK;

  constructor(canvas: HTMLCanvasElement, cb: BoardCallbacks = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d")!;
    this.cb = cb;
    this.board = new Int8Array(this.sizeN * this.sizeN);
    this.bindInput();
    const ro = new ResizeObserver(() => this.layout());
    ro.observe(canvas.parentElement ?? canvas);
    this.layout();
  }

  // ── 布局 ─────────────────────────────────────────────

  private get margin(): number {
    return this.cssSize * 0.055;
  }
  private get cell(): number {
    return (this.cssSize - this.margin * 2) / (this.sizeN - 1);
  }
  gx(i: number): number {
    return this.margin + (i - 1) * this.cell;
  }

  private layout(): void {
    const parent = this.canvas.parentElement;
    const w = parent ? Math.min(parent.clientWidth, parent.clientHeight) : 640;
    this.cssSize = Math.max(320, w);
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.round(this.cssSize * this.dpr);
    this.canvas.height = Math.round(this.cssSize * this.dpr);
    this.canvas.style.width = `${this.cssSize}px`;
    this.canvas.style.height = `${this.cssSize}px`;
    this.render();
  }

  // ── 状态 ─────────────────────────────────────────────

  setSize(n: number): void {
    this.sizeN = n;
    this.board = new Int8Array(n * n);
    this.dead.clear();
    this.anims.clear();
    this.lastMove = null;
  }

  setPosition(board: ArrayLike<number>, lastMove: number | null, toPlay: number): void {
    this.board = Int8Array.from(board);
    this.lastMove = lastMove;
    this.toPlay = toPlay;
    this.updateHintTitle();
    this.render();
  }

  /** 播放一手：设置位置并触发挥子动画（captured 为被提点及其颜色） */
  playMove(
    board: ArrayLike<number>,
    point: number | null,
    color: number,
    captured: { point: number; color: number }[],
  ): void {
    this.board = Int8Array.from(board);
    this.lastMove = point;
    this.toPlay = color === BLACK ? WHITE : BLACK;
    const now = performance.now();
    if (point != null) this.anims.set(point, { t0: now, dur: 200, kind: "place", color });
    for (const c of captured) this.anims.set(c.point, { t0: now, dur: 340, kind: "capture", color: c.color });
    this.schedule();
  }

  setHints(h: HintMove[] | null): void {
    this.hints = h;
    this.updateHintTitle();
    this.render();
  }
  setTerritory(t: number[] | null): void {
    this.territory = t;
    this.render();
  }
  setDeadStones(pts: Iterable<number>): void {
    this.dead = new Set(pts);
    this.render();
  }

  // ── 输入 ─────────────────────────────────────────────

  private bindInput(): void {
    this.canvas.addEventListener("mousemove", (e) => {
      const p = this.pointAt(e);
      if (p !== this.hover) {
        this.hover = p;
        this.updateHintTitle();
        this.cb.onHover?.(p);
        this.render();
      }
    });
    this.canvas.addEventListener("mouseleave", () => {
      this.hover = null;
      this.updateHintTitle();
      this.cb.onHover?.(null);
      this.render();
    });
    this.canvas.addEventListener("click", (e) => {
      const p = this.pointAt(e);
      if (p == null) return;
      if (this.mode === "scoring") {
        if (this.board[p] !== 0) this.cb.onToggleDead?.(p);
      } else if (this.mode === "play" && this.clickableColor === this.toPlay) {
        if (this.board[p] === 0) this.cb.onPlay?.(p);
      }
    });
  }

  private pointAt(e: MouseEvent): number | null {
    const r = this.canvas.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * this.cssSize;
    const py = ((e.clientY - r.top) / r.height) * this.cssSize;
    const x = Math.round((px - this.margin) / this.cell) + 1;
    const y = Math.round((py - this.margin) / this.cell) + 1;
    if (x < 1 || x > this.sizeN || y < 1 || y > this.sizeN) return null;
    // 距交叉点太远不算
    const dx = px - this.gx(x);
    const dy = py - this.gx(y);
    if (dx * dx + dy * dy > this.cell * this.cell * 0.36) return null;
    return (y - 1) * this.sizeN + (x - 1);
  }

  // ── 渲染 ─────────────────────────────────────────────

  private schedule(): void {
    if (this.raf) return;
    const loop = () => {
      const now = performance.now();
      let active = false;
      for (const [p, a] of this.anims) {
        if (now - a.t0 > a.dur + 60) this.anims.delete(p);
        else active = true;
      }
      this.render();
      this.raf = active ? requestAnimationFrame(loop) : 0;
    };
    this.raf = requestAnimationFrame(loop);
  }

  render(): void {
    const { ctx } = this;
    const S = this.cssSize;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, S, S);
    this.drawWood();
    this.drawGrid();
    if (this.territory) this.drawTerritory();
    this.drawStones();
    if (this.mode === "scoring") this.drawDeadMarks();
    this.drawLastMove();
    if (this.hints && (this.mode === "play" || this.mode === "review")) this.drawHints();
    this.drawHover();
  }

  private drawWood(): void {
    // 纯净木色底：无纹理噪点，仅轻微上下明暗模拟受光
    const { ctx } = this;
    const S = this.cssSize;
    const grad = ctx.createLinearGradient(0, 0, 0, S);
    grad.addColorStop(0, "#e2b46b");
    grad.addColorStop(0.5, "#dcae5f");
    grad.addColorStop(1, "#d6a756");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, S, S);
  }

  private drawGrid(): void {
    const { ctx } = this;
    const N = this.sizeN;
    ctx.lineCap = "round";
    for (let pass = 0; pass < 2; pass++) {
      ctx.strokeStyle = pass === 0 ? "rgba(255,238,190,.35)" : "rgba(92,60,22,.85)";
      ctx.lineWidth = (pass === 0 ? 1.6 : 1.15) * Math.max(1, this.cell / 40);
      ctx.beginPath();
      for (let i = 1; i <= N; i++) {
        ctx.moveTo(this.gx(i) - 0.7, this.gx(1) + 0.7);
        ctx.lineTo(this.gx(i) - 0.7, this.gx(N) + 0.7);
        ctx.moveTo(this.gx(1) + 0.7, this.gx(i) - 0.7);
        ctx.lineTo(this.gx(N) + 0.7, this.gx(i) - 0.7);
      }
      ctx.stroke();
    }
    // 星位
    ctx.fillStyle = "rgba(80,50,18,.92)";
    const stars =
      this.sizeN === 19
        ? [4, 10, 16]
        : this.sizeN === 13
          ? [4, 7, 10]
          : this.sizeN === 9
            ? [3, 5, 7]
            : [];
    for (const sx of stars)
      for (const sy of stars) {
        ctx.beginPath();
        ctx.arc(this.gx(sx), this.gx(sy), 3.4 * Math.max(1, this.cell / 40), 0, 7);
        ctx.fill();
      }
    // 坐标
    const fs = Math.max(9, this.cell * 0.3);
    ctx.font = `${fs}px Georgia,serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(70,44,16,.62)";
    const LET = "ABCDEFGHJKLMNOPQRST";
    for (let i = 1; i <= N; i++) {
      const off = this.margin * 0.42;
      ctx.fillText(LET[i - 1], this.gx(i), this.margin - off);
      ctx.fillText(LET[i - 1], this.gx(i), this.cssSize - this.margin + off);
      ctx.fillText(String(N + 1 - i), this.margin - off, this.gx(i));
      ctx.fillText(String(N + 1 - i), this.cssSize - this.margin + off, this.gx(i));
    }
  }

  private drawStone(x: number, y: number, color: number, alpha = 1, scale = 1): void {
    const { ctx } = this;
    const r = this.cell * 0.465 * scale;
    ctx.save();
    ctx.globalAlpha = alpha;
    const sh = ctx.createRadialGradient(x + r * 0.15, y + r * 0.42, r * 0.1, x + r * 0.15, y + r * 0.42, r * 1.35);
    sh.addColorStop(0, "rgba(30,15,3,.42)");
    sh.addColorStop(0.62, "rgba(30,15,3,.20)");
    sh.addColorStop(1, "rgba(30,15,3,0)");
    ctx.fillStyle = sh;
    ctx.beginPath();
    ctx.arc(x + r * 0.15, y + r * 0.42, r * 1.35, 0, 7);
    ctx.fill();
    let g: CanvasGradient;
    if (color === BLACK) {
      g = ctx.createRadialGradient(x - r * 0.34, y - r * 0.4, r * 0.08, x, y, r * 1.02);
      g.addColorStop(0, "#65656d");
      g.addColorStop(0.32, "#2c2c31");
      g.addColorStop(0.78, "#151518");
      g.addColorStop(1, "#050506");
    } else {
      g = ctx.createRadialGradient(x - r * 0.34, y - r * 0.4, r * 0.08, x, y, r * 1.02);
      g.addColorStop(0, "#ffffff");
      g.addColorStop(0.5, "#f7f3e9");
      g.addColorStop(0.86, "#e7e1d1");
      g.addColorStop(1, "#cfc8b4");
    }
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 7);
    ctx.fill();
    const hl = ctx.createRadialGradient(x - r * 0.36, y - r * 0.44, 0, x - r * 0.36, y - r * 0.44, r * 0.55);
    hl.addColorStop(0, color === BLACK ? "rgba(255,255,255,.30)" : "rgba(255,255,255,.85)");
    hl.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = hl;
    ctx.beginPath();
    ctx.arc(x - r * 0.3, y - r * 0.34, r * 0.5, 0, 7);
    ctx.fill();
    if (color === WHITE) {
      ctx.strokeStyle = "rgba(150,155,170,.35)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(x, y, r - 0.5, Math.PI * 0.15, Math.PI * 0.85);
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawStones(): void {
    const now = performance.now();
    const N = this.sizeN;
    for (let p = 0; p < N * N; p++) {
      const c = this.board[p];
      if (c === 0) continue;
      const x = this.gx((p % N) + 1);
      const y = this.gx(Math.floor(p / N) + 1);
      const a = this.anims.get(p);
      if (!a) {
        this.drawStone(x, y, c, this.dead.has(p) ? 0.35 : 1);
        continue;
      }
      const t = Math.min(1, (now - a.t0) / a.dur);
      if (a.kind === "place") {
        const ease = 1 - Math.pow(1 - t, 3);
        this.drawStone(x, y - (1 - ease) * this.cell * 0.25, c, 0.5 + 0.5 * ease, 0.8 + 0.2 * ease);
      } else {
        this.drawStone(x, y, a.color, 1 - t, 1 - t * 0.2);
      }
    }
  }

  private drawDeadMarks(): void {
    const { ctx } = this;
    const N = this.sizeN;
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(200,60,40,.95)";
    for (const p of this.dead) {
      const x = this.gx((p % N) + 1);
      const y = this.gx(Math.floor(p / N) + 1);
      const s = this.cell * 0.18;
      ctx.beginPath();
      ctx.moveTo(x - s, y - s);
      ctx.lineTo(x + s, y + s);
      ctx.moveTo(x + s, y - s);
      ctx.lineTo(x - s, y + s);
      ctx.stroke();
    }
  }

  private drawLastMove(): void {
    if (this.lastMove == null) return;
    const { ctx } = this;
    const N = this.sizeN;
    const c = this.board[this.lastMove];
    if (!c) return;
    const x = this.gx((this.lastMove % N) + 1);
    const y = this.gx(Math.floor(this.lastMove / N) + 1);
    ctx.strokeStyle = c === BLACK ? "rgba(235,225,200,.95)" : "rgba(20,16,10,.9)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, this.cell * 0.19, 0, 7);
    ctx.stroke();
  }

  private updateHintTitle(): void {
    const hint = this.hints?.slice(0, MAX_HINTS).find((item) => item.point === this.hover);
    this.canvas.title = hint ? t("hint.tooltip", {
      kind: t(isPreferredHint(hint) ? "hint.preferred" : "hint.alternative"),
      color: t(this.toPlay === BLACK ? "stone.black" : "stone.white"),
      p: (hintWinrate(hint, this.toPlay) * 100).toFixed(1),
    }) : "";
  }

  private drawHints(): void {
    const { ctx } = this;
    const N = this.sizeN;
    const hints = this.hints!.slice(0, MAX_HINTS);
    const radius = this.cell * 0.46;
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    hints.forEach((hint) => {
      const x = this.gx((hint.point % N) + 1);
      const y = this.gx(Math.floor(hint.point / N) + 1);
      const preferred = isPreferredHint(hint);
      const inset = Math.max(2.2, Math.min(3, this.cell * 0.07));
      ctx.fillStyle = hintBackground(hint, hints, this.toPlay);
      ctx.strokeStyle = preferred ? HINT_COLORS.preferred : HINT_COLORS.border;
      ctx.lineWidth = preferred ? Math.min(2.2, this.cell * 0.1) : 1.2;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      if (preferred) {
        // 双环均在选点内，紧邻候选不重叠，也不会随胜率变化跳到其他点。
        ctx.lineWidth = 0.9;
        ctx.beginPath();
        ctx.arc(x, y, radius - inset, 0, Math.PI * 2);
        ctx.stroke();
      }

      // 小棋盘显示空间充足；窄窗口的十九路棋盘简写为整数，悬停可看完整胜率。
      const compact = this.cell < 28;
      const winrate = hintWinrate(hint, this.toPlay);
      const pct = compact
        ? `${Math.round(winrate * 100)}`
        : `${(winrate * 100).toFixed(1)}%`;
      let fontSize = Math.min(18, Math.max(9, this.cell * (compact ? 0.48 : 0.3)));
      ctx.font = `600 ${fontSize}px Consolas,monospace`;
      const available = (radius - (preferred ? inset : 0)) * 2 - 2;
      fontSize *= Math.min(1, available / ctx.measureText(pct).width);
      ctx.font = `600 ${fontSize}px Consolas,monospace`;
      // 浅色半透明选点会露出木纹和网格，给文字描深色细边以保持胜率可读。
      ctx.strokeStyle = HINT_COLORS.background;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.strokeText(pct, x, y + 0.5);
      ctx.fillStyle = HINT_COLORS.foreground;
      ctx.fillText(pct, x, y + 0.5);
    });
    ctx.restore();
  }

  private drawTerritory(): void {
    const { ctx } = this;
    const N = this.sizeN;
    const t = this.territory!;
    for (let p = 0; p < N * N; p++) {
      const v = t[p] ?? 0;
      if (Math.abs(v) < 0.12 || this.board[p] !== 0) continue;
      const x = this.gx((p % N) + 1);
      const y = this.gx(Math.floor(p / N) + 1);
      ctx.beginPath();
      ctx.arc(x, y, this.cell * 0.33, 0, 7);
      ctx.fillStyle = v > 0 ? `rgba(63,111,208,${Math.min(0.72, Math.abs(v) * 0.8)})` : `rgba(214,86,58,${Math.min(0.72, Math.abs(v) * 0.8)})`;
      ctx.fill();
    }
  }

  private drawHover(): void {
    if (this.hover == null || this.mode !== "play") return;
    if (this.clickableColor !== this.toPlay) return;
    if (this.board[this.hover] !== 0) return;
    const { ctx } = this;
    const N = this.sizeN;
    const x = this.gx((this.hover % N) + 1);
    const y = this.gx(Math.floor(this.hover / N) + 1);
    const hinted = this.hints?.slice(0, MAX_HINTS).some((hint) => hint.point === this.hover);
    if (!hinted) this.drawStone(x, y, this.toPlay, 0.45);
    // 首选的金环保持可见；悬停轮廓使用绿色，避免被误认成首选。
    ctx.strokeStyle = hinted ? HINT_COLORS.border : "rgba(228,192,84,.8)";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.arc(x, y, this.cell * 0.5, 0, 7);
    ctx.stroke();
  }
}
