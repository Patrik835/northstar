# Northstar Investment OS — Product and Technical Requirements

> Last reviewed: 2026-08-08

> Detailed implementation backlog: [NORTHSTAR_ROADMAP.md](NORTHSTAR_ROADMAP.md)

## 1. Product Vision

Northstar is a private-by-design, EU-focused investment operating system for people
whose wealth is spread across brokers, exchanges, currencies, and asset classes. It
must give each user one trustworthy view of what they own, how it is performing, where
their risk is concentrated, and what needs attention.

The product begins with stocks, ETFs, cash, and crypto because reliable automated data
is the foundation for every later feature. It then expands to real estate, bonds,
pensions, private investments, commodities, precious metals, collectibles, and other
manually valued assets. Northstar is an investment product, not a trading terminal or
an everyday budgeting application.

Initial deployment is self-hosted for Patrik and early users on a Raspberry Pi, but the
application is a general-purpose public product. Architecture, security, data ownership,
and APIs must support a later move to managed cloud infrastructure without a rewrite.

### 1.1 Target Users

- EU-based self-directed investors with assets held across several platforms.
- Users who want an EUR-denominated consolidated view while retaining original-currency
  values.
- Investors who care about long-term performance, income, allocation, and diversification
  more than intraday trading.
- Initial family users, followed by public users who register and verify their email.

### 1.2 Product Promise

- **Complete:** supported APIs and carefully selected provider-native imports cover the
  automated portfolio; purpose-built manual workflows later cover assets such as property.
- **Trustworthy:** values are traceable to a source, calculations are deterministic, and
  stale, missing, estimated, or partially imported data is clearly labelled.
- **Current:** automated accounts refresh every 1–2 hours at launch, support manual
  refresh, and display the time of the last successful sync.
- **Comparable:** original values are retained and normalized to EUR using dated FX rates.
- **Explainable:** AI may explain verified portfolio calculations but never invent or
  replace them.
- **Secure:** integrations are read-only, credentials are encrypted, and all portfolio
  access is strictly tenant-scoped.

## 2. Scope and Phased Roadmap

The detailed Kanban breakdown lives in `NORTHSTAR_ROADMAP.md`. This section defines the
required outcome of each product phase.

### Phase 0 — Application Foundation (current baseline)

- Versioned FastAPI backend, React web app, PostgreSQL, Alembic migrations, Docker
  deployment, and scheduled-job infrastructure.
- Public registration with email verification, login sessions, password changes,
  account lockout, and admin account management.
- Tenant-scoped data access and encrypted broker credentials.
- Connector interface and core portfolio entities.
- Trading 212 connection and initial portfolio synchronization.

### Phase 1 — Trustworthy Stock, ETF, and Crypto Core

- Production-ready Trading 212, Binance Spot, and eToro read-only connections.
- Periodic position/value synchronization every 60–120 minutes, defaulting to 120
  minutes, plus user-triggered refresh.
- Current eToro positions, cash, value, and broker-reported P&L plus retained month-end snapshots.
- Canonical instruments so the same holding is aggregated correctly across sources.
- Dated ECB FX rates and EUR conversion while preserving original currencies.
- Complete, resumable transaction imports with automatic deduplication and reconciliation.
- Provider-specific CSV import only where a valuable account cannot be connected through
  an official supported API, initially Trading 212 Crypto.
- Visible freshness, sync progress, partial-import warnings, and safe error recovery.

### Phase 2 — Portfolio Analytics and Dashboard

- Searchable holdings and unified transaction/activity views.
- Consolidated daily portfolio history and 1M/3M/6M/1Y/all chart ranges.
- Net contributions, realized/unrealized gain, dividends, fees, currency effects, total
  return, time-weighted return, and money-weighted return/XIRR.
- Allocation by asset type, holding, broker, currency, sector, and geography.
- Performance contribution, drawdown, volatility, concentration, and diversification.
- Dividend history, yield, income calendar, and projected income.
- Cached benchmark comparison using configurable investable ETF proxies.
- Target allocation, drift reporting, and educational rebalancing calculations.
- CSV exports for holdings, transactions, income, and performance.

### Phase 3 — News, Alerts, and Grounded AI

