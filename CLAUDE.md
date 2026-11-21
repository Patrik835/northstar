# CLAUDE.md

Northstar Investment OS is a self-hosted, multi-user portfolio tracker for EU investors. It
pulls stocks, ETFs, cash and crypto from broker APIs (Trading 212, Binance, Bybit EU, eToro,
IBKR) and from file imports (XTB, Trade Republic, Scalable Capital, Trading 212 Crypto). It
also supports manually added holdings. It runs as a Raspberry Pi deployment behind a
Cloudflare Tunnel.

## Product principles (read first)

- **Usability and simplicity come first.** A non-technical user should be able to go from a new
  account to seeing their portfolio without reading docs. Prefer sensible defaults over new
  settings. Don't add an env var or a user-facing option when a good default will do.
- **Optional features must degrade quietly.** AI, news and benchmarks switch on as soon as their
  key is set (`settings.ai_available` / `news_available` / `benchmarks_available`; frontend:
  `useFeatures()` in `src/api/features.ts`). Missing keys must never break a page. Hide the
  feature, or show a single plain-language line about it.
- **Every empty state tells the user what to do next.** Point to the one action that fixes it
  (connect a source, import a file, add a holding).
- **Honest numbers.** Never show a complete figure computed from partial data. When cost or
  history coverage is partial, label it partial or withhold it (see `docs/CODEBASE_REVIEW.md`).
- **Fewer, clearer screens beat more features.** Before adding a page, check whether it fits
  in an existing one.
- Show money with `src/lib/format.ts` (`formatEur`, `formatChange`, `formatPercentChange`,
  `tone`) so € values, +/− signs and green/red look the same everywhere. Activity names come from
  `src/domain/activity.ts`. Gain/loss totals use `summarizePnl` (`holdings/holdingMath.ts`), which
  respects partial coverage. Don't recompute P/L elsewhere.
- Lead with the few numbers users care about. Put advanced detail behind "More details" or a
  collapsed section, not on the main view.
- Use plain language in the UI. Don't show internal terms such as "reconciliation",
  "sync run" or "canonical instrument" to users.

## Layout

```text
backend/app/api/v1/         FastAPI routes (thin; delegate to services)
backend/app/services/       business logic (portfolio, performance, analytics, imports)
backend/app/repositories/   user-scoped DB access — every query must be scoped to the user
backend/app/integrations/   connectors/, market_data/, news/, ai/, email/
backend/app/models/         SQLAlchemy models; enums.py holds Broker etc.
backend/app/scheduling/     APScheduler jobs (run inside the API process)
backend/alembic/versions/   numbered migrations (00NN_description.py)
frontend/src/features/      one folder per page (dashboard, holdings, connections, …)
frontend/src/api/           fetch client + shared TS types (types.ts mirrors backend schemas)
frontend/src/domain/        broker display metadata
frontend/src/routing/       tiny custom router (no react-router); pathname only, read query via window.location
frontend/src/layouts/AppLayout.tsx  sidebar sections + section tabs (Holdings↔Activity, Analytics↔News)
frontend/src/styles/global.css   all styling (no CSS framework)
ops/                        backup / restore scripts
```

Docs: `README.md` (setup + config), `PROJECT_REQUIREMENTS.md` (product contract),
`NORTHSTAR_ROADMAP.md` (tickets), `docs/CONNECTORS.md` (adding providers),
`docs/CODEBASE_REVIEW.md` (known issues).

## Commands

```bash
make up          # creates .env + secrets if missing (ops/init-env.sh), then builds and starts
                 # db, migrate, api, web :8080, mailpit :8025, backup
make bootstrap   # optional: pre-create an admin from INITIAL_ADMIN_* (first web signup is admin anyway)
make migrate     # run alembic upgrade head
make test        # backend pytest (uses in-memory SQLite by default via tests/conftest.py)
make lint        # ruff + eslint + tsc/vite build
make e2e         # Playwright (frontend/e2e)

cd backend && pytest tests/test_x.py -k name   # single test
cd frontend && npm run dev                      # Vite dev server, proxies /api → :8000
```

Backend venv lives at `backend/.venv`. CI (`.github/workflows/ci.yml`) also runs pytest against
Postgres, alembic downgrade/upgrade round-trip, `pip-audit` and `npm audit`.

## Conventions

- **Python**: 3.10+ target, ruff (`E,F,I,UP,B`), line length 100, async SQLAlchemy, Pydantic v2
  schemas in `app/schemas/`. Routes stay thin. Logic goes in services, and DB access goes in repositories.
- **Money**: use `Decimal`, never float. Values are normalized to EUR via persisted ECB FX rates.
- **Providers**: never add `if broker == ...` branches to generic services or React pages.
  Put provider behavior in `ConnectorDefinition` (`integrations/connectors/registry.py`) or the
  import-source metadata. Follow `docs/CONNECTORS.md`.
- **Credentials** are encrypted with `CREDENTIAL_ENCRYPTION_KEY`. Never log or return them.
- **Migrations**: add a new numbered file. Don't edit applied ones. Both upgrade and downgrade
  must work (CI checks this).
- **Frontend**: React 19 + TypeScript, no UI/state/router libraries. Keep it that way unless
  there is a strong reason. Update `src/api/types.ts` when backend schemas change.
  Keep pages small: put sub-components and pure helpers in sibling files (see
  `holdings/HoldingDetails.tsx`, `holdings/holdingMath.ts`, `connections/SourceDialog.tsx`).
  Empty states must point to the next action. `/holdings?add=1` and `/connections?type=api|csv`
  are onboarding deep links.
- **Tests**: every bug fix gets a regression test. Connectors get mocked contract tests. Use
  `tests/test_postgres_concurrency.py`-style tests for locking/race fixes.

## Gotchas

- `.env` is required. `make up` generates it, and `ops/init-env.sh` only replaces `generate-me`
  placeholders. Never regenerate `CREDENTIAL_ENCRYPTION_KEY` on an existing install, because
  stored broker credentials would become unreadable. Production (`APP_ENV=production`) requires an
  HTTPS `PUBLIC_WEB_URL`. Secure cookies and the CORS origin follow it unless overridden.
- The first account on a fresh install becomes the admin and is active immediately
  (`GET /auth/setup` → `needs_setup`). Later accounts verify email (Mailpit at
  http://localhost:8025 in dev), unless `SMTP_HOST` is empty, which turns email off entirely.
- Tests read the repo-root `.env`. Pass `_env_file=None` when constructing `Settings` in tests.
- The scheduler runs inside the API process. Set `SCHEDULER_ENABLED=false` for tests or extra replicas.
- IBKR syncs daily (05:30 UTC). Other live connectors sync every `PORTFOLIO_SYNC_MINUTES`.
- The asset search catalogue is a bundled snapshot (`frontend/public/asset-catalogue.json`),
  refreshed with `python -m app.refresh_asset_catalogue`.
- Don't commit `.env`, `backups/`, or personal broker exports (e.g. the `.xlsx` in repo root).
