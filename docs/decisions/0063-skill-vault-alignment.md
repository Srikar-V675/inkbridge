# 0063 The export skill follows the vault's own rules (INK-106)

Status: accepted. Owner checks pending (real vault export, hand edit and conflict).

## What dominated
Tech ref v4 section 15 and the user's vault (`_CLAUDE.md`) disagree with what the skill wrote: notes
at the vault root, crops in `attachments/inkbridge/`, no vault frontmatter, no `For future agent`
callout, and a re-export that rewrote any changed block even if the user had edited it. The last one
broke the rule that user text is never overwritten.

## What changed
- **`body` hash.** sha256 hex of a block's interior (between the markers) minus any leading
  `> [!warning] Inkbridge` or `> [!conflict] Inkbridge` callouts, so a `removed`/`merged` flag or a
  conflict callout never counts as a user edit. Stored as `body` in each `inkbridge.chunks` entry
  whenever the skill writes a block (new, rewrite, append, recreate). A hash refresh only touches the
  marker line, so `body` stays.
- **Edited block.** The entry has `body` and it differs from the hash of the current interior. An entry
  without `body` (exported before INK-106) is never edited: it is rewritten as before.
- **Conflict.** A `changed` item, or a `replaced` item that would be rewritten, on an edited block is
  not rewritten. The marker line and the entry get the new hash and reading (so `check_sync` is fresh
  next time), `body` stays (so the block stays protected), and a `> [!conflict] Inkbridge` callout with
  the new words goes on top, replacing an earlier conflict callout. `plan` lists these under `conflict`
  (also in `needs_body`). To give a block back to the skill, delete its `body` key.
- **New notes** get the vault frontmatter (`tags: [library]`, `type: library`, `format: reference`,
  optional `index` and `relates`, `publish: false`, `date`, `ai-first: true`, then `inkbridge:`) and
  the collapsed `For future agent` callout before the title.
- **Paths.** Notes in `content/library/<title>.md`, crops in
  `content/raw/attachments/inkbridge/{id}-{hash12}.png`. The CLI creates parent folders and refuses to
  overwrite an existing file on `new`.
- **Style guard.** Words and titles with em/en dashes, arrows, middle dots or emoji are refused with an
  error naming the line.
- **`validate --strict`** checks the frontmatter and callout `new` writes. Plain `validate` and `apply`
  stay lenient. `new` always checks strict.

## Consequences
- Old notes keep working and keep their old embed paths until their blocks are rewritten; crops are not
  moved.
- A block stays protected until its `body` key is removed; no command resets it.
- Whitespace-only edits count as edits (the safe side). A blockquote left directly under a managed
  callout with no blank line between can be ignored by the hash; documented limit.
- Strict validation is for fresh notes (flat YAML as written, before Obsidian reformats properties).
- The backend is unchanged: it never writes the vault and stores no note text. No migration.

## Out of scope
Atoms, project and hub propagation, the profile and refinement loop (INK-142), and a command to reset
`body`.