- Holding-specific company news, earnings, and dividend calendar events.
- In-app and optional email alerts for sync failures, stale data, allocation drift, and
  upcoming portfolio events.
- Cached AI portfolio reviews built only from deterministic analytics.
- Portfolio-aware chat with persisted, user-owned conversation history.
- Clear source timestamps, usage limits, redaction, prompt-injection defenses, and a
  prominent informational-only/not-financial-advice disclaimer.

### Phase 4 — Diversified Investment OS

- Generic manually valued assets with ownership share, valuation history, income,
  expenses, liabilities, notes, and documents.
- Real estate with purchase value, current valuation, rent, costs, mortgage balance,
  and calculated equity.
- Bonds, savings products, pensions, private equity, commodities, precious metals,
  collectibles, and other custom investments.
- Crypto wallets, staking, Earn products, and later DeFi integrations.

### Future Platform Phases

- Multiple named portfolios per user, followed by permissioned household aggregation.
- Country-pluggable European tax modules after transaction and tax-lot data is mature.
- Mobile clients consuming the same versioned backend.
- Regulated EU account-aggregation providers and additional broker connectors.
- Cloud deployment and dedicated background workers when a single Raspberry Pi process
  is no longer sufficient.

## 3. Explicit Non-Goals

The following are intentionally outside the initial stock/ETF/crypto product:

- Placing, changing, or cancelling trades, orders, transfers, or withdrawals.
- Automatic portfolio rebalancing or autonomous investment decisions.
- Intraday or streaming market-data guarantees; launch freshness is 1–2 hours.
- Everyday banking, expense tracking, household budgeting, or bill payment.
- Jurisdiction-specific tax calculations or claims that reports are tax-ready.
- Multiple portfolios, household sharing, or public/social portfolio sharing in the POC.
- Automatic real-estate appraisal or alternative-asset pricing before Phase 4.
- Native mobile applications in the initial web release.
- Treating AI output as financial advice or as a source of calculated portfolio values.

## 4. Users, Authentication, and Tenancy

### 4.1 Account Model

- Public self-service registration is supported and enabled by default through
  `PUBLIC_SIGNUP_ENABLED=true`.
- Registration requires username, email, password, password confirmation, and successful
  single-use email verification before login.
- Verification links expire, resending invalidates earlier unused links, and only token
  digests are persisted.
- Admins can list users and create accounts directly. Admin-created accounts remain a
  supported operational path, not the primary signup flow.
- Each POC user has one implicit consolidated portfolio containing all their connections
  and manual data.

### 4.2 Authentication Security

- Passwords use Argon2 or an equivalently strong adaptive hash and are never stored in
  plaintext.
- Authentication uses random opaque session tokens in secure, HTTP-only, SameSite
  cookies. Only token digests are stored.
- Five failed attempts trigger a 15-minute account lockout.
- Public release additionally requires IP- and username-aware rate limiting, secure
  password reset, session revocation, and optional TOTP two-factor authentication.
- Production uses HTTPS through Cloudflare Tunnel and `COOKIE_SECURE=true`.

### 4.3 Tenant Isolation

- Every connection, position, transaction, snapshot, profile, import, news association,
  recommendation, conversation, alert, and manual asset belongs to a user.
- Repository and service operations must include the authenticated `user_id`; knowing an
  object UUID must never grant access to another user's data.
- Cross-user views are prohibited until explicit household permissions are implemented.
- Admin privileges do not implicitly expose portfolio holdings or broker credentials.

## 5. Portfolio Domain and Data Quality

### 5.1 Core Entities

- **User / UserProfile:** identity, goals, risk tolerance, and time horizon.
- **BrokerConnection:** user, provider, account label, encrypted credentials, connection
  status, freshness, and last safe error. Launch supports one connection per provider;
  multiple same-provider accounts are deferred unless demonstrated user demand justifies
  the additional setup and reporting complexity.
- **Instrument / InstrumentAlias:** canonical security or asset plus provider-specific
  identifiers, symbols, names, asset class, currency, exchange, sector, and geography.
- **Position:** connection, instrument, quantity, broker-reported cost/value, original
  currency/value, EUR value, and valuation timestamp.
