import { useCallback, useEffect, useState } from "react";

import { dataMode, loadBundle } from "./lib/data";
import type { Bundle } from "./lib/types";
import { MacroPage } from "./pages/MacroPage";
import { MomentumPage } from "./pages/MomentumPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RiskPage } from "./pages/RiskPage";

type Tab = "overview" | "momentum" | "risk" | "macro";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "momentum", label: "Momentum" },
  { id: "risk", label: "Risk" },
  { id: "macro", label: "Macro" },
];

type Theme = "light" | "dark" | "system";
const THEME_LABEL: Record<Theme, string> = {
  system: "Theme: system",
  light: "Theme: light",
  dark: "Theme: dark",
};

function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme | null) ?? "system",
  );
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  const cycle = useCallback(
    () => setTheme((t) => (t === "system" ? "light" : t === "light" ? "dark" : "system")),
    [],
  );
  return { theme, cycle };
}

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const { theme, cycle } = useTheme();

  const load = useCallback(() => {
    setLoading(true);
    loadBundle()
      .then((b) => {
        setBundle(b);
        setError(undefined);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load data"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const asOf = bundle?.regime?.as_of ?? bundle?.meta?.as_of ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Market Dashboard
          <span>
            {asOf ? `Session ${asOf}` : "Loading…"}
            {bundle?.meta?.freshness?.symbols
              ? ` · ${bundle.meta.freshness.symbols} instruments`
              : ""}
          </span>
        </div>

        <nav className="tabs" role="tablist" aria-label="Sections">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>

        {/* Refreshing is pointless on the static build: the data only changes
            when the scheduled job republishes it. */}
        {dataMode === "api" && (
          <button className="icon-button" type="button" onClick={load}>
            Refresh
          </button>
        )}
        <button className="icon-button" type="button" onClick={cycle}>
          {THEME_LABEL[theme]}
        </button>
      </header>

      {error && (
        <p className="banner">
          Could not load data ({error}).{" "}
          {dataMode === "api"
            ? "Is the api container running?"
            : "The published data files may still be building."}
        </p>
      )}

      {loading && !bundle && <p className="empty">Loading market data…</p>}

      {bundle && (
        <>
          {tab === "overview" && <OverviewPage bundle={bundle} />}
          {tab === "momentum" && <MomentumPage bundle={bundle} />}
          {tab === "risk" && <RiskPage bundle={bundle} />}
          {tab === "macro" && <MacroPage bundle={bundle} />}

          <footer className="card-sub" style={{ marginTop: 28, textAlign: "center" }}>
            Computed {bundle.meta?.generated_at?.slice(0, 16).replace("T", " ")} UTC ·{" "}
            {bundle.meta?.freshness?.bars?.toLocaleString()} daily bars · market data via OpenBB /
            yfinance. Educational use only — not investment advice.
          </footer>
        </>
      )}
    </div>
  );
}
