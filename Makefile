.PHONY: install dev-web dev-server serve install-skill test lint

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

# Symlink, so a git pull updates the skill; every Claude session sees it, not just this repo's.
install-skill:
	mkdir -p ~/.claude/skills
	@if [ -e ~/.claude/skills/inkbridge-export ] && [ ! -L ~/.claude/skills/inkbridge-export ]; then echo "~/.claude/skills/inkbridge-export exists and is not a symlink; move it first"; exit 1; fi
	ln -sfn $(CURDIR)/skills/inkbridge-export ~/.claude/skills/inkbridge-export

test:
	cd server && uv run pytest
	cd web && npm test

lint:
	cd server && uv run ruff check . ../skills ../scripts ../eval
	cd web && npm run lint && npx tsc -b
