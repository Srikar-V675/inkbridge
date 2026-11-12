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
| `INKBRIDGE_WEB_DIST` | API | `web/dist` if it has `index.html` | Built web app the API serves on `/`, `/assets`, `/favicon.svg`; read at import |
| `INKBRIDGE_PUBLIC_URL` | API (deep links) | `http://localhost:8000` | Base of chunk deep links in notes; use a `.local` name for the tablet |
| `INKBRIDGE_RECOGNIZE_DOCUMENTS` | worker | unset = off | Comma-separated canvas ids Gemini may read (test and eval pages only: free tier may train on content) |
| `INKBRIDGE_RECOGNIZER` | worker | `gemini` | `gemini` or `claude` (Haiku through one persistent `claude -p` session on the subscription; does not train on content; INK-185, decision 0104). `claude` also turns the latest-ink offer read off |
| `INKBRIDGE_RECOGNIZE_IDLE_S` | worker | 5 (1.5 with the Claude reader) | Seconds a canvas must be idle before reading |
| `INKBRIDGE_CHUNK_CONTAINMENT` | API (chunker) | unset = off | Fraction in (0, 1], for example `0.6`: keep a chunk's id when that share of it survives in one cluster (decision 0029); invalid values are ignored with a warning |
| `INKBRIDGE_VAULT` | export skill | unset (skill asks) | Vault folder for notes |
| `INKBRIDGE_CHUNKER` | API (chunker) | `v2` | `v2` or `v1`; a canvas's own `chunker` setting wins; invalid values warn and mean the default (decisions 0081, 0110) |
| `INKBRIDGE_CROP_SOURCE` | API, worker, web | `browser` | `browser` (tablet uploads PNGs) or `server` (Pillow renders them; `PUT /regions/{id}/image` answers 403); read at call time (decision 0065) |
| `INKBRIDGE_OFFERS` | API | off | `1`, `true`, `on` or `yes` turns the proactive offers on; off means no scan, no model call, no chip (INK-206, decision 0121) |
| `INKBRIDGE_QUIET_S` | offers | 3 | Seconds after the last pen stroke before an offer may appear |
| `INKBRIDGE_OFFER_OPEN_TTL_S` | offers | 60 | How long an open offer may sit unseen before it expires (INK-205) |
| `INKBRIDGE_DEVICE_LOG` | API, web | off | `1` mounts `/debug/device-log` and `/debug/echo` and writes `data/logs/device.jsonl` (decision 0059) |
| `INKBRIDGE_RUNNER` | API | unset = pull path only | `claude` starts an agent per task (Ask question, tapped offer) with `claude -p` (decision 0007) |
| `INKBRIDGE_CLAUDE_BIN` | runner, Claude reader | `claude` | Path of the `claude` binary |
| `INKBRIDGE_RUNNER_MCP_CONFIG` | runner | unset | MCP config the runner passes with `--strict-mcp-config`; must list the inkbridge server and the vault server. `make serve` / `make serve-https` write the inkbridge entry (default `data/runner-mcp.json`, decision 0109) |
| `INKBRIDGE_RUNNER_MCP_NAME` | runner | `inkbridge` | Name of the inkbridge server in that config |
| `INKBRIDGE_RUNNER_VAULT_TOOLS` | runner | unset | Full read-only vault tool names (a `search`/`read`/`get`/`list` word, no write word), for example `mcp__vault__obsidian_search` (decision 0060) |
| `INKBRIDGE_RUNNER_TIMEOUT_S` | runner | 180 | Seconds before a runner attempt is killed; must be a number above 0 |
| `INKBRIDGE_AGENT_DAILY_TASKS` | API | 30 | Runner tasks per 24 h; questions you ask are exempt; 0 = none (decision 0095) |

No variable controls timing logs: the server always logs (`inkbridge.*` to stderr); the browser sink writes `web/dev.log` in dev builds only. The eval harness reads `GEMINI_API_KEY` only with `--allow-model`.
