# 0021: Vault export skill: agent writes the words, a helper keeps the note byte-safe

Status: accepted (INK-037). Implements tech ref 9.6 and 9.7; format in `docs/vault-note-format.md`.

- **Split of work.** `skills/inkbridge-export/SKILL.md` tells the agent how to read the canvas
  (`read_canvas`, `get_region` for hard chunks) and how to write each block's words as a study
  note (headings, bullets, LaTeX, Mermaid for diagrams). The mechanics are done by
  `skills/inkbridge-export/scripts/inknote.py`, which uses only the standard library: building
  a note, validating it, planning and applying a `check_sync` result, and saving crops. Those
  rules are where "byte-identical outside the markers" lives, and a model cannot be trusted to
  reproduce them reliably. The script runs under the agent's own file access; the Inkbridge API
  never writes the vault. Claude Desktop without a shell follows the same format by hand. Its
  check is INK-039.
- **Frontmatter as one JSON line.** `inkbridge: {...}` is a JSON object on one line, which is
  valid YAML. Re-exports rewrite only that line, so the user's own frontmatter keys are never
  re-serialised and need no YAML library. The cost is a long line in the file. Obsidian still shows
  it as a property.
- **Markers carry the full content hash**, so a block can be checked against the frontmatter
  (`validate`).
- **Re-export rules:**
  - `fresh_after_reread` changes only the entry and the opening marker line.
  - `replaced` rewrites the block from its successor. If the successor already has a block (a
    merge reported twice), the block is flagged `merged` with a pointer instead, so the same words
    are not written twice.
  - `removed` is flagged with a callout once and never deleted. Entries with a `status` are not
    sent to `check_sync` again.
  - `new` is appended at the end of the note.
  - A block the user deleted is not recreated without `--recreate`.
  - When nothing needs doing, the note is returned byte-identical, including `exported`.
- **Crops:** `attachments/inkbridge/{id}-{hash[:12]}.png`, from `GET /regions/{id}/png`. A new
  ink version gets a new file name, so an old note's preview never silently shows newer ink. A
  chunk without a stored crop gets no embed rather than a broken one.
- **`read_canvas` gains `text_hash`.** It is the value the note stores as `reading`.
  `GET /documents/{id}/chunks` already had it.
- **Vault location** is still an open question. The skill uses `INKBRIDGE_VAULT`, else asks the
  user.
- **Line endings:** LF. A CRLF note is refused with a message and left untouched (never silently converted).
- **Safety of the helper:** ids and hashes from the canvas must be plain (`[A-Za-z0-9_-]`, 64-hex) because they become file names and marker lines; words containing an ink marker are refused; every note the helper returns is validated first; writes go through a temp file and rename, and an unchanged note is not written at all. When one block is hit twice by a sync result, a rewrite wins over a hash refresh or a flag, and any remaining overlap is refused.
