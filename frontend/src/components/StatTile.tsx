import { type ReactNode } from "react";

interface Props {
  label: string;
  value: string;
  /** Signed change; rendered with an arrow glyph so the sign is never
   *  carried by color alone. */
  delta?: { text: string; direction: "up" | "down" | "flat" };
  foot?: ReactNode;
  className?: string;
}

const ARROW = { up: "▲", down: "▼", flat: "–" } as const;

export function StatTile({ label, value, delta, foot, className = "span-3" }: Props) {
  return (
    <section className={`card ${className}`}>
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      <p className="stat-foot">
        {delta && (
          <span className={`delta ${delta.direction}`}>
            <span aria-hidden="true">{ARROW[delta.direction]}</span>
            {delta.text}
          </span>
        )}
        {delta && foot ? " · " : null}
        {foot}
      </p>
    </section>
  );
}
