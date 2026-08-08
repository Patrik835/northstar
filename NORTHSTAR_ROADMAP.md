# Northstar Investment OS — Requirements Refresh and Kanban Roadmap

> Updated 2026-08-08: requirements/documentation and the first Binance/eToro connector
> slices are complete. Items explicitly marked partial still need follow-up tickets.

## Summary

`PROJECT_REQUIREMENTS.md` now defines the broader product vision:

- Northstar is a public, EU-focused investment operating system for people with diversified investments.
- The first milestone delivers trustworthy stocks, ETFs, and crypto tracking.
- Real estate, private investments, bonds, pensions, commodities, and other assets follow through a generic manual-asset framework.
- The POC has one consolidated portfolio per user; multiple portfolios and household sharing come later.
- Broker data refreshes every 1–2 hours, supports manual refresh, and always displays freshness/error status.
- EUR is the default display currency; original currencies remain visible.
- Public signup remains, with email verification and stronger production security.
- No trading, budgeting, or tax calculations in the initial product.
- AI is added only after deterministic portfolio analytics are reliable.

This direction matches the strongest capabilities offered by mature trackers: genuine total-return reporting, dividends, multi-currency valuation, benchmarking, ETF exposure analysis, and support for property and alternative assets. See [Sharesight](https://www.sharesight.com/features/), [getquin](https://www.getquin.com/portfolio-tracker/), and [Kubera](https://www.kubera.com/portfolio-tracker).

## Verified Current State

### Implemented

- FastAPI, React, PostgreSQL, Alembic, Docker Compose, versioned APIs, layered backend, connector registry, and scheduler foundations.
- Multi-user data ownership and user-scoped portfolio/connection repositories.
- Public registration, email verification/resend, login/logout, opaque cookie sessions, password changes, account lockout, and admin-created users.
- Argon2 password hashing and AES-256-GCM broker credential encryption.
- Trading 212 credential validation, positions, cash, provider-reported unrealized P/L,
  recent activity, daily snapshot, scheduled/manual synchronization, and
  limited-permission handling.
- Binance signed authentication, Spot balances, EUR market-pair valuation, discoverable
  Spot trades, completed transfers, trade/withdrawal fees, positive asset distributions,
  one-time upgrade backfill, snapshots, and scheduled/manual synchronization.
- eToro public API authentication, aggregate positions/cash/copy value, instrument metadata,
  broker-reported position/copy/account P&L in provider currency and EUR, closed-trade
  history, current/month-end snapshots, and scheduled/manual synchronization.
- Working-day ECB FX fetching, dated database storage, same-day caching, cross-currency
  conversion, and last-known-good fallback for synchronization.
- Persisted live-connection sync runs with initial/manual/scheduled triggers,
  running/success/partial/error states, item counts, timestamps, and safe details.
- Bounded exponential retry/backoff for transient broker failures, including provider
  `Retry-After` and Trading 212 reset-header handling.
- Connection cards show fresh, stale, or never-synchronized state, the last successful
  synchronization, and the most recent failed attempt without erasing known-good data.
- Existing live connections can validate and replace encrypted credentials without
  returning or prefilling saved secrets, then immediately synchronize with the new key.
- Trading 212 orders, dividends, and cash history paginate through provider continuation
  paths with per-stream cursors, bounded backfill batches, and interruption-safe resume.
- Trading 212 synchronization is covered for repeat-run transaction, position, and daily
  snapshot idempotency, including resumed and post-backfill incremental history.
- Canonical instruments and provider aliases that combine equivalent securities and crypto while preserving every broker's original identifiers.
- Searchable holdings UI with consolidated stock/ETF and crypto views, per-platform
  filtering, aggregated broker-reported P/L, and expandable per-source details.
- Trading 212 Crypto CSV imports with validation, overlap-safe deduplication, transaction-backed balance reconstruction, current Binance pricing, and explicit valuation fallback warnings.
- Compact connected-source management plus a searchable/filterable source directory designed to accommodate additional brokers and import types.
- Connection setup guides, encrypted credential storage, masked hints, secure reconnect,
  and deletion.
- Goals, risk tolerance, and time-horizon profile.
- Basic dashboard total, position count, and allocation-by-source API/UI.
- Core database tables for positions, transactions, snapshots, news, recommendations, and chat history.
- Fifty-one backend tests currently pass, including crypto CSV parsing/reconstruction,
  canonical matching, holdings aggregation, sync-run state handling, and mocked Binance,
  eToro, ECB, and public crypto-price contracts; frontend lint and the production build
  also pass.

### Partially Implemented

- Trading 212 still needs real-account backfill verification, detailed data-quality reporting, and broader reconciliation tests.
- Binance activity now covers current/transfer/income-discovered Spot pairs, completed
  deposits and withdrawals, trade and withdrawal fees, and positive asset distributions.
  Binance's symbol-required trade endpoint still prevents automatic discovery of a fully
  sold-out asset with no current balance, transfer, income, or previously known record;
  deeper full-history reconciliation remains.
- Binance and eToro have mocked contract coverage and successful real read-only account
  smoke tests.
- eToro's aggregate portfolio, dedicated Real-account P&L, and closed trades are supported;
  broader product/history reconciliation remains.
- Asset-type allocation is returned by the API but not displayed.
- Daily snapshots exist, but there is no historical portfolio API, performance engine, or chart.
- AI, news, and benchmark adapters exist only as interfaces/placeholders.
- Public signup exists, but production-grade recovery, IP-aware throttling, 2FA, privacy controls, and abuse protection do not.

### Still Missing From Existing Requirements

- Transaction page and advanced holding detail analytics.
- Historical value charts and date-range filtering.
- Profit/loss, total return, dividends, fees, deposits, and withdrawal analytics.
- Per-holding, asset-class, currency, sector, geography, and source allocation.
- Benchmarks and per-source comparison.
- Recent activity feed.
- News and earnings calendar.
- AI recommendations and portfolio-aware chat.
- Background-job health, stuck-run recovery, deeper observability, and notifications.
- Login rate limiting beyond account lockout.
- Responsive/mobile-quality web UX and broader automated testing.

## Requirements and Interface Changes

- Replace the implicit broker-symbol model with canonical `Instrument` and `InstrumentAlias` records so the same security held at different brokers is aggregated correctly.
- Permit multiple accounts from the same broker by replacing the current one-user/one-broker constraint with user-owned, labelled connections.
- Extend transactions with fees, taxes withheld, source/import provenance, broker account, original currency, and synchronization identifiers.
- Add persisted daily FX rates, market prices, sync runs, import jobs, and data-quality issues.
- Keep current positions fresh every 1–2 hours while retaining one end-of-day valuation point for long-term charts.
- Introduce provider interfaces with these initial defaults:
  - Broker-reported prices for connected holdings.
  - ECB daily reference rates for FX; the ECB publishes rates each working day. See the [ECB exchange-rate data](https://data.ecb.europa.eu/key-figures/ecb-interest-rates-and-exchange-rates/exchange-rates).
  - Finnhub for company news and earnings.
  - Alpha Vantage daily ETF price series as benchmark proxies, cached to remain within its free allowance. See the [Alpha Vantage documentation](https://www.alphavantage.co/documentation/) and [free-tier limits](https://www.alphavantage.co/support/).
- Make eToro a periodic live source for positions/value while retaining month-end snapshots. Its official API supports read-only portfolio access with API and user keys. See [eToro authentication](https://api-portal.etoro.com/getting-started/authentication).
- Add API groups for holdings, transactions, history/performance, income, imports, manual assets, news, notifications, and assistant conversations.
- Every response containing portfolio values must expose `as_of`, original currency, EUR value, and stale/estimated status.
- Treat AI output as explanations of calculated data, never as the source of portfolio calculations.

## Kanban Roadmap

All implementation tickets should target approximately 1–3 working days and include backend, frontend, tests, and migration work where applicable.

### Milestone 1 — Trustworthy Stock, ETF, and Crypto Core

1. [x] Rewrite requirements with the new vision, phased roadmap, non-goals, and implementation-status matrix.
2. [x] Align README and configuration documentation with public signup and 1–2 hour synchronization.
3. [x] Connect eToro and Binance end to end through creation, manual refresh, and scheduled synchronization.
4. [x] Add canonical instruments and broker-symbol aliases.
5. [x] Add daily ECB FX-rate storage, fetching, caching, and conversion service.
6. [x] Preserve original-currency and EUR values throughout portfolio responses.
7. [x] Add sync-run records with running/success/partial/error states and safe error details.
8. [x] Add retry/backoff and provider rate-limit handling to scheduled synchronization.
9. [x] Add stale-data indicators and last-successful-sync status to connection cards.
10. [x] Add credential replacement and reconnect flow without exposing saved secrets.
11. [x] Add Trading 212 paginated transaction backfill with resumable cursors.
12. [x] Add Trading 212 synchronization idempotency tests. (Rate-limit headers are handled.)
13. [x] Replace Trading 212 name-based ETF guessing with verified asset types stored on existing canonical instruments.
14. [x] Implement Binance signed-request authentication and credential validation.
15. [x] Import Binance Spot balances and convert non-zero assets into positions.
16. [x] Resolve Binance asset prices through EUR, stablecoin, and intermediate quote pairs.
17. [x] Import Binance trades, deposits, withdrawals, trade/withdrawal fees, and supported asset-distribution income events.
18. [x] Implement eToro authentication using the documented public API base URL and request headers.
19. [x] Import current eToro positions, cash, value, and broker-reported P&L where exposed, retaining provider-currency and EUR values.
20. [x] Store eToro daily/current valuations and reliable month-end snapshots.
21. [x] Support the native Trading 212 Crypto CSV with validation, atomic persistence, and repeat-import deduplication. Generic CSV mapping is intentionally out of scope.
22. [removed] Do not provide generic transaction templates; supported imports should accept the provider's native export without user reformatting.
23. [moved] Reserve manual entry for the Phase 4 diversified-asset model in item 63, beginning with real estate rather than manually maintained stocks or crypto.
24. Add automatic reconciliation checks to synchronization and supported CSV imports without a separate user-operated data-quality workflow. (Partial: Trading 212 Crypto repeated/overlapping files are deduplicated.)

### Milestone 2 — Portfolio Analytics and Usable Dashboard

25. Build a holdings API/page with search, sorting, grouping, and original/EUR values. (Partial: API, search, asset/platform grouping, fixed value ordering, and both currencies are implemented; selectable sorting remains.)
26. Build holding detail with quantity, cost, value, gain/loss, source accounts, and activity. (Partial: expandable quantity, average price, value, aliases, source accounts, freshness, and aggregated/per-source broker-reported P/L are implemented; calculated gain/loss and activity remain.)
27. Build a unified transaction/activity API and filterable page.
28. Add editable categories, tags, notes, and target allocation to holdings.
29. Build consolidated daily portfolio-history queries with 1M/3M/6M/1Y/all ranges.
30. Add total-value and net-invested-capital chart.
31. Implement money-weighted return/XIRR from dated external cash flows.
32. Implement time-weighted return using daily valuations and cash-flow boundaries.
33. Separate return into capital gain, income, fees, and currency movement.
34. Add realized/unrealized gain and average-cost reporting without tax claims.
35. Add allocation charts by asset type, holding, broker, currency, sector, and geography.
36. Add best/worst performers and contribution-to-return views.
37. Add dividend history, yield metrics, monthly income chart, and projected income calendar.
38. Add benchmark configuration and comparison using cached ETF proxies.
39. Add drawdown, volatility, concentration, and diversification metrics.
40. Add ETF look-through exposure when provider metadata is available.
41. Add target-allocation drift and educational rebalancing calculations.
42. Add CSV export for holdings, transactions, performance, and income.

### Milestone 3 — News, Alerts, and Grounded AI

43. Implement Finnhub company-news ingestion with deduplication and user/ticker linking.
44. Add earnings and dividend calendar events for held instruments.
45. Build dashboard news/calendar cards with source links and read state.
46. Add in-app alerts for stale connections, sync failures, allocation drift, and upcoming events.
47. Add optional email notification preferences and digest delivery.
48. Build a versioned portfolio-context service from deterministic analytics.
49. Implement cached AI portfolio reviews with timestamps and calculation references.
50. Implement persisted AI conversations with history loading and deletion.
51. Build the enabled chat UI with streaming/error states and strict tenant isolation.
52. Add prompt-injection protections, usage limits, redaction, disclaimers, and AI evaluation cases.

### Public-Release Security and Operations Gate

53. Add IP- and username-aware authentication rate limiting with trusted-proxy handling.
54. Add secure email-based password reset and session revocation.
55. Add optional TOTP two-factor authentication and recovery codes.
56. Add account data export and permanent account deletion.
57. Add privacy/consent records, retention rules, and GDPR-facing documentation.
58. Add security audit events without logging credentials or portfolio prompt contents.
59. Add scheduler/job monitoring, structured logs, health metrics, and admin failure visibility.
60. Add automated PostgreSQL backup plus documented and tested restore procedure.
61. Add CI for migrations, backend tests, frontend build/lint, and dependency auditing.
62. Add responsive navigation, loading/error/empty states, keyboard accessibility, and browser E2E coverage.

### Later — Diversified Investment OS

63. Introduce a generic manually valued asset model with ownership, valuation history, income, expenses, and documents.
64. Add real-estate properties with purchase value, current valuation, ownership share, rental income, expenses, mortgage balance, and equity.
65. Add recurring reminders for property valuation, rent, expenses, and loan updates.
66. Add bonds, savings products, pensions, private equity, commodities, precious metals, collectibles, and other custom assets.
67. Add crypto wallets, staking, Earn products, DeFi positions, and wallet-address integrations.
68. Add liabilities associated with investments, while keeping everyday budgeting out of scope.
69. Add multiple named portfolios and strategy-level reporting.
70. Add permissioned household sharing and consolidated household views.
71. Add country-pluggable European tax modules only after transaction/lot data is mature.
72. Add mobile applications using the same versioned backend.
73. Evaluate regulated account-aggregation providers for broader EU bank and broker connectivity.
74. Add encrypted document storage, beneficiary/estate summaries, and controlled read-only sharing as long-term features.

## Test and Acceptance Plan

- Connector contract tests cover authentication, pagination, rate limits, partial permissions, malformed responses, duplicate events, and safe failures.
- Golden calculation tests cover FX conversion, deposits/withdrawals, dividends, fees, multi-currency returns, XIRR, TWR, and benchmark comparison.
- Tenant-isolation tests verify that connections, imports, holdings, transactions, analytics, news, exports, and chat never cross users.
- Migration tests upgrade a copy of the existing schema and preserve current Trading 212 data.
- End-to-end acceptance flow: register, verify email, connect or import an account, complete synchronization, inspect holdings/activity/history, and export the result.
- A dashboard is considered trustworthy only when totals reconcile with source accounts, freshness is visible, stale or estimated values are labelled, and calculation components can be explained.
- Initial exclusions remain explicit: no order execution, no automatic rebalancing, no budgeting, no jurisdiction-specific tax calculation, no household sharing, and no near-real-time price promise.
