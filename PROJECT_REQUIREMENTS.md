# All-in-One Investment Dashboard — Project Requirements

## 1. Overview

A self-hosted web app (mobile later) that unifies a user's entire investment picture —
stocks, ETFs, and crypto — across multiple brokers/exchanges into a single dashboard.
Each user connects their own accounts and gets rich visualizations, trend/comparison
views, AI-generated portfolio recommendations based on their goals, portfolio-relevant
news, and an AI chat assistant that has their portfolio and profile as context.

Initial users will be Patrik and his family, but the app should be built as a
**scalable, general-purpose product**, not a one-off personal script. Prioritize clean
architecture, extensibility, and security of stored secrets — code and data models
should make it straightforward to onboard more users, add more data sources, and add
new features later without rearchitecting. **Phase 1 is web-only**; a mobile app
(likely React Native, reusing the same backend) is a future phase, not part of this
build.

## 2. Architecture Principles

These apply across the whole build, not just one section:

- **Connector pattern for data sources**: each broker/exchange (Trading212, eToro,
  Binance, future ones) is implemented as a self-contained connector module behind a
  common interface (e.g. `fetch_positions()`, `fetch_transactions()`,
  `fetch_snapshot_value()`). Adding a new source should mean writing one new connector,
  not touching core app logic.
- **Layered backend**: clear separation between API routes, business/service logic, data
  access, and external integrations (brokers, OpenAI, news provider). Avoid putting
  broker/API-specific logic directly in route handlers.
- **Database migrations**: use a migration tool (e.g. Alembic) from day one so the schema
  can evolve as features are added, instead of manual DB changes.
- **Config via environment variables** (API base URLs, secrets, feature flags) — no
  hardcoded credentials or environment-specific values in code.
- **API versioning**: prefix backend routes (e.g. `/api/v1/...`) so breaking changes
  later don't require a frontend rewrite.
- **Feature-flaggable AI/news features**: since OpenAI and the news provider are paid/
  rate-limited external services, structure them so they can be toggled off per
  environment (e.g. for local dev) without breaking the rest of the app.
- **Testability**: connectors and services should be written so they can be unit-tested
  with mocked API responses, not only tested against live broker accounts.
- Deployment target for v1 is Patrik's Raspberry Pi (Section 10), but avoid design choices
  that would make a later move to a proper cloud host (e.g. for more users/scale) require
  a rewrite — e.g. don't bake in filesystem paths or single-machine assumptions where
  avoidable.

## 3. Users & Multi-Tenancy

- Multiple users, each with
  **their own** isolated data:
  - own login
  - own broker/exchange connections and API keys
  - own portfolio positions, snapshots, goals, and dashboard
  - own AI chat history
- No cross-user visibility (User A never sees User B's data) unless explicitly added later.
- No public sign-up flow. Patrik is an **admin** user with access to a small admin UI
  (a protected screen/section within the app — not a separate app) where he can create
  new user accounts (username + temporary/initial password). Users log in with those
  credentials and can change their password afterward from their own settings. (Open
  signup can be added later if the app grows beyond invite-only — see Section 12.)

## 4. Authentication

- Simple username + password login, self-built (no third-party auth provider for v1).
- Passwords hashed with a strong algorithm (bcrypt or argon2) — never stored in plaintext.
- Session handled via secure, HTTP-only cookies (JWT or server session — Codex to
  pick a sane default) with reasonable expiry.
- App is exposed to the internet via Cloudflare Tunnel, so:
  - Enforce HTTPS (Cloudflare handles TLS termination).
  - Add basic protections: rate-limit login attempts, lockout/backoff after repeated
    failures.
- No password reset / email flow needed for v1 given the small initial user base
  (Patrik can reset manually via DB/admin script if needed) — but design the User model
  so email-based reset can be added later without a schema rewrite (e.g. leave room for
  an email field even if unused in v1).

## 5. Data Sources

### 4.1 Trading212 — ✅ Included in v1
- Used for buying/selling stocks and crypto — active trading account.
- Official public API (beta): https://t212public-api-docs.redoc.ly/
- Auth: HTTP Basic (API Key as username, API Secret as password, Base64-encoded).
- Environments: demo (`demo.trading212.com/api/v0`) and live (`live.trading212.com/api/v0`).
  **v1 uses the live environment** — these are real portfolios, not test data.
- Data to pull:
  - Current portfolio positions (instrument, quantity, value, P&L)
  - Account cash balance
  - Order/transaction history (for activity feed / transaction log)
- Sync approach: **polling** (no webhooks available). Poll periodically (e.g. every
  15–60 min, configurable) respecting rate-limit headers returned by the API.
- Each user stores their own Trading212 API Key + Secret (see Section 8 — encrypted at rest).

### 4.2 eToro — ✅ Included in v1
- User has existing positions, not actively trading there.
- Only needs the **portfolio value at the close of the last trading day of each month**
  (a monthly snapshot, not real-time tracking).
- Official public API: https://api-portal.etoro.com/ (launched Feb 2026, still young —
  expect possible rough edges/breaking changes).
