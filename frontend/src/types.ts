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
  human_color: number;
  ai_color: number | null;
  komi: number;
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
  winrate_black: number;
  score_lead_black: number;
  order: number;
}

export interface HintData {
  to_play: number;
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

export interface EngineStatus {
  available: boolean;
  engine: { exe: string; model: string; backend: string; gpu: boolean } | null;
  missing: { id: string; size_mb: number }[];
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
