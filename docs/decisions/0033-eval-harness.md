# 0033: Eval harness and dataset format

Status: accepted (INK-050). Code: `eval/` (`evalkit/`, `run.py`, `make_synthetic.py`,
`data/FORMAT.md`), tests `server/tests/test_eval_*.py`.

1. **`eval/` at the repo root, not under `server/`.** It is a developer tool, not shipped in the
   wheel, and scene/PNG data does not belong in the package tree. Code is the small package
   `eval/evalkit/` so imports do not collide with generic names. `.gitignore` ignores `data/`
   (the runtime data dir), so `!eval/data/` re-includes the datasets.
2. **Lint and tests ride the existing jobs.** `make lint` and the CI server job run
   `ruff check` on `../eval`. evalkit tests live in `server/tests/test_eval_*.py` and put `eval/`
   on `sys.path`, so `make test` and CI need no new job. `eval/run.py` imports `inkbridge`
   (chunker, hashes), so it runs as `cd server && uv run python ../eval/run.py ...`. It reuses
   `content_hash`/`text_hash`/`bbox_of`; the hash allow-lists are never reimplemented.
3. **Results are named sections in `eval/results.md`**: `<!-- eval:NAME -->` ... `<!-- /eval -->`.
   Re-running an experiment replaces only its own block, so INK-051/052/061 and hand-written
   findings never clobber each other.
4. **Readers are pluggable.** Built-ins: `oracle`, `noisy:RATE` (seeded, for self-tests) and
   `gemini`; `module:attr` loads any object with `name` and `read(page, chunk)` (the E1 arms of
   INK-051). The Gemini reader is behind a gate (`load_gemini_reader`): it needs `--allow-model`,
   a manifest with `test_pages_only: true`, a non-synthetic set, `GEMINI_API_KEY`, and a
   `page.png` for every page. The CLI exits 2 on refusal. Tests never reach a model.
5. **Edits are scripts of four ops** (`add`, `delete`, `translate`, `redraw`), so every INK-052
   edit type is expressible without new code. `meaning_changed` is the ground truth for a real
   edit; `text_after` is the expected reading.
6. **Synthetic fixtures are a harness proof only.** `eval/data/synthetic-v1` is generated
   deterministically (`make_synthetic.py`, drift guarded by a test), carries `synthetic: true`
   everywhere and prints a banner in every result section. It says nothing about handwriting; the
   real 12-15 page set is supplied by the user (list in `eval/data/FORMAT.md`).
7. **`stale` is a pure-function model of `check_sync`** (hash-only vs early cutoff). INK-052 must
   reconcile it with `db/sync.py` and may replace the body; the table shape is the contract.
