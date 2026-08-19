import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartCard } from "../components/ChartCard";
import { AXIS_PROPS, CURSOR_LINE, GRID_PROPS, makeTooltip } from "../components/chartBits";
import { api } from "../lib/api";
import { dayLabel, direction, fullDate, money, num, signedMoney, signedPct } from "../lib/format";
import { useApi } from "../lib/useApi";

const RANGES = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
];

const PRICE_TOOLTIP = makeTooltip({
  labelFormatter: fullDate,
  valueFormatter: (v) => money(v),
  names: { close: "Close" },
});

const ARROW = { up: "▲", down: "▼", flat: "–" } as const;

export function MarketPage() {
  const [days, setDays] = useState(90);
  const [selected, setSelected] = useState<string>("");
  const [newSymbol, setNewSymbol] = useState("");
  const [addError, setAddError] = useState<string>();

  const watchlist = useApi(() => api.watchlist(), []);
  const symbols = useMemo(() => (watchlist.data ?? []).map((w) => w.symbol), [watchlist.data]);

  useEffect(() => {
    if (!selected && symbols.length) setSelected(symbols[0]);
  }, [symbols, selected]);

  const quotes = useApi(
    () => (symbols.length ? api.quotes(symbols) : Promise.resolve([])),
    [symbols.join(",")],
  );
  const candles = useApi(
    () => (selected ? api.candles(selected, days) : Promise.resolve([])),
    [selected, days],
  );

  const priceData = useMemo(
    () => (candles.data ?? []).map((c) => ({ date: c.date, close: num(c.close) })),
    [candles.data],
  );

  const quoteBySymbol = useMemo(
    () => Object.fromEntries((quotes.data ?? []).map((q) => [q.symbol, q])),
    [quotes.data],
  );

  const add = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setAddError(undefined);
      try {
        await api.addWatchlist({ symbol: newSymbol });
        setNewSymbol("");
        watchlist.reload();
      } catch (err) {
        setAddError(err instanceof Error ? err.message : "Failed to add symbol");
      }
    },
    [newSymbol, watchlist],
  );

  const remove = useCallback(
    async (id: number, symbol: string) => {
      await api.removeWatchlist(id);
      if (selected === symbol) setSelected("");
      watchlist.reload();
    },
    [selected, watchlist],
  );

  const selectedQuote = selected ? quoteBySymbol[selected] : undefined;

  return (
    <>
      <div className="filter-row">
        <label htmlFor="symbol-select">Symbol</label>
        <select
          id="symbol-select"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={symbols.length === 0}
        >
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <label htmlFor="market-range" style={{ marginLeft: 8 }}>
          Range
        </label>
        <div className="segmented" id="market-range" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r.days} type="button" aria-pressed={days === r.days} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
        </div>

        <form onSubmit={add} style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <input
            type="text"
            value={newSymbol}
            placeholder="Add symbol"
            aria-label="Add symbol to watchlist"
            onChange={(e) => setNewSymbol(e.target.value)}
          />
          <button className="primary-button" type="submit" disabled={!newSymbol.trim()}>
            Add
          </button>
        </form>
      </div>

      {addError && <p className="banner">{addError}</p>}

      <div className="grid">
        <ChartCard
          title={selected ? `${selected} closing price` : "Closing price"}
          subtitle={
            selectedQuote
              ? `${money(selectedQuote.price)} · ${signedMoney(selectedQuote.change)} (${signedPct(
                  selectedQuote.change_pct,
                )}) today`
              : "Pick a symbol from the watchlist."
          }
          className="span-8"
          refreshing={candles.refreshing}
          error={candles.error}
          empty={priceData.length === 0}
          emptyMessage="No price history available."
          chart={
            <ResponsiveContainer width="100%" height={300}>
              {/* Single series: the title names it, so no legend box. A soft
                  area under the line reads as magnitude without shouting. */}
              <AreaChart data={priceData} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
                <defs>
                  <linearGradient id="closeFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid {...GRID_PROPS} />
                <XAxis dataKey="date" {...AXIS_PROPS} tickFormatter={dayLabel} minTickGap={40} />
                <YAxis
                  {...AXIS_PROPS}
                  width={64}
                  domain={["auto", "auto"]}
                  tickFormatter={(v: number) => money(v).replace(/\.00$/, "")}
                />
                <Tooltip content={PRICE_TOOLTIP} cursor={CURSOR_LINE} />
                <Area
                  type="monotone"
                  dataKey="close"
                  stroke="var(--series-1)"
                  strokeWidth={2}
                  fill="url(#closeFill)"
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          }
          tableRows={priceData}
          tableColumns={[
            { header: "Date", render: (r) => fullDate(r.date) },
            { header: "Close", numeric: true, render: (r) => money(r.close) },
          ]}
        />

        <section className="card span-4">
          <header className="card-head">
            <div>
              <h2 className="card-title">Watchlist</h2>
              <p className="card-sub">Quotes cached server-side for 60s.</p>
            </div>
            <div className="card-actions">
              <button className="ghost-button" type="button" onClick={() => quotes.reload()}>
                Refresh
              </button>
            </div>
          </header>

          <div className={`table-wrap ${quotes.refreshing ? "refreshing" : ""}`}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Symbol</th>
                  <th className="num" scope="col">Price</th>
                  <th className="num" scope="col">Change</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(watchlist.data ?? []).map((w) => {
                  const q = quoteBySymbol[w.symbol];
                  const dir = q ? direction(q.change) : "flat";
                  return (
                    <tr
                      key={w.id}
                      onClick={() => setSelected(w.symbol)}
                      style={{ cursor: "pointer" }}
                    >
                      <td>{w.symbol}</td>
                      <td className="num">{q ? money(q.price) : "—"}</td>
                      <td className={`num ${dir === "up" ? "pos" : dir === "down" ? "neg" : ""}`}>
                        {q ? (
                          <>
                            <span aria-hidden="true">{ARROW[dir]}</span> {signedPct(q.change_pct)}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="row-actions">
                        <button
                          type="button"
                          aria-label={`Remove ${w.symbol}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            void remove(w.id, w.symbol);
                          }}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {(watchlist.data ?? []).length === 0 && <p className="empty">Watchlist is empty.</p>}
          </div>
        </section>
      </div>
    </>
  );
}
