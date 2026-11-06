.PHONY: install dev-web dev-server serve test lint

install:
	cd server && uv sync
	cd web && npm install

dev-web:
	cd web && npm run dev -- --host

dev-server:
	cd server && uv run uvicorn inkbridge.api:app --reload --host 0.0.0.0 --port 8000

# uvicorn idle keep-alive seconds; hypothesis H4 (default 5 closes most connections)
KEEPALIVE ?= 65

serve:
	cd web && npm run build
	cd server && uv run uvicorn inkbridge.api:app --host 0.0.0.0 --port 8000 --timeout-keep-alive $(KEEPALIVE)

test:
	cd server && uv run pytest
	cd web && npm test

lint:
	cd server && uv run ruff check . ../skills ../scripts ../eval
	cd web && npm run lint && npx tsc -b
