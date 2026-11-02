# Eval harness (INK-050)

Offline, deterministic tooling to score recognition, chunking and staleness. The committed set
`data/synthetic-v1` is SYNTHETIC: it proves the harness works and says nothing about handwriting.
The real 12-15 page set is still to be provided (see `data/FORMAT.md`).

## Run

```bash
cd server
uv run python ../eval/run.py chunks                       # E5, offline
uv run python ../eval/run.py transcribe --reader oracle   # E1 base
uv run python ../eval/run.py stale                        # E4 base
```

Each run prints its table and replaces its own section in `eval/results.md`
(`--label NAME` names the section, `--out` and `--data` override paths).
Options: `--reader oracle | noisy:0.1 | gemini | module:attr`, `--allow-model`.

## Models

`test_pages_only: true` is your own assertion that every page is a test page. Leave it false or absent for any page with personal content, and never commit real pages with personal content under `eval/data`.

Nothing here calls a model unless you pass `--allow-model` with any reader other than oracle or noisy (gemini or `module:attr`) on a real set whose
manifest says `"synthetic": false, "test_pages_only": true`, with `GEMINI_API_KEY` in your shell.
Gemini's free tier trains on content: test pages only, never personal notes. Tests never call a
model.

## Add a reader

Any object with `name` and `read(page, chunk) -> Reading` (see `evalkit/readers.py`), passed as
`--reader my_module:my_reader` (the module must be importable). An optional
`read_diagram(page) -> (nodes, edges)` enables the `diagram` experiment.

## Add a real set

Create `eval/data/pages-v1/` following `data/FORMAT.md`, with a manifest
`"synthetic": false, "test_pages_only": true`, and run with `--data eval/data/pages-v1`.
