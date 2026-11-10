# 0109: Serve targets load `.env`; the runner's MCP config follows the served origin

Status: accepted (INK-194). Owner check pending (see the last section).

## Context

On 10 Nov the owner ran `make serve-https` and found the Ask runner and handwriting recognition off. `make` does not parse `.env` (the README said so and told the owner to `set -a; . ./.env` by hand), so `INKBRIDGE_RUNNER`, `GEMINI_API_KEY` and `INKBRIDGE_RECOGNIZE_DOCUMENTS` were unset. The runner's MCP config, `data/runner-mcp.json`, was hand-written with `INKBRIDGE_API_URL=http://127.0.0.1:8000`. That URL cannot reach the HTTPS server on port 4173, and it cannot verify the private CA that `scripts/lan-cert.sh` makes. So the runner's MCP calls could not work on the HTTPS origin even with the runner switched on.

## Decision

- **The serve targets read `.env` in the shell.** `serve` and `serve-https` run `set -a; . ./.env; set +a` as one shell step, not through make's own parser, so quoted values and spaces are safe. The file is therefore read as shell syntax: a `$` in a value must be quoted or escaped. An empty `INKBRIDGE_DATA_DIR=` line is unset, because an empty value would make the data dir the server directory.
- **The runner's MCP config is generated for the origin being served.** When `INKBRIDGE_RUNNER=claude`, the target runs `scripts/runner_config.py`, which writes the `inkbridge` entry of `mcpServers` in the file named by `INKBRIDGE_RUNNER_MCP_CONFIG` (default `data/runner-mcp.json`, made absolute). For `make serve` the origin is `http://127.0.0.1:8000`. For `make serve-https` it is `https://127.0.0.1:4173` with `SSL_CERT_FILE` set to the CA PEM `data/tls/inkbridge-ca.pem`. `SSL_CERT_FILE` is set only for https, and an https origin with a missing CA file is an error, not a config that fails TLS later.
- **Other servers are kept.** The script replaces only the named entry (`--name`, default `inkbridge`). The vault server the runner needs (`--strict-mcp-config`) stays as it is in the file.
- **No server code change and no migration.** The API still reads `INKBRIDGE_RUNNER_MCP_CONFIG` as before.

## Consequences

- With the runner on, every `make serve` or `make serve-https` rewrites the `inkbridge` entry of the runner config. Hand edits to that entry are lost; edit the other entries freely.
- `INKBRIDGE_RUNNER_MCP_CONFIG` in `.env` selects the file. A relative path is taken from the repo root.
- The vault server entry must be added to the file by hand once.
- The MCP server registered with `claude mcp add` for interactive use is separate. For the https origin, register it with `-e INKBRIDGE_API_URL=https://127.0.0.1:4173 -e SSL_CERT_FILE=<repo>/data/tls/inkbridge-ca.pem` (see the README).
- `make -n` proves the chain, not the TLS round trip. The owner check below proves that.
- If `INKBRIDGE_DATA_DIR` is set in `.env`, `scripts/lan-cert.sh` runs before `.env` is read and still writes to `data/tls`, while the CA path follows `INKBRIDGE_DATA_DIR`. Keep the two equal, or leave the variable unset, until the cert script reads `.env` too.

## Owner checks

- With `INKBRIDGE_RUNNER=claude` in `.env`, run `make serve-https`, ask a question from the tablet, and confirm the runner answers (its MCP call over https trusts the CA).
- The same over `make serve`, on http.
