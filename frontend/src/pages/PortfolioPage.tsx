import { useCallback, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartCard, type TableColumn } from "../components/ChartCard";
import { StatTile } from "../components/StatTile";
import {
  AXIS_PROPS,
  CURSOR_FILL,
  CURSOR_LINE,
  GRID_PROPS,
  Legend,
  SERIES,
  makeTooltip,
} from "../components/chartBits";
import { api, type Holding, type Portfolio } from "../lib/api";
import {
  compactMoney,
  dayLabel,
  direction,
  fullDate,
  money,
  money0,
  num,
  qty,
  signedMoney,
  signedPct,
} from "../lib/format";
import { useApi } from "../lib/useApi";

const RANGES = [
  { label: "30D", days: 30 },
  { label: "90D", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "3Y", days: 1095 },
];

const PERF_TOOLTIP = makeTooltip({
  labelFormatter: fullDate,
  valueFormatter: (v) => money0(v),
  names: { market_value: "Market value", cost_basis: "Cost basis" },
});

const HOLDING_TOOLTIP = makeTooltip({
  valueFormatter: (v) => money(v),
  names: { value: "Market value" },
});

const ALLOC_TOOLTIP = makeTooltip({
  valueFormatter: (v) => money(v),
  names: { value: "Market value" },
});

