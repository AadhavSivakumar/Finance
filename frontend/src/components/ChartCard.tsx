import { type ReactNode, useId, useState } from "react";

export interface TableColumn<T> {
  header: string;
  numeric?: boolean;
  render: (row: T) => ReactNode;
}

interface Props<T> {
  title: string;
  subtitle?: string;
  className?: string;
  refreshing?: boolean;
  error?: string;
  /** Empty message shown when there is nothing to plot. */
  empty?: boolean;
  emptyMessage?: string;
  chart: ReactNode;
  /** The WCAG-clean twin. Every chart has one -- values must be readable
   *  without relying on color or a hover tooltip. */
  tableRows?: T[];
  tableColumns?: TableColumn<T>[];
  actions?: ReactNode;
}

export function ChartCard<T>({
  title,
  subtitle,
  className = "span-6",
  refreshing,
  error,
  empty,
  emptyMessage = "No data yet.",
  chart,
  tableRows,
  tableColumns,
  actions,
}: Props<T>) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const panelId = useId();
  const hasTable = Boolean(tableRows && tableColumns);

  return (
    <section className={`card ${className}`} aria-labelledby={`${panelId}-title`}>
      <header className="card-head">
        <div>
          <h2 className="card-title" id={`${panelId}-title`}>
            {title}
          </h2>
          {subtitle && <p className="card-sub">{subtitle}</p>}
        </div>
        <div className="card-actions">
          {actions}
          {hasTable && (
            <>
              <button
                className="ghost-button"
                type="button"
                aria-pressed={view === "chart"}
                onClick={() => setView("chart")}
              >
                Chart
              </button>
              <button
                className="ghost-button"
                type="button"
                aria-pressed={view === "table"}
                onClick={() => setView("table")}
              >
                Table
              </button>
            </>
          )}
        </div>
      </header>

      {error ? (
        <p className="empty">{error}</p>
      ) : empty ? (
        <p className="empty">{emptyMessage}</p>
      ) : (
        <div className={refreshing ? "refreshing" : undefined}>
          {view === "chart" || !hasTable ? (
            chart
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {tableColumns!.map((c) => (
                      <th key={c.header} className={c.numeric ? "num" : undefined} scope="col">
                        {c.header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tableRows!.map((row, i) => (
                    <tr key={i}>
                      {tableColumns!.map((c) => (
                        <td key={c.header} className={c.numeric ? "num" : undefined}>
                          {c.render(row)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
