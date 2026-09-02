import { useMemo, useState } from "react";

/**
 * Correlation is a DIVERGING quantity: -1 and +1 are opposite meanings and 0
 * is "nothing". So the scale is two opposed hues (blue/red) around a neutral
 * gray midpoint -- never a rainbow, and never a single-hue ramp, which would
 * imply -1 and +1 are merely "less" and "more" of the same thing.
 */
function correlationColor(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "var(--grid)";
  const t = Math.max(-1, Math.min(1, v));
  const mag = Math.abs(t);
  // Opacity carries magnitude; hue carries sign. Both channels encode the
  // same number on purpose here -- redundancy helps CVD readers.
  const hue = t >= 0 ? "var(--series-1)" : "var(--series-8)";
  return `color-mix(in srgb, ${hue} ${(mag * 88).toFixed(0)}%, var(--surface))`;
}

interface Props {
  labels: string[];
  matrix: (number | null)[][];
  window: number;
}

export function CorrelationHeatmap({ labels, matrix, window }: Props) {
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);

  const cell = useMemo(() => Math.max(16, Math.min(30, 620 / Math.max(labels.length, 1))), [labels]);

  if (!labels.length) return <p className="empty">No correlation data yet.</p>;

  return (
    <div>
      <div className="legend" style={{ alignItems: "center" }}>
        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>−1</span>
        <span
          aria-hidden="true"
          style={{
            width: 140, height: 10, borderRadius: 3,
            background:
              "linear-gradient(to right, var(--series-8), color-mix(in srgb, var(--series-8) 20%, var(--surface)), var(--grid), color-mix(in srgb, var(--series-1) 20%, var(--surface)), var(--series-1))",
          }}
        />
        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>+1</span>
        <span style={{ color: "var(--text-muted)", fontSize: 12, marginLeft: 8 }}>
          {window}-day window
        </span>
      </div>

      <div className="table-wrap">
        <table style={{ borderCollapse: "separate", borderSpacing: 2, width: "auto" }}>
          <thead>
            <tr>
              <th />
              {labels.map((l, j) => (
                <th
                  key={l}
                  scope="col"
                  style={{
                    fontSize: 10, padding: 2, whiteSpace: "nowrap",
                    color: hover?.j === j ? "var(--text-primary)" : "var(--text-muted)",
                    writingMode: "vertical-rl", transform: "rotate(180deg)",
                    height: 78, border: 0,
                  }}
                >
                  {l}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => (
              <tr key={labels[i]}>
                <th
                  scope="row"
                  style={{
                    fontSize: 11, padding: "0 8px 0 0", textAlign: "right",
                    whiteSpace: "nowrap", border: 0,
                    color: hover?.i === i ? "var(--text-primary)" : "var(--text-muted)",
                  }}
                >
                  {labels[i]}
                </th>
                {row.map((v, j) => (
                  <td
                    key={`${i}-${j}`}
                    onMouseEnter={() => setHover({ i, j })}
                    onMouseLeave={() => setHover(null)}
                    title={`${labels[i]} vs ${labels[j]}: ${v === null ? "n/a" : v.toFixed(2)}`}
                    style={{
                      width: cell, height: cell, padding: 0, border: 0,
                      borderRadius: 3,
                      background: correlationColor(v),
                      outline:
                        hover && (hover.i === i || hover.j === j)
                          ? "1px solid var(--text-muted)"
                          : "none",
                    }}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="card-sub" style={{ marginTop: 10 }}>
        {hover
          ? `${labels[hover.i]} vs ${labels[hover.j]}: ${
              matrix[hover.i]?.[hover.j]?.toFixed(2) ?? "n/a"
            }`
          : "Hover a cell to read the pair. Blue = move together, red = move opposite."}
      </p>
    </div>
  );
}