- Requires: verified eToro account for the API key to appear in account settings.
  **Confirmed: all family members have verified eToro accounts**, so the eToro
  integration should be built as available to every user, not Patrik-only.
- Auth: API key + user key sent as headers (`x-api-key`, `x-user-key`, `x-request-id`).
- Relevant endpoints:
  - Portfolio Management endpoints for tracking P&L / portfolio value.
  - `market-data/instruments/history/closing-price` for historical closing prices if
    portfolio-value-at-a-date isn't directly exposed.
- Sync approach: **scheduled monthly job** — runs shortly after the last trading day of
  the month closes, fetches portfolio value, stores it as a snapshot. No need for
  frequent polling.
- Each user stores their own eToro API Key + User Key (encrypted at rest).

### 4.3 Binance — ✅ Included in v1 (crypto)
- Official API: https://developers.binance.com/
- Auth: API Key + Secret Key, generated by the user in Binance account settings.
  **Critical: instruct users (in-app, in the settings/connect flow) to create a
  READ-ONLY key** — enable "Reading" only, disable "Spot & Margin Trading",
  "Withdrawals", and "Futures". The app should never request trading permissions.
- Data to pull:
  - Spot wallet balances (`/api/v3/account`) — current crypto holdings
  - Current market prices for held assets (public market-data endpoints, no auth needed)
  - Trade history for the activity feed, similar to Trading212
- Sync approach: polling, same pattern as Trading212 (respect Binance's request-weight
  rate limits — these are stricter than Trading212's).
- Each user stores their own Binance API Key + Secret (encrypted at rest).

### 4.4 XTB — ❌ Excluded from v1
- XTB discontinued their public API (xapi.xtb.com / ws.xtb.com) as of March 14, 2025.
  No official API currently exists. Unofficial/community wrappers exist but rely on
  undocumented protocols and likely violate XTB's ToS — not suitable to build on.
- **v1: XTB is completely out of scope.**
- v2 (future): add manual entry so users can log an XTB portfolio value once a month,
  similar in spirit to the eToro snapshot but entered by hand instead of pulled via API.
  Keep the data model open to this so it's a small addition later, not a rearchitecture.

### 4.5 Future sources
- Architecture should keep each broker/exchange as a self-contained "connector" module
  (own auth, own sync logic, own data mapping to the common Position/Transaction/
  Snapshot model) so more sources can be added later without touching the core app.

## 6. AI Features

### 5.1 AI Provider
- **OpenAI API** for both recommendations and the Q&A chatbot.
- API key stored server-side as an app-level secret (not per-user) unless Patrik decides
  later that each user should bring their own key.

### 5.2 Goals & Risk Profile (new user input needed)
- Add a simple onboarding/settings section where each user sets:
  - Investment goals (e.g. free-text or simple categories: retirement, wealth growth,
    short-term savings, etc.)
  - Risk tolerance (e.g. low / medium / high, or a 1–5 scale)
  - Optional: target time horizon
- This profile is stored per user and feeds both the AI recommendations and the chatbot
  context.

### 5.3 AI Recommendations
- Periodically (or on-demand via a "Refresh recommendations" button) generate
  recommendations based on:
  - Current aggregated portfolio (holdings, allocation, concentration)
  - The user's stated goals and risk tolerance
- Example outputs: flag over-concentration in one stock/sector, suggest more
  diversification, note if current risk level doesn't match stated risk tolerance,
  general (non-personalized-advice-styled) observations.
- **Important disclaimer requirement**: all AI recommendations must be clearly labeled
  as informational/educational only, not financial advice, displayed prominently next to
  any recommendation output.
- Recommendations are generated server-side (portfolio data sent to OpenAI as context),
  cached/stored so they don't need to be regenerated on every page load.

### 5.4 Portfolio-Based News
- Show news relevant to the user's actual holdings (e.g. earnings dates/reports for
  stocks they own).
