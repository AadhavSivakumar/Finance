# Finance Dashboard

Portfolio tracking and business finance metrics in one dashboard.

- **Portfolio** — holdings derived from a transaction log, average-cost basis,
  unrealized/realized P&L, allocation, and daily revaluation over time.
- **Business** — MRR/ARR, recognized revenue vs expenses, net burn, runway,
  gross margin, and expense breakdown.
- **Market** — quotes and price history for a watchlist.

FastAPI + Postgres + Redis on the back, React + Vite on the front, all in
Docker.

> New to Docker, or want the full dev→deploy walkthrough? **[DOCKER.md](DOCKER.md)**
> explains every file in this repo and the path to a live VPS.

---

## Quick start

```bash
cp .env.example .env
docker compose up
```

| URL | What |
|---|---|
| http://localhost:5173 | Dashboard |
| http://localhost:8000/api/docs | API docs (Swagger) |
| http://localhost:8000/health/ready | Readiness probe |

If another project already owns one of those ports, set `WEB_PORT` / `API_PORT`
in `.env` — only the host side of a port mapping can collide, and nothing
inside the stack changes.

A demo dataset loads on first start. Reload it any time with:

```bash
docker compose exec api python -m app.seed
```

### Prerequisites

Docker Engine and the Compose v2 plugin:

```bash
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER    # then log out and back in
```

---

## Market data

Three interchangeable providers, selected with `MARKET_PROVIDER`:

| Provider | Needs | Notes |
|---|---|---|
| `openbb` | nothing (yfinance) | **Default in `.env.example`.** Real quotes and history via the [OpenBB Platform](https://openbb.co). |
| `demo` | nothing | Deterministic synthetic prices. Offline, no network calls. The code default. |
| `finnhub` | free API key | Straight to Finnhub. |

### OpenBB

OpenBB is an aggregator — `MARKET_OPENBB_PROVIDER` picks the upstream source:

```
MARKET_PROVIDER=openbb
MARKET_OPENBB_PROVIDER=yfinance     # no key; fmp/intrinio/polygon need one
```

Three things worth knowing before you commit to it:

- **It is heavy.** ~317MB installed, taking the api image from ~330MB to
  ~753MB, and ~5s to import. The import is lazy, so `MARKET_PROVIDER=demo`
  never pays it. Drop `openbb` from `requirements.txt` if you don't want it.
- **It pins your web stack.** `openbb-core` hard-pins `fastapi==0.136.3` and
  `uvicorn>=0.40,<0.41`, so those versions are dictated by OpenBB, not chosen.
- **It needs a writable `HOME`.** It writes `~/.openbb_platform` at import and
  has no env var to relocate it, so both compose files set `HOME=/tmp`. Without
  that, the production overlay's `read_only: true` fails at import.

Quirks the provider layer handles for you: yfinance returns a bar for the
in-progress trading day with `close=NaN` (filtered out), leaves
`change`/`change_percent` null (computed from `prev_close`), and returns
`last_price=None` for crypto via the equity endpoint (crypto is routed to
`obb.crypto.price.historical` instead).

### Caching and failure behaviour

Quotes cache in Redis for 60s, daily candles for 1h — a 180-day performance
query drops from ~1.7s to ~0.03s warm. If Redis is down the app degrades to
uncached rather than failing.

A symbol that cannot be priced is **omitted** rather than fatal: the portfolio
summary values that position at average cost and flags it `has_quote: false`,
so one delisted ticker cannot take down the whole page.

---

## Layout

```
backend/                FastAPI service
  app/
    config.py           env-driven settings
    models.py           SQLAlchemy tables
    schemas.py          Pydantic request/response models
    routers/            HTTP endpoints (health, portfolios, market, business)
    services/
      prices.py         market data providers + Redis cache
      portfolio_calc.py holdings, P&L, allocation, performance
      business_metrics.py  MRR, burn, runway, margin
    seed.py             demo dataset
  alembic/              versioned migrations
  Dockerfile            multi-stage; commented line by line
  docker-entrypoint.sh  wait for DB → migrate → exec the app

frontend/               React + Vite dashboard
  src/
    components/         ChartCard (with table twin), StatTile, chart tokens
    pages/              Portfolio, Business, Market
    lib/                API client, formatting, fetch hook
  Dockerfile            deps → dev / build → nginx
  nginx.conf            static serving + /api proxy

docker-compose.yml      development stack
docker-compose.prod.yml production overlay (TLS, hardening, limits)
deploy/Caddyfile        automatic HTTPS
DOCKER.md               the walkthrough
```

---

## Accounting conventions

Stated up front because tools differ and silent differences are the worst kind:

- **Cost basis** uses the **average cost** method. Holdings are derived from
  the transaction log, never stored — one source of truth.
- **Portfolio performance** is a point-in-time revaluation at daily closes. It
  includes contributions and withdrawals, so it answers "what is this worth",
  not "how good is my stock picking" (that would be time-weighted return).
- **MRR** counts recurring revenue only. Annual contracts contribute
  `amount / 12`; one-time revenue contributes nothing.
- **Recognized revenue** is accrual: monthly streams recognize fully each active
  month, annual streams amortize over 12, one-time lands in its start month.
- **Gross margin** treats a fixed set of expense categories as cost of revenue
  (hosting, infrastructure, cloud, payment processing, support, cogs) — see
  `COGS_CATEGORIES` in `backend/app/services/business_metrics.py`.
- **Runway** = latest cash snapshot ÷ current net burn. Infinite when
  profitable.
- Single currency per portfolio. **No FX conversion** — mixing currencies in
  one portfolio will produce wrong totals.
- Money is `Decimal` end to end and serialized as JSON strings, so no precision
  is lost in transit.

---

## Development

Both services hot-reload from bind mounts; edits on the host take effect
immediately. Rebuild only when dependencies or a Dockerfile change:

```bash
docker compose up --build
```

```bash
# migrations
docker compose exec api alembic revision --autogenerate -m "describe change"
docker compose exec api alembic upgrade head

# database shell
docker compose exec db psql -U finance finance

# frontend typecheck
docker compose exec web npm run typecheck
```

---

## Deploying

See [DOCKER.md §14](DOCKER.md#14-deploying-to-a-vps). In short:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml push
# on the server, with .env and DOMAIN set:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Security notes

This ships with **no authentication** — it assumes a single trusted user behind
TLS. Before putting real financial data on a public domain, add auth (an OAuth
proxy in front of Caddy is the least invasive option) and change every default
credential in `.env`.
