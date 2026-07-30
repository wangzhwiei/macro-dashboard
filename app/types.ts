export type Signal = "bullish" | "bearish" | "neutral";

export interface BreadthDetail {
  bullish: number;
  bearish: number;
  neutral: number;
  total: number;
}

export interface OverallSummary {
  score: number;
  signal: Signal;
  title: string;
  narrative: string;
  breadth: number;
  breadthDetail: BreadthDetail;
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
  breadthDetail: BreadthDetail;
  confidence: number;
  updatedAt: string;
  summary: string;
  validCount: number;
  totalCount: number;
  weeklyScores: number[];
}

export interface IndicatorMethodology {
  title: string;
  formula: string;
  calibration: string;
  steps: string[];
  components: Array<{
    code: string;
    weight: number;
  }>;
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
  series: Array<{ date: string; value: number }>;
  methodology: IndicatorMethodology;
}

export interface DashboardData {
  generatedAt: string;
  mode: string;
  dates: string[];
  overall: OverallSummary;
  categories: CategorySummary[];
  indicators: Indicator[];
}
