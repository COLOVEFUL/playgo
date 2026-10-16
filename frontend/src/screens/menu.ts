/** 主菜单：新对局 / 继续对局 / 棋谱库 / 引擎管理。 */

import { api, onWs } from "../api";
import { errPayloadText, errText, t } from "../i18n";
import type { MsgKey } from "../i18n";
import type { EngineStatus, GameState, RecordItem } from "../types";
import { closeDialog, engineStatus, showDialog, showScreen, toast } from "../main";

// 选项表携带字面量键，渲染期再 t()（语言切换后可重渲染）
const DIFFS: { id: string; labelKey: MsgKey; noteKey: MsgKey }[] = [
  { id: "easy", labelKey: "diff.easy", noteKey: "diff.easy_note" },
  { id: "medium", labelKey: "diff.medium", noteKey: "diff.medium_note" },
  { id: "hard", labelKey: "diff.hard", noteKey: "diff.hard_note" },
];
const TIMES: { id: string; label: string; noteKey: MsgKey }[] = [
  { id: "standard", label: "30:00", noteKey: "time.standard_note" },
  { id: "blitz", label: "5:00", noteKey: "time.blitz_note" },
  { id: "long", label: "60:00", noteKey: "time.long_note" },
  { id: "free", label: "", noteKey: "time.free_note" },
];

const DIFF_KEY: Record<string, MsgKey> = {
  easy: "diff.easy",
  medium: "diff.medium",
  hard: "diff.hard",
};

let sel = { mode: "ai", diff: "medium", color: 1, time: "standard" };
let panelMode: "engine" | "records" = "engine";

export function initMenu(): void {
  const root = document.getElementById("screen-menu")!;
  root.innerHTML = `
  <div class="menu-main">
    <div class="menu-hero">
      <div class="big">弈</div>
      <div class="slogan">${t("menu.slogan")}</div>
    </div>
    <div class="menu-cards" id="resume-slot"></div>
    <div class="menu-cards">
      <div class="mcard" id="card-new">
        <div class="ico">⚫</div><h2>${t("menu.card_ai")}</h2>
        <p>${t("menu.card_ai_desc")}</p>
      </div>
      <div class="mcard" id="card-pvp">
        <div class="ico">⚪</div><h2>${t("menu.card_pvp")}</h2>
        <p>${t("menu.card_pvp_desc")}</p>
      </div>
      <div class="mcard" id="card-records">
        <div class="ico">📖</div><h2>${t("menu.card_review")}</h2>
        <p>${t("menu.card_review_desc")}</p>
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
  panelMode = focus === "records" ? "records" : focus ? "engine" : panelMode;
  // 继续对局卡片
  const slot = document.getElementById("resume-slot")!;
  try {
    const st = await api<{ game: GameState | null; engine?: EngineStatus }>("/api/state");
    const panel = document.getElementById("menu-panel")!;
    if (st.game && st.game.status !== "ended") {
      const diff = t(DIFF_KEY[st.game.difficulty] ?? "diff.medium");
      const color = t(st.game.human_color === 1 ? "common.black_stone" : "common.white_stone");
      slot.innerHTML = `
        <div class="mcard" id="card-resume" style="border-color:rgba(126,180,120,.45)">
          <div class="ico">⏵</div><h2>${t("menu.resume")}</h2>
          <p>${st.game.mode === "ai"
            ? t("menu.resume_ai", { diff, color })
            : t("menu.resume_pvp")}
          · ${t("menu.move_n", { n: st.game.moves.length + 1 })} · ${t("menu.vs", {
            black: st.game.names.black,
            white: st.game.names.white,
          })}</p>
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
      ? t("menu.engine_ready", {
          backend: t(eng.gpu ? "engine.opencl" : "engine.eigen"),
          model: eng.model,
        })
      : `<span style="color:#e8a04c">${t("menu.engine_not_ready")}</span>`;
    panel.innerHTML = `
      <div class="sec" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        <span style="font-size:12.5px">${engLine}</span>
        <div style="flex:1"></div>
        ${missing.length ? `<button class="btn primary" id="btn-dl" style="padding:7px 16px;font-size:12px">${t("menu.download_btn")}</button>` : ""}
        <button class="btn" id="btn-recheck" style="padding:7px 16px;font-size:12px">${t("menu.refresh")}</button>
      </div>`;
    const dl = document.getElementById("btn-dl");
    if (dl) dl.addEventListener("click", showDownload);
    document.getElementById("btn-recheck")!.addEventListener("click", () => {
      void api<EngineStatus>("/api/engines/status").then(() => refreshMenu());
    });
  } catch {
    /* 后端未就绪 */
  }
  if (panelMode === "records") await showRecords();
}

