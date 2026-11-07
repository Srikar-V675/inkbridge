.PHONY: install dev-web dev-server serve serve-https install-skill test lint

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

# The same over HTTPS for the tablet (INK-181, decision 0076): a browser hands the page every pen
# sample only in a secure context, and http://<laptop-ip> is not one. scripts/lan-cert.sh makes a
# local CA and a certificate in data/tls/; trust data/tls/inkbridge-ca.crt on the tablet once.
# 4173 because the laptop firewall lets the LAN reach 4173 and 5173 only.
HTTPS_PORT ?= 4173
LAN_IP ?= $(shell ip -4 -o route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($$i == "src") print $$(i + 1)}')

serve-https:
	scripts/lan-cert.sh
	cd web && npm run build
	cd server && INKBRIDGE_PUBLIC_URL=$${INKBRIDGE_PUBLIC_URL:-https://$(LAN_IP):$(HTTPS_PORT)} uv run uvicorn inkbridge.api:app --host 0.0.0.0 --port $(HTTPS_PORT) --timeout-keep-alive $(KEEPALIVE) --ssl-keyfile ../data/tls/lan.key --ssl-certfile ../data/tls/lan.pem

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
