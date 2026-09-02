import { useMemo, useState } from "react";

import type { Bundle, MetricDef } from "../lib/types";

/**
 * Every metric the dashboard shows, explained.
 *
 * Sourced from the backend catalog so the definitions here and the tooltips
 * elsewhere are literally the same objects.
 */
export function GlossaryPage({ bundle }: { bundle: Bundle }) {
  const [query, setQuery] = useState("");
  const metrics = bundle.metrics ?? [];

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? metrics.filter(
          (m) =>
            m.label.toLowerCase().includes(q) ||
            m.short.toLowerCase().includes(q) ||
            m.key.toLowerCase().includes(q),
        )
      : metrics;
    return filtered.reduce<Record<string, MetricDef[]>>((acc, m) => {
      (acc[m.group ?? "Other"] ??= []).push(m);
      return acc;
    }, {});
  }, [metrics, query]);

  const DIRECTION_COPY: Record<string, string> = {
    higher: "Higher is generally better",
    lower: "Lower is generally better",
    context: "Neither good nor bad on its own",
  };

  return (
    <>
      <div className="filter-row">
        <label htmlFor="glossary-search">Search</label>
        <input
          id="glossary-search"
          type="text"
          value={query}
          placeholder="e.g. volatility, beta, RSI"
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 260 }}
        />
        <span className="muted" style={{ marginLeft: "auto", fontSize: 12 }}>
          {Object.values(groups).flat().length} of {metrics.length} metrics
        </span>
      </div>

      <div className="grid">
        {Object.entries(groups).map(([group, items]) => (
          <section className="card span-6" key={group}>
            <header className="card-head">
              <div>
                <h2 className="card-title">{group}</h2>
                <p className="card-sub">{items.length} metrics</p>
              </div>
            </header>

            <dl className="glossary">
              {items.map((m) => (
                <div key={m.key}>
                  <dt>
                    {m.label}
                    {m.unit && <span className="muted"> ({m.unit})</span>}
                    <span className={`direction ${m.direction}`}>
                      {DIRECTION_COPY[m.direction ?? "context"]}
                    </span>
                  </dt>
                  <dd>
                    <p className="short">{m.short}</p>
                    <p>{m.reading}</p>
                    {m.caveat && (
                      <p className="caveat">
                        <strong>Watch out:</strong> {m.caveat}
                      </p>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        {Object.keys(groups).length === 0 && (
          <p className="empty span-12">No metrics match “{query}”.</p>
        )}
      </div>
    </>
  );
}
