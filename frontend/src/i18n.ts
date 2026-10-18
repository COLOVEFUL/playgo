/** i18n 核心：词典查询、语言存储/检测/切换订阅、错误码文案。
 *
 * 约定：所有 t() 必须在渲染期调用（模块顶层求值会冻结语言）；
 * 静态选项表请携带字面量键（labelKey/noteKey），渲染时再 t()。
 */

import type { ErrPayload } from "./types";
import { en } from "./locales/en";
import type { MsgKey } from "./locales/zh";
import { zh } from "./locales/zh";

export type Lang = "zh" | "en";
export type { MsgKey };

const LANG_KEY = "playgo.lang";

let current: Lang = "zh";
const listeners = new Set<() => void>();

function detect(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === "zh" || saved === "en") return saved;
  } catch {
    /* 隐私模式等 localStorage 不可用 */
  }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

/** 初始化语言（main.ts 在首次渲染前调用）。 */
export function initLang(): Lang {
  current = detect();
  document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
  return current;
}

export function lang(): Lang {
  return current;
}

export function setLang(l: Lang): void {
  if (l === current) return;
  current = l;
  try {
    localStorage.setItem(LANG_KEY, l);
  } catch {
    /* 存不上就算了 */
  }
  document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
  for (const fn of listeners) fn();
}

export function onLangChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const DICTS: Record<Lang, Record<string, string>> = { zh, en };

/** 查词典；params 以 {name} 占位符插值。 */
export function t(key: MsgKey, params?: Record<string, string | number>): string {
  let s: string = DICTS[current][key] ?? zh[key] ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.split(`{${k}}`).join(String(v));
    }
  }
  return s;
}

// ── 错误码 → 文案（与后端 errors.py 的 code 一一对应） ──
const ERR_KEY: Record<string, MsgKey> = {
  "game.bad_difficulty": "err.game_bad_difficulty",
  "game.quick_rank_unavailable": "err.game_quick_rank_unavailable",
  "engine.policy_missing": "err.engine_policy_missing",
  "engine.human_model_required": "err.engine_human_model_required",
  "engine.human_policy_missing": "err.engine_human_policy_missing",
  "engine.human_board_size": "err.engine_human_board_size",
  "game.not_started": "err.game_not_started",
  "game.ended": "err.game_ended",
  "game.not_your_turn": "err.game_not_your_turn",
  "game.ended_by_timeout": "err.game_ended_by_timeout",
  "move.out_of_bounds": "err.move_out_of_bounds",
  "move.occupied": "err.move_occupied",
  "move.illegal": "err.move_illegal",
  "move.suicide": "err.move_suicide",
  "move.superko": "err.move_superko",
  "scoring.not_active": "err.scoring_not_active",
  "engine.start_failed": "err.engine_start_failed",
  "engine.ready_timeout": "err.engine_ready_timeout",
  "engine.exited": "err.engine_exited",
  "engine.not_ready": "err.engine_not_ready",
  "engine.analyze_timeout": "err.engine_analyze_timeout",
  "engine.not_installed": "err.engine_not_installed",
  "engine.bad_package": "err.engine_bad_package",
  "engine.package_not_installed": "err.engine_package_not_installed",
  "engine.all_failed": "err.engine_all_failed",
  "record.not_found": "err.record_not_found",
  "record.bad_extension": "err.record_bad_extension",
  "record.too_large": "err.record_too_large",
  "record.invalid_sgf": "err.record_invalid_sgf",
  "record.unsupported_sgf": "err.record_unsupported_sgf",
  "download.busy": "err.download_busy",
  "download.no_items": "err.download_no_items",
  "download.failed": "err.download_failed",
  "review.failed": "err.review_failed",
  "error.unknown": "err.unknown",
};

/** 结构化错误载荷 → 本地化文案；未知码原样显示 code。 */
export function errPayloadText(p: ErrPayload): string {
  const key = ERR_KEY[p.code];
  if (!key) return p.code;
  const params: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(p.args ?? {})) {
    params[k] = typeof v === "number" ? v : String(v);
  }
  return t(key, params);
}

/** 任意异常（ApiError 或普通 Error）→ 显示文本。 */
export function errText(e: unknown): string {
  if (e && typeof e === "object" && "code" in e && "args" in e) {
    return errPayloadText(e as ErrPayload);
  }
  return String(e instanceof Error ? e.message : e);
}
