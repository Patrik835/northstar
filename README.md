# Northstar Investment OS

Northstar is a self-hosted, multi-user investment operating system for EU investors.
It starts by consolidating stocks, ETFs, cash, and crypto across Trading 212, eToro,
Binance, Bybit EU, Interactive Brokers, and provider-native imports from XTB, Trade Republic,
Scalable Capital, and Trading 212 Crypto. The longer-term
product expands to manually valued real estate and other diversified investments while
keeping portfolio data private, traceable, and understandable.

The repository currently contains the application foundation and functional read-only
connectors for Trading 212, Binance Spot, Bybit EU, eToro, and Interactive Brokers. Public
registration with email verification, authentication, encrypted and replaceable broker
credentials, user profiles, scheduled and manual refresh, persisted ECB currency
conversion, observable synchronization runs,
rate-limit-aware retry/backoff, visible connection freshness, and
the aggregated analytics dashboard are implemented. Canonical instruments combine equivalent holdings across
brokers, while searchable Holdings and Activity views expose consolidated stock/ETF and
crypto positions, provider-first open P/L, non-tax average-cost realized results, explicit
history coverage, source detail, and filterable portfolio events. The overview includes a
responsive total-value/invested-amount chart. Observed snapshots are used where available;
older ranges can be explicitly labelled as reconstructed estimates from imported trades,
cached weekly market prices, and dated FX rates.
The dedicated Analytics workspace adds allocation drill-downs, current P/L leaders and
contribution, configurable ETF comparison, risk/concentration measures, and educational
allocation targets without crowding Overview. Sector and geography use verified metadata
first, followed by conservative local mappings for known instruments and identifiers.
Holdings, transactions, imported income, and selected-range performance can be downloaded
as authenticated CSV files directly from their relevant pages.
All live connectors have automated contract coverage; Binance and eToro also have
successful real read-only account smoke tests. Interactive Brokers still needs an
equivalent real-account smoke test.
Trading 212 Crypto, Trade Republic, and Scalable Capital are supported through repeatable,
deduplicated native file imports where a safe supported retail investment API is unavailable.
Provider metadata coverage, advanced return attribution, real estate, and broader market
coverage remain planned or progressive. News, alerts, optional digests, cached grounded
reviews, and tenant-scoped portfolio chat are implemented behind provider feature flags.

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

Provider integrations use a shared normalized contract and metadata-driven registry.
See [docs/CONNECTORS.md](docs/CONNECTORS.md) before adding a live API connector or
provider-native statement import; new providers should not add broker-name branches to
generic synchronization services or React pages.

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
| `PASSWORD_RESET_TTL_MINUTES` | `60` | Lifetime of a single-use password recovery link. A successful reset revokes all sessions. |
| `AUTH_LOGIN_IP_LIMIT` / `AUTH_LOGIN_ACCOUNT_LIMIT` | `30` / `10` | Login attempts allowed per rolling rate-limit window. Identifiers are stored only as keyed hashes. |
| `AUTH_REGISTRATION_IP_LIMIT` | `5` | Registrations allowed per IP each hour. |
| `AUTH_EMAIL_IP_LIMIT` / `AUTH_EMAIL_ACCOUNT_LIMIT` | `10` / `3` | Verification/recovery emails allowed per IP/account each hour. |
| `PORTFOLIO_SYNC_MINUTES` | `120` | Scheduled broker refresh interval. Keep it between 60 and 120 minutes for the initial deployment unless provider limits require a slower cadence. |
| `SCHEDULER_ENABLED` | `true` | Runs portfolio and enabled content jobs in the API process. Disable it in tests or secondary API replicas. |
| `NEWS_ENABLED` / `FINNHUB_API_KEY` | `false` / empty | Enables daily held-ticker news and earnings ingestion. Dividend dates appear when the Finnhub subscription exposes that endpoint. |
| `NEWS_BRIEF_CANDIDATE_LIMIT` | `300` | Maximum deduplicated articles from the last 24 hours considered for each cached portfolio news brief. |
| `AI_ENABLED` / `OPENAI_API_KEY` | `false` / empty | Enables cached portfolio reviews and the portfolio assistant. Portfolio calculations remain local and deterministic. |
| `OPENAI_MODEL` | `gpt-5.6-terra` | Responses API model used for concise reviews and chat. Existing deployments can choose another supported text model. |
| `AI_DAILY_REVIEW_LIMIT` / `AI_DAILY_MESSAGE_LIMIT` | `3` / `30` | Per-user safeguards against accidental or abusive AI usage. |
| `ALPHA_VANTAGE_KEY` | empty | Enables cached weekly stock/ETF prices for reconstructed portfolio history. The backfill is paced and resumes daily within the free allowance. |
| `BENCHMARKS_ENABLED` | `true` | Reports benchmark capability through the feature-status endpoint. Comparison still requires a cached ETF and Alpha Vantage data. |
| `LOG_FORMAT` | `text` | Use `json` in production for structured request and job logs. |
| `MONITORING_TOKEN` | empty | Enables the Prometheus-format `/api/v1/metrics` endpoint when set; send it as a Bearer token. |
| `BACKUP_DIRECTORY` | `./backups` | Host directory receiving verified PostgreSQL custom-format archives. Keep an off-host copy. |
| `BACKUP_INTERVAL_SECONDS` / `BACKUP_RETENTION_DAYS` | `86400` / `14` | Backup frequency and local retention. |

