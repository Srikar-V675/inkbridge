# Deep Dive: vault export skill (`skills/inkbridge-export/`, `inknote.py`)

> Snapshot written 26 Oct 2026; sections marked Updated 13 Nov 2026 were refreshed.

The backend never writes the vault. The skill (`SKILL.md`, 5.6K) tells an agent how to export a canvas to a note and keep it fresh; `scripts/inknote.py` (about 1,000 lines by 13 Nov 2026, **standard library only**, Python 3.11+) does the mechanical parts so text outside the markers and every unchanged block stay **byte-identical**. Decision 0021; format `docs/vault-note-format.md`; end-to-end run `scripts/vault_loop_e2e.py` (decision 0022).

## What changed since 26 Oct (Updated 13 Nov 2026)

The sections below describe the 26 Oct helper. The mechanics (parse, validate, plan, apply, atomic writes) are unchanged; the note shape and the skill's behaviour moved toward the user's vault. Decisions 0062, 0063, 0103, 0125; format in `docs/vault-note-format.md`.

- **Install and vault alignment** (INK-105, INK-106, decisions 0062, 0063). `make install-skill` symlinks the skill into `~/.claude/skills`; the skill finds its helper from its own directory, so it works from any session. New notes follow the vault's rules: `content/library/<title>.md`, frontmatter `tags: [library]`, `type: library`, `format: reference`, optional `index` and `relates`, `publish: false`, `date`, `ai-first: true`, then the one-line `inkbridge:` entry; crops go to `content/raw/attachments/inkbridge/`. The skill reads `$INKBRIDGE_VAULT/_CLAUDE.md` at the start of every export and the vault's rules win.
- **Callout, source key, Related Notes** (INK-210, decision 0125). `inknote.py new` takes `--summary`. The collapsed `> [!info]- For future agent` callout carries the summary, a line `Saved <date> from the Inkbridge canvas <id>.` and then the provenance lines. `source: inkbridge` joins the frontmatter. When `--relates` is given, `new_note` also closes the note with a `## Related Notes` list; blocks appended on re-export go above that list. Nothing outside the markers is touched on re-export. SKILL.md gained a "Write like this vault" section (keep the user's words, keep their questions and gaps as theirs, atoms in `wiki/concepts/` are proposed and never created unasked, the project hub is never edited); only the dash, arrow and emoji ban is checked by `validate`.
- **Entries carry `body`** (INK-106). Each `inkbridge.chunks` entry has a `body` hash (`_body_hash` over the block interior, ignoring leading `[!warning]` and `[!conflict] Inkbridge` callouts, `ENTRY_KEYS` now includes `body`). A block whose interior no longer matches `body` was edited by the user: `apply` does not rewrite it and adds a `[!conflict] Inkbridge` callout with the new reading (`_edited`, `_conflict_callout`, plan bucket `conflict`). Deleting the entry's `body` key hands the block back to the skill.
- **Diagram chunks.** Readings of diagrams now carry relation lines (`a -> b`, decision 0123); the skill turns them into mermaid edges. The skill does not export `kind: connector` chunks.
- **Learning loop** (INK-142, decision 0103). Subcommands grew to `canvas`, `crops`, `new`, `validate`, `sync`, `plan`, `apply`, `learn`, `rules`. `learn NOTE --vault V` finds hand-edited blocks (old text from the vault's git history: the first revision whose block hashes to `body`; no history is listed under `no_history`, never an error), records them under `## Observed edits` in `meta/Inkbridge Export Profile.md`, and writes a `### ... ` proposal under `## Proposals` once 3 distinct chunks show the same pattern. Kinds are a closed set (`RULE_KINDS`: heading question, heading level, crop removed). Proposals are never applied by the agent: only `Status: approved`, set by the user, makes a rule active, and `rules` prints the approved ones for the agent to follow when writing words. Rules cannot touch markers, hashes, `apply` or `validate`. Learning needs the helper, so Claude Desktop without a shell does not learn.
- **Without the helper** the skill documents the by-hand path (format, `body` hash, one-line JSON frontmatter).
- **MCP tools.** The skill uses `read_canvas`, `get_region` and `check_sync`, passing `document_id` when the canvas is not the default.

## Skill rules (`SKILL.md`, 26 Oct snapshot)

- The agent writes the words of each block; the helper builds, checks and updates the note around them.
- Text outside `<!-- ink:ID hash:H -->` ... `<!-- /ink -->` is the user's; never changed.
- Rewrite only blocks `check_sync` reports as `changed` or `replaced`; do not recreate a block the user deleted unless asked.
- Never request recognition of a canvas that is not in `INKBRIDGE_RECOGNIZE_DOCUMENTS` (Gemini privacy).
- Vault folder: `$INKBRIDGE_VAULT` or ask. Crops go in `attachments/inkbridge/`.

First export: `read_canvas` -> `get_region` for chunks with `text: null`, diagrams or doubtful readings -> `inknote.py canvas` -> agent writes `bodies.json` (`{chunk_id: markdown}`; a heading becomes the section, `$...$` for maths, a mermaid block for diagrams) -> `crops` -> `new` -> `validate`. Re-export: `sync` -> `plan` -> write bodies only for `needs_body` -> `crops` -> `apply` -> `validate`. Without a shell (Claude Desktop) follow the format by hand.

## Parsing (`parse`, `inknote.py:91-136`)

- Refuses CRLF ("convert to LF first; nothing was changed").
- Requires frontmatter opening `---\n`, exactly one `inkbridge:` line whose value is JSON on that single line (valid YAML too), and a closing `---`. Other frontmatter keys are never re-serialised: updates replace only the byte span of the `inkbridge:` line (`meta_span`).
- Blocks: opening marker regex `^<!-- ink:ID hash:64hex -->$` (id `[A-Za-z0-9_-]{1,64}`), closing `<!-- /ink -->`. Errors on a block not closed before another opens, a stray closing marker, an unclosed block, and any other line starting `<!-- ink:` or `<!-- /ink` (malformed marker). Each `Block` records byte offsets (`start`, `end`, `body_start`, `body_end`) so edits are splices.

## Validation (`validate`, `:142-195`)

Unknown top-level keys; `canvas` non-empty string; `exported` ISO-8601; per entry: only keys `id, hash, reading, section, status, successor, body` (`body` added after 26 Oct); unique non-empty `id`; `hash` 64 hex; `reading` 64 hex or null; `section` string or null; `status` in `{removed, merged}`; `merged` needs a string `successor`. Per block: no duplicates; each block has an entry; the marker hash equals the entry hash. Prints `{"valid": bool, "errors": [...]}`; exit 1 when invalid.

## Building blocks (`render_block`, `:221-235`)

Checks id, hash and `deep_link` are plain (no whitespace, `<`, `>` or parentheses: they land in file names and markdown links), refuses bodies containing an ink marker (an agent could otherwise break the note), then emits:
```
<!-- ink:ID hash:H -->
<body>

[Open in Inkbridge](<deep_link>)
> [!ink]- Source ink
> ![[attachments/inkbridge/<id>-<first 12 of hash>.png]]
<!-- /ink -->
```
The crop callout is included when no vault is given or the file exists. Section = the block's own first heading else the nearest heading above (`_section`), recomputed on every export (`_refresh_sections`).

`new_note` takes only chunks that have a body and are `active`, in the canvas's reading order, erroring on bodies for chunks not active.

## Plan (`plan`, `:312-349`)

| Bucket | Source |
|---|---|
| `unchanged` | `fresh` |
| `refresh_hash` | `fresh_after_reread` |
| `rewrite` + `needs_body` | `changed` for a chunk with a block; `replaced` whose successor has no block yet (the successor then counts as taken, so two replaced entries sharing one successor rewrite once) |
| `merged` | `replaced` whose successor already has a block |
| `flag_removed` | `removed`, if a block exists and the entry has no status yet |
| `append` + `needs_body` | `new` |
| `user_deleted` | `changed`/`replaced` for a chunk whose block the user removed |

## Apply (`apply`, `:361-463`)

Collects splices `(start, end, replacement)` against the original text:
- `changed`: replace the whole block; entry gets the new hash and reading.
- `replaced` (rewrite): replace the block with one for the successor; the entry is cleared and re-keyed to the successor id.
- `replaced` (merged): insert a warning callout at the body start and set entry `status: merged`, `successor`.
- `fresh_after_reread`: only the opening marker line and the entry's hash/reading change; the words stay.
- `flag_removed`: insert "> [!warning] Inkbridge: this ink is no longer on the canvas." and `status: removed`.
- `new` (and `--recreate` for user-deleted blocks): rendered blocks appended at the end.
- A rewrite wins over a hash refresh or flag on the same block. If nothing changed the text is returned unchanged and `exported` is not touched. Splices are checked for overlap ("touches one block twice; nothing was changed"), applied from the end backwards, then the result must `validate` (`_checked`).

## CLI and HTTP

Subcommands `canvas`, `crops`, `new`, `validate`, `sync`, `plan`, `apply`. HTTP uses `urllib` only: `GET /documents/{id}/chunks`, `GET /regions/{id}/png`, `POST /documents/{id}/check_sync` (timeout `wait_s + 30`; only entries without a `status` are sent, since flagged ones are settled). Files are written atomically (temp file then rename); an unchanged note is not rewritten, preserving mtime. Exit codes: 0 ok, 1 invalid/crop failures, 2 note or input error, 3 API or IO error.

## End-to-end harness (`scripts/vault_loop_e2e.py`, 296 lines)

Runs the loop against a live API on a **throwaway database** (never point it at real notes). It loads `inknote.py` via `importlib`, plays the user (writes scenes over HTTP) and the recognition worker (writes readings straight into the throwaway DB with `db.save_recognition`, source `user`; nothing goes to Gemini).
- **Page** (`page_elements`): a heading word of 6 strokes, two lines of 5 and 4 strokes (strokes 15 px apart, i.e. one chunk each at `k = 1.5`), and two rectangles joined by a long bound arrow. Expected: exactly 5 chunks (asserted).
- **Steps**: first export (valid note, the harness inserts a user remark between blocks), then (1) **nudge** one stroke 0.4 px: the reading is re-saved, `check_sync` must show no `changed`/`replaced`, `needs_body` empty, and no block's words differ after `apply`; (2) **move** the diagram 300 px: all five `fresh`, `apply` returns the note unchanged; (3) **edit one line**: add a stroke to "momentum", new reading "momentum beta = 0.9", re-upload the stale crop; exactly one `changed`, one rewrite, only that block differs, the user remark survives and the note validates.
- **`tune()`** prints three markdown tables used by decision 0022: chunk counts for `k` in 1.0 to 3.0 against word gaps 20 to 90 px; line pitch 40 and 60 px against `k`; and id retention for a chunk of n strokes gaining g strokes (`n / (n + g) > match_threshold` keeps the id, so a 1-stroke chunk always gets a new id).
Output is the walkthrough in `docs/vault-loop-walkthrough.md`.

## Testing

`server/tests/test_vault_export.py` (19K) drives the helper against a live API; `scripts/vault_loop_e2e.py` plays the user and the recognition worker on a throwaway DB, and its result is in `docs/vault-loop-walkthrough.md` (a nudge refreshes one hash and no words; a move flags nothing; one changed line rewrites one block). Real handwritten pages are still pending (decision 0022).
