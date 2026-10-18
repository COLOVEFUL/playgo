/** 推荐点胜率越低越浅、越透明；金环仍仅代表引擎综合首选。 */

import type { HintMove } from "./types";

export const MAX_HINTS = 5;
export const HINT_COLORS = {
  background: "#14553f",
  foreground: "#f3fff7",
  border: "#b9d7c5",
  preferred: "#efd48b",
};

export function hintWinrate(hint: HintMove, toPlay: number): number {
  return Math.max(0, Math.min(1, toPlay === 1 ? hint.winrate_black : 1 - hint.winrate_black));
}

export function hintBackground(hint: HintMove, hints: HintMove[], toPlay: number): string {
  const best = Math.max(...hints.map((candidate) => hintWinrate(candidate, toPlay)));
  // 使用绝对百分点差：小于 3pp 保持底色，不能把相近候选强行拉成最大色差。
  // 落后越多透明度越高，木纹透出后呈现更浅的绿色；25pp 时保留 25% 不透明度。
  const gap = best - hintWinrate(hint, toPlay);
  const amount = Math.max(0, Math.min(1, (gap - 0.03) / 0.22));
  return `rgba(20, 85, 63, ${(1 - 0.75 * amount).toFixed(3)})`;
}

export function isPreferredHint(hint: HintMove): boolean {
  // 不能按数组第一项推断：停一手或坐标过滤后，剩余第一项未必是综合首选。
  return hint.order === 0;
}
