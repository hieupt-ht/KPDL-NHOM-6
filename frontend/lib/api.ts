import type { ClusterResult, CorrelationPoint, DateRange, ForecastContinuous, ForecastDiscrete, HistogramBin, Metric, SeasonalPoint, StatusResponse, TimeseriesPoint, TrendPoint } from "@/types/api";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function getTimeseries(query: DateRange & { granularity: "day" | "week" | "month"; metric: Metric }): Promise<TimeseriesPoint[]> { void query; throw new Error("Not implemented"); }
export function getHistogram(query: DateRange & { metric: Metric }): Promise<HistogramBin[]> { void query; throw new Error("Not implemented"); }
export function getTrend(query: DateRange & { granularity: "month" | "week"; metric: Metric }): Promise<TrendPoint[]> { void query; throw new Error("Not implemented"); }
export function getSeasonal(query: DateRange & { period_type: "hour_of_day" | "day_of_week" | "month"; metric: Metric }): Promise<SeasonalPoint[]> { void query; throw new Error("Not implemented"); }
export function getCorrelation(query: DateRange = {}): Promise<CorrelationPoint[]> { void query; throw new Error("Not implemented"); }
export function getClusters(query: DateRange = {}): Promise<ClusterResult[]> { void query; throw new Error("Not implemented"); }
export function getForecastContinuous(query: DateRange = {}): Promise<ForecastContinuous> { void query; throw new Error("Not implemented"); }
export function getForecastDiscrete(query: DateRange = {}): Promise<ForecastDiscrete> { void query; throw new Error("Not implemented"); }
export function getStatus(query: DateRange = {}): Promise<StatusResponse> { void query; throw new Error("Not implemented"); }
export function runJob(service: "analysis" | "clustering" | "prediction"): Promise<void> { void service; throw new Error("Not implemented"); }