// ── 新对局 ──
function showNewGame(mode: "ai" | "pvp"): void {
  sel.mode = mode;
  const d = showDialog(`
    <h2>${t(mode === "ai" ? "ng.ai_title" : "ng.pvp_title")}</h2>
    <div class="body">
      <div class="form-grid">
        ${mode === "ai" ? `
        <div class="form-item"><label>${t("ng.difficulty")}</label>
          <div class="seg" id="seg-diff">${DIFFS.map(
            (x) =>
              `<button data-v="${x.id}" class="${x.id === sel.diff ? "on" : ""}">${t(x.labelKey)}<span class="note">${t(x.noteKey)}</span></button>`,
          ).join("")}</div>
        </div>
        <div class="form-item"><label>${t("ng.your_color")}</label>
          <div class="seg" id="seg-color">
            <button data-v="1" class="${sel.color === 1 ? "on" : ""}">${t("ng.black_first")}</button>
            <button data-v="2" class="${sel.color === 2 ? "on" : ""}">${t("ng.white_second")}</button>
          </div>
        </div>` : `
        <div class="form-item"><label>${t("ng.black_name")}</label><input class="btn" id="in-black" value="${t("play.default_black")}" style="text-align:left"></div>
        <div class="form-item"><label>${t("ng.white_name")}</label><input class="btn" id="in-white" value="${t("play.default_white")}" style="text-align:left"></div>`}
        <div class="form-item"><label>${t("ng.time")}</label>
          <div class="seg" id="seg-time">${TIMES.map(
            (x) =>
              `<button data-v="${x.id}" class="${x.id === sel.time ? "on" : ""}">${x.label || t("time.free_label")}<span class="note">${t(x.noteKey)}</span></button>`,
          ).join("")}</div>
        </div>
        <div class="form-item"><label>${t("ng.komi")}</label>
          <div class="seg" id="seg-komi">
            <button data-v="7.5" class="on">${t("ng.komi_std")}</button>
            <button data-v="6.5">${t("ng.komi_65")}</button>
            <button data-v="0.5">${t("ng.komi_handi")}</button>
          </div>
        </div>
      </div>
    </div>
    <div class="actions">
      <button class="btn" id="dlg-cancel">${t("ng.cancel")}</button>
      <button class="btn primary" id="dlg-start">${t("ng.start")}</button>
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
      const ib = d.querySelector("#in-black") as HTMLInputElement | null;
      const iw = d.querySelector("#in-white") as HTMLInputElement | null;
      await api("/api/game/new", {
        mode,
        difficulty: sel.diff,
        human_color: sel.color,
        time_preset: sel.time,
        komi,
        black_name: ib?.value || t("play.default_black"),
        white_name: iw?.value || t("play.default_white"),
      });
      closeDialog();
      showScreen("play");
    } catch (e) {
      toast(errText(e), true);
    }
  });
}

// ── 棋谱库 ──
async function showRecords(): Promise<void> {
  panelMode = "records";
  const panel = document.getElementById("menu-panel")!;
  panel.innerHTML = `<div class="sec"><h3>${t("rec.title")}</h3><div style="font-size:12px;color:var(--ink-dim)">${t("rec.loading")}</div></div>`;
  let items: RecordItem[] = [];
  try {
    items = await api<RecordItem[]>("/api/records");
  } catch (e) {
    toast(errText(e), true);
  }
  const rows = items
    .map(
      (r) => `<tr>
        <td>${r.date}</td><td>${r.black}</td><td>${r.white}</td>
        <td class="result-tag">${r.result || "?"}</td><td>${t("rec.moves_n", { n: r.moves })}</td>
        <td><button class="btn primary" data-f="${r.file}">${t("rec.review")}</button></td>
      </tr>`,
    )
    .join("");
  panel.innerHTML = `
    <div class="sec"><h3>${t("rec.title")}</h3>
      ${items.length ? `<table class="records">
        <tr><th>${t("rec.date")}</th><th>${t("rec.black")}</th><th>${t("rec.white")}</th><th>${t("rec.result")}</th><th>${t("rec.moves")}</th><th></th></tr>
        ${rows}</table>` : `<div style="font-size:12.5px;color:var(--ink-dim);padding:8px 0">${t("rec.empty")}</div>`}
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
  const all: { id: string; labelKey: MsgKey; descKey: MsgKey }[] = [
    { id: "strong-model", labelKey: "dl.strong_model", descKey: "dl.model_desc" },
    { id: "opencl-exe", labelKey: "dl.opencl", descKey: "dl.opencl_desc" },
    { id: "eigen-exe", labelKey: "dl.eigen", descKey: "dl.eigen_desc" },
  ];
  const items = all.filter((x) => !(es?.installed ?? {})[x.id]);
  const d = showDialog(`
    <h2>${t("dl.title")}</h2>
    <div class="body">
      ${t("dl.desc")}
      ${items.map(
        (x) => `<div class="dl-row" data-id="${x.id}">
        <div class="label"><span><b>${t(x.labelKey)}</b><br><small style="color:var(--ink-dim)">${t(x.descKey)}</small></span><span class="pct-label"></span></div>
        <div class="progress"><i></i></div>
      </div>`,
      ).join("")}
    </div>
    <div class="actions">
      <button class="btn" id="dlg-cancel">${t("dl.close")}</button>
      <button class="btn primary" id="dlg-dl">${t("dl.download_all", { n: items.length })}</button>
    </div>`);
  d.querySelector("#dlg-cancel")!.addEventListener("click", closeDialog);
  d.querySelector("#dlg-dl")!.addEventListener("click", async () => {
    try {
      await api("/api/engines/download", { ids: items.map((x) => x.id) });
      toast(t("dl.started"));
    } catch (e) {
      toast(errText(e), true);
    }
  });
}

// WS 下载进度 → 更新弹层内对应行（模块顶层注册一次）
onWs((ev) => {
  if (ev.type !== "download") return;
  const row = document.querySelector(`.dl-row[data-id="${ev.id}"]`);
  if (!row) return;
  const pctLabel = row.querySelector(".pct-label")!;
  const bar = row.querySelector(".progress > i") as HTMLElement;
  if (ev.phase === "downloading") {
    bar.style.width = `${ev.pct ?? 0}%`;
    const mbps = Math.round(((ev.speed_kbps as number) ?? 0) / 1024);
    pctLabel.textContent = t("dl.progress", { pct: ev.pct ?? 0, mbps });
  } else if (ev.phase === "extracting") {
    bar.style.width = "100%";
    pctLabel.textContent = t("dl.extracting");
  } else if (ev.phase === "done") {
    bar.style.width = "100%";
    pctLabel.textContent = t("dl.done");
  } else if (ev.phase === "error") {
    pctLabel.textContent = t("dl.failed");
    if (ev.error) toast(errPayloadText(ev.error), true);
  }
});
