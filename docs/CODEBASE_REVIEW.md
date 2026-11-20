# Codebase cleanup and quality review

Reviewed on 2026-10-08. The cleanup preserves current features, public API responses,
authorization, validation, and database history. Findings below describe the original review. All proposed fixes were approved and applied
in the follow-up recorded below.

## Cleanup completed

- Removed unused `AnalyticsRepository.benchmark_instrument` and
  `AnalyticsRepository.instrument_is_held_by_user`, including the unused model import.
- Removed unused `InstrumentResolver._refresh`. The active resolver still maintains aliases
  and preserves the existing restriction on manual metadata enrichment.
- Removed the unused frontend `HoldingMetadata` type.
- Removed the holdings page's unused recomputation of legacy calculated-cost/gain fields.
  Rendered P/L continues to use the existing performance breakdown. Backend fields remain
  available to API consumers.
- Removed the always-false `PnlSummary.hasPartialCoverage` property and its unreachable branch.
  Partial P/L is still identified by the number of covered sources.
- Removed 20 unused CSS rules for retired connection cards, allocation lists, wide panels,
  and the old chat placeholder/input layout. Dynamic alert, broker, and job-status styles
  were checked and retained.
- Removed the nonexistent `dev` target from Makefile's `.PHONY` declaration.

Reference checks covered backend application imports and definitions, frontend imports and
exports, literal and dynamic class names, tests, entry points, and operational scripts.
No complete runtime module was proven unreachable. Framework-registered routes, Pydantic
validators, model registrations, provider interfaces, migration files, and user data were
retained.

## Original findings

### R1 — High: dependency security advisories

`npm audit` reports two high-severity affected packages in the installed frontend tree:

| Package | Installed | Dependency path | Patched version indicated by audit |
| --- | --- | --- | --- |
| `brace-expansion` | 5.0.9 | ESLint → minimatch | 5.0.12 |
| `source-map-js` | 1.2.1 | Vite → PostCSS | 1.2.2 |

