/** 段级位文案与实际运行参数；保持菜单、对局页一致。 */
import { t } from "./i18n";
import type { EngineStatus } from "./types";

export function difficultyLabel(id: string, style = "human"): string {
  const rank = ({ easy: "15k", medium: "1d", hard: "max" } as Record<string, string>)[id] ?? id;
  if (rank === "max") return t("diff.max");
  const suffix = t(style === "rank" ? "diff.estimate" : "diff.target");
  if (/^([1-9]|1[0-9]|20)k$/.test(rank)) return t("diff.kyu", { n: parseInt(rank), suffix });
  if (/^[1-9]d$/.test(rank)) return t("diff.dan", { n: parseInt(rank), suffix });
  return rank;
}

export function difficultyDetails(id: string, status: EngineStatus | null, style = "human"): string {
  const engine = status?.engine;
  if (!engine) return t("diff.pending");
  const preset = status?.difficulties.find((x) => x.id === id);
  const visits = id !== "max" && style === "rank" ? 1 : preset ? (engine.gpu ? preset.visits : preset.cpu_visits) : "—";
  const scale = engine.model.startsWith("lionffen_b6c64") ? "b6c64" : "b18c384nbt";
  const main = t("diff.engine_details", {
    backend: engine.backend, model: engine.model, scale, visits,
  });
  return id === "max" ? `${t("diff.max_note")} ${main}`
    : style === "rank" ? `${t("diff.quick_note")} ${main}`
    : `${t("diff.human_details", { model: engine.human_model ?? status!.human_sl.model })} ${main}`;
}

export function difficultySummary(id: string, status: EngineStatus | null, style = "human"): string {
  if (!status?.engine) return t("diff.pending");
  const preset = status.difficulties.find((x) => x.id === id);
  const visits = id !== "max" && style === "rank" ? 1 : preset ? (status.engine.gpu ? preset.visits : preset.cpu_visits) : "—";
  return t(id === "max" ? "diff.active_max" : style === "rank" ? "diff.active_quick" : "diff.active_human", {
    model: status.engine.model, backend: status.engine.backend, visits,
  });
}
