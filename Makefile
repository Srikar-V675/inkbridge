.PHONY: install dev-web dev-server test lint

install:
	cd server && uv sync
	cd web && npm install

dev-web:
	cd web && npm run dev -- --host

dev-server:
	cd server && uv run uvicorn inkbridge.api:app --reload --host 0.0.0.0 --port 8000

test:
	cd server && uv run pytest
	cd web && npm test

lint:
	cd server && uv run ruff check . ../skills
	cd web && npm run lint && npx tsc -b
