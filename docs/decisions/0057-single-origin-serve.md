# 0057 Serve the built web app from the API on one port (INK-100)

Status: accepted. Tablet numbers pending.

## What dominated
The tablet reached the API through the Vite dev proxy. That proxy produced websocket `ECONNRESET`s, the dev
build runs React StrictMode so the canvas loads twice, and the proxy hides the device IP behind 127.0.0.1 in
`api.log` (hypotheses H3 and H4, tech ref v4 section 12). One origin removes the proxy from the path.

## What changed
- `inkbridge/api/web.py` `mount_web(app, dist)`, called as the last line of `inkbridge/api/__init__.py`, so
  every API route and router wins. Exactly three fixed paths: `/assets` (hashed files, `Cache-Control:
  public, max-age=31536000, immutable`), `/` (`index.html`, `no-cache`) and `/favicon.svg`.
- No SPA catch-all: it would make `/dev.log` or any typo answer with `index.html`, and the app has one route.
  Everything else, including anything beside `dist`, is 404. `StaticFiles` refuses `../` out of `assets/`.
- `config.web_dist()`: `INKBRIDGE_WEB_DIST`, else `<repo>/web/dist`, only when it holds `index.html`. Without
  a build the API stays API-only. It is resolved at import, so set the variable before uvicorn starts and
  restart after a new build (`make serve` builds first).
- `make serve KEEPALIVE=65` runs the build then uvicorn on :8000 with `--timeout-keep-alive`; `KEEPALIVE=5`
  is the other arm of H4. Tablet numbers are pending.

## What it does not do
- `/__log` stays Vite-dev-only (it lives in `configureServer`, never in `dist`); a test asserts the API
  does not answer it (CLAUDE.md "dev-only helpers stay dev-only").
- `DEFAULT_PUBLIC_URL` stays `http://localhost:5173` so existing links keep working; owners set
  `INKBRIDGE_PUBLIC_URL` to the :8000 URL.
- No supervisor (systemd user unit), no fonts from esm.sh and no `EXCALIDRAW_ASSET_PATH` change (separate
  ticket). Nothing in `web/` changes: the socket URL already comes from `window.location.host`.
