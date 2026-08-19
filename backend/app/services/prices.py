"""Market data access.

Three providers sit behind one interface:

* ``demo``    -- deterministic synthetic prices, no network, no API key. This is
                 what lets ``docker compose up`` produce a working dashboard on a
                 fresh clone.
* ``openbb``  -- real market data via the OpenBB Platform, which itself
                 aggregates upstream sources (yfinance by default, no key
                 required; FMP/Intrinio/Polygon etc. with a key).
* ``finnhub`` -- real quotes/candles straight from Finnhub, requires
                 ``MARKET_API_KEY``.

Quotes and candles are cached in Redis because upstream providers rate-limit
hard and a dashboard polls the same handful of symbols repeatedly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import httpx
import redis

from ..config import get_settings
from ..schemas import Candle, Quote

log = logging.getLogger(__name__)
settings = get_settings()


class MarketDataError(RuntimeError):
    """Upstream market data could not be retrieved for a symbol."""


_redis: redis.Redis | None = None


def get_cache() -> redis.Redis | None:
    """Lazily connect. A dead cache must degrade to slow, never to broken."""
    global _redis
    if _redis is None:
        try:
            _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            _redis.ping()
        except redis.RedisError as exc:  # pragma: no cover - environment dependent
            log.warning("redis unavailable, running uncached: %s", exc)
            _redis = None
    return _redis


def _q(value: float) -> Decimal:
    return Decimal(f"{value:.6f}")


# --------------------------------------------------------------------------
# Demo provider
# --------------------------------------------------------------------------


def _seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)


# Approximate *present-day* price for the symbols the demo dataset uses.
# Without these, a hash-derived base puts a bond ETF at $487 and Bitcoin at
# $157 -- the maths is fine but the dashboard reads as nonsense, which defeats
# the point of a demo. Unknown symbols still fall back to the hash.
REFERENCE_PRICES: dict[str, float] = {
    "AAPL": 225.0,
    "MSFT": 420.0,
    "NVDA": 175.0,
    "GOOGL": 195.0,
    "AMZN": 220.0,
    "META": 600.0,
    "TSLA": 340.0,
    "VTI": 300.0,
    "VXUS": 72.0,
    "BND": 74.0,
    "VOO": 545.0,
    "SPY": 590.0,
    "QQQ": 510.0,
    "BTC-USD": 62000.0,
    "ETH-USD": 3000.0,
    "SOL-USD": 150.0,
}


def _demo_close(symbol: str, day: date) -> float:
    """Smooth, deterministic pseudo-price: same symbol+date always same value.

    Two sine waves of different periods plus a slow drift give something that
    looks like a price series without needing stored state.
    """
    seed = _seed(symbol)
    base = REFERENCE_PRICES.get(symbol, 20 + (seed % 480))
    t = day.toordinal()
    slow = math.sin((t + seed % 97) / 61.0) * 0.11
    fast = math.sin((t + seed % 31) / 9.0) * 0.035
    # Drift is anchored to TODAY, not a fixed past epoch, so the reference
    # price above means "roughly what it costs now" and history slopes up to
    # it. Anchoring to a past epoch instead compounds ~6%/yr onto the base and
    # leaves every demo position showing an implausible +90%.
    drift = ((t - date.today().toordinal()) / 365.0) * 0.06
    return max(0.5, base * (1 + slow + fast + drift))


class DemoProvider:
    name = "demo"

    def get_candles(self, symbol: str, start: date, end: date) -> list[Candle]:
        out: list[Candle] = []
        day = start
        while day <= end:
            if day.weekday() < 5:  # markets are closed on weekends
                close = _demo_close(symbol, day)
                prev = _demo_close(symbol, day - timedelta(days=1))
                out.append(
                    Candle(
                        date=day,
                        open=_q(prev),
                        high=_q(max(prev, close) * 1.008),
                        low=_q(min(prev, close) * 0.992),
                        close=_q(close),
                        volume=Decimal(str(500_000 + (_seed(symbol) + day.toordinal()) % 4_000_000)),
                    )
                )
            day += timedelta(days=1)
        return out

    def get_quote(self, symbol: str) -> Quote:
        today = date.today()
        close = _demo_close(symbol, today)
        prev = _demo_close(symbol, today - timedelta(days=1))
        change = close - prev
        return Quote(
            symbol=symbol,
            price=_q(close),
            change=_q(change),
            change_pct=_q((change / prev * 100) if prev else 0.0),
            as_of=today,
        )


# --------------------------------------------------------------------------
# Finnhub provider
# --------------------------------------------------------------------------


class FinnhubProvider:
    name = "finnhub"
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("MARKET_API_KEY is required when MARKET_PROVIDER=finnhub")
        self.api_key = api_key

    def _get(self, path: str, **params) -> dict:
        params["token"] = self.api_key
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{self.BASE}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    def get_quote(self, symbol: str) -> Quote:
        data = self._get("/quote", symbol=symbol)
        price = float(data.get("c") or 0)
        prev = float(data.get("pc") or 0)
        change = price - prev
        return Quote(
            symbol=symbol,
            price=_q(price),
            change=_q(change),
            change_pct=_q((change / prev * 100) if prev else 0.0),
            as_of=date.today(),
        )

    def get_candles(self, symbol: str, start: date, end: date) -> list[Candle]:
        data = self._get(
            "/stock/candle",
            symbol=symbol,
            resolution="D",
            **{
                "from": int(datetime.combine(start, time.min).timestamp()),
                "to": int(datetime.combine(end, time.min).timestamp()),
            },
        )
        if data.get("s") != "ok":
            return []
        return [
            Candle(
                date=date.fromtimestamp(ts),
                open=_q(o),
                high=_q(h),
                low=_q(low),
                close=_q(c),
                volume=Decimal(str(v)),
            )
            for ts, o, h, low, c, v in zip(
                data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
            )
        ]


# --------------------------------------------------------------------------
# OpenBB provider
# --------------------------------------------------------------------------


FIAT_SUFFIX_RE = re.compile(r"-(USD|USDT|EUR|GBP|JPY)$")


def _is_crypto(symbol: str) -> bool:
    """OpenBB routes crypto through a different namespace than equities.

    yfinance-style crypto tickers carry a fiat suffix (BTC-USD, ETH-EUR).
    `obb.equity.price.quote("BTC-USD")` does not error -- it returns a row with
    `last_price=None`, which is worse than an error because it fails silently.
    """
    return bool(FIAT_SUFFIX_RE.search(symbol.upper()))


def _f(value) -> float | None:
    """Coerce to a real float, rejecting None/NaN/inf.

    yfinance returns a bar for the *in-progress* trading day whose close is
    NaN. Left alone it propagates into Decimal and every downstream total
    becomes NaN, so every value from upstream goes through here.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _dec(value) -> Decimal | None:
    f = _f(value)
    return None if f is None else Decimal(f"{f:.6f}")