export function PortfolioPage({ portfolios }: { portfolios: Portfolio[] }) {
  const [portfolioId, setPortfolioId] = useState(portfolios[0]?.id ?? 0);
  const [days, setDays] = useState(180);
  const [allocBy, setAllocBy] = useState<"asset_class" | "symbol">("asset_class");

  const summary = useApi(() => api.summary(portfolioId), [portfolioId]);
  const perf = useApi(() => api.performance(portfolioId, days), [portfolioId, days]);
  const alloc = useApi(() => api.allocation(portfolioId, allocBy), [portfolioId, allocBy]);
  const txns = useApi(() => api.transactions(portfolioId), [portfolioId]);

  const currency = summary.data?.base_currency ?? "USD";

  const perfData = useMemo(
    () =>
      (perf.data ?? []).map((p) => ({
        date: p.date,
        market_value: num(p.market_value),
        cost_basis: num(p.cost_basis),
      })),
    [perf.data],
  );

  const holdingsData = useMemo(
    () =>
      (summary.data?.holdings ?? []).map((h) => ({
        symbol: h.symbol,
        value: num(h.market_value),
        pl: num(h.unrealized_pl),
      })),
    [summary.data],
  );

  const allocData = useMemo(
    () => (alloc.data ?? []).map((a) => ({ key: a.key, value: num(a.market_value) })),
    [alloc.data],
  );

  const reloadAll = useCallback(() => {
    summary.reload();
    perf.reload();
    alloc.reload();
    txns.reload();
  }, [summary, perf, alloc, txns]);

  const s = summary.data;

  return (
    <>
      <div className="filter-row">
        <label htmlFor="portfolio-select">Portfolio</label>
        <select
          id="portfolio-select"
          value={portfolioId}
          onChange={(e) => setPortfolioId(Number(e.target.value))}
        >
          {portfolios.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        <label htmlFor="range-group" style={{ marginLeft: 8 }}>
          Range
        </label>
        <div className="segmented" id="range-group" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.days}
              type="button"
              aria-pressed={days === r.days}
              onClick={() => setDays(r.days)}
            >
              {r.label}
            </button>
          ))}
        </div>

        <button className="ghost-button" type="button" onClick={reloadAll} style={{ marginLeft: "auto" }}>
          Refresh
        </button>
      </div>

      <div className="grid">
        <StatTile
          label="Market value"
          value={s ? money0(s.market_value, currency) : "—"}
          delta={
            s
              ? {
                  text: `${signedMoney(s.unrealized_pl, currency)} (${signedPct(s.unrealized_pl_pct)})`,
                  direction: direction(s.unrealized_pl),
                }
              : undefined
          }
          foot="unrealized"
        />
        <StatTile
          label="Cost basis"
          value={s ? money0(s.cost_basis, currency) : "—"}
          foot={s ? `${s.holdings.length} open positions` : undefined}
        />
        <StatTile
          label="Realized P&L"
          value={s ? signedMoney(s.realized_pl, currency) : "—"}
          delta={s ? { text: "closed lots", direction: direction(s.realized_pl) } : undefined}
        />
        <StatTile
          label="Dividend income"
          value={s ? money(s.dividend_income, currency) : "—"}
          foot="lifetime"
        />

        <ChartCard
          title="Portfolio value vs cost basis"
          subtitle="Revalued daily at closing prices. Includes contributions, so it is not a time-weighted return."
          className="span-8"
          refreshing={perf.refreshing}
          error={perf.error}
          empty={perfData.length === 0}
          emptyMessage="Add transactions to see performance."
          chart={
            <>
              <Legend
                entries={[
                  { label: "Market value", color: "var(--series-1)" },
                  { label: "Cost basis", color: "var(--series-2)" },
                ]}
              />
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={perfData} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
                  <CartesianGrid {...GRID_PROPS} />
                  <XAxis
                    dataKey="date"
                    {...AXIS_PROPS}
                    tickFormatter={dayLabel}
                    minTickGap={40}
                  />
                  <YAxis
                    {...AXIS_PROPS}
                    width={56}
                    tickFormatter={(v: number) => compactMoney(v, currency)}
                  />
                  <Tooltip content={PERF_TOOLTIP} cursor={CURSOR_LINE} />
                  {/* 2px strokes, no dots: a dot per day is noise at this density. */}
                  <Line
                    type="monotone"
                    dataKey="market_value"
                    stroke="var(--series-1)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="cost_basis"
                    stroke="var(--series-2)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </>
          }
          tableRows={perfData}
          tableColumns={
            [
              { header: "Date", render: (r) => fullDate(r.date) },
              { header: "Market value", numeric: true, render: (r) => money(r.market_value, currency) },
              { header: "Cost basis", numeric: true, render: (r) => money(r.cost_basis, currency) },
              {
                header: "Unrealized",
                numeric: true,
                render: (r) => (
                  <span className={r.market_value - r.cost_basis >= 0 ? "pos" : "neg"}>
                    {signedMoney(r.market_value - r.cost_basis, currency)}
                  </span>
                ),
              },
            ] as TableColumn<(typeof perfData)[number]>[]
          }
        />

        <ChartCard
          title="Allocation"
          subtitle="Share of current market value."
          className="span-4"
          refreshing={alloc.refreshing}
          error={alloc.error}
          empty={allocData.length === 0}
          actions={
            <div className="segmented" role="group" aria-label="Group allocation by">
              <button
                type="button"
                aria-pressed={allocBy === "asset_class"}
                onClick={() => setAllocBy("asset_class")}
              >
                Class
              </button>
              <button
                type="button"
                aria-pressed={allocBy === "symbol"}
                onClick={() => setAllocBy("symbol")}
              >
                Symbol
              </button>
            </div>
          }
          chart={
            <>
              <Legend
                entries={allocData
                  .slice(0, 8)
                  .map((d, i) => ({ label: d.key, color: SERIES[i % SERIES.length] }))}
              />
              <ResponsiveContainer width="100%" height={232}>
                <PieChart>
                  {/* Donut, not pie: part-to-whole at a glance with the total
                      readable in the middle. Segments capped at 8 -- the tail
                      folds into "Other" server-side if it ever grows. */}
                  <Pie
                    data={allocData}
                    dataKey="value"
                    nameKey="key"
                    innerRadius="58%"
                    outerRadius="86%"
                    paddingAngle={1}
                    stroke="var(--surface)"
                    strokeWidth={2}
                    isAnimationActive={false}
                  >
                    {allocData.map((d, i) => (
                      <Cell key={d.key} fill={SERIES[i % SERIES.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={ALLOC_TOOLTIP} />
                </PieChart>
              </ResponsiveContainer>
            </>
          }
          tableRows={alloc.data ?? []}
          tableColumns={[
            { header: allocBy === "symbol" ? "Symbol" : "Class", render: (r) => r.key },
            { header: "Value", numeric: true, render: (r) => money(r.market_value, currency) },
            { header: "Weight", numeric: true, render: (r) => `${num(r.weight_pct).toFixed(1)}%` },
          ]}
        />

        <ChartCard
          title="Holdings by market value"
          subtitle="One series, one color — bar length already encodes size."
          className="span-6"
          refreshing={summary.refreshing}
          error={summary.error}
          empty={holdingsData.length === 0}
          chart={
            <ResponsiveContainer width="100%" height={Math.max(200, holdingsData.length * 34 + 40)}>
              <BarChart
                data={holdingsData}
                layout="vertical"
                margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
                barCategoryGap={6}
              >
                <CartesianGrid {...GRID_PROPS} horizontal={false} vertical />
                <XAxis
                  type="number"
                  {...AXIS_PROPS}
                  tickFormatter={(v: number) => compactMoney(v, currency)}
                />
                <YAxis type="category" dataKey="symbol" {...AXIS_PROPS} width={72} />
                <Tooltip content={HOLDING_TOOLTIP} cursor={CURSOR_FILL} />
                <Bar
                  dataKey="value"
                  fill="var(--series-1)"
                  radius={[0, 4, 4, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          }
          tableRows={summary.data?.holdings ?? []}
          tableColumns={holdingColumns(currency)}
        />

        <TransactionsCard
          portfolioId={portfolioId}
          currency={currency}
          rows={txns.data ?? []}
          refreshing={txns.refreshing}
          error={txns.error}
          onChanged={reloadAll}
        />
      </div>
    </>
  );
}

function holdingColumns(currency: string): TableColumn<Holding>[] {
  return [
    { header: "Symbol", render: (h) => h.symbol },
    { header: "Name", render: (h) => h.name || "—" },
    { header: "Qty", numeric: true, render: (h) => qty(h.quantity) },
    { header: "Avg cost", numeric: true, render: (h) => money(h.avg_cost, currency) },
    {
      header: "Last",
      numeric: true,
      // A missing quote is called out in words, not by color alone -- the
      // number is otherwise indistinguishable from a real one.
      render: (h) =>
        h.has_quote ? (
          money(h.last_price, currency)
        ) : (
          <span className="muted" title="No live quote — valued at average cost">
            {money(h.last_price, currency)} (at cost)
          </span>
        ),
    },
    { header: "Value", numeric: true, render: (h) => money(h.market_value, currency) },
    {
      header: "Unrealized",
      numeric: true,
      render: (h) => (
        <span className={num(h.unrealized_pl) >= 0 ? "pos" : "neg"}>
          {signedMoney(h.unrealized_pl, currency)} ({signedPct(h.unrealized_pl_pct)})
        </span>
      ),
    },
    { header: "Weight", numeric: true, render: (h) => `${num(h.weight_pct).toFixed(1)}%` },
  ];
}

// ---------------------------------------------------------------------------

interface TxnProps {
  portfolioId: number;
  currency: string;
  rows: import("../lib/api").Transaction[];
  refreshing: boolean;
  error?: string;
  onChanged: () => void;
}

const today = () => new Date().toISOString().slice(0, 10);

function TransactionsCard({ portfolioId, currency, rows, refreshing, error, onChanged }: TxnProps) {
  const [form, setForm] = useState({
    symbol: "",
    type: "buy",
    quantity: "",
    price: "",
    fee: "0",
    executed_at: today(),
  });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string>();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFormError(undefined);
    try {
      await api.createTransaction(portfolioId, {
        ...form,
        quantity: form.quantity,
        price: form.price,
        fee: form.fee || "0",
      });
      setForm({ ...form, symbol: "", quantity: "", price: "" });
      onChanged();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to add transaction");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    await api.deleteTransaction(portfolioId, id);
    onChanged();
  };

  return (
    <section className="card span-6">
      <header className="card-head">
        <div>
          <h2 className="card-title">Transactions</h2>
          <p className="card-sub">Holdings are derived from this log — it is the source of truth.</p>
        </div>
      </header>

      <form className="form-grid" onSubmit={submit} style={{ marginBottom: 14 }}>
        <div>
          <label className="stat-label" htmlFor="txn-symbol">Symbol</label>
          <input
            id="txn-symbol"
            type="text"
            required
            value={form.symbol}
            placeholder="AAPL"
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            style={{ width: "100%" }}
          />
        </div>
        <div>
          <label className="stat-label" htmlFor="txn-type">Type</label>
          <select
            id="txn-type"
            value={form.type}
            onChange={(e) => setForm({ ...form, type: e.target.value })}
            style={{ width: "100%" }}
          >
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
            <option value="dividend">Dividend</option>
          </select>
        </div>
        <div>
          <label className="stat-label" htmlFor="txn-qty">Quantity</label>
          <input
            id="txn-qty"
            type="number"
            step="any"
            min="0"
            required
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: e.target.value })}
            style={{ width: "100%" }}
          />
        </div>
        <div>
          <label className="stat-label" htmlFor="txn-price">Price</label>
          <input
            id="txn-price"
            type="number"
            step="any"
            min="0"
            required
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
            style={{ width: "100%" }}
          />
        </div>
        <div>
          <label className="stat-label" htmlFor="txn-date">Date</label>
          <input
            id="txn-date"
            type="date"
            required
            value={form.executed_at}
            onChange={(e) => setForm({ ...form, executed_at: e.target.value })}
            style={{ width: "100%" }}
          />
        </div>
        <button className="primary-button" type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add"}
        </button>
      </form>

      {formError && <p className="banner">{formError}</p>}
      {error && <p className="empty">{error}</p>}

      <div className={`table-wrap ${refreshing ? "refreshing" : ""}`} style={{ maxHeight: 320, overflowY: "auto" }}>
        <table>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Symbol</th>
              <th scope="col">Type</th>
              <th className="num" scope="col">Qty</th>
              <th className="num" scope="col">Price</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id}>
                <td>{fullDate(t.executed_at)}</td>
                <td>{t.symbol}</td>
                <td>{t.type}</td>
                <td className="num">{qty(t.quantity)}</td>
                <td className="num">{money(t.price, currency)}</td>
                <td className="row-actions">
                  <button type="button" onClick={() => remove(t.id)} aria-label={`Delete ${t.symbol} transaction`}>
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="empty">No transactions yet.</p>}
      </div>
    </section>
  );
}
