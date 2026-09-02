import type { ModelRow } from "../lib/types";

/**
 * The honesty panel.
 *
 * Every evaluated model is listed, including the ones that failed the gate,
 * with the baseline they were measured against. A dashboard that showed only
 * its working models would make "we cannot predict direction" look like a
 * missing feature rather than the finding it is.
 */
export function ModelPanel({ models }: { models: ModelRow[] }) {
  if (!models.length) return <p className="empty">No models trained yet.</p>;

  const label: Record<string, string> = {
    spike_2atr: "Sudden move (next day > 2× ATR)",
    up_5d: "Direction (up over 5 days)",
  };

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Target</th>
            <th scope="col">Model</th>
            <th className="num" scope="col">AUC</th>
            <th className="num" scope="col">Lift</th>
            <th className="num" scope="col">Base rate</th>
            <th className="num" scope="col">Top-decile</th>
            <th scope="col">Shown?</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={`${m.target}-${m.model}`}>
              <td>{label[m.target] ?? m.target}</td>
              <td className="muted">{m.model.replace("_", " ")}</td>
              <td className="num">{m.roc_auc?.toFixed(3) ?? "—"}</td>
              <td className="num">{m.lift ? `${m.lift.toFixed(2)}×` : "—"}</td>
              <td className="num">{m.base_rate?.toFixed(2)}%</td>
              <td className="num">{m.top_decile_precision?.toFixed(2)}%</td>
              <td>
                {m.is_active ? (
                  <span className="delta up">
                    <span aria-hidden="true">●</span> in use
                  </span>
                ) : (
                  <span className="muted" title="Evaluated, but showed no measurable edge">
                    ○ no edge found
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="card-sub" style={{ marginTop: 10 }}>
        Measured out-of-sample by walk-forward validation with a purge between
        train and test. A model is only used if it ranks meaningfully better
        than chance (AUC ≥ 0.55) and lifts the base rate by ≥ 1.2×. Direction
        does not clear that bar and is deliberately not shown as a forecast.
      </p>
    </div>
  );
}
