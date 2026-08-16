export interface ForecastPoint { date: string; value: number }

export interface ForecastHistoryPoint {
  date: string;
  forecast: number | null;
  actual: number | null;
  consensus: number | null;
  consensusSource?: string | null;
  forecastKind?: "walk_forward" | "confirmed_nowcast" | "live_nowcast" | null;
  officialRounding?: number | null;
}

export interface ForecastInput {
  name: string;
  id: string;
  unit: string;
  source: string;
  frequency: string;
  role: string;
  aggregation: string;
  providerId?: string | null;
  latestAvailableDate?: string | null;
  modelUsageNote?: string | null;
  series: ForecastPoint[];
}

export interface ForecastModel { name: string; unit: string; description: string; formula: string; status?: "READY" | "WAITING_FOR_FIXED_FACTORS"; forecastMonth?: string; earliestForecastDate?: string; missingFactors?: string[] }
export interface ForecastMetric { rmse: number; mae: number; sampleStart: string; sampleEnd: string; directionHit?: number; observations?: number }

export interface ForecastData {
  schemaVersion: number;
  generatedAt: string;
  displayStart: string;
  backtestStart: string;
  source: string;
  dailyAsOf: string;
  daily: Record<string, ForecastPoint[]>;
  history: Record<string, ForecastHistoryPoint[]>;
  models: Record<string, ForecastModel>;
  metrics: Record<string, ForecastMetric>;
  highFrequency: Record<string, ForecastInput[]>;
}