The 1–2 hour interval is a freshness target, not a real-time market-data promise. Trading
212, Binance, and eToro use that scheduled/manual refresh workflow. Interactive
Brokers Activity Flex data refreshes once daily, so it has a daily 05:30 UTC job and a
48-hour stale threshold instead of wasteful intraday polling. Safe provider
reads retry short-lived network, `429`, and `5xx` failures with bounded exponential
backoff and honor provider cooldown headers. Long cooldowns are left for the next
scheduled run so one throttled account cannot hold up the rest. Current values retain
their source currency, are converted to EUR for aggregation, and connection cards show
fresh/stale state plus the last successful synchronization. Intraday connections are stale
after 24 hours without a successful refresh; Interactive Brokers becomes stale after 48
hours, and file imports do not age against a live schedule.

## CSV exports

- **Holdings:** use **Export CSV** on Holdings. The download follows the selected asset
  group, source, and instrument search.
- **Transactions and income:** use the two download actions on Activity. Both follow the
  selected source, date range, and search; the transaction export also follows the
  Buy/Sell or Dividend filter.
- **Performance:** use **Export CSV** beside the Overview history range controls. The file
  contains the same selected 1W–all period plus its return and attribution coverage.

Exports require a signed-in session, are not cached by the browser, preserve source and
EUR fields, and open cleanly in common spreadsheet applications.

## Account recovery and privacy controls

The sign-in screen links to email-based password recovery. Reset responses do not reveal
whether an address is registered; links expire, can be used once, and a successful reset
signs the account out everywhere. Login, registration, resend, and recovery endpoints are
also throttled by IP and, where applicable, by normalized account identifier.

Signed-in users can open **Settings → Your data** to download a JSON archive after entering
their current password. The archive includes user-owned portfolio and activity data but
never password hashes, session/reset tokens, encrypted broker credentials, or internal
provider error details. Permanent deletion is in the collapsed danger zone and requires the
password plus an exact `DELETE` confirmation. The sole active administrator cannot delete
their account until another administrator exists.

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

## XTB imports

