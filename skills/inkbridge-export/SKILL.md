---
name: inkbridge-export
description: Turn an Inkbridge handwritten canvas into an Obsidian vault note that keeps its provenance, or re-export an existing note so only the sections whose ink changed meaning are rewritten. Use when the user asks to export, sync or update a note from their Inkbridge canvas.
---

# Inkbridge canvas -> vault note

You turn a handwritten canvas into a markdown note in the user's vault, and later bring that note
up to date without clobbering anything the user wrote. The note format is specified in
`docs/vault-note-format.md` in the Inkbridge repo (`$D/../../docs/`, see Helper below). Read it once
if anything below is unclear.

**Rules.**
- Inkbridge never writes the vault. You write the note with your own file tools, or with the helper
  script below, which runs under your own file access.
- Text outside the `<!-- ink:ID hash:H -->` ... `<!-- /ink -->` markers is the user's. Never change
  it.
- Only rewrite the blocks that `check_sync` reports as `changed` or `replaced`.
- Do not recreate a block the user deleted unless they ask you to.
- Read `$INKBRIDGE_VAULT/_CLAUDE.md` at the start of every export. The vault's rules win over this
  skill's defaults for folders, frontmatter and writing style.
- Do not write a daily note, a board or a task, and never overwrite the vault's `index.md`.
- Never overwrite a block the user edited. The helper detects it (the entry's `body` hash) and
  writes a conflict callout instead; tell the user which blocks have one.
- No em or en dashes, arrows, middle dots or emojis in anything you write. Use `-`, `->` and commas.
- Personal notes are read by you, not by Gemini. Never ask for recognition of a canvas the user has
  not opted in (`INKBRIDGE_RECOGNIZE_DOCUMENTS` on the API).

## Setup

- **Vault folder:** use `$INKBRIDGE_VAULT` if it is set. Otherwise ask the user where their vault
  is, and suggest they set `INKBRIDGE_VAULT`. Notes go to `content/library/<title>.md` (make the
  title safe as a file name: none of `/ \ : * ? " < > |`). Crops go to
  `content/raw/attachments/inkbridge/`.
- **Index and links:** pick `--index` from the `.base` files in the vault's `indexes/` folder (ask
  if none fits; omit it if the user has none). Pass `--relates` for existing notes the canvas
  obviously continues (optional).
- **API:** `$INKBRIDGE_API_URL` (default `http://127.0.0.1:8000`); the canvas id is
  `$INKBRIDGE_DOCUMENT` (default `default`) unless the user names one.
- **Helper:** `scripts/inknote.py` inside this skill's directory (the folder this SKILL.md was loaded
  from; Claude Code prints it as "Base directory for this skill"). It needs only Python 3.11+ and
  works from any working directory. Write its JSON inputs to a scratch folder, not into the vault.

```
D=$(dirname "$(readlink -f "<base directory>/SKILL.md")")   # follows the symlink made by make install-skill
H="$D/scripts/inknote.py"
```

These shell variables do not persist between Bash calls, so repeat the two lines (or inline the path) in every call that uses `$H`.

`$D/../../docs/vault-note-format.md` is the note format when this skill is a symlink into the repo.
If it is not there, ask the user for the repo path.

## First export

1. Call the MCP tool `read_canvas` (with `document_id` if not the default). Look at the overview
   image and the chunks in reading order. For each chunk you will use `text`, `latex`, `kind`,
   `content_hash`, `text_hash` and `deep_link`.
2. For any chunk whose `text` is null, or that is a diagram, or whose reading looks wrong, call
   `get_region` with its id and read the crop yourself.
3. Save the outline for the helper: `python3 $H canvas --document ID > /tmp/inkb/canvas.json`.
   This is the same data as `read_canvas`, as JSON.
