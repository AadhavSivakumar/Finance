import { useMemo, useState } from "react";

import { ChartCard } from "../components/ChartCard";
import { MetricInfo } from "../components/MetricInfo";
import { signedPct } from "../lib/format";
import type { Bundle, Mover } from "../lib/types";

const WINDOWS = [
  { key: "ret_5d", label: "1W" },
  { key: "ret_21d", label: "1M" },
  { key: "ret_63d", label: "3M" },
  { key: "ret_252d", label: "1Y" },
] as const;

type WindowKey = (typeof WINDOWS)[number]["key"];

const GROUPS = [
  { key: "all", label: "All" },
  { key: "equity", label: "Stocks" },
  { key: "sector", label: "Sectors" },
  { key: "index", label: "Indices" },
  { key: "crypto", label: "Crypto" },
] as const;

function rank(rows: Mover[], key: WindowKey, dir: 1 | -1) {
  return rows
    .filter((r) => r[key] !== null)
    .sort((a, b) => dir * ((b[key] as number) - (a[key] as number)))
    .slice(0, 15);
}

export function MomentumPage({ bundle }: { bundle: Bundle }) {
  const byKey = new Map((bundle.metrics ?? []).map((m) => [m.key, m]));
  const [win, setWin] = useState<WindowKey>("ret_21d");
  const [group, setGroup] = useState<string>("all");

  const rows = useMemo(
    () => (group === "all" ? bundle.movers : bundle.movers.filter((m) => m.group === group)),
    [bundle.movers, group],
  );

  const leaders = useMemo(() => rank(rows, win, 1), [rows, win]);
  const laggards = useMemo(() => rank(rows, win, -1), [rows, win]);

  const cols = (r: Mover) => r;

  return (
    <>
      {/* One filter row above everything it scopes -- never per-card filters. */}
      <div className="filter-row">
        <label htmlFor="win">Window</label>
        <div className="segmented" id="win" role="group" aria-label="Return window">
          {WINDOWS.map((w) => (
            <button key={w.key} type="button" aria-pressed={win === w.key} onClick={() => setWin(w.key)}>
              {w.label}
            </button>
          ))}
        </div>
        <label htmlFor="grp" style={{ marginLeft: 8 }}>Universe</label>
        <div className="segmented" id="grp" role="group" aria-label="Instrument group">
          {GROUPS.map((g) => (
            <button key={g.key} type="button" aria-pressed={group === g.key} onClick={() => setGroup(g.key)}>
              {g.label}
            </button>
          ))}
        </div>
        <span className="muted" style={{ marginLeft: "auto", fontSize: 12 }}>
          {rows.length} instruments
        </span>
      </div>

      <div className="grid">
        <ChartCard
          title="Leaders"
          actions={<MetricInfo metric={byKey.get(win)} />}
          subtitle={`Strongest ${WINDOWS.find((w) => w.key === win)?.label} performers.`}
          className="span-6"
          empty={leaders.length === 0}
          chart={<RankTable rows={leaders} win={win} />}
        />
        <ChartCard
          title="Laggards"
          actions={<MetricInfo metric={byKey.get(win)} />}
          subtitle={`Weakest ${WINDOWS.find((w) => w.key === win)?.label} performers.`}
          className="span-6"
          empty={laggards.length === 0}
          chart={<RankTable rows={laggards} win={win} />}
        />

        <ChartCard
          title="Relative strength vs the market"
          actions={<MetricInfo metric={byKey.get("rel_strength_21d")} />}
          subtitle="21-day return minus the S&P 500's, so it isolates what is outperforming rather than what is simply rising."
          className="span-12"
          empty={rows.length === 0}
          chart={
            <RankTable
              rows={rows
                .filter((r) => r.rel_strength_21d !== null)
                .sort((a, b) => (b.rel_strength_21d as number) - (a.rel_strength_21d as number))
                .slice(0, 20)}
              win="ret_21d"
              extra="rel_strength_21d"
            />
          }
          tableRows={rows.filter((r) => r.rel_strength_21d !== null).slice(0, 100).map(cols)}
          tableColumns={[
            { header: "Symbol", render: (r) => r.symbol },
            { header: "Name", render: (r) => r.name },
            { header: "21d", numeric: true, render: (r) => signedPct(r.ret_21d ?? 0) },
            { header: "vs SPY", numeric: true, render: (r) => signedPct(r.rel_strength_21d ?? 0) },
          ]}
        />
      </div>
    </>
  );
}

function RankTable({
  rows, win, extra,
}: { rows: Mover[]; win: WindowKey; extra?: keyof Mover }) {
  const max = Math.max(...rows.map((r) => Math.abs((r[extra ?? win] as number) ?? 0)), 1);

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Symbol</th>
            <th scope="col">Name</th>
            <th className="num" scope="col">{extra ? "vs SPY" : "Return"}</th>
            <th scope="col" style={{ width: "34%" }} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const v = (r[extra ?? win] as number) ?? 0;
            return (
              <tr key={r.symbol}>
                <td><strong>{r.symbol}</strong></td>
                <td className="muted" style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {r.name}
                </td>
                <td className={`num ${v >= 0 ? "pos" : "neg"}`}>{signedPct(v)}</td>
                <td>
                  {/* Inline bar: length encodes magnitude, hue encodes sign. */}
                  <span
                    aria-hidden="true"
                    style={{
                      display: "block",
                      height: 8,
                      borderRadius: 4,
                      width: `${(Math.abs(v) / max) * 100}%`,
                      background: v >= 0 ? "var(--series-1)" : "var(--series-8)",
                    }}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
