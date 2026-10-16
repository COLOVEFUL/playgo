/** 主菜单：新对局 / 继续对局 / 棋谱库 / 引擎管理。 */

import { api, onWs } from "../api";
import type { EngineStatus, GameState, RecordItem } from "../types";
import { closeDialog, engineStatus, showDialog, showScreen, toast } from "../main";

const DIFFS = [
  { id: "easy", label: "简单", note: "约 15k~5k" },
  { id: "medium", label: "中等", note: "约业余 1~4 段" },
  { id: "hard", label: "困难", note: "超职业棋力" },
];
const TIMES = [
  { id: "standard", label: "30:00", note: "读秒60s×3" },
  { id: "blitz", label: "5:00", note: "读秒30s×3" },
  { id: "long", label: "60:00", note: "读秒60s×5" },
  { id: "free", label: "不限时", note: "" },
];

let sel = { mode: "ai", diff: "medium", color: 1, time: "standard" };

export function initMenu(): void {
  const root = document.getElementById("screen-menu")!;
  root.innerHTML = `
  <div class="menu-main">
    <div class="menu-hero">
      <div class="big">弈</div>
      <div class="slogan">棋 逢 对 手 · 落 子 无 悔</div>
    </div>
    <div class="menu-cards" id="resume-slot"></div>
    <div class="menu-cards">
      <div class="mcard" id="card-new">
        <div class="ico">⚫</div><h2>人机对弈</h2>
        <p>与 KataGo 引擎对局，三档棋力。可随时启用 AI 推荐与形势判断。</p>
      </div>
      <div class="mcard" id="card-pvp">
        <div class="ico">⚪</div><h2>双人对弈</h2>
        <p>同屏轮流落子，黑先白后，完整计时与读秒规则。</p>
      </div>
      <div class="mcard" id="card-records">
        <div class="ico">📖</div><h2>棋谱库 · 复盘</h2>
        <p>浏览历史对局，逐步回放，AI 深度复盘与胜率曲线。</p>
      </div>
    </div>
    <div class="panel menu-panel" id="menu-panel"></div>
    <div style="height:12px"></div>
  </div>`;

  document.getElementById("card-new")!.addEventListener("click", () => showNewGame("ai"));
  document.getElementById("card-pvp")!.addEventListener("click", () => showNewGame("pvp"));
  document.getElementById("card-records")!.addEventListener("click", () => showRecords());
}

export async function refreshMenu(focus?: string): Promise<void> {
  // 继续对局卡片
  const slot = document.getElementById("resume-slot")!;
  try {
    const st = await api<{ game: GameState | null; engine?: EngineStatus }>("/api/state");
    const panel = document.getElementById("menu-panel")!;
    if (st.game && st.game.status !== "ended") {
      const diff = { easy: "简单", medium: "中等", hard: "困难" }[st.game.difficulty] ?? "";
      slot.innerHTML = `
        <div class="mcard" id="card-resume" style="border-color:rgba(126,180,120,.45)">
          <div class="ico">⏵</div><h2>回到对局</h2>
          <p>${st.game.mode === "ai" ? `人机 · ${diff} · ${st.game.human_color === 1 ? "执黑" : "执白"}` : "双人对弈"}
          · 第 ${st.game.moves.length + 1} 手 · ${st.game.names.black} vs ${st.game.names.white}</p>
        </div>`;
      document.getElementById("card-resume")!.addEventListener("click", () => showScreen("play"));
    } else {
      slot.innerHTML = "";
    }
    // 引擎状态行
    const es = engineStatus ?? st.engine;
    const eng = es?.engine;
    const missing = es?.missing ?? [];
    const engLine = eng
      ? `引擎就绪：KataGo ${eng.gpu ? "GPU·OpenCL" : "CPU·Eigen"} + ${eng.model}`
      : missing.length
        ? `<span style="color:#e8a04c">引擎未就绪</span>`
        : "引擎未就绪";
    panel.innerHTML = `
      <div class="sec" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        <span style="font-size:12.5px">${engLine}</span>
        <div style="flex:1"></div>
        ${missing.length ? `<button class="btn primary" id="btn-dl" style="padding:7px 16px;font-size:12px">下载增强引擎</button>` : ""}
        <button class="btn" id="btn-recheck" style="padding:7px 16px;font-size:12px">刷新</button>
      </div>`;
    const dl = document.getElementById("btn-dl");
    if (dl) dl.addEventListener("click", showDownload);
    document.getElementById("btn-recheck")!.addEventListener("click", () => {
      void api<EngineStatus>("/api/engines/status").then(() => refreshMenu());
    });
  } catch {
    /* 后端未就绪 */
  }
  if (focus === "records") showRecords();
}

