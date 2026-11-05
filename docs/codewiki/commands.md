# Commands

| Command | What it does |
|---|---|
| `make install` | `uv sync` (server) + `npm install` (web) |
| `make dev-server` | FastAPI on `:8000` with reload, bound to `0.0.0.0` |
| `make serve` | Builds the web app, then the API serves it on `:8000` (`KEEPALIVE=65` sets uvicorn `--timeout-keep-alive`); tablet opens `http://<laptop>:8000/?canvas=default` |
| `make dev-web` | Vite on `:5173` with `--host` so the tablet can reach it |
| `make test` | Server pytest + web `npm test` |
| `make lint` | `ruff check` (server, skills, scripts, eval), `oxlint`, `tsc -b` |
| `cd server && uv run pytest tests/test_health.py::test_health` | Single server test |
| `cd web && npm run build` | Production build (no `/__log`) |
| `uv run --directory server inkbridge-mcp` | Run the MCP stdio server |
| `uv run --directory server inkbridge-mcp-smoke --api http://127.0.0.1:8000` | Drive the MCP server over stdio; prints PASS/FAIL, exits 1 on failure |
| `scripts/vault_loop_e2e.py` | End-to-end vault loop walkthrough on a throwaway DB (output: `docs/vault-loop-walkthrough.md`) |

Eval harness (offline, deterministic; details in `eval/README.md`, decision 0033):

| Command (run from `server/`) | What it does |
|---|---|
| `uv run python ../eval/run.py chunks` | E5 chunk quality, offline |
| `uv run python ../eval/run.py transcribe --reader oracle` | E1 base |
| `uv run python ../eval/run.py stale` | E4 base |
| `uv run python ../eval/run.py input_repr --reader arms-noisy:image=0.05,image+strokes=0.02,strokes=0.2` | E1 input arms (decision 0034) |

Each run replaces its own section in `eval/results.md`. Real-model runs need `--allow-model` and a manifest with `"synthetic": false, "test_pages_only": true`. The committed set is synthetic.

Measurement scripts (`scripts/`): `bench_scene_save.py` (save latency, decision 0030), `orphan_growth.py` (decision 0028), `chunk_identity_eval.py` (decision 0029), `vault_loop_e2e.py`.

`npm install` in `web/` also runs `patch-package` (pen-feel patch).

Register the MCP server:
```bash
claude mcp add inkbridge -- uv run --directory /path/to/inkbridge/server inkbridge-mcp
```
Claude Desktop config is in `docs/mcp-tools.md`.

CI (`.github/workflows/ci.yml`) runs the same lint, test and build. Keep `make lint test` green before pushing.

Workflow: one ticket per branch/PR (`feat|fix|chore|docs/INK-xxx-slug`); never commit feature work to `main`; add paths explicitly (never `git add -A` or `git add docs`, since `docs/tickets/` is untracked on purpose).
