.PHONY: dev up down logs migrate bootstrap test lint

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api web

migrate:
	docker compose run --rm migrate

bootstrap:
	docker compose run --rm api python -m app.bootstrap

test:
	cd backend && pytest

lint:
	cd backend && ruff check .
	cd frontend && npm run build