- **Transaction:** source account, external ID, type, quantity, price, gross/net value,
  fees, tax withheld, original currency, execution time, and import provenance.
- **PortfolioSnapshot:** source and consolidated end-of-day values in original currency
  and EUR.
- **FXRate / MarketPrice:** provider, instrument or currency pair, date/time, value, and
  provenance.
- **SyncRun / ImportJob / DataQualityIssue:** observable ingestion state, counts,
  warnings, failures, and reconciliation results.
- **NewsItem / Alert / AIRecommendation / Conversation / ChatMessage:** user-scoped
  information and intelligence features.
- **ManualAsset / AssetValuation / AssetCashFlow / Liability:** Phase 4 diversified-asset
  model.

### 5.2 Data Invariants

- Store decimals for financial values; never use binary floating-point arithmetic.
- Retain source-native identifiers and values alongside normalized values.
- All normalized values include valuation time, FX-rate date, source, and
  stale/estimated flags.
- Synchronization and imports are idempotent and cannot duplicate transactions.
- Partial imports preserve the last known good portfolio and surface an actionable
  warning rather than silently replacing it with incomplete data.
- Daily historical valuations begin when a connection is first synced unless reliable
  transactions and market data allow an explicitly identified backfill.
- Deleted connections remove imported data according to the documented retention policy.

## 6. Data Sources and Synchronization

### 6.1 Common Connector Contract

Each provider is isolated behind a connector supporting the applicable subset of:

- credential validation;
- current positions and cash;
- transactions and cash flows from a resumable cursor;
- current/daily portfolio valuation;
- provider capability and permission reporting;
- rate-limit and retry metadata.

All external calls run server-side. Connectors return normalized domain objects and safe
errors; provider-specific payloads do not leak into route handlers or the frontend.

### 6.2 Trading 212

- Live Invest/Stocks ISA API with HTTP Basic authentication using API key and secret.
- Import current positions, cash, orders/fills, dividends, deposits, withdrawals, and
  fees exposed by the account.
- Retain Trading 212's per-position and account-summary unrealized P/L in the primary
  account currency and convert it to EUR with the synchronized position values.
- Orders/fills, dividends, and cash movements use provider `nextPagePath` pagination,
  per-stream resumable cursors, bounded pages per run, and idempotent transaction storage.
- Rate-limit-aware retry, canonical instruments, non-EUR support, and verified asset types
  from Trading 212 instrument metadata are implemented; deeper reconciliation remains.
- Keys must be read-only and include the history permissions needed for activity import.

### 6.3 Binance

- Official Binance Spot REST API using a signed read-only API key.
- Import non-zero Spot balances; discoverable Spot trades; trade and withdrawal fees;
  completed deposits and withdrawals; and positive asset-distribution income events.
- Use stable provider-derived transaction identifiers, a versioned one-time activity
  backfill for existing connections, overlap-safe incremental synchronization, and the
  provider's documented history windows and pagination limits.
- Discover trade symbols from current balances plus assets seen in transfers and income.
  Binance requires a symbol for Spot trade history, so fully sold-out assets with no other
  discoverable account record remain part of the deeper full-history/reconciliation work.
- Resolve assets through EUR or safe intermediate quote pairs and clearly mark assets
  that cannot be priced.
- Users must be instructed to enable Reading only and disable trading, futures, margin,
  and withdrawals.

### 6.4 eToro

- Official public API with `x-api-key`, `x-user-key`, and unique `x-request-id` headers.
- Users create a Real-environment key with read permission only.
- Import current positions, cash, portfolio value, and P&L where exposed by the API.
- Read eToro's dedicated Real-account P&L response, aggregate its open position lines by
  instrument, retain copy-portfolio P&L where exposed, and store both provider-currency
  and ECB-converted EUR values on current positions and daily snapshots. Keep these
  nullable and explicitly broker-reported rather than treating them as calculated returns.
- Refresh with other live connections and retain a reliable last-trading-day snapshot
  for each month.

### 6.5 Provider-Specific CSV Data

- CSV is used selectively when an important provider account has no usable official API;
  Northstar does not ask users to maintain generic stock or crypto records manually.
