# 0009: Request body caps and the migration lock

Status: accepted (INK-040)

## Body caps
- An ASGI middleware (`inkbridge/api/limits.py`) answers **413** before any route reads the body.
  A declared `Content-Length` over the cap is rejected without reading; otherwise the body is read
  up to the cap and replayed, so chunked uploads with no length are capped too.
- Caps: **11 MiB** for crop uploads (`POST /documents/{id}/regions`, `PUT /regions/{id}/image`:
  the 10 MB PNG cap plus 1 MiB for multipart framing and form fields) and **128 MiB** for every
  other request, which in practice means the scene `PUT`. The whole canvas is one PUT and a long
  freedraw stroke with pressures is ~35 KB (600 points), so 128 MiB holds ~3,800 such strokes. It
  bounds server memory; it cannot match the 50,000-element cap, so a very large canvas will need
  to be split. The client shows a 413 as "Save rejected (413)". The route-level 10 MB PNG check
  stays as the exact limit.
- Why middleware: FastAPI parses a JSON body whole and Starlette spools a multipart upload to
  disk before the route runs, so a check inside the route comes after the cost was paid.
- Buffering up to the cap in memory is what FastAPI does for JSON anyway. For uploads it means up
  to 11 MiB is held in memory before Starlette spools it, which is acceptable at that size.
- An early 413 does not drain the body; uvicorn closes the connection, so a client still sending
  a large body may see a reset instead of the 413.

## Migration lock
- `migrate()` runs all pending files, and the v2 backfill, in **one `BEGIN IMMEDIATE`
  transaction** with a 120 s busy timeout. SQLite's write lock is the cross-process lock: a second
  API process or worker starting at the same time waits, then re-reads `schema_version` and
  applies nothing. No lock file, works on any OS SQLite supports.
- `executescript` cannot be used inside it (it commits first), so files are split into statements
  with `sqlite3.complete_statement` (semicolons inside strings and trigger bodies are kept).
- Consequence: a failing migration rolls back **everything** in that run, including files before
  it. The old per-file `executescript` left a half-applied file behind on error.
- A backfill on a large database runs under the same lock; a second process waiting longer than
  120 s fails to start with "database is locked" and must be restarted.
- The lock test runs two connections in one process; SQLite locks are per connection, and a
  manual check with two processes racing `init_db` on a fresh file passed 5/5.
- The interrupted-backfill heal moved from `init_db` into the locked section and is the only
  backfill trigger: "version 4 recorded and some region has no content_hash".

## MCP client
- A 404 raises `NotFound` (an `ApiError`); `get_region` calls a crop missing only then. Any other
  image error keeps the transcription and attaches the real error text.
- Status errors are detected by status code, not `raise_for_status()`: Starlette's TestClient uses
  its own httpx build whose exception class the client did not catch.
- The MCP server closes the `httpx.Client` it created when `mcp.run` returns or raises.
