# Commands

| Command | What it does |
|---|---|
| `make install` | `uv sync` (server) + `npm install` (web) |
| `make dev-server` | FastAPI on `:8000` with reload, bound to `0.0.0.0` |
| `make dev-web` | Vite on `:5173` with `--host` so the tablet can reach it |
| `make test` | Server pytest + web `npm test` |
| `make lint` | `ruff check` (server, skills, scripts), `oxlint`, `tsc -b` |
| `cd server && uv run pytest tests/test_health.py::test_health` | Single server test |
| `cd web && npm run build` | Production build (no `/__log`) |
| `uv run --directory server inkbridge-mcp` | Run the MCP stdio server |
| `uv run --directory server inkbridge-mcp-smoke --api http://127.0.0.1:8000` | Drive the MCP server over stdio; prints PASS/FAIL, exits 1 on failure |
| `scripts/vault_loop_e2e.py` | End-to-end vault loop walkthrough on a throwaway DB (output: `docs/vault-loop-walkthrough.md`) |

Register the MCP server:
```bash
claude mcp add inkbridge -- uv run --directory /path/to/inkbridge/server inkbridge-mcp
```
Claude Desktop config is in `docs/mcp-tools.md`.

CI (`.github/workflows/ci.yml`) runs the same lint, test and build. Keep `make lint test` green before pushing.

Workflow: one ticket per branch/PR (`feat|fix|chore|docs/INK-xxx-slug`); never commit feature work to `main`; add paths explicitly (never `git add -A` or `git add docs`, since `docs/tickets/` is untracked on purpose).
