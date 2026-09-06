import type { TrackRecord as TR } from "../lib/types";

/**
 * Realised outcomes of predictions the dashboard actually published.
 *
 * A backtest estimates lift; this measures it, on picks that existed before
 * their outcomes did. It is the only number here that cannot be flattered by
 * a modelling mistake, which is why it sits next to the backtest figure rather
 * than replacing it -- the gap between the two is itself information.
 */
export function TrackRecordPanel({ record }: { record?: TR }) {
  const s = record?.summary;
  if (!record || !s) {
    return (
      <p className="empty">
        No resolved predictions yet. Outcomes appear the session after a prediction is published.
      </p>
    );
  }

  const fewEvents = s.top_hits < 20;

  return (
    <div>
      <div className="grid" style={{ gap: 10, marginBottom: 12 }}>
        <Tile label="Days scored" value={String(s.days_scored)} />
        <Tile label="Top-decile picks" value={String(s.top_picks)} />
        <Tile label="Actually spiked" value={String(s.top_hits)} />
        <Tile
          label="Live lift"
          value={s.lift !== null ? `${s.lift.toFixed(1)}×` : "—"}
          foot={`backtest ${s.backtest_lift?.toFixed(1) ?? "—"}×`}
        />
      </div>

      <div className="table-wrap" style={{ maxHeight: 260, overflowY: "auto" }}>
        <table>
          <thead>
            <tr>
              <th scope="col">Session</th>
              <th className="num" scope="col">Picks</th>
              <th className="num" scope="col">Hit</th>
              <th className="num" scope="col">Precision</th>
              <th className="num" scope="col">Base rate</th>
              <th className="num" scope="col">Lift</th>
            </tr>
          </thead>
          <tbody>
            {[...record.days].reverse().map((d) => (
              <tr key={d.as_of}>
                <td>{d.as_of}</td>
                <td className="num">{d.top_k}</td>
                <td className={`num ${d.top_hits > 0 ? "pos" : "muted"}`}>{d.top_hits}</td>
                <td className="num">{d.top_precision.toFixed(1)}%</td>
                <td className="num">{d.base_rate.toFixed(2)}%</td>
                <td className="num">
                  {d.lift === null ? <span className="muted">no spikes that day</span> : `${d.lift.toFixed(1)}×`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="card-sub" style={{ marginTop: 10 }}>
        Pooled: {s.top_hits} of {s.top_picks} top-decile picks spiked ({s.top_precision}%) against a{" "}
        {s.base_rate}% base rate. The backtest figure is for the <em>current</em> model; picks from
        before its last retrain were made by an earlier generation, so the two are not a like-for-like
        pair until the record rolls forward.
        {fewEvents && (
          <>
            {" "}
            <strong>Only {s.top_hits} events so far</strong> — far too few for statistical confidence.
            Spikes are rare; read this as “consistent with the backtest”, not “confirmed by it”,
            until the count is in the dozens.
          </>
        )}
      </p>
    </div>
  );
}

function Tile({ label, value, foot }: { label: string; value: string; foot?: string }) {
  return (
    <div className="span-3" style={{ padding: "8px 10px", background: "color-mix(in srgb, var(--text-primary) 4%, transparent)", borderRadius: 8 }}>
      <div className="stat-label">{label}</div>
      <div style={{ fontSize: 22, fontWeight: 620, lineHeight: 1.2, margin: "2px 0" }}>{value}</div>
      {foot && <div className="stat-foot">{foot}</div>}
    </div>
  );
}
