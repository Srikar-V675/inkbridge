# Inkbridge

Spec: `docs/project-doc.html`. Layout and commands: `README.md`.

## Rules
- Strokes are the source of truth; recognitions are a cache keyed by stroke hash.
- Agent write tools only add elements (`customData.draft = true`). Never edit or delete user ink; enforce in `server/`, not the client.
- The MCP server is a thin HTTP client of the API. No direct DB access from `mcp/`.
- Python in `server/` (uv, ruff, pytest, `requires-python >= 3.11`). Frontend in `web/`.
- Commit messages: imperative, no attribution or Co-Authored-By lines.
- Branches: `main` plus short-lived `feat/`, `chore/`, `fix/` branches.

## Commands
`make install | dev-server | dev-web | test | lint`
