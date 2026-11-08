# Vault note format

An Inkbridge note is an ordinary markdown file in the user's vault that remembers which ink each
section came from. It is written by an agent with the `inkbridge-export` skill
(`skills/inkbridge-export/`). Inkbridge itself never writes the vault and stores no note text
(decision 0021). `skills/inkbridge-export/scripts/inknote.py validate NOTE` checks a note against
this page.

## Example

````markdown
---
tags: [library]
type: library
format: reference
index: "[[Machine Learning & AI.base]]"
publish: false
date: 2026-10-26
ai-first: true
inkbridge: {"canvas": "default", "exported": "2026-10-26T10:00:00+00:00", "chunks": [{"id": "9f2a41c07b3e", "hash": "51a8…", "reading": "2d90…", "section": "Gradient descent", "body": "c41e…"}]}
---
> [!info]- For future agent
> Provenance note for an Inkbridge canvas. Text between ink markers is managed by the
> inkbridge-export skill and synced with check_sync. Text outside the markers is the
> user's and is never changed.

# Optimisation

Anything the user writes here is theirs and is never touched.

<!-- ink:9f2a41c07b3e hash:51a8… -->
## Gradient descent

- update: $\theta \leftarrow \theta - \eta \nabla L$

[Open in Inkbridge](http://laptop.local:8000/?canvas=default&chunk=9f2a41c07b3e)
> [!ink]- Source ink
> ![[content/raw/attachments/inkbridge/9f2a41c07b3e-51a8f2c0d9e1.png]]
<!-- /ink -->
````

Hashes are shortened with `…` above; in a real note they are 64 hex characters.

## Frontmatter

The frontmatter has exactly one line starting with `inkbridge:`. Its value is a JSON object on that
line, which is also valid YAML. Other frontmatter keys belong to the user. Updates rewrite only the
`inkbridge:` line, so the other keys are never re-serialised.

The vault's own standard is `~/Documents/kaizen/_CLAUDE.md`; `new` writes the keys it asks for
(a note under `content/library/`). Other keys belong to the user.

| Key | Value |
|---|---|
| `tags` | `[library]`, exactly one type tag |
| `type` | `library` |
| `format` | `reference` (the vault also allows `course`, `book`, `video`) |
| `index` | optional, `"[[Name.base]]"` |
| `relates` | optional, a list of `"[[Note]]"` links |
| `publish` | `false` |
| `date` | `YYYY-MM-DD`, the day of the first export |
| `ai-first` | `true` |

`inknote.py validate NOTE --strict` checks these keys and the callout; plain `validate` stays
lenient so notes exported before this format can still be re-exported.

| Key | Type | Meaning |
|---|---|---|
| `canvas` | non-empty string | The canvas (document) id. |
| `exported` | ISO-8601 timestamp | The last time an export changed this note. |
| `chunks` | list | One entry per chunk the note was made from, in the note's order. No other keys are allowed. |

Each `chunks` entry:

| Key | Type | Meaning |
|---|---|---|
| `id` | string, unique in the list | Chunk id (12 hex for chunks). |
| `hash` | 64 hex | The chunk's **content hash** when its block was last written (position-independent). |
| `reading` | 64 hex or null | The **reading hash** (`text_hash`) of the reading the block was written from; null if there was none. |
| `section` | string or null | The heading the block sits under: its own first heading, else the nearest heading above it. Recomputed on every export. |
| `status` | optional: `removed` or `merged` | Set when `check_sync` reported the ink gone (`removed`), or replaced by a chunk that already has a block (`merged`). Entries with a status are not sent to `check_sync` again. |
| `successor` | string, with `status: merged` | The chunk whose block now carries this ink. |
| `body` | 64 hex, optional | sha256 of the block interior as the skill wrote it, ignoring leading `[!warning]` and `[!conflict]` Inkbridge callouts. A block whose interior no longer matches was edited by the user and is never rewritten. An entry without `body` (a note from before this key) counts as possibly edited: if its ink changes it gets a conflict callout and `body` is set from its current text. |

## Blocks

```
<!-- ink:ID hash:HASH -->
...the agent's words...
<!-- /ink -->
```

- **Markers** each sit on a line of their own. `ID` is the chunk id and `HASH` is the same content
  hash as the frontmatter entry. Blocks do not nest. Every block has a frontmatter entry, and an
  id appears in at most one block.
- **Inside a block:** the words (headings, bullets, LaTeX, Mermaid for diagrams), then a plain-URL
  deep link `[Open in Inkbridge](<deep_link>)` that opens the canvas at the chunk (INK-035). Last
  comes a folded callout `> [!ink]- Source ink` embedding the crop
  `content/raw/attachments/inkbridge/{id}-{first 12 hex of hash}.png`. The crop is fetched from
  `GET /regions/{id}/png` and embedded only if it was saved.
- **Interior:** everything between the two markers is what `body` hashes.
- **Style:** words and titles use `-`, `->` and commas: no em or en dashes, arrows, middle dots
  or emojis (the helper refuses them).
- **Outside the blocks:** text belongs to the user and is never changed by a re-export.
- **Line endings:** markers are matched per line on `\n`. Keep the note's line endings as LF.

## Re-export rules (from `check_sync`)

| check_sync status | What happens to the note |
|---|---|
| `fresh` | Nothing. |
| `fresh_after_reread` | Only the entry's `hash` and `reading` and the block's opening marker change. The words stay. |
| `changed` | The block between its markers is rewritten with new words; the entry gets the new hash and reading. |
| `changed` or `replaced`, block edited by the user | Not rewritten. The marker line and the entry get the new hash and reading, `body` stays, and a `[!conflict]` callout with the new reading goes on top of the block (replacing an earlier one). |
| `replaced` | The block is rewritten from the successor chunk and its id becomes the successor's. If the successor already has a block in this note, the block is instead flagged `merged`: a warning callout is added at its top and the entry gets `status: merged` and `successor`. |
| `removed` | A warning callout is added once at the top of the block, and the entry gets `status: removed`. The block is not deleted. |
| `new` | A new block is appended at the end of the note, with a new entry. |
| block deleted by the user | Left out. Recreated (appended) only when asked (`--recreate`). |

**Conflict callout.** It starts `> [!conflict] Inkbridge:` and quotes the new words. The user merges
by hand and deletes the callout. Because `body` is unchanged, the block stays protected until the
`body` key is removed from its entry, which hands the block back to the skill. The entry's hash and
reading move to the new values at once, so deleting the callout without merging hides the drift.

If nothing needs doing, the file is left byte-identical and `exported` is not touched.

## Export profile

`<vault>/meta/Inkbridge Export Profile.md` is the user's file. The helper (`inknote.py learn`)
only appends inside two sections it creates when missing, `## Observed edits` and `## Proposals`;
every other byte is left alone. Learning never writes the note.

An edit is a block whose entry has `body` and whose current interior hashes differently. The old
text is the first revision in the vault's git history of the note whose block hashes to `body`; with
no repository or no such revision the block is skipped (`no_history`).

Kinds (closed set): `heading_question` (first heading became a question), `heading_level` (heading
level changed), `crop_removed` (the `Source ink` callout was removed).

Observed line (one per kind, block and new text; repeats are skipped):

```
- 2026-11-08 heading_question Optimisation#<chunk_id> <sha8 of the new text>
```

When 3 distinct blocks show one kind and the kind has no `###` heading in `## Proposals` yet (any
status, so a rejected one is not proposed again), the helper appends:

```
### 2026-11-08 heading_question
- Status: proposed
- Before: ## gradient descent
- After: ## What is gradient descent?
- Evidence: 3 edits (Optimisation#a0, Optimisation#b0, Optimisation#c0)
- Confidence: low
```

Confidence is low for 3 edits, medium for 4 to 5, high for 6 or more. The user approves by changing
the line to `- Status: approved`; anything else is inert. `inknote.py rules` prints approved
proposals of a known kind as JSON, and the agent follows them when writing words. Rules never reach
markers, `body`, hashes, provenance or `apply`/`validate`.
