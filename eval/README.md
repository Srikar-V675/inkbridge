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
uv run python ../eval/run.py input_repr --reader arms-noisy:image=0.05,image+strokes=0.02,strokes=0.2  # E1 arms
```

Each run prints its table and replaces its own section in `eval/results.md`
(`--label NAME` names the section, `--out` and `--data` override paths).
Options: `--reader oracle | noisy:0.1 | arms-noisy:image=R,image+strokes=R,strokes=R | gemini | module:attr`, `--allow-model`.

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

## E1: input representation (INK-051)

`input_repr` compares three inputs for each chunk: the image only, the image plus compact strokes,
and the strokes only (`evalkit/arms.py`, decision 0034). The committed table runs on the synthetic
set with simulated noise, so it shows the harness, not handwriting. The real run needs a reader
that implements `read_arm(page, chunk, payload)` (it sees the strokes); a reader that does not is
refused for this experiment. Put it in a module, then run it on your own set, with the same
`test_pages_only` gate as Gemini (your assertion; never use personal pages):

```bash
cd server
uv run python ../eval/run.py input_repr --data eval/data/pages-v1 --reader my_module:arm_reader --allow-model
```

## Add a real set

Create `eval/data/pages-v1/` following `data/FORMAT.md`, with a manifest
`"synthetic": false, "test_pages_only": true`, and run with `--data eval/data/pages-v1`.
