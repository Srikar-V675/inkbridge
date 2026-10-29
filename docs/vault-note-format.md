# Vault note format

An Inkbridge note is an ordinary markdown file in the user's vault that remembers which ink each
section came from. It is written by an agent with the `inkbridge-export` skill
(`skills/inkbridge-export/`). Inkbridge itself never writes the vault and stores no note text
(decision 0021). `skills/inkbridge-export/scripts/inknote.py validate NOTE` checks a note against
this page.

## Example

````markdown
---
tags: [ml]
inkbridge: {"canvas": "default", "exported": "2026-10-26T10:00:00+00:00", "chunks": [{"id": "9f2a41c07b3e", "hash": "51a8…", "reading": "2d90…", "section": "Gradient descent"}]}
---
# Optimisation

Anything the user writes here is theirs and is never touched.

<!-- ink:9f2a41c07b3e hash:51a8… -->
## Gradient descent

- update: $\theta \leftarrow \theta - \eta \nabla L$

[Open in Inkbridge](http://laptop.local:5173/?canvas=default&chunk=9f2a41c07b3e)
> [!ink]- Source ink
> ![[attachments/inkbridge/9f2a41c07b3e-51a8f2c0d9e1.png]]
<!-- /ink -->
````

Hashes are shortened with `…` above; in a real note they are 64 hex characters.

## Frontmatter

The frontmatter has exactly one line starting with `inkbridge:`. Its value is a JSON object on that
line, which is also valid YAML. Other frontmatter keys belong to the user. Updates rewrite only the
`inkbridge:` line, so the other keys are never re-serialised.

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
  `attachments/inkbridge/{id}-{first 12 hex of hash}.png`. The crop is fetched from
  `GET /regions/{id}/png` and embedded only if it was saved.
- **Outside the blocks:** text belongs to the user and is never changed by a re-export.
- **Line endings:** markers are matched per line on `\n`. Keep the note's line endings as LF.

## Re-export rules (from `check_sync`)

| check_sync status | What happens to the note |
|---|---|
| `fresh` | Nothing. |
| `fresh_after_reread` | Only the entry's `hash` and `reading` and the block's opening marker change. The words stay. |
| `changed` | The block between its markers is rewritten with new words; the entry gets the new hash and reading. |
| `replaced` | The block is rewritten from the successor chunk and its id becomes the successor's. If the successor already has a block in this note, the block is instead flagged `merged`: a warning callout is added at its top and the entry gets `status: merged` and `successor`. |
| `removed` | A warning callout is added once at the top of the block, and the entry gets `status: removed`. The block is not deleted. |
| `new` | A new block is appended at the end of the note, with a new entry. |
| block deleted by the user | Left out. Recreated (appended) only when asked (`--recreate`). |

If nothing needs doing, the file is left byte-identical and `exported` is not touched.
