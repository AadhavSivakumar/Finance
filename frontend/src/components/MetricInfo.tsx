import { useId, useState } from "react";

import type { MetricDef } from "../lib/types";

/**
 * An inline "what is this?" affordance next to a metric name.
 *
 * Definitions come from the backend catalog, not from strings hardcoded here,
 * so the explanation cannot drift from the computation it describes.
 *
 * Click rather than hover: hover tooltips are unreachable by keyboard and
 * unusable on touch, and these explanations are paragraphs rather than labels.
 */
export function MetricInfo({ metric }: { metric?: MetricDef }) {
  const [open, setOpen] = useState(false);
  const id = useId();

  if (!metric) return null;

  return (
    <span style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 4 }}>
      <button
        type="button"
        className="info-dot"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`What is ${metric.label}?`}
        onClick={() => setOpen((v) => !v)}
      >
        ?
      </button>
      {open && (
        <span className="info-pop" id={id} role="note">
          <strong>{metric.label}</strong>
          <span className="info-short">{metric.short}</span>
          <span className="info-reading">{metric.reading}</span>
          {metric.caveat && (
            <span className="info-caveat">
              <strong>Watch out:</strong> {metric.caveat}
            </span>
          )}
          <button type="button" className="ghost-button" onClick={() => setOpen(false)}>
            Close
          </button>
        </span>
      )}
    </span>
  );
}

/** A column header that carries its own explanation. */
export function MetricHeader({
  metric, fallback, numeric = true,
}: { metric?: MetricDef; fallback: string; numeric?: boolean }) {
  return (
    <th className={numeric ? "num" : undefined} scope="col">
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, justifyContent: numeric ? "flex-end" : "flex-start" }}>
        {metric?.label ?? fallback}
        <MetricInfo metric={metric} />
      </span>
    </th>
  );
}
