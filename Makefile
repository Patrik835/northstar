.PHONY: setup up down logs migrate bootstrap test lint backup restore-test e2e

# Creates .env and generates secrets on first run; never changes existing values.
setup:
	@sh ops/init-env.sh

up: setup
	docker compose up --build -d
	@echo "Northstar is starting at http://localhost:8080 — the first account you create becomes the admin."

down:
	docker compose down

logs:
	docker compose logs -f api web

migrate:
	docker compose run --rm migrate

# Optional: pre-create an admin from INITIAL_ADMIN_* instead of registering in the browser.
bootstrap:
	docker compose run --rm api python -m app.bootstrap

test:
	cd backend && pytest

lint:
	cd backend && ruff check .
	cd frontend && npm run lint
	cd frontend && npm run build

backup:
	docker compose exec backup /usr/local/bin/northstar-backup once

restore-test:
	docker compose run --rm --entrypoint /usr/local/bin/northstar-restore-smoke-test backup \
		/backups/$${BACKUP_FILE:?Set BACKUP_FILE to a dump filename}

e2e:
	cd frontend && npm run e2e
