# 0079 Retrieve across canvases, keyword first (INK-136)

Status: accepted.

## Decisions
1. Two lexical rankers, each its own ranked list: `chunks_fts` (over `region_fts`, active auto chunks only) and `answers_fts` (over `answer_fts`). BM25 scores of two indexes are not comparable, so fusion works on ranks only: reciprocal rank fusion, `score(d) = sum over lists 1 / (60 + rank)`, rank from 1, ties broken by key so output is deterministic. Each ranker returns 50 candidates; the fused list is cut to `k` (1..50, default 8).
2. `answer_fts(question_id UNINDEXED, document_id UNINDEXED, question, answer)` is created by migration 0010 and backfilled by `INSERT ... SELECT` in the same file, so there is no Python backfill. `answer_question` indexes the row in the same transaction as the answer (only when the guarded UPDATE won), so the index cannot lag. Cancelled and pending questions are never indexed. `tests/fts_check.py` checks the index after every test.
3. Scope is `canvas` (default; one `document_id`, `INKBRIDGE_DOCUMENT` on the MCP side, `"default"` on the API side; unknown canvas is 404) or `all`. Under `all`, archived canvases are skipped, as Home hides them; under `canvas` the named canvas is searched even when archived. Orphaned chunks are never returned.
4. Every result has the same fields, `null` when not applicable: `kind` (`chunk` or `answer`), `id`, `chunk_id` (the chunk, or for an answer the first `chunk` source, else null), `canvas`, `canvas_title`, `snippet` (matches in `[ ]`), `deep_link`, `source` (reading source, or `answer`), `score`, `matched_by` (the rankers that returned it, so INK-138 can show why).
5. Read-only: no writes and no links between canvases (decision of 22 Oct holds).
6. Tokenizer stays FTS5 `unicode61` with the existing prefix matching, so `region_fts`, `answer_fts` and `search` behave alike. Whether a trigram index helps with handwriting misreads is E3's question; test it there before adding a second index.
7. Seam for INK-138: add an entry to `db.retrieve.RANKERS` (a function returning best-first dicts with `kind`, `id`, `canvas`, `canvas_title`, `snippet`, `key`). The tool, API and response shape stay as they are.

## Why
One fused list lets an agent ask once and get the best ink and the best past answers. Fusing ranks avoids pretending two BM25 scales compare, and it is the shape a semantic ranker needs later.

## Known gaps
- Vault text is never indexed: nothing reads the vault and a `note` source lives only in `questions.sources_json`. If an agent quoted a note inside its own `answer_md`, that quote is indexed as part of the answer.
- An answer's `chunk_id` is stored as given and may name a chunk that has since been orphaned; the deep link still opens the canvas.
- Canvas briefs do not exist yet, so they are not indexed; that waits for the canvas brief ticket.
- `db/__init__.py` does not re-export `retrieve`: a function of that name would shadow the module and break patching `RANKERS`.