XTB [discontinued its public API on 14 March 2025](https://intercom-help.eu/xtb/en/articles/3868-does-xtb-offer-investment-automation-tools),
so Northstar uses xStation's native reports without asking for login credentials:

1. Sign in to xStation on the web and export the current **Open positions** report from
   the Orders view.
2. Export the full available **Closed positions** and **Cash operations** history.
3. In Northstar, open **Connections → XTB** and select the CSV or XLSX reports together.
4. Import newer or overlapping reports later; provider IDs and stable fingerprints prevent
   duplicate activity.

Current reports populate stock/ETF quantities, average prices, values, explicit cash
balances, broker-reported P/L, valuation dates, and canonical ISIN/symbol aliases. History
reports add buys, sells, dividends, deposits, withdrawals, and fees where the export exposes
them. Uploading history alone never clears the last current holdings. XTB documents its
[open-position report](https://www.xtb.com/int/help-center/our-platforms-5-1/open-positions-and-pending-orders-1)
and [account-history export](https://www.xtb.com/en/help-center/our-platforms/history-on-the-xstation-platform);
the parser accepts both current CSV and Excel variants, discovers the relevant sheet, and
works around the incorrect `A1:A1` dimensions present in native XTB workbooks. CFDs and
other non-stock/ETF rows are skipped with a visible warning.

## Trade Republic and Scalable Capital imports

Northstar accepts each broker's native transaction CSV without asking for login details,
PINs, or browser-session access:

- **Trade Republic:** open **Profile → Statements → Transaction export**, choose the full
  available period, and upload the resulting CSV from **Connections → Trade Republic**.
- **Scalable Capital:** open **Broker → Transactions**, select all transactions, choose
  **Export CSV**, and upload it from **Connections → Scalable Capital**.

Imports retain trades, dividends/distributions, fees and taxes, rebuild open quantities and
moving-average cost, and use ISINs to combine the same security across brokers. Re-importing
an overlapping file is safe. Because these transaction exports do not contain a live
positions valuation, current value and open P/L use the latest imported trade price and are
clearly marked as estimated. Import a newer full-history CSV to refresh the estimate.

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

### Backups, restore testing, and monitoring

The Compose `backup` service creates a PostgreSQL custom-format archive immediately on
startup and then daily. Each archive is checked with `pg_restore --list` before it is made
visible, and old local archives are removed after the configured retention period.

```bash
make backup
BACKUP_FILE=northstar-YYYYMMDDTHHMMSSZ.dump make restore-test
```

`restore-test` verifies an archive by restoring it into a disposable
`northstar_restore_test` database and then removes that database. For an intentional real
restore, stop the API and scheduler, take one final backup, then run the guarded restore:

```bash
docker compose stop api
docker compose run --rm --entrypoint /usr/local/bin/northstar-restore \
  -e RESTORE_CONFIRM=investing backup /backups/northstar-YYYYMMDDTHHMMSSZ.dump
docker compose up -d api web
```

The restore refuses to run unless `RESTORE_CONFIRM` exactly matches `PGDATABASE`.
Practice this procedure and copy archives to encrypted
off-host storage; a backup that exists only on the application host does not protect
against disk or host loss.

The API exposes unauthenticated liveness at `/api/v1/health` and database readiness at
`/api/v1/health/ready`. When `MONITORING_TOKEN` is configured, `/api/v1/metrics` returns
Prometheus-format API, scheduled-job, connector-run, and backup-age metrics only for
`Authorization: Bearer <token>`. Administrators can inspect recent job and connector
failures in **Admin → Operations**. Production should use `LOG_FORMAT=json` and alert on
readiness failure, failed jobs/syncs, and backup age above `BACKUP_MAX_AGE_HOURS`.

### Automated checks

GitHub Actions runs backend lint/tests/dependency audit, upgrade/downgrade migration checks,
frontend lint/build/dependency audit, and the Docker-based release flow. The Playwright
suite runs in desktop Chromium and a mobile viewport, exercises registration through
account deletion against real API/email/database containers, and checks public auth pages
for serious or critical accessibility violations.

For local checks:

```bash
make test
make lint
cd frontend && npx playwright install chromium
make e2e
```

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
  account lockout. Database-backed IP/account throttles protect login, registration, and
  email-token endpoints; nginx replaces untrusted forwarding chains with its direct client
  address. Keep the origin private behind Cloudflare and add edge throttling as a second
  layer for the public deployment.
- Password recovery uses a hashed, expiring, single-use token and revokes all sessions.
  Recovery requests return the same response for registered and unknown addresses.
- Broker credentials are encrypted using AES-256-GCM with a fresh 96-bit nonce and
  authenticated context for every saved credential payload.
- Reconnect accepts a complete new credential set, validates it with the provider before
  replacement, and immediately synchronizes the existing connection. Saved secret values
  are never returned to or prefilled in the browser.
- Secrets are accepted only by the backend and returned only as masked hints.
- Binance and Bybit EU are modeled as read-only, and their connection guides explicitly
  tell users to disable trading and withdrawals. Interactive Brokers uses a reporting-only
  Flex token and never asks for the account password.
- Trading 212 Crypto, Trade Republic, and Scalable Capital imports never request broker
  login credentials. Uploaded files are parsed in memory and normalized records are stored
  under the authenticated user. The legacy Bybit statement endpoint remains available only
  for compatibility with earlier deployments.
- Every repository query taking portfolio/connection data includes the authenticated
  `user_id`. Admin APIs are separately guarded.

## Architectural notes and open decisions

- Finnhub is the feature-flagged news/calendar adapter. A daily job deduplicates company
  news and earnings for held tickers and links each item only to relevant users. Dividend
  dates are imported when the configured Finnhub plan exposes its dividend endpoint. When
  AI is enabled, a tenant-scoped daily brief ranks the ten most important linked articles
  and summarizes the three largest portfolio developments from the last 24 hours.
- OpenAI uses one server-side application key and remains optional. The Responses API is
  called with provider storage disabled and a privacy-preserving user safety identifier.
  Reviews are context-hash cached; chat is tenant-scoped, streamed, usage-limited, and
  moderated. Only a redacted versioned snapshot of deterministic portfolio calculations is
  sent for reviews and chat, and every generated explanation carries an informational-only
  disclaimer. News briefing uses a separate minimized context containing every aggregated
  holding's symbol, name, asset type, and portfolio weight plus linked 24-hour news. It never
  includes credentials, account IDs, quantities, notes, or absolute portfolio values, and
  identical daily inputs reuse the stored result.
- Alpha Vantage weekly stock/ETF and USD/EUR series are stored in a durable cache for
  reconstructed pre-snapshot history. Requests are paced, largest holdings are filled
  first, and unfinished coverage resumes on later daily runs within the free allowance.
  Reconstructed chart periods are identified as estimates. The same paced cache now
  enriches company sector/country metadata and powers the configurable ETF comparison.
  A deterministic local resolver covers known symbols, industry terms, ETF mandates, and
  ISIN country codes while leaving uncertain instruments unclassified.
- APScheduler is appropriate for one Raspberry Pi API process. If the API is later
  replicated, move jobs to a dedicated worker or use a distributed scheduler so they
  do not execute once per replica.
- Trading 212 backfills orders/fills, dividends, and cash movements through the official
  continuation paths. Per-stream cursors are committed with each page, so an interrupted
  backfill resumes without duplicating stored activity. Each run reads the newest page
  plus at most five older pages per stream to stay inside provider limits. Binance imports
  discoverable Spot trades, trade and withdrawal fees, completed deposits and withdrawals,
  and positive asset distributions. A versioned marker gives existing connections one
  initial activity backfill before overlap-safe incremental syncs. Binance requires a symbol
  for Spot trade history, so a fully sold-out asset with no current balance, transfer, or
  income record cannot yet be discovered automatically. Binance `LDUSDC` Earn balances are
  valued through USDC and consolidated under canonical USDC. eToro imports the documented
  aggregate portfolio, enriches holdings and snapshots with broker-reported P&L from the
  Real-account P&L endpoint, and imports current/historical opening activity plus closed-trade
  exits. The official API does not expose dividend-ledger activity. Reported P&L is retained in
  its provider currency and converted to EUR without presenting it as an app-calculated
  return. All
  five intraday live connectors refresh every 1–2 hours, eToro receives an additional
  month-end synchronization, and Interactive Brokers Activity Flex refreshes daily.
- ECB daily reference rates are fetched and cached in each synchronization process for
  EUR aggregation, persisted by ECB publication date, and reused across processes. A
  daily 16:30 UTC job refreshes the cache; broker syncs fall back to the newest stored
  working-day rates when the ECB is temporarily unavailable.
- Every live broker refresh stores a sync run before contacting the provider and finishes
  it as `success`, `partial`, or `error`. Counts, trigger (`initial`, `manual`, or
  `scheduled`), timestamps, and bounded user-safe error details are available from
  `GET /api/v1/connections/{connection_id}/sync-runs`.
- Trading 212, eToro, and Interactive Brokers position totals are silently checked
  against the independently reported provider account total after each successful refresh. Differences must exceed
  both 3% and EUR 5 before the connection and Holdings page show a warning. Binance is
  excluded because its snapshot total is calculated from the same imported balances.
- Transient safe provider reads use at most three attempts with exponential backoff.
  Standard `Retry-After`, Trading 212 reset timestamps, Binance's `418`/`429`, and
  Interactive Brokers Flex pacing errors are handled without exposing
  provider response bodies to users.
- XTB is a manual native-report source because its API is discontinued. CSV/XLSX imports
  retain the report valuation time and are not included in automatic **Sync all** runs.
- Bybit EU uses the official V5 API with a system-generated HMAC key. Northstar requires a
  read-only key, synchronizes Unified and Funding balances plus recent Spot activity, and
  includes it in **Sync all**. The old CSV/XLSX endpoint is retained only for compatibility.
- Trade Republic and Scalable Capital are native transaction-CSV sources. They are excluded
  from automatic **Sync all** runs and show last-trade valuations as estimates.
