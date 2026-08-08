# Northstar Investment OS

Northstar is a self-hosted, multi-user investment operating system for EU investors.
It starts by consolidating stocks, ETFs, cash, and crypto across Trading 212, eToro,
Binance, CSV imports, and manual entries. The longer-term product expands to real
estate and other diversified investments while keeping portfolio data private,
traceable, and understandable.

The repository currently contains the application foundation and functional read-only
connectors for Trading 212, Binance Spot, and eToro. Public registration with email
verification, authentication, encrypted broker credentials, user profiles, scheduled
synchronization, manual refresh, ECB currency conversion, and the basic aggregated
dashboard are implemented. Canonical instruments now combine equivalent holdings across
brokers, while a searchable holdings view exposes consolidated stock/ETF and crypto
positions plus each platform's original detail. The Binance and eToro connectors have
automated contract coverage but still need smoke testing with real read-only accounts.
Trading 212 Crypto is supported through repeatable, deduplicated CSV imports because its
separate Crypto account has no Public API. Generic CSV/manual imports, advanced analytics,
news, and AI remain planned or scaffolded.

See [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md) for the product contract and
[NORTHSTAR_ROADMAP.md](NORTHSTAR_ROADMAP.md) for the ticket-sized implementation
roadmap.

## Structure

```text
backend/
  app/api/v1/             versioned HTTP routes
  app/services/           business workflows
  app/repositories/       user-scoped data access
  app/integrations/       broker, news, and AI adapters
  app/models/             SQLAlchemy persistence models
  app/scheduling/         periodic job entry points
  alembic/                database migrations
frontend/
  src/features/           route-level product areas
  src/api/                typed API boundary
docker-compose.yml        Postgres, migrations, API, and web server
```

## First run

Requirements: Docker with Compose.

1. Copy `.env.example` to `.env`.
2. Generate secrets (see below), replace the placeholder values, and choose an initial
   admin password.
3. Run `make up`.
4. Run `make bootstrap` once to create the initial admin.
5. Open `http://localhost:8080`.

Public signup is enabled by default. Create an account from the registration page, then
open `http://localhost:8025` to retrieve the development verification email from
Mailpit. The bootstrap admin remains useful for administration and can also create
accounts directly. Set `PUBLIC_SIGNUP_ENABLED=false` to run an invite/admin-created-only
deployment.

Production must replace the `SMTP_*` values with a real SMTP provider and set
`PUBLIC_WEB_URL` to the public HTTPS address so verification links point to the correct
host.

Generate the two required keys:

```bash
openssl rand -hex 32
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

The first value is `APP_SECRET_KEY`; the second is
`CREDENTIAL_ENCRYPTION_KEY`. On the Raspberry Pi, keep `.env` readable only by the
deployment account, use a strong `POSTGRES_PASSWORD`, set `COOKIE_SECURE=true`, and
route the Cloudflare Tunnel to port 8080.

## Runtime configuration

The main launch defaults are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PUBLIC_SIGNUP_ENABLED` | `true` | Enables self-service registration; verified email is required before login. |
| `PUBLIC_WEB_URL` | `http://localhost:8080` | Base URL used in verification links; use the public HTTPS URL in production. |
| `EMAIL_VERIFICATION_TTL_HOURS` | `24` | Lifetime of a single-use verification link. |
| `PORTFOLIO_SYNC_MINUTES` | `120` | Scheduled broker refresh interval. Keep it between 60 and 120 minutes for the initial deployment unless provider limits require a slower cadence. |
| `SCHEDULER_ENABLED` | `true` | Runs portfolio and enabled content jobs in the API process. Disable it in tests or secondary API replicas. |

The 1–2 hour interval is a freshness target, not a real-time market-data promise. Trading
212, Binance, and eToro all use the same scheduled/manual refresh workflow. Current
values retain their source currency, are converted to EUR for aggregation, and expose
their last successful synchronization time.

## Trading 212 Crypto imports

Trading 212's Public API supports Invest and Stocks ISA accounts, not its separate Crypto
account. Northstar therefore presents Trading 212 Crypto as a CSV import source:

1. In the Trading 212 Crypto account, open **Menu → History → Export**.
2. Include completed Buy, Sell, Deposit, and Withdrawal activity. Use the full available
   date range for the first import.
