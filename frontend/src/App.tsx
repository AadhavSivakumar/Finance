import { useCallback, useEffect, useState } from "react";

import { api, type Portfolio } from "./lib/api";
import { useApi } from "./lib/useApi";
import { BusinessPage } from "./pages/BusinessPage";
import { MarketPage } from "./pages/MarketPage";
import { PortfolioPage } from "./pages/PortfolioPage";

type Tab = "portfolio" | "business" | "market";

const TABS: { id: Tab; label: string }[] = [
  { id: "portfolio", label: "Portfolio" },
  { id: "business", label: "Business" },
  { id: "market", label: "Market" },
];

type Theme = "light" | "dark" | "system";

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

const THEME_LABEL: Record<Theme, string> = {
  system: "Theme: system",
  light: "Theme: light",
  dark: "Theme: dark",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("portfolio");
  const { theme, cycle } = useTheme();
  const portfolios = useApi(() => api.listPortfolios(), []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Finance Dashboard
          <span>Portfolio performance &amp; business metrics</span>
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

        <button className="icon-button" type="button" onClick={cycle}>
          {THEME_LABEL[theme]}
        </button>
      </header>

      {portfolios.error && (
        <p className="banner">
          Could not reach the API ({portfolios.error}). Is the <code>api</code> container running?
        </p>
      )}

      {tab === "portfolio" &&
        (portfolios.loading ? (
          <p className="empty">Loading…</p>
        ) : (portfolios.data ?? []).length === 0 ? (
          <EmptyPortfolios onCreated={portfolios.reload} />
        ) : (
          <PortfolioPage portfolios={portfolios.data as Portfolio[]} />
        ))}

      {tab === "business" && <BusinessPage />}
      {tab === "market" && <MarketPage />}
    </div>
  );
}

function EmptyPortfolios({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("Main Portfolio");
  const [busy, setBusy] = useState(false);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createPortfolio({ name });
      onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card span-12" style={{ maxWidth: 520 }}>
      <h2 className="card-title">No portfolios yet</h2>
      <p className="card-sub" style={{ marginBottom: 14 }}>
        Create one, or load the demo dataset with
        <code> docker compose exec api python -m app.seed</code>.
      </p>
      <form onSubmit={create} style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          value={name}
          aria-label="Portfolio name"
          onChange={(e) => setName(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="primary-button" type="submit" disabled={busy || !name.trim()}>
          Create
        </button>
      </form>
    </section>
  );
}