- Trading 212 Crypto uses its official History CSV export because Trading 212's Public API
  currently supports only Invest and Stocks ISA accounts. Imports reconstruct crypto
  holdings, deduplicate overlapping files, retain transaction provenance, and label
  last-trade-price valuation fallbacks.
- Each supported CSV source owns its mapping, validation, duplicate detection, and atomic
  import workflow so users can upload the provider's native export without reformatting it.
- Manual entry is reserved for Phase 4 assets that are naturally manually valued, starting
  with real estate. Unsupported stock/ETF/crypto brokers are not represented through
  generic manual holdings or transaction forms.
- XTB remains excluded until an official API or a dedicated low-effort import is added.

### 6.6 Synchronization Policy

- `PORTFOLIO_SYNC_MINUTES` is configurable, defaults to `120`, and should be kept between
  `60` and `120` for the initial deployment unless provider limits require a slower rate.
- Users can request a manual refresh, subject to per-provider rate limits and job
  deduplication.
- Users can replace credentials on an existing live connection. Saved secrets are never
  returned or prefilled; replacements are provider-validated before encrypted storage and
  trigger an immediate synchronization without deleting historical portfolio data.
- Current positions are updated on each successful sync; consolidated historical charts
  retain one end-of-day valuation.
- Scheduler jobs use single-instance/coalescing behavior and expose run status.
- Rate limits, transient errors, invalid credentials, missing permissions, and provider
  outages produce distinct user-facing states.

## 7. Currency, Market Data, and Benchmarks

- EUR is the initial base/display currency; each source value also retains its original
  currency.
- ECB working-day reference rates are the default FX source and are cached by date.
- Broker-reported values/prices are authoritative for connected current positions.
- Market-data access is provider-abstracted and free-first; paid providers may be added
  later without changing portfolio services.
- Finnhub is the initial news and financial-calendar provider and remains feature-flagged.
- Alpha Vantage daily series may provide cached investable ETF benchmark proxies. The
  benchmark feature remains disabled when data is unavailable or provider terms/limits
  are unsuitable.
- Benchmarks compare return, not raw account value, and show the selected proxy,
  currency, period, and data timestamp.

## 8. Dashboard and Analytics Requirements

### 8.1 Dashboard

- Total current portfolio value in EUR with last-updated and data-quality status.
- Change and return for the selected period, with net contributions distinguished from
  investment performance.
- Portfolio-history chart with 1M/3M/6M/1Y/all ranges.
- Allocation by source and asset class, followed by currency, sector, geography, and
  individual holding.
- Best/worst holdings, recent activity, income, upcoming events, news, and alerts.
- Responsive, keyboard-accessible loading, empty, stale, partial, and error states.

### 8.2 Holdings and Activity

- Holdings table supports search, sorting, grouping, and drill-down.
- Holding detail shows accounts, quantity, cost, value, gain/loss, income, transactions,
  prices, and valuation freshness.
- Unified activity supports date, source, instrument, and transaction-type filters.
- Users may attach categories, tags, notes, and target allocation without overwriting
  provider data.

### 8.3 Performance and Risk

- Provide net invested capital, absolute gain, total return, TWR, and MWR/XIRR.
- Attribute returns to capital gain, dividends/income, fees, and currency movement where
  data supports it.
- Provide realized/unrealized performance without claiming tax treatment.
- Provide contribution to return, volatility, drawdown, concentration, and allocation
  drift with calculation definitions.
- ETF look-through is optional when reliable holdings metadata is available and must
  state its source/as-of date.

## 9. News, Alerts, and AI

### 9.1 News and Events

- Daily scheduled ingestion fetches relevant news and earnings/dividend events for
  currently held instruments.
- Items are deduplicated, linked only to relevant users, and retain headline, source,
  URL, ticker, and publication time.
- Provider failures do not block the core portfolio experience.

### 9.2 AI Requirements

- OpenAI is the initial provider, using one server-side application key and an
  environment-configured model.
- Recommendations and chat are disabled safely when AI is not configured.
- Model context is produced by a versioned portfolio-context service using the current
  user's calculated holdings, analytics, recent activity, goals, and risk profile.
- Responses distinguish sourced facts, deterministic calculations, and generated
  explanation. They include an as-of time and informational-only disclaimer.
