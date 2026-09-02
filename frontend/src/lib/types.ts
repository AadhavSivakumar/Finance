export interface Mover {
  symbol: string;
  name: string;
  short_label: string;
  group: string;
  sector: string;
  universe: string;
  close: number | null;
  ret_1d: number | null;
  ret_5d: number | null;
  ret_21d: number | null;
  ret_63d: number | null;
  ret_252d: number | null;
  rsi_14: number | null;
  vol_20d: number | null;
  vol_ratio_10_60: number | null;
  atr_pct: number | null;
  pct_from_52w_high: number | null;
  drawdown_pct: number | null;
  volume_z: number | null;
  rel_strength_21d: number | null;
  px_over_sma200: number | null;
}

export interface Regime {
  as_of: string;
  trend: "risk-on" | "risk-off" | "mixed";
  breadth_pct: number;
  advancers_pct: number;
  spy_px_over_sma200: number | null;
  vix_level: number | null;
  vix_percentile_1y: number | null;
  avg_correlation: number | null;
  notes: string[];
}

export interface SignalRow {
  symbol: string;
  name: string;
  as_of: string;
  kind: string;
  direction: "bullish" | "bearish" | "neutral";
  strength: number | null;
  detail: string;
}

export interface ModelRow {
  target: string;
  model: string;
  trained_at: string | null;
  n_train: number;
  n_features: number;
  train_start: string | null;
  train_end: string | null;
  roc_auc: number | null;
  base_rate: number | null;
  accuracy: number | null;
  baseline_accuracy: number | null;
  edge_vs_baseline: number | null;
  top_decile_precision: number | null;
  lift: number | null;
  is_active: boolean;
  horizon_days: number | null;
  folds: number | null;
}

export interface PredictionRow {
  symbol: string;
  name: string;
  sector: string;
  as_of: string;
  target: string;
  model: string;
  probability: number;
  percentile: number | null;
  model_roc_auc: number | null;
  model_lift: number | null;
  model_base_rate: number | null;
}

export interface Correlations {
  as_of: string;
  window: number;
  symbols: string[];
  labels: string[];
  matrix: (number | null)[][];
}

export interface MacroSeries {
  series_id: string;
  title: string;
  units: string;
  category: string;
  latest_value: number | null;
  latest_date: string;
  change_1y: number | null;
  points: { date: string; value: number | null }[];
}

export interface ComputeRunRow {
  kind: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  detail: Record<string, unknown>;
  error: string;
}

export interface Freshness {
  as_of: string | null;
  symbols: number;
  bars: number;
  runs: ComputeRunRow[];
}

export interface MetricDef {
  key: string;
  label: string;
  unit: string;
  short: string;
  reading: string;
  direction?: "higher" | "lower" | "context";
  caveat?: string;
  group?: string;
}

export interface NewsItem {
  title: string;
  link: string;
  source: string;
  summary: string;
  published_at: string | null;
  symbols: string[];
}

export interface SymbolRow {
  symbol: string;
  name: string;
  group: string;
  sector: string;
}

export interface Bundle {
  meta: { generated_at: string; as_of: string | null; freshness: Freshness };
  regime: Regime;
  movers: Mover[];
  sectors: Mover[];
  signals: SignalRow[];
  models: ModelRow[];
  predictions: Record<string, PredictionRow[]>;
  correlations: Correlations;
  macro: MacroSeries[];
  history: Record<string, { date: string; close: number }[]>;
  news: NewsItem[];
  metrics: MetricDef[];
  symbols?: SymbolRow[];
}
