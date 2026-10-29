# Environment variables

See `.env.example`. Never commit `.env`.

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | recognizer | none | Gemini key; never log or commit |
| `GEMINI_MODEL` | recognizer | `gemini-3.5-flash-lite` | Recognition model |
| `INKBRIDGE_DATA_DIR` | API | `./data` | SQLite file and crops directory |
| `INKBRIDGE_DB` | API | `<data dir>/inkbridge.db` | Overrides the DB path (read at call time) |
| `INKBRIDGE_API_URL` | MCP client, Vite proxy | `http://127.0.0.1:8000` | Where the API lives |
| `INKBRIDGE_DOCUMENT` | MCP | `default` | Default canvas id for tools |
| `INKBRIDGE_PUBLIC_URL` | API (deep links) | `http://localhost:5173` | Base of chunk deep links in notes; use a `.local` name for the tablet |
| `INKBRIDGE_RECOGNIZE_DOCUMENTS` | worker | unset = off | Comma-separated canvas ids Gemini may read (test and eval pages only: free tier may train on content) |
| `INKBRIDGE_RECOGNIZE_IDLE_S` | worker | 5 | Seconds a canvas must be idle before reading |
| `INKBRIDGE_VAULT` | export skill | unset (skill asks) | Vault folder for notes |
| `INKBRIDGE_RUNNER` | planned (INK-048) | unset | Optional Ask AI runner adapter |