- Recommendations are cached; chat history is persisted per user and can be deleted.
- Do not log full prompts/responses containing sensitive portfolio data by default.

## 10. Security, Privacy, and Operations

- Broker credentials are encrypted with AES-256-GCM using a server-side key outside the
  database and are never returned after creation except as a masked hint.
- Secret values, session tokens, verification tokens, broker payload credentials, and
  sensitive AI context must be redacted from logs.
- Public release requires authentication throttling, password recovery, optional 2FA,
  privacy/consent records, account export, and permanent account deletion.
- PostgreSQL backups and restore procedures must be automated and tested.
- Scheduled jobs expose structured logs, metrics, last success, failure count, and safe
  admin-visible diagnostics.
- Dependency auditing, backend tests, frontend build/lint, migration tests, and critical
  end-to-end flows run in CI.
- Production secrets use environment variables or managed secrets; `.env` is restricted
  to the deployment user and never committed.

## 11. Architecture and Deployment

- **Backend:** Python, FastAPI, SQLAlchemy async, Pydantic, and versioned REST APIs.
- **Database:** PostgreSQL with Alembic migrations.
- **Frontend:** React/Vite SPA; mobile later reuses the REST backend.
- **Scheduling:** APScheduler is acceptable for one API process. Replicated deployment
  requires a dedicated/distributed worker so jobs execute once.
- **Deployment:** Docker Compose on Raspberry Pi behind Cloudflare Tunnel for the initial
  release; no filesystem or single-host assumptions in business logic.
- **Configuration:** environment-driven feature flags, provider keys, URLs, email,
  security settings, and scheduling intervals.
- **Testing:** external providers are mockable; route handlers remain thin; services and
  calculations are independently testable.

## 12. Acceptance Criteria

- A new public user can register, receive and complete email verification, log in, and
  access only their own empty portfolio.
- A user can connect or import a supported account without exposing secrets to the
  frontend or logs.
- After synchronization, source totals reconcile or the application presents a concrete
  data-quality warning explaining the difference.
- Dashboard values show source, currency, EUR conversion, valuation time, and freshness.
- Repeated synchronization/import produces no duplicate transactions.
- External cash flows are separated from investment return in performance reporting.
- Provider, news, benchmark, or AI failure cannot prevent access to the last known good
  portfolio.
- Account deletion and connection deletion do not leave accessible user-owned data.
- Tenant-isolation, security, calculation, migration, connector, and browser acceptance
  tests cover the critical paths before public production exposure.

## 13. Implementation Status Matrix

Status meanings:

- **Complete:** implemented and usable for its currently defined scope.
- **Partial:** meaningful implementation exists, but the requirements above are not met.
- **Planned:** represented only by scaffolding or not implemented.
- **Future:** intentionally belongs to a later product phase.

