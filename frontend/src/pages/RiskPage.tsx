import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { ChartCard } from "../components/ChartCard";
import { CorrelationHeatmap } from "../components/CorrelationHeatmap";
import { MetricInfo } from "../components/MetricInfo";
import { StatTile } from "../components/StatTile";
import { AXIS_PROPS, CURSOR_FILL, GRID_PROPS, makeTooltip } from "../components/chartBits";
import { pct, signedPct } from "../lib/format";
import type { Bundle } from "../lib/types";

const VOL_TOOLTIP = makeTooltip({
  valueFormatter: (v) => `${v.toFixed(1)}%`,
  names: { vol_20d: "20-day volatility" },
});

export function RiskPage({ bundle }: { bundle: Bundle }) {
  const byKey = new Map((bundle.metrics ?? []).map((m) => [m.key, m]));
  const { correlations, movers, regime } = bundle;

  const mostVolatile = useMemo(
    () =>
      movers
        .filter((m) => m.vol_20d !== null)
        .sort((a, b) => (b.vol_20d as number) - (a.vol_20d as number))
        .slice(0, 15)
        .map((m) => ({ label: m.symbol, vol_20d: m.vol_20d as number })),
    [movers],
  );

  const expanding = useMemo(
    () =>
      movers
        .filter((m) => m.vol_ratio_10_60 !== null)
        .sort((a, b) => (b.vol_ratio_10_60 as number) - (a.vol_ratio_10_60 as number))
        .slice(0, 15),
    [movers],
  );

  const deepest = useMemo(
    () =>
      movers
        .filter((m) => m.drawdown_pct !== null)
        .sort((a, b) => (a.drawdown_pct as number) - (b.drawdown_pct as number))
        .slice(0, 15),
    [movers],
  );

  return (
    <div className="grid">
      <StatTile
        label="Avg correlation"
        value={regime?.avg_correlation?.toFixed(2) ?? "—"}
        foot="cross-asset, 90-day — rises in a crisis"
      />
      <StatTile
        label="VIX percentile"
        value={
          regime?.vix_percentile_1y !== null && regime?.vix_percentile_1y !== undefined
            ? `${regime.vix_percentile_1y.toFixed(0)}th`
            : "—"
        }
        foot="of the past year"
      />
      <StatTile
        label="Breadth"
        value={regime ? pct(regime.breadth_pct, 0) : "—"}
        foot="above their 200-day"
      />
      <StatTile
        label="Instruments"
        value={String(movers.length)}
        foot="tracked in the universe"
      />

      <ChartCard
        title="Cross-asset correlation"
        actions={<MetricInfo metric={byKey.get("corr_spy_60")} />}
        subtitle="How much the major asset classes are moving together. When everything turns blue at once, diversification has stopped working."
        className="span-12"
        empty={!correlations?.labels?.length}
        chart={
          <CorrelationHeatmap
            labels={correlations?.labels ?? []}
            matrix={correlations?.matrix ?? []}
            window={correlations?.window ?? 90}
          />
        }
      />

      <ChartCard
        title="Most volatile"
        actions={<MetricInfo metric={byKey.get("vol_20d")} />}
        subtitle="Annualised 20-day realised volatility. One series, one colour — bar length already encodes size."
        className="span-6"
        empty={mostVolatile.length === 0}
        chart={
          <ResponsiveContainer width="100%" height={Math.max(240, mostVolatile.length * 26 + 40)}>
            <BarChart data={mostVolatile} layout="vertical" margin={{ top: 4, right: 20, bottom: 4, left: 4 }} barCategoryGap={5}>
              <CartesianGrid {...GRID_PROPS} horizontal={false} vertical />
              <XAxis type="number" {...AXIS_PROPS} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <YAxis type="category" dataKey="label" {...AXIS_PROPS} width={80} />
              <Tooltip content={VOL_TOOLTIP} cursor={CURSOR_FILL} />
              <Bar dataKey="vol_20d" fill="var(--series-1)" radius={[0, 4, 4, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        }
        tableRows={mostVolatile}
        tableColumns={[
          { header: "Symbol", render: (r) => r.label },
          { header: "20-day vol", numeric: true, render: (r) => `${r.vol_20d.toFixed(1)}%` },
        ]}
      />

      <ChartCard
        title="Volatility expanding"
        actions={<MetricInfo metric={byKey.get("vol_ratio_10_60")} />}
        subtitle="10-day volatility relative to 60-day. Above 1 means the market is waking up — compression precedes expansion."
        className="span-6"
        empty={expanding.length === 0}
        chart={
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Symbol</th>
                  <th scope="col">Name</th>
                  <th className="num" scope="col">10d / 60d</th>
                </tr>
              </thead>
              <tbody>
                {expanding.map((r) => (
                  <tr key={r.symbol}>
                    <td><strong>{r.symbol}</strong></td>
                    <td className="muted" style={{ maxWidth: 190, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {r.name}
                    </td>
                    <td className="num">{(r.vol_ratio_10_60 as number).toFixed(2)}×</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
      />

      <ChartCard
        title="Deepest drawdowns"
        actions={<MetricInfo metric={byKey.get("drawdown_pct")} />}
        subtitle="Distance below the running peak of the tracked history."
        className="span-12"
        empty={deepest.length === 0}
        chart={
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Symbol</th>
                  <th scope="col">Name</th>
                  <th className="num" scope="col">Drawdown</th>
                  <th className="num" scope="col">From 52w high</th>
                  <th className="num" scope="col">RSI</th>
                </tr>
              </thead>
              <tbody>
                {deepest.map((r) => (
                  <tr key={r.symbol}>
                    <td><strong>{r.symbol}</strong></td>
                    <td className="muted">{r.name}</td>
                    <td className="num neg">{signedPct(r.drawdown_pct ?? 0)}</td>
                    <td className="num">{signedPct(r.pct_from_52w_high ?? 0)}</td>
                    <td className="num">{r.rsi_14?.toFixed(0) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
      />
    </div>
  );
}
