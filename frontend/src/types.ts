/** 与后端对应的 DTO 类型。 */

export const BLACK = 1;
export const WHITE = 2;

export interface ClockView {
  main: number;
  byo_periods: number;
  byo_left: number;
  in_byo: boolean;
  unlimited: boolean;
  display: number; // 实时显示用剩余秒
}

export interface MoveInfo {
  n: number;
  color: number;
  point: number | null;
  captured: number[];
  clock_left: number;
}

/** 后端统一错误载荷：稳定码 + 插值参数（文案由前端按语言组合）。 */
export interface ErrPayload {
  code: string;
  args: Record<string, unknown>;
}

export interface ScorePreview {
  black_area: number;
  white_area: number;
  winner: number;
  margin: number;
  ownership: number[];
}

export interface GameResult {
  winner: number | null;
  reason: string;
  margin: number;
  sgf_result: string;
}

export interface GameState {
  id: string;
  mode: "pvp" | "ai";
  difficulty: string;
  ai_style: "rank" | "human";
  human_color: number;
  ai_color: number | null;
  komi: number;
  /** 复盘接管试下：黑白皆由玩家执，不限时，终局不存谱 */
  takeover?: boolean;
  review_source?: { file: string; moves: number } | null;
  time: { main: number; byo: number; periods: number };
  names: { black: string; white: string };
  status: "playing" | "scoring" | "ended";
  to_play: number;
  board: number[];
  size: number;
  moves: MoveInfo[];
  captures: { black: number; white: number };
  last_move: number | null;
  clocks: Record<string, ClockView>;
  result: GameResult | null;
  dead_stones: number[];
  score_preview: ScorePreview | null;
  ai_thinking: boolean;
}

export interface HintMove {
  point: number;
  winrate_black: number; // 黑方视角（落该手后）；展示按玩家棋色（= to_play）翻转
  score_lead_black: number;
  order: number;
}

export interface HintData {
  to_play: number; // 推荐局面的行棋方 = 请求推荐的玩家，胜率展示视角
  move_count: number;
  winrate_black: number;
  score_lead_black: number;
  moves: HintMove[];
}

export interface TerritoryData {
  move_count: number;
  winrate_black: number;
  score_lead_black: number;
  ownership: number[];
}

export interface RecordItem {
  file: string;
  date: string;
  black: string;
  white: string;
  result: string;
  moves: number;
  komi: number;
}

export interface ReviewPosition {
  n: number;
  winrate_black: number;
  score_lead_black: number;
  best: { point: number; winrate_black: number } | null;
  ownership: number[];
}

export interface ReviewAnalysis {
  file: string;
  visits: number;
  /** 视角标记：后端只下发 "black" 标记过的新版数据（旧版按行棋方翻转，已作废） */
  perspective?: string;
  positions: ReviewPosition[];
}

export interface RecordDetail {
  file: string;
  size: number;
  komi: number;
  black: string;
  white: string;
  result: string;
  date: string;
  moves: { color: number; point: number | null }[];
  analysis: ReviewAnalysis | null;
}

/** 下载项（包卡片内逐项进度） */
export interface DownloadItem {
  id: string;
  size_mb: number;
}

/** 引擎包视图（CPU 轻量默认 / GPU 最强可选） */
export interface EnginePackageInfo {
  id: string; // "cpu" | "gpu"
  backend: string; // "eigen" | "opencl"
  gpu: boolean;
  model: string;
  installed: boolean;
  active: boolean;
  missing: DownloadItem[];
  size_mb: number; // missing 项体积合计
}

export interface EngineStatus {
  available: boolean;
  engine: { exe: string; model: string; backend: string; gpu: boolean; human_model?: string | null } | null;
  human_sl: { model: string; installed: boolean; loaded: boolean; size_mb: number };
  difficulties: { id: string; strategy: "human" | "best"; visits: number; cpu_visits: number; quick: boolean }[];
  /** 用户选中的包（实际运行可能是回落包，见 packages[].active） */
  selected: string;
  packages: EnginePackageInfo[];
  downloading?: boolean;
  installed?: Record<string, boolean>;
}

/** WS 事件 */
export type WsEvent =
  | { type: "state"; game: GameState }
  | { type: "clocks"; clocks: Record<string, ClockView>; to_play: number; status: string }
  | { type: "engine"; engine: EngineStatus }
  | { type: "error"; error: ErrPayload }
  | { type: "saved"; path: string }
  | {
      type: "download";
      id: string;
      phase: string;
      pct?: number;
      error?: ErrPayload;
      [k: string]: unknown;
    }
  | { type: "engine_restarted"; engine: EngineStatus }
  | { type: "review_progress"; file: string; done: number; total: number }
  | { type: "review_done"; file: string; total: number }
  | { type: "review_error"; file: string; error: ErrPayload }
  | { type: "pong"; t: number };
