# 0001 Repo structure

- Monorepo: `web/` (frontend), `server/` (one Python package, API + recognizer + MCP), `eval/`.
- One Python package, two entrypoints, rather than separate `backend/` and `mcp/`: they share
  models and config, and the MCP side talks to the API over HTTP so the draft-only write
  invariant lives in one place.
- `eval/` is top-level because it exercises the web app, server and agent together.
- Task runner is `make` (already installed); Python tooling is `uv`.