4. Write the words of each block into `/tmp/inkb/bodies.json` as `{chunk_id: markdown}`. Make it a
   real study note, not a transcript:
   - Start a block with a heading (`##` or `###`) when it opens a topic; that heading becomes its
     `section`.
   - Use bullet points for lists, `$...$` / `$$...$$` for maths (prefer the chunk's `latex`), and
     a ```` ```mermaid ```` flowchart for a chunk you recognise as a diagram (boxes and arrows).
   - Keep each block about its own chunk. Leave out a chunk only if it is noise; leave it out of
     `bodies.json` too.
5. Save the crops: `python3 $H crops /tmp/inkb/canvas.json --vault "$INKBRIDGE_VAULT"`. Chunks
   without a stored crop are reported under `failed` and simply get no preview.
6. Build and check the note:
   `python3 $H new /tmp/inkb/canvas.json /tmp/inkb/bodies.json --title "TITLE" --vault "$INKBRIDGE_VAULT" --index "[[X.base]]" --relates "[[A]]" --out "$INKBRIDGE_VAULT/content/library/TITLE.md"`,
   then `python3 $H validate "$INKBRIDGE_VAULT/content/library/TITLE.md" --strict` (it must print
   `"valid": true`). Then call `obsidian_validate_note` on the note when the vault MCP is
   available; if it reports a failure, say so and do not call the export done.
7. Tell the user where the note is, how many sections it has, and which chunks had no reading or
   no crop.

## Re-export (sync an existing note)

1. `python3 $H sync NOTE.md > /tmp/inkb/sync.json`. This calls `check_sync`; with MCP only, call the
   `check_sync` tool with the frontmatter `chunks` (`id`, `hash`, `reading`; skip entries that have
   a `status`).
2. `python3 $H plan NOTE.md /tmp/inkb/sync.json` lists what will happen:
   - `unchanged`: fresh chunks, left byte for byte.
   - `refresh_hash`: the ink moved or was redrawn but reads the same. Only the stored hash changes,
     never the words.
   - `rewrite`: changed or replaced chunks; their blocks get new words.
   - `conflict`: the user edited the block, so it is not rewritten. A `[!conflict]` callout with
     the new reading is added on top and the user merges by hand. To give a block back to the
     skill, delete its `body` key in the frontmatter entry.
   - `merged`: replaced by a chunk that already has a block; the block is flagged, not rewritten.
   - `flag_removed`: ink gone from the canvas; a warning callout is added at the top of the block.
   - `append`: new chunks, added at the end of the note.
   - `user_deleted`: the user removed the block; it is left out unless they ask for it back.
   - `needs_body`: the chunk ids you must write words for (`conflict` ids are in it, like `rewrite`).
3. Refresh the canvas JSON (`canvas` command), read the chunks listed in `needs_body` (with
   `read_canvas` / `get_region` as above), and write only those into `/tmp/inkb/bodies.json`.
   `changed` with `reading: null` means no machine reading came back in time: look at the crop with
   `get_region`.
4. Run `crops` again (new ink gets a new crop file), then
   `python3 $H apply NOTE.md /tmp/inkb/sync.json /tmp/inkb/canvas.json /tmp/inkb/bodies.json --vault "$INKBRIDGE_VAULT"`.
   Add `--recreate` only if the user asked for deleted blocks back. Then run `validate`.
5. Report it the way the user sees it, for example "1 section updated, 2 hashes refreshed, 1 new,
   1 removed". If nothing changed, say so: the file is untouched.

## Without the helper (Claude Desktop, no shell)

Follow `docs/vault-note-format.md` by hand:
- Notes live in `content/library/`, crops in `content/raw/attachments/inkbridge/`. The frontmatter
  has `tags: [library]` (one type tag), `type: library`, `format: reference`, `publish: false`,
  `date`, `ai-first: true`, then the `inkbridge:` line; the collapsed `> [!info]- For future agent`
  callout follows it. No daily note, same style rule as above.
- Each entry carries `body`: the sha256 of the block interior (between the markers), ignoring
  leading `[!warning]` / `[!conflict] Inkbridge` callouts. Never overwrite a block whose hash no
  longer matches `body`; add a `[!conflict]` callout with the new reading instead.
- Write the frontmatter line `inkbridge: {"canvas": ..., "exported": ..., "chunks": [...]}` as one
  line of JSON.
- Write one marker block per chunk.
- On re-export, edit only the blocks and the `inkbridge:` line that `check_sync` points at.