class OpenBBProvider:
    """Market data via the OpenBB Platform.

    OpenBB is an aggregator: `provider=` selects the upstream source. yfinance
    is the default because it needs no API key; set MARKET_OPENBB_PROVIDER to
    fmp/intrinio/polygon (plus that vendor's key in OpenBB's own config) for
    production-grade data.
    """

    name = "openbb"

    def __init__(self, source: str = "yfinance") -> None:
        # Imported lazily and cached on the instance: `import openbb` takes
        # ~5s and pulls in pandas/numpy. Nobody running MARKET_PROVIDER=demo
        # should pay that on every worker start.
        from openbb import obb

        self._obb = obb
        self.source = source

    # -- internals ---------------------------------------------------------

    def _historical(self, symbol: str, start: date, end: date) -> list:
        api = self._obb.crypto if _is_crypto(symbol) else self._obb.equity
        try:
            resp = api.price.historical(
                symbol, start_date=start, end_date=end, provider=self.source
            )
        except Exception as exc:  # noqa: BLE001 - OpenBB raises many types
            raise MarketDataError(f"{symbol}: {exc}") from exc
        return list(resp.results or [])

    def _clean_bars(self, rows: list) -> list[tuple[date, dict]]:
        """Drop rows whose close is unusable, and normalise the date type."""
        out: list[tuple[date, dict]] = []
        for r in rows:
            close = _f(getattr(r, "close", None))
            if close is None:
                continue
            d = getattr(r, "date", None)
            if isinstance(d, datetime):
                d = d.date()
            if not isinstance(d, date):
                continue
            # Open/high/low occasionally come back null on thin instruments;
            # falling back to close keeps the bar usable instead of dropping it.
            out.append(
                (
                    d,
                    {
                        "open": _f(getattr(r, "open", None)) or close,
                        "high": _f(getattr(r, "high", None)) or close,
                        "low": _f(getattr(r, "low", None)) or close,
                        "close": close,
                        "volume": _f(getattr(r, "volume", None)) or 0.0,
                    },
                )
            )
        out.sort(key=lambda t: t[0])
        return out

    # -- public ------------------------------------------------------------

    def get_candles(self, symbol: str, start: date, end: date) -> list[Candle]:
        bars = self._clean_bars(self._historical(symbol, start, end))
        return [
            Candle(
                date=d,
                open=Decimal(f"{v['open']:.6f}"),
                high=Decimal(f"{v['high']:.6f}"),
                low=Decimal(f"{v['low']:.6f}"),
                close=Decimal(f"{v['close']:.6f}"),
                volume=Decimal(f"{v['volume']:.2f}"),
            )
            for d, v in bars
        ]

    def get_quote(self, symbol: str) -> Quote:
        if not _is_crypto(symbol):
            quote = self._quote_from_equity_endpoint(symbol)
            if quote is not None:
                return quote
        # Crypto, or an equity whose quote endpoint came back empty: derive the
        # quote from the last two usable daily closes.
        return self._quote_from_history(symbol)

    def _quote_from_equity_endpoint(self, symbol: str) -> Quote | None:
        try:
            resp = self._obb.equity.price.quote(symbol, provider=self.source)
        except Exception as exc:  # noqa: BLE001
            log.debug("quote endpoint failed for %s, falling back: %s", symbol, exc)
            return None

        rows = list(resp.results or [])
        if not rows:
            return None

        row = rows[0]
        price = _f(getattr(row, "last_price", None))
        if price is None:
            return None

        prev = _f(getattr(row, "prev_close", None))
        # yfinance leaves change/change_percent null, so compute them.
        change = _f(getattr(row, "change", None))
        if change is None and prev is not None:
            change = price - prev
        change = change or 0.0

        pct = _f(getattr(row, "change_percent", None))
        if pct is None:
            pct = (change / prev * 100) if prev else 0.0
        elif abs(pct) < 1 and change and prev:
            # Some providers report a fraction (0.0123) rather than percent.
            pct = change / prev * 100

        return Quote(
            symbol=symbol,
            price=Decimal(f"{price:.6f}"),
            change=Decimal(f"{change:.6f}"),
            change_pct=Decimal(f"{pct:.6f}"),
            currency=getattr(row, "currency", None) or "USD",
            as_of=date.today(),
        )

    def _quote_from_history(self, symbol: str) -> Quote:
        end = date.today()
        bars = self._clean_bars(self._historical(symbol, end - timedelta(days=10), end))
        if not bars:
            raise MarketDataError(f"{symbol}: no usable price data")

        last_date, last = bars[-1]
        prev = bars[-2][1]["close"] if len(bars) > 1 else last["close"]
        change = last["close"] - prev
        return Quote(
            symbol=symbol,
            price=Decimal(f"{last['close']:.6f}"),
            change=Decimal(f"{change:.6f}"),
            change_pct=Decimal(f"{(change / prev * 100) if prev else 0:.6f}"),
            as_of=last_date,
        )


