# 0062 Deep links on the served origin, and the export skill installed for every session (INK-105)

Status: accepted. Owner checks pending (tablet tap, real vault).

## What dominated
Links built by the API pointed at the Vite dev port (5173), which INK-100 (decision 0057) stopped serving
for the tablet: the app is now served from :8000. A link tapped on the tablet opened nothing. The export
skill also could not run outside the repo: its instructions set a repo-relative helper path and told the
agent to run it "from the repo or copy it", so a session in another folder had no working helper.

## What changed
- `config.DEFAULT_PUBLIC_URL` is `http://localhost:8000`, the API's own served origin. This supersedes the
  "stays 5173" line in 0057. `INKBRIDGE_PUBLIC_URL` still overrides it. `make dev-web` users on :5173 set it.
- The API cannot know its LAN name (the MCP client reaches it on 127.0.0.1), so a `.local` name stays an
  env setting. `.env.example`, README and `docs/codewiki/env-vars.md` say so.
- The web app builds no links. The socket URL already uses `window.location.host`. Nothing in `web/` changes.
- The skill finds its helper from its own directory: `D=$(dirname "$(readlink -f "<base directory>/SKILL.md")")`,
  then `$D/scripts/inknote.py`. The helper is stdlib-only, so it runs from any working directory. The note
  format is `$D/../../docs/vault-note-format.md` when the skill is a symlink into the repo.
- `make install-skill` symlinks `skills/inkbridge-export` into `~/.claude/skills`. A `git pull` updates it,
  and every session sees it. Tests pin both points: no repo-relative `H=` line, and the helper runs from a
  symlink outside the repo.
- MCP is registered once at user scope (`claude mcp add --scope user inkbridge ...`), so the tools are
  available in every project. Tool rows in `docs/mcp-tools.md` do not change.

## What it does not do
- No host detection from the request `Host` header. MCP reaches the API on 127.0.0.1, so it would emit a
  loopback link. The env setting is the source of truth.
- No change to existing notes. Links already written with `localhost:5173` stay as written; they open only
  while the Vite dev server runs. Whether a re-export refreshes them depends on the note's block layout
  (not checked here).
- Claude Desktop has no shell and does not supply "Base directory for this skill". It keeps the manual
  section of SKILL.md.
