// Relative base URL on purpose: the same built bundle works behind any
// hostname because nginx (prod) and the Vite proxy (dev) both forward /api to
// the backend. Baking an absolute API URL into the bundle at build time is the
// classic reason a container image stops being environment-portable.
const BASE = "";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
const del = (path: string) => request<void>(path, { method: "DELETE" });

// --- types (mirror backend/app/schemas.py) ---------------------------------

export type TxnType = "buy" | "sell" | "dividend";
export type Interval = "monthly" | "annual" | "one_time";
export type AssetClass = "equity" | "etf" | "crypto" | "cash" | "other";

export interface Portfolio {
  id: number;
  name: string;
  base_currency: string;
}

export interface Holding {
  symbol: string;
  name: string;
  asset_class: AssetClass;
  quantity: string;
  avg_cost: string;
  cost_basis: string;
  last_price: string;
  market_value: string;
  unrealized_pl: string;
  unrealized_pl_pct: string;
  weight_pct: string;
  /** False when no live quote was available; the position is valued at cost. */
  has_quote: boolean;
}

export interface PortfolioSummary {
  portfolio_id: number;
  name: string;
  base_currency: string;
  market_value: string;
  cost_basis: string;
  unrealized_pl: string;
  unrealized_pl_pct: string;
  realized_pl: string;
  dividend_income: string;
  holdings: Holding[];
}

export interface AllocationSlice {
  key: string;
  market_value: string;
  weight_pct: string;
}

export interface PerformancePoint {
  date: string;
  market_value: string;
  cost_basis: string;
}

export interface Transaction {
  id: number;
  portfolio_id: number;
  symbol: string;
  type: TxnType;
  quantity: string;
  price: string;
  fee: string;
  executed_at: string;
  note: string;
}

export interface Quote {
  symbol: string;
  price: string;
  change: string;
  change_pct: string;
  currency: string;
  as_of: string;
}

export interface Candle {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

export interface WatchlistItem {
  id: number;
  symbol: string;
  note: string;
}

export interface MonthlyPoint {
  month: string;
  revenue: string;
  mrr: string;
  expenses: string;
  net: string;
}

export interface BusinessSummary {
  as_of: string;
  mrr: string;
  arr: string;
  monthly_expenses: string;
  net_burn: string;
  gross_margin_pct: string;
  cash: string;
  runway_months: string | null;
  mom_revenue_growth_pct: string;
  series: MonthlyPoint[];
}

export interface ExpenseBreakdownRow {
  category: string;
  monthly_amount: string;
  share_pct: string;
}

export interface RevenueStream {
  id: number;
  name: string;
  customer: string;
  interval: Interval;
  amount: string;
  currency: string;
  start_date: string;
  end_date: string | null;
}

export interface Expense {
  id: number;
  category: string;
  vendor: string;
  interval: Interval;
  amount: string;
  currency: string;
  start_date: string;
  end_date: string | null;
}

export interface CashSnapshot {
  id: number;
  as_of: string;
  amount: string;
  currency: string;
}

// --- endpoints -------------------------------------------------------------

export const api = {
  listPortfolios: () => get<Portfolio[]>("/api/portfolios"),
  createPortfolio: (body: { name: string; base_currency?: string }) =>
    post<Portfolio>("/api/portfolios", body),
  summary: (id: number) => get<PortfolioSummary>(`/api/portfolios/${id}/summary`),
  allocation: (id: number, by: "symbol" | "asset_class") =>
    get<AllocationSlice[]>(`/api/portfolios/${id}/allocation?by=${by}`),
  performance: (id: number, days: number) =>
    get<PerformancePoint[]>(`/api/portfolios/${id}/performance?days=${days}`),
  transactions: (id: number) => get<Transaction[]>(`/api/portfolios/${id}/transactions`),
  createTransaction: (id: number, body: Record<string, unknown>) =>
    post<Transaction>(`/api/portfolios/${id}/transactions`, body),
  deleteTransaction: (id: number, txnId: number) =>
    del(`/api/portfolios/${id}/transactions/${txnId}`),

  quotes: (symbols: string[]) =>
    get<Quote[]>(`/api/market/quotes?symbols=${encodeURIComponent(symbols.join(","))}`),
  candles: (symbol: string, days: number) =>
    get<Candle[]>(`/api/market/candles/${encodeURIComponent(symbol)}?days=${days}`),
  watchlist: () => get<WatchlistItem[]>("/api/market/watchlist"),
  addWatchlist: (body: { symbol: string; note?: string }) =>
    post<WatchlistItem>("/api/market/watchlist", body),
  removeWatchlist: (id: number) => del(`/api/market/watchlist/${id}`),

  business: (months: number) => get<BusinessSummary>(`/api/business/summary?months=${months}`),
  expenseBreakdown: () => get<ExpenseBreakdownRow[]>("/api/business/expenses/breakdown"),
  revenueStreams: () => get<RevenueStream[]>("/api/business/revenue"),
  createRevenue: (body: Record<string, unknown>) =>
    post<RevenueStream>("/api/business/revenue", body),
  deleteRevenue: (id: number) => del(`/api/business/revenue/${id}`),
  expenses: () => get<Expense[]>("/api/business/expenses"),
  createExpense: (body: Record<string, unknown>) => post<Expense>("/api/business/expenses", body),
  deleteExpense: (id: number) => del(`/api/business/expenses/${id}`),
  cash: () => get<CashSnapshot[]>("/api/business/cash"),
  createCash: (body: Record<string, unknown>) => post<CashSnapshot>("/api/business/cash", body),
};