// ── 新对局 ──
function showNewGame(mode: "ai" | "pvp"): void {
  sel.mode = mode;
  const d = showDialog(`
    <h2>${mode === "ai" ? "人机对弈" : "双人对弈"}</h2>
    <div class="body">
      <div class="form-grid">
        ${mode === "ai" ? `
        <div class="form-item"><label>AI 难度</label>
          <div class="seg" id="seg-diff">${DIFFS.map((x) => `<button data-v="${x.id}" class="${x.id === sel.diff ? "on" : ""}">${x.label}<span class="note">${x.note}</span></button>`).join("")}</div>
        </div>
        <div class="form-item"><label>您的执子</label>
          <div class="seg" id="seg-color">
            <button data-v="1" class="${sel.color === 1 ? "on" : ""}">执黑先行</button>
            <button data-v="2" class="${sel.color === 2 ? "on" : ""}">执白后行</button>
          </div>
        </div>` : `
        <div class="form-item"><label>黑方名称</label><input class="btn" id="in-black" value="黑方" style="text-align:left"></div>
        <div class="form-item"><label>白方名称</label><input class="btn" id="in-white" value="白方" style="text-align:left"></div>`}
        <div class="form-item"><label>用时</label>
          <div class="seg" id="seg-time">${TIMES.map((x) => `<button data-v="${x.id}" class="${x.id === sel.time ? "on" : ""}">${x.label}<span class="note">${x.note}</span></button>`).join("")}</div>
        </div>
        <div class="form-item"><label>贴目（中国规则数子法）</label>
          <div class="seg" id="seg-komi">
            <button data-v="7.5" class="on">7.5 目（标准）</button>
            <button data-v="6.5">6.5 目</button>
            <button data-v="0.5">0.5 目（让子棋用）</button>
          </div>
        </div>
      </div>
    </div>
    <div class="actions">
      <button class="btn" id="dlg-cancel">取消</button>
      <button class="btn primary" id="dlg-start">开始对局</button>
    </div>`);

  const bindSeg = (id: string, cb: (v: string) => void) => {
    d.querySelectorAll(`#${id} button`).forEach((b) =>
      b.addEventListener("click", () => {
        d.querySelectorAll(`#${id} button`).forEach((x) => x.classList.remove("on"));
        (b as HTMLElement).classList.add("on");
        cb((b as HTMLElement).dataset.v!);
      }),
    );
  };
  bindSeg("seg-diff", (v) => (sel.diff = v));
  bindSeg("seg-color", (v) => (sel.color = Number(v)));
  bindSeg("seg-time", (v) => (sel.time = v));
  let komi = 7.5;
  bindSeg("seg-komi", (v) => (komi = Number(v)));

  d.querySelector("#dlg-cancel")!.addEventListener("click", closeDialog);
  d.querySelector("#dlg-start")!.addEventListener("click", async () => {
    try {
      await api("/api/game/new", {
        mode,
        difficulty: sel.diff,
        human_color: sel.color,
        time_preset: sel.time,
        komi,
        black_name:
          mode === "pvp" ? (d.querySelector("#in-black") as HTMLInputElement).value || "黑方" : "黑方",
        white_name:
          mode === "pvp" ? (d.querySelector("#in-white") as HTMLInputElement).value || "白方" : "白方",
      });
      closeDialog();
      showScreen("play");
    } catch (e) {
      toast(String(e), true);
    }
  });
}