3. In Northstar, open **Connections**, find **Trading 212 Crypto**, and upload the CSV.
4. Upload later or overlapping exports through **Import newer CSV**; stable IDs and row
   fingerprints prevent duplicates.

The import validates before commit, reconstructs crypto quantities and moving-average EUR
cost, and values supported assets with public Binance Spot prices. If a live price is not
available, the UI explicitly reports that the last imported trade price was used.

## Development workflows

### Docker Compose (recommended)

The normal development and deployment workflow runs the entire stack in Docker:

```bash
make up
```

Docker Compose automatically:

1. starts PostgreSQL;
2. runs `alembic upgrade head` in the one-off `migrate` service;
3. starts Uvicorn in the `api` container; and
4. serves the React application through nginx on `http://localhost:8080`.

You do not need to run Alembic or Uvicorn manually when using this workflow. Rebuild
the containers after source or dependency changes:

```bash
docker compose up --build -d
```

Use `make logs` to follow the API and web logs and `make down` to stop the stack.

### Without Docker (optional)

This workflow is only for developers who intentionally want to run the backend and
frontend processes directly on the host. It requires a reachable PostgreSQL instance
and a `DATABASE_URL` in `.env` that is valid from the host machine (typically using
`localhost`, not the Docker hostname `db`).

Run the backend:

```bash
cd backend
# Python 3.10+ is supported; deployment currently uses Python 3.12.
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

In another terminal, run the frontend:

```bash
cd frontend
npm install
npm run dev
```

The Vite server proxies `/api` to `http://localhost:8000`. In this host-based workflow,
the frontend is available on Vite's development URL and backend API documentation is
available at `http://localhost:8000/docs`.

## Security decisions

- Authentication uses random opaque sessions. Only a SHA-256 digest is stored in
  Postgres; the raw token is an HTTP-only, SameSite cookie.
- Public accounts require a single-use email verification link before login. Only the
  token digest is stored, links expire after 24 hours, and resend invalidates older links.
- Passwords use Argon2 through `pwdlib`. Five failed attempts trigger a 15-minute
  account lockout. An IP-aware rate limiter should be added at the Cloudflare edge or
  API middleware before public exposure.
- Broker credentials are encrypted using AES-256-GCM with a fresh 96-bit nonce and
  authenticated context for every saved credential payload.
- Secrets are accepted only by the backend and returned only as masked hints.
- Binance is modeled as read-only and its connection UI explicitly tells users to
  disable trading, futures, and withdrawals.
- Trading 212 Crypto imports never request Trading 212 login credentials. Uploaded files
  are parsed in memory and normalized records are stored under the authenticated user.
- Every repository query taking portfolio/connection data includes the authenticated
  `user_id`. Admin APIs are separately guarded.

## Architectural notes and open decisions

- Finnhub is the default news adapter because its company-news and earnings data fit
  the requirement. It remains disabled by default and isolated behind `NewsProvider`.
  Free-tier limits should be rechecked when that implementation begins.
- OpenAI uses one app-level key and is disabled by default. Recommendation/chat output
  is designed to be cached per user and always carries a financial-advice disclaimer.
- Benchmarks remain disabled by default. The requirements propose cached Alpha Vantage
  daily ETF series as investable benchmark proxies, behind a replaceable provider
  interface and subject to rechecking current terms and limits before implementation.
- APScheduler is appropriate for one Raspberry Pi API process. If the API is later
  replicated, move jobs to a dedicated worker or use a distributed scheduler so they
  do not execute once per replica.
- Trading 212 history currently starts with the first successful sync. Binance currently
  imports trades and fees for assets held at synchronization time; deposits, withdrawals,
  income events, sold-out symbols, and resumable full-history backfill remain roadmap
  work. eToro imports the documented aggregate portfolio and closed-trade history. All
  three live connectors refresh every 1–2 hours, and eToro receives an additional
  month-end synchronization.
- ECB daily reference rates are fetched and cached in each synchronization process for
  EUR aggregation. Persisted dated FX history and fallback behavior remain roadmap work.
- XTB remains unsupported as a live API source. It will use the planned CSV/manual
  fallback unless an official supported API becomes available.