def build_provider():
    if settings.market_provider == "openbb":
        return OpenBBProvider(settings.market_openbb_provider)
    if settings.market_provider == "finnhub":
        return FinnhubProvider(settings.market_api_key)
    return DemoProvider()


_provider = None


def provider():
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider


# --------------------------------------------------------------------------
# Cached public API
# --------------------------------------------------------------------------


def get_quote(symbol: str) -> Quote:
    symbol = symbol.upper()
    cache = get_cache()
    key = f"quote:{provider().name}:{symbol}"
    if cache:
        try:
            if cached := cache.get(key):
                return Quote(**json.loads(cached))
        except redis.RedisError:
            pass

    quote = provider().get_quote(symbol)

    if cache:
        try:
            cache.setex(key, settings.quote_cache_seconds, quote.model_dump_json())
        except redis.RedisError:
            pass
    return quote


def get_quotes(symbols: list[str]) -> dict[str, Quote]:
    """Best-effort batch fetch.

    Symbols that fail are OMITTED rather than raising: with live upstream data
    one delisted or mistyped ticker must not take down the whole portfolio
    summary. Callers decide how to present a missing quote.
    """
    out: dict[str, Quote] = {}
    for symbol in dict.fromkeys(s.upper() for s in symbols):
        try:
            out[symbol] = get_quote(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("no quote for %s: %s", symbol, exc)
    return out


def get_candles(symbol: str, start: date, end: date) -> list[Candle]:
    """Candles are cached too -- an OpenBB call is a network round trip, and
    the performance chart asks for one window per held symbol."""
    symbol = symbol.upper()
    cache = get_cache()
    key = f"candles:{provider().name}:{symbol}:{start}:{end}"

    if cache:
        try:
            if cached := cache.get(key):
                return [Candle(**c) for c in json.loads(cached)]
        except redis.RedisError:
            pass

    candles = provider().get_candles(symbol, start, end)

    if cache and candles:
        try:
            cache.setex(
                key,
                settings.candle_cache_seconds,
                json.dumps([json.loads(c.model_dump_json()) for c in candles]),
            )
        except redis.RedisError:
            pass
    return candles
