import { NewsFeed } from "../components/NewsFeed";
import type { NewsItem } from "../lib/types";

export function NewsPage({
  items, generatedAt,
}: { items: NewsItem[]; generatedAt: string | null }) {
  const tagged = items.filter((i) => i.symbols.length > 0);

  return (
    <div className="grid">
      <section className="card span-8">
        <header className="card-head">
          <div>
            <h2 className="card-title">Market headlines</h2>
            <p className="card-sub">
              Public RSS feeds, refreshed every few minutes. Nothing here is
              scored or ranked — it is context for the numbers, not a signal.
            </p>
          </div>
        </header>
        <NewsFeed items={items} generatedAt={generatedAt} />
      </section>

      <section className="card span-4">
        <header className="card-head">
          <div>
            <h2 className="card-title">Mentioned instruments</h2>
            <p className="card-sub">Tickers matched in the current headlines.</p>
          </div>
        </header>
        {tagged.length === 0 ? (
          <p className="empty">No tracked tickers mentioned right now.</p>
        ) : (
          <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
            <table>
              <tbody>
                {tagged.slice(0, 40).map((n, i) => (
                  <tr key={`${n.link}-${i}`}>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {n.symbols.map((s) => (
                        <span key={s} className="ticker-chip" style={{ marginRight: 4 }}>
                          {s}
                        </span>
                      ))}
                    </td>
                    <td className="muted" style={{ fontSize: 12 }}>
                      {n.title.slice(0, 80)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
