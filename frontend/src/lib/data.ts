import type { Bundle } from "./types";

/**
 * One dashboard, two deployment shapes.
 *
 *   static  -- GitHub Pages. Everything is a precomputed JSON file produced by
 *              `python -m app.export`; there is no server to query.
 *   api     -- the local Docker stack, reading Postgres through FastAPI.
 *
 * Both paths go through the same backend query module, so the numbers are
 * identical; only the transport differs. The mode is chosen at build time via
 * VITE_DATA_SOURCE, defaulting to `api` for local development.
 *
 * BASE_URL matters for Pages: the site is served from /<repo>/, not /, so
 * asset and data paths must be relative to Vite's configured base.
 */
const MODE = (import.meta.env.VITE_DATA_SOURCE ?? "api") as "api" | "static";

const DATA_BASE = `${import.meta.env.BASE_URL ?? "/"}data`.replace(/\/+/g, "/");

export const dataMode = MODE;

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${url}`);
  return (await res.json()) as T;
}

/**
 * The whole dashboard in one request.
 *
 * In static mode that is a single ~740KB file (well under 200KB gzipped),
 * which beats ten round trips on a cold Pages cache. In API mode the same
 * shape is assembled from the individual endpoints, in parallel.
 */
export async function loadBundle(): Promise<Bundle> {
  if (MODE === "static") {
    return getJSON<Bundle>(`${DATA_BASE}/all.json`);
  }

  const [regime, movers, sectors, signals, models, spike, up5, correlations, macro, freshness] =
    await Promise.all([
      getJSON<Bundle["regime"]>("/api/regime"),
      getJSON<Bundle["movers"]>("/api/movers"),
      getJSON<Bundle["sectors"]>("/api/sectors"),
      getJSON<Bundle["signals"]>("/api/signals?days=5&limit=500"),
      getJSON<Bundle["models"]>("/api/models"),
      getJSON<Bundle["predictions"][string]>("/api/predictions?target=spike_2atr&limit=50"),
      getJSON<Bundle["predictions"][string]>("/api/predictions?target=up_5d&limit=50"),
      getJSON<Bundle["correlations"]>("/api/correlations"),
      getJSON<Bundle["macro"]>("/api/macro"),
      getJSON<Bundle["meta"]["freshness"]>("/api/freshness"),
    ]);

  return {
    meta: { generated_at: new Date().toISOString(), as_of: regime?.as_of ?? null, freshness },
    regime,
    movers,
    sectors,
    signals,
    models,
    predictions: { spike_2atr: spike, up_5d: up5 },
    correlations,
    macro,
    // Histories are fetched lazily in API mode; the static bundle ships them.
    history: {},
  };
}

export async function loadHistory(symbol: string): Promise<{ date: string; close: number }[]> {
  if (MODE === "static") {
    const all = await getJSON<Bundle["history"]>(`${DATA_BASE}/history.json`);
    return all[symbol] ?? [];
  }
  return getJSON(`/api/history/${encodeURIComponent(symbol)}?days=400`);
}
