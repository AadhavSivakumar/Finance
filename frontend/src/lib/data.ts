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

/**
 * Headlines refresh far more often than the dashboard rebuilds, so in static
 * mode they are fetched from the `data` branch rather than the published Pages
 * bundle. raw.githubusercontent.com serves `access-control-allow-origin: *`
 * with a 5-minute cache, which matches the news job's cadence exactly.
 *
 * Falls back to whatever shipped in the bundle if that request fails, so a
 * missing branch degrades to slightly stale news rather than an empty panel.
 */
const NEWS_URL =
  import.meta.env.VITE_NEWS_URL ??
  "https://raw.githubusercontent.com/AadhavSivakumar/Finance/data/news.json";

export async function loadNews(): Promise<{ items: unknown[]; generated_at: string } | null> {
  const url = MODE === "static" ? NEWS_URL : "/api/news";
  try {
    const res = await fetch(bust(url), { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const body = await res.json();
    // The API returns a bare array; the static file wraps it with metadata.
    return Array.isArray(body) ? { items: body, generated_at: "" } : body;
  } catch {
    return null;
  }
}

/**
 * Cache-buster with a coarse time bucket.
 *
 * GitHub Pages serves the bundle with `cache-control: max-age=600`, and a
 * browser that keeps a tab open will happily reuse a copy for the full ten
 * minutes after a new build lands. A bucket that changes every five minutes
 * makes the URL -- and therefore the cache key -- roll over on that cadence,
 * while still letting the CDN and browser reuse the response inside a bucket.
 * `Date.now()` on every request would defeat caching entirely.
 */
function bust(url: string): string {
  const bucket = Math.floor(Date.now() / (5 * 60 * 1000));
  return `${url}${url.includes("?") ? "&" : "?"}v=${bucket}`;
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(bust(url), { headers: { Accept: "application/json" } });
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

  const [regime, movers, sectors, signals, models, correlations, macro, freshness] =
    await Promise.all([
      getJSON<Bundle["regime"]>("/api/regime"),
      getJSON<Bundle["movers"]>("/api/movers"),
      getJSON<Bundle["sectors"]>("/api/sectors"),
      getJSON<Bundle["signals"]>("/api/signals?days=5&limit=500"),
      getJSON<Bundle["models"]>("/api/models"),
      getJSON<Bundle["correlations"]>("/api/correlations"),
      getJSON<Bundle["macro"]>("/api/macro"),
      getJSON<Bundle["meta"]["freshness"]>("/api/freshness"),
    ]);

  // Every prediction target the API knows about. Kept as one list so the
  // API-mode fetch cannot drift from what the static bundle publishes.
  const TARGETS = ["spike_2atr", "absmove_2atr", "up_5d"] as const;
  const tr = (t: string) =>
    getJSON<NonNullable<Bundle["track_record"]>[string]>(`/api/track-record?target=${t}`).catch(() => undefined);
  const pr = (t: string) =>
    getJSON<Bundle["predictions"][string]>(`/api/predictions?target=${t}&limit=50`).catch(() => []);

  const [news, metrics, trackRecords, predictionSets] = await Promise.all([
    getJSON<Bundle["news"]>("/api/news?limit=80").catch(() => []),
    getJSON<Bundle["metrics"]>("/api/metrics").catch(() => []),
    Promise.all(TARGETS.map(tr)),
    Promise.all(TARGETS.map(pr)),
  ]);

  return {
    meta: { generated_at: new Date().toISOString(), as_of: regime?.as_of ?? null, freshness },
    regime,
    movers,
    sectors,
    signals,
    models,
    predictions: Object.fromEntries(TARGETS.map((t, i) => [t, predictionSets[i]])),
    correlations,
    macro,
    news,
    metrics,
    track_record: Object.fromEntries(
      TARGETS.map((t, i) => [t, trackRecords[i]]).filter(([, v]) => v !== undefined),
    ),
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
