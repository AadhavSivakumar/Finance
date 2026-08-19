import { useCallback, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartCard } from "../components/ChartCard";
import { StatTile } from "../components/StatTile";
import {
  AXIS_PROPS,
  CURSOR_FILL,
  CURSOR_LINE,
  GRID_PROPS,
  Legend,
  makeTooltip,
} from "../components/chartBits";
import { api } from "../lib/api";
import {
  compactMoney,
  direction,
  money,
  money0,
  monthLabel,
  num,
  signedMoney,
  signedPct,
} from "../lib/format";
import { useApi } from "../lib/useApi";

const WINDOWS = [
  { label: "6M", months: 6 },
  { label: "12M", months: 12 },
  { label: "24M", months: 24 },
];

const CASHFLOW_TOOLTIP = makeTooltip({
  labelFormatter: monthLabel,
  valueFormatter: (v) => money0(v),
  names: { revenue: "Revenue", expenses: "Expenses" },
});

const MRR_TOOLTIP = makeTooltip({
  labelFormatter: monthLabel,
  valueFormatter: (v) => money0(v),
  names: { mrr: "MRR" },
});

const NET_TOOLTIP = makeTooltip({
  labelFormatter: monthLabel,
  valueFormatter: (v) => money0(v),
  names: { net: "Net" },
});

const EXPENSE_TOOLTIP = makeTooltip({
  valueFormatter: (v) => money(v),
  names: { amount: "Monthly cost" },
});

