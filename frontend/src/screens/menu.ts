/** 主菜单：新对局 / 继续对局 / 棋谱库 / 引擎管理。 */

import { api, onWs } from "../api";
import { errPayloadText, errText, t } from "../i18n";
import type { MsgKey } from "../i18n";
import { difficultyDetails, difficultyLabel } from "../difficulty";
import type { EnginePackageInfo, EngineStatus, GameState, RecordItem } from "../types";
import { closeDialog, engineStatus, setEngineStatus, showDialog, showScreen, toast } from "../main";

// 选项表携带字面量键，渲染期再 t()（语言切换后可重渲染）
const TIMES: { id: string; label: string; noteKey: MsgKey }[] = [
  { id: "standard", label: "30:00", noteKey: "time.standard_note" },
  { id: "blitz", label: "5:00", noteKey: "time.blitz_note" },
  { id: "long", label: "60:00", noteKey: "time.long_note" },
  { id: "free", label: "", noteKey: "time.free_note" },
];

let sel = { mode: "ai", diff: "10k", style: "rank", color: 1, time: "standard" };
let panelMode: "engine" | "records" = "engine";

// 引擎包卡片：包内下载项 → 标签键（渲染期 t()，语言切换可重建）
const PKG_ITEMS: Record<string, { id: string; labelKey: MsgKey }[]> = {
  cpu: [
    { id: "eigen-exe", labelKey: "dl.eigen" },
    { id: "lite-model", labelKey: "dl.lite_model" },
  ],
  gpu: [
    { id: "opencl-exe", labelKey: "dl.opencl" },
    { id: "strong-model", labelKey: "dl.strong_model" },
  ],
};
const PKG_TITLE: Record<string, MsgKey> = {
  cpu: "pkg.cpu_title",
  gpu: "pkg.gpu_title",
};

let switching: string | null = null; // 切换中的包 id（按钮转"切换中…"并禁用）

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

/** 单张引擎包卡片：标题/描述 + 动作按钮（使用中/切换/下载）+ 缺失项进度行 */
function renderPkgCard(p: EnginePackageInfo, downloading: boolean): string {
  const items = PKG_ITEMS[p.id] ?? [];
  const labelOf = (id: string): string => {
    const e = items.find((x) => x.id === id);
    return e ? t(e.labelKey) : id;
  };
  const action = p.active
    ? `<span class="chip">${t("pkg.active")}</span>`
    : p.installed
      ? `<button class="btn" data-switch="${p.id}" style="padding:7px 16px;font-size:12px"${
          switching === p.id ? " disabled" : ""
        }>${switching === p.id ? t("pkg.switching") : t("pkg.switch")}</button>`
      : `<button class="btn primary" data-dl="${p.id}" style="padding:7px 16px;font-size:12px"${
          downloading ? " disabled" : ""
        }>${t("pkg.download", { n: p.size_mb })}</button>`;
  return `
    <div class="pkg-card${p.active ? " active" : ""}" data-pkg="${p.id}">
      <div class="pkg-head"><b>${t(p.gpu ? "pkg.gpu_title" : "pkg.cpu_title")}</b>${action}</div>
      <p class="pkg-desc">${t(p.gpu ? "pkg.gpu_desc" : "pkg.cpu_desc")}</p>
      ${p.missing
        .map(
          (m) => `<div class="dl-row" data-id="${m.id}">
        <div class="label"><span>${labelOf(m.id)} (${m.size_mb}MB)</span><span class="pct-label"></span></div>
        <div class="progress"><i></i></div>
      </div>`,
        )
        .join("")}
    </div>`;
}

