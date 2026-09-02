import { useMemo, useState } from "react";

import type { NewsItem } from "../lib/types";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

interface Props {
  items: NewsItem[];
  generatedAt?: string | null;
  /** Only symbols in the universe get a tag chip. */
  onSymbolClick?: (symbol: string) => void;
}

export function NewsFeed({ items, generatedAt, onSymbolClick }: Props) {
  const [source, setSource] = useState<string>("all");

  const sources = useMemo(
    () => ["all", ...Array.from(new Set(items.map((i) => i.source))).sort()],
    [items],
  );
  const shown = source === "all" ? items : items.filter((i) => i.source === source);

  if (!items.length) return <p className="empty">No headlines loaded.</p>;

  return (
    <div>
      <div className="segmented" role="group" aria-label="News source" style={{ marginBottom: 12 }}>
        {sources.map((s) => (
          <button key={s} type="button" aria-pressed={source === s} onClick={() => setSource(s)}>
            {s === "all" ? "All" : s}
          </button>
        ))}
      </div>

      <ul className="news-list">
        {shown.map((n, i) => (
          <li key={`${n.link}-${i}`}>
            <a href={n.link} target="_blank" rel="noopener noreferrer">
              {n.title}
            </a>
            <div className="news-meta">
              <span>{n.source}</span>
              {n.published_at && <span>· {timeAgo(n.published_at)}</span>}
              {n.symbols.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="ticker-chip"
                  onClick={() => onSymbolClick?.(s)}
                  title="Tickers are matched by pattern and are approximate"
                >
                  {s}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>

      <p className="card-sub" style={{ marginTop: 12 }}>
        {generatedAt ? `Headlines fetched ${timeAgo(generatedAt)}. ` : ""}
        Ticker tags are pattern-matched and approximate — a headline about a person
        named Cooper can still match a company called Cooper.
      </p>
    </div>
  );
}
