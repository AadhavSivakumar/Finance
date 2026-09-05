import { dataMode } from "../lib/data";

/**
 * Says, plainly, how old everything on the page is.
 *
 * Without this a reader cannot distinguish "the market has not moved" from
 * "the data has not updated", and the two failure modes look identical. Each
 * timestamp is shown with its cadence so a two-hour-old headline feed reads
 * as expected rather than broken.
 */

function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

function sessionAgeDays(asOf: string | null | undefined): number | null {
  if (!asOf) return null;
  const d = new Date(`${asOf}T21:00:00Z`).getTime(); // ~US close
  return Math.floor((Date.now() - d) / 86_400_000);
}

interface Props {
  asOf: string | null;
  generatedAt: string | null;
  newsGeneratedAt: string | null;
}

export function Freshness({ asOf, generatedAt, newsGeneratedAt }: Props) {
  const days = sessionAgeDays(asOf);
  // Weekends legitimately make Friday's session 2-3 days old. Beyond four,
  // ingestion is not keeping up and the reader should know.
  const stale = days !== null && days > 4;

  return (
    <div className={`freshness ${stale ? "stale" : ""}`} role="status" aria-live="polite">
      <span>
        <strong>Market data</strong> session {asOf ?? "—"}
        {days !== null && days > 1 && <span className="muted"> ({days} d old)</span>}
      </span>
      <span className="sep" aria-hidden="true">·</span>
      <span>
        <strong>Computed</strong> {ago(generatedAt)}
        <span className="muted"> · daily after the US close</span>
      </span>
      <span className="sep" aria-hidden="true">·</span>
      <span>
        <strong>Headlines</strong> {ago(newsGeneratedAt)}
        <span className="muted">
          {dataMode === "static" ? " · refreshed hourly-ish by GitHub" : " · every 5 min"}
        </span>
      </span>
      {stale && (
        <span className="stale-flag">
          <span aria-hidden="true">⚠</span> data may be stale
        </span>
      )}
    </div>
  );
}
