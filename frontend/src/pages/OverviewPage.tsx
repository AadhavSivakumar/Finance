import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { ChartCard } from "../components/ChartCard";
import { ModelPanel } from "../components/ModelPanel";
import { StatTile } from "../components/StatTile";
import { AXIS_PROPS, CURSOR_FILL, GRID_PROPS, makeTooltip } from "../components/chartBits";
import { pct, signedPct } from "../lib/format";
import { NewsFeed } from "../components/NewsFeed";
import type { Bundle, NewsItem } from "../lib/types";

const SECTOR_TOOLTIP = makeTooltip({
  valueFormatter: (v) => signedPct(v),
  names: { ret_21d: "21-day return" },
});

const TREND_COPY: Record<string, string> = {
  "risk-on": "Trend, breadth and volatility line up constructively.",
  "risk-off": "Trend, breadth and volatility line up defensively.",
  mixed: "Signals disagree — no clean regime read.",
};

export function OverviewPage({ bundle, news = [] }: { bundle: Bundle; news?: NewsItem[] }) {
  const { regime, sectors, models, signals, predictions } = bundle;
  const spike = predictions?.spike_2atr ?? [];

  const sectorData = sectors
    .filter((s) => s.ret_21d !== null)
    .map((s) => ({ label: s.short_label || s.symbol, ret_21d: s.ret_21d as number }));

  return (
    <div className="grid">
      <section className="card span-12">
        <p className="stat-label">Market regime · {regime?.as_of}</p>
        <p className="stat-value" style={{ textTransform: "capitalize" }}>
          {regime?.trend ?? "—"}
        </p>
        <p className="card-sub">{TREND_COPY[regime?.trend] ?? ""}</p>
        <ul style={{ margin: "12px 0 0", paddingLeft: 18, color: "var(--text-secondary)" }}>
          {(regime?.notes ?? []).map((n) => (
            <li key={n} style={{ fontSize: 13 }}>{n}</li>
          ))}
        </ul>
      </section>

      <StatTile
        label="Breadth"
        value={regime ? pct(regime.breadth_pct, 0) : "—"}
        foot="above their 200-day average"
      />
      <StatTile
        label="Advancers today"
        value={regime ? pct(regime.advancers_pct, 0) : "—"}
        foot="of the tracked universe"
      />
      <StatTile
        label="VIX"
        value={regime?.vix_level ? regime.vix_level.toFixed(2) : "—"}
        foot={
          regime?.vix_percentile_1y !== null && regime?.vix_percentile_1y !== undefined
            ? `${regime.vix_percentile_1y.toFixed(0)}th percentile of the past year`
            : undefined
        }
      />
      <StatTile
        label="Avg correlation"
        value={
          regime?.avg_correlation !== null && regime?.avg_correlation !== undefined
            ? regime.avg_correlation.toFixed(2)
            : "—"
        }
        foot="cross-asset, 90-day"
      />

      <ChartCard
        title="Sector rotation"
        subtitle="21-day return by sector. Diverging colour marks above or below zero, not rank."
        className="span-7"
        empty={sectorData.length === 0}
        chart={
          <ResponsiveContainer width="100%" height={Math.max(240, sectorData.length * 26 + 40)}>
            <BarChart
              data={sectorData}
              layout="vertical"
              margin={{ top: 4, right: 20, bottom: 4, left: 4 }}
              barCategoryGap={5}
            >
              <CartesianGrid {...GRID_PROPS} horizontal={false} vertical />
              <XAxis type="number" {...AXIS_PROPS} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <YAxis type="category" dataKey="label" {...AXIS_PROPS} width={92} />
              <Tooltip content={SECTOR_TOOLTIP} cursor={CURSOR_FILL} />
              <Bar dataKey="ret_21d" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                {sectorData.map((d) => (
                  <Cell key={d.label} fill={d.ret_21d >= 0 ? "var(--series-1)" : "var(--series-8)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        }
        tableRows={sectorData}
        tableColumns={[
          { header: "Sector", render: (r) => r.label },
          { header: "21-day", numeric: true, render: (r) => signedPct(r.ret_21d) },
        ]}
      />

      <section className="card span-5">
        <header className="card-head">
          <div>
            <h2 className="card-title">Sudden-move candidates</h2>
            <p className="card-sub">
              Highest modelled probability of a next-day move larger than 2× ATR.
            </p>
          </div>
        </header>
        {spike.length === 0 ? (
          <p className="empty">No active model for this target.</p>
        ) : (
          <>
            <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Symbol</th>
                    <th scope="col">Name</th>
                    <th className="num" scope="col">Probability</th>
                  </tr>
                </thead>
                <tbody>
                  {spike.slice(0, 12).map((p) => (
                    <tr key={p.symbol}>
                      <td>{p.symbol}</td>
                      <td className="muted">{p.name}</td>
                      <td className="num">{(p.probability * 100).toFixed(2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="card-sub" style={{ marginTop: 10 }}>
              The base rate is {spike[0]?.model_base_rate?.toFixed(2)}%, so these are roughly{" "}
              {spike[0]?.model_lift?.toFixed(1)}× likelier than a random day — not likely in
              absolute terms. Most of them will not move.
            </p>
          </>
        )}
      </section>

      <section className="card span-7">
        <header className="card-head">
          <div>
            <h2 className="card-title">Model scorecard</h2>
            <p className="card-sub">What the models can and cannot do, measured out-of-sample.</p>
          </div>
        </header>
        <ModelPanel models={models} />
      </section>

      <section className="card span-12">
        <header className="card-head">
          <div>
            <h2 className="card-title">Latest headlines</h2>
            <p className="card-sub">
              Context for the numbers above. Refreshed independently of the
              market data, which only changes once a day.
            </p>
          </div>
        </header>
        <NewsFeed items={news.slice(0, 12)} />
      </section>

      <section className="card span-5">
        <header className="card-head">
          <div>
            <h2 className="card-title">Signals</h2>
            <p className="card-sub">Explainable events on the latest session.</p>
          </div>
        </header>
        <div className="table-wrap" style={{ maxHeight: 340, overflowY: "auto" }}>
          <table>
            <tbody>
              {signals.slice(0, 40).map((s, i) => (
                <tr key={`${s.symbol}-${s.kind}-${i}`}>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <strong>{s.symbol}</strong>
                  </td>
                  <td>
                    <span
                      className={
                        s.direction === "bullish"
                          ? "pos"
                          : s.direction === "bearish"
                            ? "neg"
                            : "muted"
                      }
                    >
                      <span aria-hidden="true">
                        {s.direction === "bullish" ? "▲" : s.direction === "bearish" ? "▼" : "•"}
                      </span>{" "}
                      {s.detail}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {signals.length === 0 && <p className="empty">No signals on the latest session.</p>}
        </div>
      </section>
    </div>
  );
}
