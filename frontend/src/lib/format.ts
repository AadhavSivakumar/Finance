// The API sends Decimals as strings so no precision is lost in JSON. Parse to
// Number only at the display/plot boundary, never before arithmetic that
// matters -- all money math happens server-side in Decimal.
export const num = (v: string | number | null | undefined): number =>
  v === null || v === undefined ? 0 : typeof v === "number" ? v : Number(v);

const currencyFmt = (currency: string, maximumFractionDigits: number) =>
  new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits,
    minimumFractionDigits: maximumFractionDigits,
  });

export function money(v: string | number | null | undefined, currency = "USD"): string {
  return currencyFmt(currency, 2).format(num(v));
}

export function money0(v: string | number | null | undefined, currency = "USD"): string {
  return currencyFmt(currency, 0).format(num(v));
}

/** Axis-friendly: $1.2M, $340K. */
export function compactMoney(v: string | number, currency = "USD"): string {
  const n = num(v);
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  const symbol = currency === "USD" ? "$" : "";
  if (abs >= 1_000_000_000) return `${sign}${symbol}${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}${symbol}${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}${symbol}${Math.round(abs / 1_000)}K`;
  return `${sign}${symbol}${abs.toFixed(0)}`;
}

export function pct(v: string | number | null | undefined, digits = 1): string {
  const n = num(v);
  return `${n >= 0 ? "" : ""}${n.toFixed(digits)}%`;
}

export function signedPct(v: string | number | null | undefined, digits = 1): string {
  const n = num(v);
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

export function signedMoney(v: string | number, currency = "USD"): string {
  const n = num(v);
  return `${n > 0 ? "+" : ""}${money(n, currency)}`;
}

export function qty(v: string | number): string {
  const n = num(v);
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 }).format(n);
}

/** "2026-03" -> "Mar 26" for month axes. */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-");
  const d = new Date(Number(y), Number(m) - 1, 1);
  return `${d.toLocaleString(undefined, { month: "short" })} ${y.slice(2)}`;
}

/** ISO date -> "Mar 4" for daily axes. */
export function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleString(undefined, { month: "short", day: "numeric" });
}

export function fullDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export const direction = (v: string | number): "up" | "down" | "flat" => {
  const n = num(v);
  return n > 0 ? "up" : n < 0 ? "down" : "flat";
};
