import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { ChartCard } from "../components/ChartCard";
import { StatTile } from "../components/StatTile";
import { AXIS_PROPS, CURSOR_LINE, GRID_PROPS, makeTooltip } from "../components/chartBits";
import { fullDate } from "../lib/format";
import type { Bundle, MacroSeries } from "../lib/types";

const CATEGORY_TITLE: Record<string, string> = {
  rates: "Interest rates",
  inflation: "Inflation",
  labor: "Labour market",
};

const tooltipFor = (units: string) =>
  makeTooltip({
    labelFormatter: fullDate,
    valueFormatter: (v) => `${v.toFixed(2)}${units}`,
    names: { value: "Value" },
  });

export function MacroPage({ bundle }: { bundle: Bundle }) {
  const macro = bundle.macro ?? [];
  const curve = macro.find((m) => m.series_id === "T10Y2Y");

  const byCategory = macro.reduce<Record<string, MacroSeries[]>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {});

  return (
    <div className="grid">
      {macro.slice(0, 4).map((s) => (
        <StatTile
          key={s.series_id}
          label={s.title}
          value={s.latest_value !== null ? `${s.latest_value.toFixed(2)}${s.units}` : "—"}
          delta={
            s.change_1y !== null
              ? {
                  text: `${s.change_1y > 0 ? "+" : ""}${s.change_1y.toFixed(2)}${s.units} 1y`,
                  direction: s.change_1y > 0 ? "up" : s.change_1y < 0 ? "down" : "flat",
                }
              : undefined
          }
          foot={s.latest_date}
        />
      ))}

      {curve && (
        <ChartCard
          title="Yield curve: 10-year minus 2-year"
          subtitle="Below zero is an inversion, which has preceded every modern US recession — though with long and variable lags."
          className="span-12"
          empty={!curve.points.length}
          chart={
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={curve.points} margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis dataKey="date" {...AXIS_PROPS} minTickGap={60} />
                <YAxis {...AXIS_PROPS} width={52} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
                <Tooltip content={tooltipFor("%")} cursor={CURSOR_LINE} />
                {/* Zero is the meaningful threshold here, so it gets a solid rule. */}
                <ReferenceLine y={0} stroke="var(--axis)" strokeWidth={1} />
                <Line
                  type="monotone" dataKey="value" stroke="var(--series-1)" strokeWidth={2}
                  dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          }
          tableRows={curve.points.slice(-60)}
          tableColumns={[
            { header: "Date", render: (p) => p.date },
            { header: "Spread", numeric: true, render: (p) => `${p.value?.toFixed(2) ?? "—"}%` },
          ]}
        />
      )}

      {Object.entries(byCategory).map(([category, series]) =>
        series
          .filter((s) => s.series_id !== "T10Y2Y")
          .map((s) => (
            <ChartCard
              key={s.series_id}
              title={s.title}
              subtitle={`${CATEGORY_TITLE[category] ?? category} · latest ${s.latest_date}`}
              className="span-6"
              empty={!s.points.length}
              chart={
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={s.points} margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
                    <CartesianGrid {...GRID_PROPS} />
                    <XAxis dataKey="date" {...AXIS_PROPS} minTickGap={60} />
                    <YAxis {...AXIS_PROPS} width={52} tickFormatter={(v: number) => v.toFixed(1)} />
                    <Tooltip content={tooltipFor(s.units)} cursor={CURSOR_LINE} />
                    <Line
                      type="monotone" dataKey="value" stroke="var(--series-1)" strokeWidth={2}
                      dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              }
              tableRows={s.points.slice(-40)}
              tableColumns={[
                { header: "Date", render: (p) => p.date },
                { header: s.units || "Value", numeric: true, render: (p) => p.value?.toFixed(2) ?? "—" },
              ]}
            />
          )),
      )}
    </div>
  );
}
