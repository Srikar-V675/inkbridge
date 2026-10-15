# Inkbridge

A stroke-based canvas that any MCP agent can read from and write to. Select handwritten
regions; an agent reads ink, image and text, and answers back as draft elements you accept
or reject. Full design: [docs/project-doc.html](docs/project-doc.html).

## Layout

| Path | What |
|---|---|
| `web/` | Vite + React + Excalidraw frontend |
| `server/` | Python package `inkbridge`: `api/` (FastAPI), `db/`, `recognizer/`, `mcp/` |
| `eval/` | Evaluation set, questions, scripts, results |
| `docs/` | Project doc and decision notes |
| `data/` | Runtime state, gitignored |

## Run

```bash
make install
make dev-server   # API on :8000
make dev-web      # canvas on :5173
make test
```