export function BusinessPage() {
  const [months, setMonths] = useState(12);

  const biz = useApi(() => api.business(months), [months]);
  const breakdown = useApi(() => api.expenseBreakdown(), []);

  const series = useMemo(
    () =>
      (biz.data?.series ?? []).map((p) => ({
        month: p.month,
        revenue: num(p.revenue),
        mrr: num(p.mrr),
        expenses: num(p.expenses),
        net: num(p.net),
      })),
    [biz.data],
  );

  const expenseRows = useMemo(
    () =>
      (breakdown.data ?? []).map((r) => ({
        category: r.category,
        amount: num(r.monthly_amount),
        share: num(r.share_pct),
      })),
    [breakdown.data],
  );

  const reloadAll = useCallback(() => {
    biz.reload();
    breakdown.reload();
  }, [biz, breakdown]);

  const d = biz.data;
  const burning = d ? num(d.net_burn) > 0 : false;

  return (
    <>
      <div className="filter-row">
        <label htmlFor="window-group">Window</label>
        <div className="segmented" id="window-group" role="group" aria-label="Months of history">
          {WINDOWS.map((w) => (
            <button
              key={w.months}
              type="button"
              aria-pressed={months === w.months}
              onClick={() => setMonths(w.months)}
            >
              {w.label}
            </button>
          ))}
        </div>
        <button className="ghost-button" type="button" onClick={reloadAll} style={{ marginLeft: "auto" }}>
          Refresh
        </button>
      </div>

      <div className="grid">
        <StatTile
          label="MRR"
          value={d ? money0(d.mrr) : "—"}
          delta={
            d
              ? { text: `${signedPct(d.mom_revenue_growth_pct)} MoM`, direction: direction(d.mom_revenue_growth_pct) }
              : undefined
          }
          foot={d ? `${money0(d.arr)} ARR` : undefined}
        />
        <StatTile
          label="Monthly expenses"
          value={d ? money0(d.monthly_expenses) : "—"}
          foot={d ? `${num(d.gross_margin_pct).toFixed(0)}% gross margin` : undefined}
        />
        <StatTile
          label={burning ? "Net burn" : "Net profit"}
          value={d ? money0(Math.abs(num(d.net_burn))) : "—"}
          delta={d ? { text: burning ? "burning" : "profitable", direction: burning ? "down" : "up" } : undefined}
          foot="per month"
        />
        <StatTile
          label="Runway"
          value={d ? (d.runway_months ? `${num(d.runway_months).toFixed(1)} mo` : "∞") : "—"}
          foot={d ? `${money0(d.cash)} cash` : undefined}
        />

        <ChartCard
          title="Revenue vs expenses"
          subtitle="Recognized monthly: annual contracts amortize over 12 months, one-time revenue lands in its own month."
          className="span-8"
          refreshing={biz.refreshing}
          error={biz.error}
          empty={series.length === 0}
          chart={
            <>
              <Legend
                entries={[
                  { label: "Revenue", color: "var(--series-1)" },
                  { label: "Expenses", color: "var(--series-2)" },
                ]}
              />
              <ResponsiveContainer width="100%" height={280}>
                {/* Both series are dollars, so they share one axis. A second
                    y-scale here would invent a correlation that isn't real. */}
                <BarChart data={series} margin={{ top: 4, right: 12, bottom: 4, left: 4 }} barGap={2}>
                  <CartesianGrid {...GRID_PROPS} />
                  <XAxis dataKey="month" {...AXIS_PROPS} tickFormatter={monthLabel} minTickGap={12} />
                  <YAxis {...AXIS_PROPS} width={56} tickFormatter={(v: number) => compactMoney(v)} />
                  <Tooltip content={CASHFLOW_TOOLTIP} cursor={CURSOR_FILL} />
                  <Bar dataKey="revenue" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="expenses" fill="var(--series-2)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </>
          }
          tableRows={series}
          tableColumns={[
            { header: "Month", render: (r) => monthLabel(r.month) },
            { header: "Revenue", numeric: true, render: (r) => money0(r.revenue) },
            { header: "MRR", numeric: true, render: (r) => money0(r.mrr) },
            { header: "Expenses", numeric: true, render: (r) => money0(r.expenses) },
            {
              header: "Net",
              numeric: true,
              render: (r) => <span className={r.net >= 0 ? "pos" : "neg"}>{signedMoney(r.net)}</span>,
            },
          ]}
        />

        <ChartCard
          title="MRR"
          subtitle="Recurring only — one-time revenue excluded by definition."
          className="span-4"
          refreshing={biz.refreshing}
          error={biz.error}
          empty={series.length === 0}
          chart={
            <ResponsiveContainer width="100%" height={232}>
              <LineChart data={series} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis dataKey="month" {...AXIS_PROPS} tickFormatter={monthLabel} minTickGap={24} />
                <YAxis {...AXIS_PROPS} width={52} tickFormatter={(v: number) => compactMoney(v)} />
                <Tooltip content={MRR_TOOLTIP} cursor={CURSOR_LINE} />
                <Line
                  type="monotone"
                  dataKey="mrr"
                  stroke="var(--series-1)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          }
          tableRows={series}
          tableColumns={[
            { header: "Month", render: (r) => monthLabel(r.month) },
            { header: "MRR", numeric: true, render: (r) => money0(r.mrr) },
          ]}
        />

        <ChartCard
          title="Net cash flow"
          subtitle="Revenue minus expenses per month. Above the zero line is profit."
          className="span-6"
          refreshing={biz.refreshing}
          error={biz.error}
          empty={series.length === 0}
          chart={
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={series} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis dataKey="month" {...AXIS_PROPS} tickFormatter={monthLabel} minTickGap={12} />
                <YAxis {...AXIS_PROPS} width={56} tickFormatter={(v: number) => compactMoney(v)} />
                <Tooltip content={NET_TOOLTIP} cursor={CURSOR_FILL} />
                {/* Zero is the meaningful reference here, so it gets a solid rule. */}
                <ReferenceLine y={0} stroke="var(--axis)" strokeWidth={1} />
                {/* Diverging polarity: two opposed hues (blue/red) around a
                    zero midpoint. Cell must be a direct Bar child — Recharts
                    inspects the element type, so a wrapper component is
                    silently ignored. */}
                <Bar dataKey="net" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  {series.map((p) => (
                    <Cell key={p.month} fill={p.net >= 0 ? "var(--series-1)" : "var(--series-8)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          }
          tableRows={series}
          tableColumns={[
            { header: "Month", render: (r) => monthLabel(r.month) },
            {
              header: "Net",
              numeric: true,
              render: (r) => <span className={r.net >= 0 ? "pos" : "neg"}>{signedMoney(r.net)}</span>,
            },
          ]}
        />

        <ChartCard
          title="Expense breakdown"
          subtitle="Current month, recognized. One series, one color."
          className="span-6"
          refreshing={breakdown.refreshing}
          error={breakdown.error}
          empty={expenseRows.length === 0}
          chart={
            <ResponsiveContainer width="100%" height={Math.max(200, expenseRows.length * 34 + 40)}>
              <BarChart
                data={expenseRows}
                layout="vertical"
                margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
                barCategoryGap={6}
              >
                <CartesianGrid {...GRID_PROPS} horizontal={false} vertical />
                <XAxis type="number" {...AXIS_PROPS} tickFormatter={(v: number) => compactMoney(v)} />
                <YAxis type="category" dataKey="category" {...AXIS_PROPS} width={132} />
                <Tooltip content={EXPENSE_TOOLTIP} cursor={CURSOR_FILL} />
                <Bar dataKey="amount" fill="var(--series-1)" radius={[0, 4, 4, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          }
          tableRows={expenseRows}
          tableColumns={[
            { header: "Category", render: (r) => r.category },
            { header: "Monthly", numeric: true, render: (r) => money(r.amount) },
            { header: "Share", numeric: true, render: (r) => `${r.share.toFixed(1)}%` },
          ]}
        />
      </div>
    </>
  );
}