export async function refreshMenu(focus?: string): Promise<void> {
  panelMode = focus === "records" ? "records" : focus ? "engine" : panelMode;
  // 继续对局卡片
  const slot = document.getElementById("resume-slot")!;
  try {
    const st = await api<{ game: GameState | null; engine?: EngineStatus }>("/api/state");
    const panel = document.getElementById("menu-panel")!;
    if (st.game && st.game.status !== "ended") {
      const diff = difficultyLabel(st.game.difficulty, st.game.ai_style);
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
    // 引擎状态行 + 双包卡片（CPU 默认轻量 / GPU 最强可选）
    const es = engineStatus ?? st.engine;
    const eng = es?.engine;
    const engLine = eng
      ? t("menu.engine_ready", {
          backend: t(eng.gpu ? "engine.opencl" : "engine.eigen"),
          model: eng.model,
        })
      : `<span style="color:#e8a04c">${t("menu.engine_not_ready")}</span>`;
    // 选中包 ≠ 实际运行包 → 选中包启动失败已回落
    const activePkg = es?.packages.find((p) => p.active);
    const fallback =
      es && activePkg && activePkg.id !== es.selected
        ? `<span style="font-size:12px;color:#e8a04c">${t("menu.engine_fallback", {
            sel: t(PKG_TITLE[es.selected] ?? "pkg.gpu_title"),
            cur: t(PKG_TITLE[activePkg.id] ?? "pkg.cpu_title"),
          })}</span>`
        : "";
    const pkgs = es?.packages ?? [];
    const downloading = es?.downloading ?? false;
    panel.innerHTML = `
      <div class="sec">
        <div class="eng-line">
          <span style="font-size:12.5px">${engLine}</span>
          ${fallback}
          <div style="flex:1"></div>
          <button class="btn" id="btn-recheck" style="padding:7px 16px;font-size:12px">${t("menu.refresh")}</button>
        </div>
        <div class="pkg-cards">${pkgs.map((p) => renderPkgCard(p, downloading)).join("")}</div>
        <div class="pkg-card human-card">
          <div class="pkg-head"><b>${t("diff.human_title")}</b>
          ${es?.human_sl.installed ? `<span class="chip">${t("diff.installed")}</span>`
            : `<button class="btn primary" id="btn-human-download" ${downloading ? "disabled" : ""}>${t("pkg.download", { n: es?.human_sl.size_mb ?? 95 })}</button>`}</div>
          <p class="pkg-desc">${t("diff.human_intro")}</p>
          ${es?.human_sl.installed ? "" : `<div class="dl-row" data-id="human-model"><div class="label"><span>Human SL · b18c384nbt</span><span class="pct-label"></span></div><div class="progress"><i></i></div></div>`}
        </div>
      </div>`;
    panel.querySelector("#btn-human-download")?.addEventListener("click", () => void downloadHuman());
    panel.querySelectorAll<HTMLButtonElement>("[data-switch]").forEach((b) =>
      b.addEventListener("click", async () => {
        const id = b.dataset.switch!;
        switching = id;
        b.disabled = true;
        b.textContent = t("pkg.switching");
        try {
          await api("/api/engines/select", { id });
          // engine_restarted 广播触发 refreshMenu；finally 兜底再刷一次
        } catch (e) {
          toast(errText(e), true);
        } finally {
          switching = null;
          void refreshMenu();
        }
      }),
    );
    panel.querySelectorAll<HTMLButtonElement>("[data-dl]").forEach((b) =>
      b.addEventListener("click", async () => {
        const pkg = pkgs.find((x) => x.id === b.dataset.dl);
        if (!pkg) return;
        try {
          await api("/api/engines/download", { ids: pkg.missing.map((m) => m.id) });
          toast(t("dl.started"));
        } catch (e) {
          toast(errText(e), true);
        }
      }),
    );
    document.getElementById("btn-recheck")!.addEventListener("click", () => {
      void api<EngineStatus>("/api/engines/status").then((s) => {
        setEngineStatus(s);
        void refreshMenu();
      });
    });
  } catch {
    /* 后端未就绪 */
  }
  if (panelMode === "records") await showRecords();
}

// ── 新对局 ──
async function downloadHuman(): Promise<void> {
  try {
    await api("/api/engines/download", { ids: ["human-model"] });
    closeDialog();
    showScreen("menu");
    void refreshMenu("engine");
    toast(t("dl.started"));
  } catch (e) {
    toast(errText(e), true);
  }
}

async function showNewGame(mode: "ai" | "pvp"): Promise<void> {
  sel.mode = mode;
  let es = engineStatus;
  if (mode === "ai") {
    try {
      es = await api<EngineStatus>("/api/engines/status");
      setEngineStatus(es);
    } catch (e) {
      toast(errText(e), true);
      return;
    }
  }
  const d = showDialog(`
    <h2>${t(mode === "ai" ? "ng.ai_title" : "ng.pvp_title")}</h2>
    <div class="body">
      <div class="form-grid">
        ${mode === "ai" ? `
        <div class="form-item strength-field"><label for="in-difficulty">${t("ng.difficulty")}</label>
          <div class="seg" id="seg-style">
            <button data-v="rank" class="${sel.style === "rank" ? "on" : ""}">${t("diff.quick")}</button>
            <button data-v="human" class="${sel.style === "human" ? "on" : ""}">${t("diff.human")}</button>
          </div>
          <select id="in-difficulty" class="strength-select">${es!.difficulties.map(
            (x) => `<option value="${x.id}" ${x.id === sel.diff ? "selected" : ""}>${difficultyLabel(x.id, sel.style)}</option>`,
          ).join("")}</select>
          <p class="strength-note">${t("diff.rank_note")}</p>
          <p class="strength-note" id="difficulty-details"></p>
          <p class="strength-note" id="difficulty-high"></p>
          <div id="human-required" class="strength-note" ${es!.human_sl.installed ? "hidden" : ""}>
            ${t("diff.download_required")}
            <button class="btn" id="dlg-human-download" ${es?.downloading ? "disabled" : ""}>${t("pkg.download", { n: es!.human_sl.size_mb })}</button>
          </div>
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
  if (mode === "ai") {
    const updateDifficulty = () => {
      d.querySelectorAll<HTMLOptionElement>("#in-difficulty option").forEach((option) => {
        const available = sel.style === "human" || es!.difficulties.find((x) => x.id === option.value)!.quick;
        option.disabled = !available;
        option.textContent = difficultyLabel(option.value, available ? sel.style : "human") + (available ? "" : ` · ${t("diff.human_only")}`);
      });
      const unsupported = sel.style === "rank" && !es!.difficulties.find((x) => x.id === sel.diff)!.quick;
      d.querySelector("#difficulty-details")!.textContent = unsupported ? t("diff.quick_range") : difficultyDetails(sel.diff, es, sel.style);
      d.querySelector("#difficulty-high")!.textContent = /^[5-9]d$/.test(sel.diff) ? t("diff.high_dan_note") : "";
      const missing = sel.style === "human" && sel.diff !== "max" && !es!.human_sl.installed;
      (d.querySelector("#human-required") as HTMLElement).hidden = !missing;
      (d.querySelector("#dlg-start") as HTMLButtonElement).disabled = missing || unsupported;
    };
    bindSeg("seg-style", (value) => {
      sel.style = value;
      updateDifficulty();
    });
    d.querySelector("#in-difficulty")!.addEventListener("change", (event) => {
      sel.diff = (event.target as HTMLSelectElement).value;
      updateDifficulty();
    });
    d.querySelector("#dlg-human-download")?.addEventListener("click", () => void downloadHuman());
    updateDifficulty();
  }
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
        ai_style: sel.style,
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

// WS 下载进度 → 更新包卡片内对应行（模块顶层注册一次）
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
