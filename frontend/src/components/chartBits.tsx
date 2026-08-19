import { type TooltipProps } from "recharts";

/**
 * Categorical slots, in fixed order, read from CSS custom properties so light
 * and dark use the mode-appropriate step of the same hue. Assign by entity --
 * never by rank, or filtering repaints the survivors.
 */
export const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
] as const;

export const AXIS_STYLE = {
  fontSize: 11,
  fill: "var(--text-muted)",
} as const;

/** Recessive hairline grid -- solid, one shade off the surface, never dashed. */
export const GRID_PROPS = {
  stroke: "var(--grid)",
  strokeWidth: 1,
  vertical: false,
} as const;

export const AXIS_PROPS = {
  stroke: "var(--axis)",
  tickLine: false,
  tick: AXIS_STYLE,
} as const;

export interface LegendEntry {
  label: string;
  color: string;
}

/** Always present for >= 2 series; a single-series chart is named by its title. */
export function Legend({ entries }: { entries: LegendEntry[] }) {
  if (entries.length < 2) return null;
  return (
    <ul className="legend">
      {entries.map((e) => (
        <li key={e.label}>
          <span className="swatch" style={{ background: e.color }} aria-hidden="true" />
          {e.label}
        </li>
      ))}
    </ul>
  );
}

interface TooltipConfig {
  /** Formats the header (the x value). */
  labelFormatter?: (label: string) => string;
  /** Formats each series value. */
  valueFormatter: (value: number, key: string) => string;
  /** Optional display names keyed by dataKey. */
  names?: Record<string, string>;
}

export function makeTooltip({ labelFormatter, valueFormatter, names }: TooltipConfig) {
  return function CustomTooltip({ active, payload, label }: TooltipProps<number, string>) {
    if (!active || !payload?.length) return null;
    return (
      <div className="tooltip" role="status">
        <div className="tooltip-title">
          {labelFormatter ? labelFormatter(String(label)) : String(label)}
        </div>
        {payload.map((entry) => {
          const key = String(entry.dataKey ?? entry.name ?? "");
          return (
            <div className="tooltip-row" key={key}>
              <span className="name">
                <span
                  className="swatch"
                  style={{ background: entry.color, borderRadius: 3, width: 10, height: 10 }}
                  aria-hidden="true"
                />
                {names?.[key] ?? entry.name}
              </span>
              <span className="value">{valueFormatter(Number(entry.value ?? 0), key)}</span>
            </div>
          );
        })}
      </div>
    );
  };
}

/** Crosshair for line/area charts: a vertical hairline, no dashes. */
export const CURSOR_LINE = { stroke: "var(--axis)", strokeWidth: 1 } as const;

/** Hover wash for bar charts -- larger than the mark, so the hit target is easy. */
export const CURSOR_FILL = { fill: "var(--text-primary)", fillOpacity: 0.05 } as const;
