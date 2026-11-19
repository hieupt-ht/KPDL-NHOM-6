import type { ClusterResult, ForecastDiscrete } from "../types/api";

/** Metadata and missing statistics must never turn into a plotted zero. */
export function clusterMeasurement(features: ClusterResult["features"] | undefined, key: string): number | null {
  const value = features?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** probability always describes High, including when the predicted label is Low. */
export function riskSummary(risk?: Pick<ForecastDiscrete, "label" | "probability">): string {
  const probability = risk?.probability;
  const formatted = probability == null || !Number.isFinite(probability) ? "—" : `${Math.round(probability * 100)}%`;
  return `${risk?.label ?? "Chưa có"} · P(Cao): ${formatted}`;
}
