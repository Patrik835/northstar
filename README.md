# Northstar investment dashboard

A self-hosted, multi-user web application that aggregates Trading 212, eToro, and
Binance portfolios. This repository currently contains the v1 application skeleton:
the system boundaries, data model, authentication flow, connector contracts, REST API,
React UI shell, migrations, tests, and Raspberry Pi-friendly containers.

Live broker synchronization, FX conversion, news fetching, and OpenAI calls are
deliberately represented by interfaces/placeholders and are the next implementation
slices. No placeholder calls a real account.

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

Development verification emails are captured by Mailpit. Open
`http://localhost:8025` to view the inbox and follow verification links. Production
should replace the `SMTP_*` values with a real SMTP provider and set `PUBLIC_WEB_URL`
to the public HTTPS address.

Generate the two required keys:

```bash
openssl rand -hex 32
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

The first value is `APP_SECRET_KEY`; the second is
`CREDENTIAL_ENCRYPTION_KEY`. On the Raspberry Pi, keep `.env` readable only by the
deployment account, use a strong `POSTGRES_PASSWORD`, set `COOKIE_SECURE=true`, and
route the Cloudflare Tunnel to port 8080.

## Development

Backend:

```bash
cd backend
# Python 3.10+ is supported; deployment currently uses Python 3.12.
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The Vite server proxies `/api` to `http://localhost:8000`. API documentation is at
`/docs` on the backend in development.

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
- Every repository query taking portfolio/connection data includes the authenticated
  `user_id`. Admin APIs are separately guarded.

## Architectural notes and open decisions

- Finnhub is the default news adapter because its company-news and earnings data fit
  the requirement. It remains disabled by default and isolated behind `NewsProvider`.
  Free-tier limits should be rechecked when that implementation begins.
- OpenAI uses one app-level key and is disabled by default. Recommendation/chat output
  is designed to be cached per user and always carries a financial-advice disclaimer.
- A benchmark provider is intentionally not selected. `BENCHMARKS_ENABLED` stays false
  until a stable free source is chosen.
- APScheduler is appropriate for one Raspberry Pi API process. If the API is later
  replicated, move jobs to a dedicated worker or use a distributed scheduler so they
  do not execute once per replica.
- Trading 212 and Binance history starts with the first successful sync. eToro uses
  monthly snapshots. The `xtb_manual` enum is reserved in the model for v2, but it is
  not exposed by v1 routes.

See [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md) for the full product scope.