These are build/lint dependencies; this finding does not establish an exploitable path
in the deployed browser application. Audit details include
[brace-expansion](https://github.com/advisories/GHSA-qhr7-859c-m2p7) and
[source-map-js](https://github.com/advisories/GHSA-68fv-2mgg-jv7q).

`pip-audit` against the existing backend virtual environment reports 37 advisory records
across four packages, or 19 unique package/advisory pairs after deduplicating repeated IDs:
`cryptography` 45.0.7, `pip` 22.0.2, `pytest` 8.4.2, and `setuptools` 59.6.0.
`cryptography` is an application dependency; the other three are development/install tools.
The application package itself is not published on PyPI and was skipped by that audit.
These are advisory matches, not confirmed application exploits.

**Proposed change:** review and upgrade affected dependencies in a separate change, rerun
security audits, and test credential encryption compatibility. The current `cryptography<46`
and `pytest<9` bounds prohibit some versions identified as patched by the audit, so blindly
running an automatic fix is insufficient. See [backend dependencies](../backend/pyproject.toml)
and [frontend lockfile](../frontend/package-lock.json).

### R2 — High: partial cost coverage can produce an incorrect aggregate gain

**Confirmed with synthetic data.** Two sources hold the same instrument: the known source is
worth €150 with a €100 cost; the other source is worth €1,000 with unknown cost. The holding's
`calculated_gain_eur` becomes €1,050, although its known open P/L is €50. Calculation subtracts
the covered cost from the value of every source. The portfolio breakdown also reports
`coverage="complete"` because unavailable sources are filtered out before coverage is combined.

**Proposed change:** sum gains only for covered sources, or withhold aggregate gain when cost
coverage is incomplete. Keep uncovered non-cash positions in portfolio coverage accounting.
Verify this example produces a €50 known subtotal marked partial, never a complete €1,050 gain.
See [holding aggregation](../backend/app/services/portfolio.py#L435) and
[portfolio coverage](../backend/app/services/portfolio.py#L545).

### R3 — Medium: CSV P/L percentage disagrees with the holdings page under partial coverage

**Confirmed using the same example as R2.** The CSV correctly exports a €50 known P/L, but
computes its percentage using the full €1,150 holding value, giving approximately 4.55%.
The page uses only the covered source and correctly shows 50% for that subtotal.

**Proposed change:** use the cost/value of covered sources for the percentage, or withhold the
percentage for partial coverage. Keep the CSV's explicit coverage column.
See [CSV calculation](../backend/app/services/csv_exports.py#L125) and
[page calculation](../frontend/src/features/holdings/HoldingsPage.tsx#L108).

### R4 — Medium: platform filtering leaves some performance figures unfiltered

**Code-path finding.** The page filters `sources` and recomputes value, quantity, and open P/L,
but carries `holding.performance` unchanged through `...holding`. The expanded details and
performance strip read cost basis, realized P/L, income, fees, and total return from that
unfiltered breakdown. Selecting one platform can therefore show another platform's figures.

**Proposed change:** recompute the performance breakdown for the selected sources using the
same coverage rules as the backend. Verify with an instrument held at two brokers with
different income and realized P/L.
See [platform projection](../frontend/src/features/holdings/HoldingsPage.tsx#L336),
[performance strip](../frontend/src/features/holdings/HoldingsPage.tsx#L826), and
[expanded cost basis](../frontend/src/features/holdings/HoldingsPage.tsx#L882).

### R5 — Medium: failed manual quotes are still recorded as successful refreshes

**Code-path finding.** `_mark_to_market` returns `False` on quote/FX failure, preserving the
last position value and timestamp. `refresh` ignores that result and always calls `_touch`,
which clears errors and advances the connection's successful-sync timestamp. Manual
connections are also outside the stale-after schedule in `connection_freshness`.

The holdings/dashboard GET paths additionally perform network requests and consolidation
while holding a user-row lock. A slow quote blocks other manual mutations for that user.

**Proposed change:** preserve the last successful timestamp on failure and expose quote
freshness accurately. Separate mutation bookkeeping from market-refresh success. Agree on
refresh cadence and failure visibility before changing request behavior.
See [manual refresh](../backend/app/services/manual_positions.py#L324),
[connection bookkeeping](../backend/app/services/manual_positions.py#L348), and
[freshness policy](../backend/app/services/freshness.py).

### R6 — Medium: cash deposits can create artificial benchmark losses and volatility

**Confirmed with synthetic data.** `_growth_series` divides current value by opening capital
plus cumulative contributions. Values of €100, €200, and €300, with a €100 deposit on the third
date and no market move that date, produce indices of 100, 200, and 150. The deposit causes an
artificial 25% index decline. Benchmark comparison and risk calculations both use this series.
The performance service separately contains a time-weighted-return calculation.

**Proposed change:** choose and document the return methodology. For cash-flow-neutral
benchmark/risk comparisons, reuse a consistent time-weighted series and test deposit and
withdrawal days. Do not silently change the existing reported simple-return metric.
See [growth series](../backend/app/services/analytics.py#L69),
[benchmark use](../backend/app/services/analytics.py#L339), and
[risk use](../backend/app/services/analytics.py#L443).

### R7 — High: password-reset token consumption is not atomic

**Concurrency risk from code review; not stress-tested.** Reset reads a token, checks `used_at`,
and updates the password without locking or conditionally claiming that token. Two requests
can pass the initial check before either commits, so a token intended to be single-use can be
accepted twice. Existing tests cover sequential reuse.

**Proposed change:** lock or atomically claim the token and validate the affected-row count in
the password-update transaction. Add a concurrent PostgreSQL test.
See [password reset](../backend/app/services/password_recovery.py#L61).

### R8 — High: the last-administrator guard can race

**Concurrency risk from code review; not stress-tested.** Account deletion counts active
administrators before deleting the caller, without serializing the invariant. With two
administrators, simultaneous deletions can both see a count of two and remove both accounts.

**Proposed change:** serialize administrator-count validation and deletion together, then
verify simultaneous deletion preserves at least one active administrator.
See [account deletion](../backend/app/services/account_data.py#L128).

### R9 — Medium: broker syncs lack cross-request exclusion and complete failure bookkeeping

**Code-path/concurrency risk.** Scheduled jobs use `max_instances=1` inside one scheduler, but
`ConnectionSyncService.sync` has no lock excluding manual syncs or another API worker.
Concurrent syncs can replace the same positions, insert duplicate cursors/snapshots, or allow
an older response to replace newer data. Correction on implementation: both `ConnectorError` and unexpected exceptions already
enter rollback/error bookkeeping. That behavior was retained and regression-tested.

**Proposed change:** enforce per-connection synchronization ownership, and record all failed
runs with safe error details while preserving rollback. Test overlapping manual/scheduled
syncs and an unexpected provider/data exception.
See [sync transaction](../backend/app/services/connection_sync.py#L81),
[failure handling](../backend/app/services/connection_sync.py#L276), and
[scheduler limits](../backend/app/scheduling/scheduler.py).

### R10 — Medium: provider quote units need explicit normalization

**Conditional code risk; a live London quote could not be retrieved during this audit.**
The current provider forwards its currency string and raw numeric price directly to FX
conversion. ECB normalization uppercases currencies, so a quote expressed as `GBp` (pence)
would become `GBP` without dividing the price by 100. This can overstate the holding by 100×.
Ticker/quote compatibility also relies on matching symbols without exchange-specific checks.

**Proposed change:** normalize provider-specific units before FX conversion and test a pence
quote. Preserve distinct listings and verify exchange-qualified ticker mappings where needed.
See [quote parser](../backend/app/integrations/market_data/current_prices.py#L37) and
[FX currency normalization](../backend/app/integrations/market_data/ecb.py#L230).

### R11 — Medium: production settings do not fail closed

**Configuration finding, not a claim about the current deployment.** `APP_ENV=production`
does not change or validate cookie security; `COOKIE_SECURE` still defaults to false.
The encryption-key validator explicitly accepts `replace-...` placeholders, although the
cipher cannot use them. Misconfiguration can pass settings validation and fail later.

**Proposed change:** validate production prerequisites at startup, including secure cookies,
HTTPS public URLs, and usable non-placeholder keys. Retain explicit development/test behavior.
See [settings](../backend/app/core/config.py#L15) and
[credential cipher](../backend/app/core/encryption.py).

### R12 — Low: build and documentation leftovers need a follow-up decision

- Neither Docker build context has a `.dockerignore`. The frontend copies the entire local
  directory after installing dependencies, including local `node_modules` when present.
  Add context exclusions and consider `npm ci` for deterministic builds. See
  [frontend Dockerfile](../frontend/Dockerfile) and [backend Dockerfile](../backend/Dockerfile).
- README and requirements still describe manual positions as purchase-cost-only and deny
  automatic market refresh. They also omit merging, although current code implements both
  market refresh on reads and weighted-cost merging. Verify and update those descriptions.
  See [README](../README.md#L46) and [requirements](../PROJECT_REQUIREMENTS.md#L331).
- Migration `0019` created `position_cost_bases` for the subsequently removed exchange
  purchase-price feature. No runtime code uses it now. Do not delete the applied migration;
  decide whether to retain dormant data or remove the table with a new forward migration and
  backup. See [migration history](../backend/alembic/versions/0019_position_cost_basis.py).

## Cleanup verification before the approved fixes

Before and after cleanup:

- All 157 backend tests passed.
- Backend Ruff checks, frontend ESLint, TypeScript checks, and production build passed.
- Eight desktop/mobile browser checks passed for manual holdings and missing exchange P/L.
- Installed Python requirements are consistent; operational shell scripts parse; Docker
  Compose configuration validates; Alembic reports a single `0019` head.
- `git diff --check` passed.

Browser checks use mocked holdings/auth responses. Backend tests largely use mocked providers
and SQLite adapters. They do not prove PostgreSQL concurrency guarantees or live broker
compatibility. The audit tools were installed only in `/tmp`; application dependencies and
lockfiles were not changed. No live account data or database schema was changed by cleanup.
The running Docker app was not rebuilt as part of this behavior-preserving code cleanup.

All recommendations were subsequently approved; implementation results follow.


## Approved fixes applied

- **R1:** cryptography 50.0.2, pytest 9.1.1, pytest-asyncio 1.4.0, pip 26.2.1,
  and setuptools 84.0.0 installed. Frontend lockfile now uses patched transitive versions.
  Python and npm audits report no known vulnerabilities. A credential fixture produced
  by the preceding cryptography 45 deployment decrypts under the upgraded version.
  Docker installation tooling also has patched minimum versions.
- **R2/R3:** known gains exclude uncovered values; unknown non-cash holdings count toward
  portfolio coverage. CSV percentages use only covered value. Regression example gives
  EUR 50 and 50%, marked partial, with incomplete total return withheld.
- **R4:** selected-platform performance combines selected sources with the backend's
  coverage rules. Desktop/mobile browser checks cover realized P/L, income, fees,
  total return, and expanded cost basis across two exchanges.
- **R5:** quote/FX requests on read occur before the user lock. Refresh re-reads positions
  and applies quotes only to matching inputs, preventing concurrent edits from being lost.
  Older market quotes cannot replace newer valuations. Failed quotes retain successful
  timestamps and expose an error; manual valuations become stale after 24 hours.
  Mutation snapshot bookkeeping does not clear unrelated refresh failures.
- **R6:** benchmark, risk, and TWR share chained time-weighted returns, treating interval
  contributions as end-of-period flows. Tests cover deposits, withdrawals, and missing
  observation dates. The existing simple-return metric is unchanged. Daily valuations
  cannot establish exact intraday cash-flow timing.
- **R7:** reset conditionally claims an unused, unexpired token in the password transaction.
  Two overlapping PostgreSQL resets accept exactly one request.
- **R8:** PostgreSQL serializes admin deletion/count validation with a transaction table
  lock. Simultaneous deletion of two administrators retains one active administrator.
- **R9:** a dedicated PostgreSQL session advisory lock owns each broker sync across its
  commits. Overlapping requests reuse persisted connection state and leave the existing
  sync to finish, avoiding duplicate requests, writes, and blocked lock waiters. Session
  closure releases ownership after worker failure. Existing safe exception bookkeeping
  remains. PostgreSQL verifies exclusion across independent sessions.
- **R10:** Yahoo pence units GBp/GBX normalize to GBP before conversion. A returned symbol
  must match the requested listing when provider metadata supplies it. Mock contracts
  verify normalization and mismatched-listing rejection; live London validation remains
  dependent on provider availability.
- **R11:** all encryption keys require valid base64 decoding to 32 bytes. Production
  additionally requires secure cookies, HTTPS public URLs, and a non-placeholder app secret. Validation errors hide input values to avoid logging secrets.
- **R12:** both Docker contexts exclude local dependencies/caches/secrets. Frontend uses
  npm ci. Product docs describe market refresh and weighted merging. Forward migration
  0020 removes the unused position_cost_bases table; historical 0019 remains unchanged.
  Downgrade restores its schema, while data restoration requires the database backup.

PostgreSQL concurrency tests require REVIEW_TEST_DATABASE_URL pointing to a disposable
PostgreSQL database: their fixture recreates that database's application tables. Never use
an application database for that test variable. Ordinary tests skip those checks when the
variable is absent.


## Final verification and deployment

Verified through 2026-10-10:

- 168 backend tests passed, including four real PostgreSQL concurrency checks.
- The Docker runtime passed 164 backend tests; its four PostgreSQL checks were run
  separately against the disposable database. Ruff, ESLint, TypeScript/build, dependency
  consistency, Compose validation, and whitespace checks passed.
- Ten desktop/mobile browser checks passed for manual holdings, unavailable exchange
  P/L, and platform-filtered performance. Four additional live desktop/mobile checks
  passed registration, verification, sign-in, export, password reset, account deletion,
  and accessibility checks. Release fixtures now use a valid example.com email and scope
  the export-password input to its form. Accounts from failed fixture runs were removed.
- Python, frontend, and Docker-runtime dependency audits reported no known vulnerabilities.
- API/web images were rebuilt and restarted. The running database is at 0020, the retired
  table is absent, and readiness reports ready. All six stored connection credential
  payloads decrypt with the upgraded cipher; no credential contents were logged.
- Pre-migration database backup: /tmp/northstar-before-review-fixes-20261008.sql
  (8,951,131 bytes, owner-only permissions). The retired table contained zero rows.
  Migration upgrade/downgrade/upgrade was verified against a disposable PostgreSQL database.
  Temporary preview and disposable database containers were stopped after verification.

Live broker API compatibility and intraday return precision remain subject to the provider
and daily-valuation limits described above. The live checks did not place trades or force
broker synchronization.