- **Recommended news source**: Finnhub (https://finnhub.io) — has a free tier covering
  company news and an earnings calendar endpoint, which fits the "earnings etc." use
  case well. Alpha Vantage is a viable alternative (also has a free tier with a NEWS_SENTIMENT
  endpoint). Codex should pick one, document the choice, and design the news-fetching
  module so the provider can be swapped later if free-tier limits become a problem.
- Sync approach: scheduled job (e.g. daily) that fetches news/upcoming earnings for
  tickers currently held by each user, stored and shown in a "News" section of the
  dashboard.

### 5.5 AI Q&A Chatbot
- Chat interface where the user can ask questions about their own investments
  ("How diversified am I?", "What's my biggest position?", "Did I get any dividends
  this month?").
- Context provided to the model per conversation: the user's current aggregated
  portfolio (positions, allocation, recent transactions) and their goals/risk profile
  from Section 6.2. Do not send other users' data.
- Same "not financial advice" disclaimer applies, shown in the chat UI.
- Store chat history per user so conversations persist across sessions (simple table:
  user_id, role, message, created_at).

## 7. Data Model (guidance, Codex can refine)

Suggested core entities:

- **User**: id, username, password_hash, is_admin (bool), created_at
- **UserProfile**: user_id, goals (text or enum), risk_tolerance, time_horizon
- **BrokerConnection**: id, user_id, broker (`trading212` | `etoro` | `binance` |
  `xtb_manual`), encrypted_credentials (JSON blob, structure varies per source), status
  (active/error), last_synced_at
- **Position** (current snapshot of holdings — Trading212 and Binance): id,
  broker_connection_id, ticker/instrument_id, asset_type (stock/crypto/etf), quantity,
  avg_price, current_value, currency, updated_at
- **PortfolioSnapshot** (point-in-time total value — used for eToro monthly values and
  optionally daily/periodic rollups for other sources, to power trend charts): id,
  broker_connection_id, snapshot_date, total_value, currency
- **Transaction** (order/activity history — Trading212, Binance): id,
  broker_connection_id, external_id, ticker, type (buy/sell/dividend/etc.), quantity,
  price, value, currency, executed_at
- **NewsItem**: id, ticker, headline, source, published_at, url, related_user_ids (or a
  join table linking news to users currently holding that ticker)
- **AIRecommendation**: id, user_id, generated_at, content, model_used
- **ChatMessage**: id, user_id, role (user/assistant), content, created_at

This structure supports per-user, per-source isolation and keeps XTB's future manual
entry as just another `BrokerConnection` with `broker = xtb_manual`.

## 8. Security Requirements

- Broker/exchange API keys/secrets **must be encrypted at rest** (e.g. AES-256-GCM via a
  server-side encryption key stored in an environment variable / secrets file, not in
  the DB).
- Binance keys specifically: app must guide users to create **read-only** keys during
  the connect flow (trading/withdrawal permissions should never be requested or needed).
- Never log API keys, secrets, or full OpenAI prompts/responses containing sensitive
  portfolio data beyond what's needed for debugging (redact where possible).
- Settings page where each user enters/updates/deletes their own API keys — keys are
  never displayed again in full after saving (mask them, e.g. `••••1234`).
- All broker/exchange/AI API calls happen server-side only — the frontend never talks
  directly to Trading212/eToro/Binance/OpenAI, and never sees raw secrets after initial
  entry.

## 9. Dashboard & Visualizations

Per-user dashboard showing a combined view across all connected sources:

- **Total portfolio value over time** (line chart, combining all connected sources)
- **Per-source breakdown** (Trading212 vs eToro vs Binance value, stacked area or split view)
- **Asset allocation** (pie/donut chart by instrument/asset class — stocks vs crypto vs
  ETFs — and by individual holding)
- **Trends**: value change over configurable time ranges (1M/3M/6M/1Y/all), % change,
  best/worst performing holdings
- **Comparisons**: portfolio performance vs a benchmark (e.g. S&P 500 / MSCI World) if a
  free market-data source for the benchmark is available; per-source comparison
  (which broker/exchange is performing best)
- **Recent activity feed** (latest buys/sells/dividends across Trading212 and Binance)
- **Monthly snapshot trend for eToro** (bar or line chart of month-end values)
- **News section** (Section 6.4) and **AI recommendations panel** (Section 6.3),
  surfaced on or near the main dashboard
- **AI chat** accessible from the dashboard (Section 6.5)
- Currency handling: **base/display currency is EUR** for all combined totals and charts.
  Convert any non-EUR values returned by a source (Codex: use a simple FX rate
  source, cached daily — e.g. ECB reference rates or a free FX API).

## 10. Tech Stack

- **Backend**: Python, FastAPI
- **Database**: PostgreSQL
- **Frontend**: React (Vite SPA), talking to FastAPI via REST API — **web only for v1**;
  built with an eye toward an eventual React Native mobile app sharing the same backend.
- **AI**: OpenAI API (chat/completions) for recommendations and Q&A
- **News**: Finnhub (or equivalent, see Section 6.4)
- **Scheduling**: background job runner for periodic Trading212/Binance sync, monthly
  eToro snapshot, daily news fetch (APScheduler is a simple fit given the small scale;
  Codex can propose alternatives if there's a good reason)
- **Deployment**: Docker Compose on Patrik's Raspberry Pi home server, exposed via the
  existing Cloudflare Tunnel setup (same pattern as patrikpalencar.uk /
  cloud.patrikpalencar.uk)

## 11. Confirmed Decisions

- Web app first; mobile is a later phase, not part of this build.
- Sources for v1: Trading212, eToro, Binance. XTB excluded from v1 (manual entry planned
  for v2).
- User accounts are created via a small admin UI (Patrik as admin), not public signup.
- Base/display currency: EUR.
- Trading212: live environment (real account data).
- Historical Trading212/Binance charting: the app builds its own value-over-time series
  by taking periodic snapshots going forward from when a user connects their account.
  **Chart history starts from the connection date, not retroactively** — these APIs
  don't expose a ready-made historical portfolio-value series, only current positions
  and transaction history.
- eToro: all family members have verified eToro accounts, so the integration is built
  as available to every user (not Patrik-only).
- AI provider: OpenAI API, for both recommendations and the Q&A chatbot.
- News provider: not finalized — Finnhub recommended (free tier, has an earnings
  calendar), Alpha Vantage as a fallback option. Codex to confirm availability/limits and
  document the final choice.

## 12. Open Items to Revisit

- Whether OpenAI usage should be a shared app-level API key (simplest) or per-user
  (more isolated, more setup friction) — assumed shared/app-level for v1; flag if you
  want it changed. Worth revisiting once the user base grows, since a shared key means
  shared usage/cost.
- Benchmark comparison (S&P 500 / MSCI World) depends on finding a suitable free
  market-data source — confirm during build if this needs a specific API or should be
  cut from v1.
- Raspberry Pi hosting is fine for the initial user count, but if the user base grows
  meaningfully, Postgres/compute may need to move to a proper cloud host — the connector/
  layered-architecture approach in Section 2 is meant to make that a deployment change,
  not a rewrite.
- Public/self-service signup (vs. today's admin-invite-only model) — not needed for v1,
  but worth flagging as a likely v2 ask if the app is opened up beyond invited users.