// ── 棋谱库 ──
async function showRecords(): Promise<void> {
  const panel = document.getElementById("menu-panel")!;
  panel.innerHTML = `<div class="sec"><h3>棋 谱 库</h3><div style="font-size:12px;color:var(--ink-dim)">加载中…</div></div>`;
  let items: RecordItem[] = [];
  try {
    items = await api<RecordItem[]>("/api/records");
  } catch (e) {
    toast(String(e), true);
  }
  const rows = items
    .map(
      (r) => `<tr>
        <td>${r.date}</td><td>${r.black}</td><td>${r.white}</td>
        <td class="result-tag">${r.result || "?"}</td><td>${r.moves} 手</td>
        <td><button class="btn primary" data-f="${r.file}">复 盘</button></td>
      </tr>`,
    )
    .join("");
  panel.innerHTML = `
    <div class="sec"><h3>棋 谱 库</h3>
      ${items.length ? `<table class="records">
        <tr><th>日期</th><th>黑方</th><th>白方</th><th>结果</th><th>手数</th><th></th></tr>
        ${rows}</table>` : `<div style="font-size:12.5px;color:var(--ink-dim);padding:8px 0">还没有棋谱——先完成一局吧。对局结束后会自动保存到这里。</div>`}
    </div>`;
  panel.querySelectorAll<HTMLButtonElement>("button[data-f]").forEach((b) =>
    b.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("open-review", { detail: b.dataset.f }));
      showScreen("review");
    }),
  );
}

// ── 引擎下载 ──
function showDownload(): void {
  const es = engineStatus;
  const items = [
    { id: "strong-model", label: "强网络 b18c384nbt（94MB）", desc: "三档难度与 AI 推荐共用" },
    { id: "opencl-exe", label: "GPU 引擎 OpenCL（6MB）", desc: "NVIDIA/AMD 显卡加速，推荐" },
    { id: "eigen-exe", label: "CPU 引擎 Eigen（6MB）", desc: "无显卡环境备用" },
  ].filter((x) => !(es?.installed ?? {})[x.id]);
  const d = showDialog(`
    <h2>引擎下载</h2>
    <div class="body">
      下载来自 KataGo 官方发布页与 katagotraining.org，一次下载永久保存在本地。
      ${items.map((x) => `<div class="dl-row" data-id="${x.id}">
        <div class="label"><span><b>${x.label}</b><br><small style="color:var(--ink-dim)">${x.desc}</small></span><span class="pct-label"></span></div>
        <div class="progress"><i></i></div>
      </div>`).join("")}
    </div>
    <div class="actions">
      <button class="btn" id="dlg-cancel">关闭</button>
      <button class="btn primary" id="dlg-dl">下载全部（${items.length} 项）</button>
    </div>`);
  d.querySelector("#dlg-cancel")!.addEventListener("click", closeDialog);
  d.querySelector("#dlg-dl")!.addEventListener("click", async () => {
    try {
      await api("/api/engines/download", { ids: items.map((x) => x.id) });
      toast("开始下载…");
    } catch (e) {
      toast(String(e), true);
    }
  });
}

// WS 下载进度 → 更新弹层内对应行
onWs((ev) => {
  if (ev.type !== "download") return;
  const row = document.querySelector(`.dl-row[data-id="${ev.id}"]`);
  if (!row) return;
  const pctLabel = row.querySelector(".pct-label")!;
  const bar = row.querySelector(".progress > i") as HTMLElement;
  if (ev.phase === "downloading") {
    bar.style.width = `${ev.pct ?? 0}%`;
    const mbps = Math.round(((ev.speed_kbps as number) ?? 0) / 1024);
    pctLabel.textContent = `${ev.pct ?? 0}% · ${mbps}MB/s`;
  } else if (ev.phase === "extracting") {
    bar.style.width = "100%";
    pctLabel.textContent = "解压中…";
  } else if (ev.phase === "done") {
    bar.style.width = "100%";
    pctLabel.textContent = "✓ 完成";
  } else if (ev.phase === "error") {
    pctLabel.textContent = "失败";
    toast(`下载失败：${ev.error}`, true);
  }
});