| Capability | Status | Current evidence / remaining work |
| --- | --- | --- |
| Layered/versioned backend, React shell, PostgreSQL, migrations, Docker | Complete | Core structure, `/api/v1`, Alembic, and Compose exist. |
| Tenant-scoped repositories and protected routes | Complete | User-scoped connections/portfolio queries and admin dependency exist; broader endpoint coverage needs regression tests as features grow. |
| Public registration and email verification | Complete | Register, verify, resend, and UI flows exist; signup defaults on. |
| Login sessions, password hashing/change, account lockout | Complete | Opaque cookie sessions, Argon2, password change, and five-attempt lockout exist. |
| Public-release auth/privacy hardening | Planned | IP throttling, reset flow, optional 2FA, privacy controls, export, and deletion remain. |
| Admin user management | Complete | Admin can list and create users. |
| Encrypted broker credentials and setup guides | Complete | AES-256-GCM, masked hints, read-only guidance, deletion, and provider-validated credential replacement exist. Reconnect responses/forms never expose or prefill saved secrets. |
| Multiple labelled accounts per provider | Deferred | Launch intentionally permits one connection per user/provider. Revisit only after demonstrated demand. |
| Trading 212 current positions, cash, recent activity, and snapshot | Partial | Live connector, canonical instruments with provider-verified stock/ETF types, per-position and snapshot unrealized P/L, EUR conversion, source-total reconciliation, rate-limit-aware retry, paginated orders/dividends/cash history, resumable per-stream cursors, and idempotency coverage work. Real-account backfill verification remains. |
| Binance Spot connector | Partial | Signed read-only authentication, Spot balances, EUR valuation, discoverable Spot-pair trades, trade/withdrawal fees, completed deposits/withdrawals, asset distributions, stable deduplication, one-time upgrade backfill, snapshots, refresh/scheduling, and mocked contracts exist. Real-account reconciliation and Binance's symbol-constrained fully sold-out/full-history gap remain. |
| eToro periodic connector and month-end history | Partial | Public API authentication, aggregate positions/cash/copy value, instrument metadata, dedicated Real-account P&L enrichment, provider/EUR P&L persistence on positions and snapshots, source-total reconciliation, closed-trade history, valuations, manual/periodic/month-end sync, and mocked contracts exist. Broader history reconciliation and exact coverage of every eToro product remain. |
| Provider-specific CSV data | Complete | Trading 212 Crypto CSV upload, validation, duplicate protection, transaction storage, holdings reconstruction, current-price/fallback valuation, snapshots, and repeat-import UI work. Generic stock/crypto CSV and manual entry are intentionally out of scope. |
| Canonical instruments and broker aliases | Complete | Global instruments retain ISIN/symbol identity while provider aliases preserve Trading 212 Invest, Trading 212 Crypto, Binance, and eToro identifiers. Sync/import resolution combines matching securities and crypto across platforms. |
| Automatic data-quality and reconciliation | Partial | Trading 212 and eToro synchronization silently compare imported holdings against independently reported provider totals and warn only beyond both 3% and EUR 5. Binance has no independent comparison total; Trading 212 Crypto overlap deduplication remains automatic. Broader transaction-level reconciliation remains. |
| ECB FX conversion and market-data cache | Complete | ECB working-day rates are fetched, persisted by publication date, cached in-process and across processes, looked up by date, converted through EUR, and backed by the newest stored rate set during temporary ECB failures. A daily refresh supplements on-demand fetching. |
| Scheduled synchronization | Partial | APScheduler refreshes Trading 212, Binance, and eToro every 120 minutes by default and adds eToro month-end and daily ECB runs. Connection syncs persist running/success/partial/error status, triggers, counts, timestamps, and safe details. Safe GET requests use bounded exponential backoff for transient failures and honor provider cooldown headers; stuck-run recovery and distributed-worker safety remain. |
| Connection freshness visibility | Complete | Connection cards distinguish fresh, stale, and never-synchronized sources, show the last successful sync/import, preserve it across failures, and show the latest failed attempt. Live sources become stale after two configured synchronization intervals. |
| Goals, risk tolerance, and time horizon | Complete | Profile API and UI are functional. |
| Basic portfolio summary | Partial | EUR total, position count, and source allocation work; the full dashboard does not. |
| Consolidated and per-platform holdings | Partial | A searchable responsive holdings page groups stocks/ETFs, crypto, cash, and other assets; supports value/P&L sorting; shows valuation time plus restrained stale/estimated/reconciliation states; and preserves source-native value and P/L details. Independently calculated gain/loss, activity, and dedicated instrument routes remain. |
| Scalable source-management UI | Complete | Connected sources use compact management rows; a searchable/filterable directory separates live API connections from file imports and scales without one oversized setup card per provider. |
| Transactions, daily history, performance, and risk analytics | Planned | Core tables exist; APIs, calculations, charts, and pages do not. |
| News and financial calendar | Planned | Finnhub interface and scheduler placeholder exist. |
| AI recommendations and portfolio chat | Planned | Tables, provider shell, feature flags, and placeholder UI exist. |
| Raspberry Pi deployment | Partial | Compose/nginx/health setup exists; production backup, monitoring, TLS-edge configuration validation, and restore testing remain. |
| Generic assets and real estate | Future | Phase 4 after the stock/ETF/crypto data foundation. |
| Multiple portfolios and household sharing | Future | POC intentionally uses one implicit portfolio per user. |
| European tax modules | Future | Explicitly excluded until transaction/tax-lot data is mature. |
| Native mobile clients | Future | Web first; backend remains reusable. |
