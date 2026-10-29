# Canvas to vault note

**Story:** as a note-taker, I want my handwritten page turned into a markdown note whose every block traces back to the ink.

1. In Claude, invoke the `inkbridge-export` skill (`skills/inkbridge-export/SKILL.md`; helper `scripts/inknote.py`).
2. The skill calls `read_canvas` (and `get_region` for chunks with `text: null`), and fetches full-size crops via `GET /regions/{id}/png`.
3. It writes a note into `INKBRIDGE_VAULT` (asks if unset): frontmatter `inkbridge: {canvas, exported, chunks:[{id, hash, reading, section}]}`, one marker block per chunk, a deep link (`INKBRIDGE_PUBLIC_URL?canvas=&chunk=`) and a folded crop preview.
4. The backend stores no note text. Provenance lives in the note.

Rules: drafts are excluded until accepted; text outside marker blocks is never touched. Decision 0021, format `docs/vault-note-format.md`. Walkthrough: `docs/vault-loop-walkthrough.md`.
