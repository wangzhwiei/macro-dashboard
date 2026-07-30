export type Signal = "bullish" | "bearish" | "neutral";

export interface OverallSummary {
  score: number;
  signal: Signal;
  title: string;
  narrative: string;
  breadth: number;
  confidence: number;
  freshness: number;
}

export interface CategorySummary {
  id: string;
  name: string;
  code: string;
  score: number;
  signal: Signal;
  breadth: number;
  confidence: number;
  updatedAt: string;
  summary: string;
  validCount: number;
  totalCount: number;
  weeklyScores: number[];
}

export interface Indicator {
  id: string;
  category: string;
  family: string;
  name: string;
  frequency: "日频" | "周频";
  unit: string;
  latest: number;
  previous: number;
  change: number;
  changeLabel: string;
  signal: Signal;
  score: number;
  percentile: number;
  updatedAt: string;
  source: string;
  core: boolean;
  reason: string;
  history: number[];
}

export interface DashboardData {
  generatedAt: string;
  mode: string;
  dates: string[];
  overall: OverallSummary;
  categories: CategorySummary[];
  indicators: Indicator[];
}
