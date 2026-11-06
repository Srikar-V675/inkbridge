# Inkbridge

[![CI](https://github.com/Srikar-V675/inkbridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Srikar-V675/inkbridge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Status:** in development (build by 27 Oct 2026). Built: scenes, manual regions, MCP read tools,
search, the content and reading hashes, a proximity chunker and a Gemini recognizer (neither wired to
saves yet), and a web client that loads and autosaves the canvas. Chunk persistence, the vault loop,
agent drawing and Ask AI follow the v3 plan.

A handwritten canvas wired into your markdown vault. The server groups ink into chunks; any MCP
agent reads the whole canvas, writes a vault note whose sections trace back to the ink (and are
flagged stale only when what you wrote changes), answers your doubts, and draws diagrams back as
drafts you accept or reject. Full design: [Project spec v3](https://claude.ai/artifact/FkyFV1UySxqfC9oFEYb1P1)
and [Technical reference v3](https://claude.ai/artifact/1uMmVHEyuvb2uS5Dgutaqy); the v1 draft is kept in
[docs/project-doc.html](docs/project-doc.html). Contributor and AI guidance: [CLAUDE.md](CLAUDE.md),
[docs/mcp-tools.md](docs/mcp-tools.md), [docs/decisions/](docs/decisions/).

## Layout

| Path | What |
|---|---|
| `web/` | Vite + React + Excalidraw frontend |
| `server/` | Python package `inkbridge`: `api/` (FastAPI), `db/`, `recognizer/`, `mcp/` |
| `eval/` | Evaluation set, questions, scripts, results |
| `docs/` | v1 project doc, MCP tool reference, decision notes |
| `data/` | Runtime state, gitignored |

## Run

```bash
make install
make dev-server   # API on :8000
make dev-web      # canvas on :5173
make serve        # build web, then API + app on :8000 (tablet: http://<laptop>:8000/?canvas=default)
make test
```

The tablet URL moves from 5173 to 8000 when you use `make serve`; `make dev-web` stays for development.
Set `INKBRIDGE_PUBLIC_URL` to the :8000 URL so vault deep links use the new port.

## Privacy

Real notes stay out of the repo and out of any model. Private snapshots of a real canvas
(`scripts/snapshot_canvas.py`) go to `~/.inkbridge-private/`, which is outside the repo and gitignored;
CI never reads that folder, nothing in it is committed, and it is never sent to Gemini or listed in
`INKBRIDGE_RECOGNIZE_DOCUMENTS`. The committed real-scale fixture is generated and synthetic
(`eval/fixtures/make_real_scale.py`, INK-095).

## License

[MIT](LICENSE)
