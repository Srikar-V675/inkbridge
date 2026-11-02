# Eval results

Each section below is written by `eval/run.py` and replaced in place on re-run. Text outside the `<!-- eval:NAME -->` blocks is hand-written and never touched.

<!-- eval:chunks -->
## chunks

_dataset: synthetic-v1, synthetic: yes, reader: none, run: 2026-11-02_

**SYNTHETIC FIXTURES: these numbers only prove the harness and say nothing about handwriting.**

| page | truth chunks | auto chunks | matched (IoU>=0.5) | merge errors | split errors | needs manual fix |
| --- | --- | --- | --- | --- | --- | --- |
| p01-text | 2 | 2 | 1.000 | 0 | 0 | 0.000 |
| p02-equation | 1 | 1 | 1.000 | 0 | 0 | 0.000 |
| p03-diagram | 2 | 2 | 1.000 | 0 | 0 | 0.000 |
| all | 5 | 5 | 1.000 | 0 | 0 | 0.000 |
<!-- /eval -->

<!-- eval:transcribe -->
## transcribe

_dataset: synthetic-v1, synthetic: yes, reader: oracle, run: 2026-11-02_

**SYNTHETIC FIXTURES: these numbers only prove the harness and say nothing about handwriting.**

| kind | n | CER | exact match | mean tokens | total cost usd | mean latency s |
| --- | --- | --- | --- | --- | --- | --- |
| diagram | 1 | 0.000 | - | 0.000 | 0.000 | 0.000 |
| equation | 1 | - | 1.000 | 0.000 | 0.000 | 0.000 |
| handwriting | 3 | 0.000 | - | 0.000 | 0.000 | 0.000 |
| all | 5 | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 |
<!-- /eval -->

<!-- eval:stale -->
## stale

_dataset: synthetic-v1, synthetic: yes, reader: none, run: 2026-11-02_

**SYNTHETIC FIXTURES: these numbers only prove the harness and say nothing about handwriting.**

| page | edit | type | real edit | hash-only flagged | early-cutoff flagged |
| --- | --- | --- | --- | --- | --- |
| p01-text | e1 | move | no | no | no |
| p01-text | e2 | nudge | no | yes | no |
| p01-text | e3 | redraw_identical | no | no | no |
| p01-text | e4 | change_word | yes | yes | yes |
| p03-diagram | e1 | add | yes | yes | yes |
| p03-diagram | e2 | merge | yes | yes | yes |
<!-- /eval -->

<!-- eval:input_repr -->
## input_repr

_dataset: synthetic-v1, synthetic: yes, reader: arms-noisy, run: 2026-11-02_

**SYNTHETIC FIXTURES: these numbers only prove the harness and say nothing about handwriting.**

| arm | n | CER | exact match | mean tokens | total cost usd | mean latency s | fell back | no input |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| image | 5 | 0.091 | 0.000 | 20.800 | 0.000031 | 0.000 | 0 | 0 |
| image+strokes | 5 | 0.068 | 1.000 | 73.000 | 0.000110 | 0.000 | 1 | 0 |
| strokes | 5 | 0.477 | 0.000 | 52.200 | 0.000078 | 0.000 | 0 | 1 |

fixed across arms: image scale 1.0, stroke width 2, stroke budget 1500 tokens
<!-- /eval -->

### E1 finding (INK-051)

1. The table above is a harness proof on SYNTHETIC fixtures with simulated noise (`arms-noisy`, rates 0.05 / 0.02 / 0.2 are inputs, not results). It says nothing about handwriting.
2. Token cost is measured from the real payloads: strokes add about 65 tokens per chunk where ink exists (stroke text `len/4`, 261 over the 4 chunks with ink), against about 21 image tokens per chunk (`ceil(w*h/750)` of the padded crop, 104 over 5 chunks).
3. Fixed across arms: image scale 1.0, stroke width 2, stroke budget 1500 tokens; image+strokes falls back to image when it has no strokes or they exceed the budget (1 chunk fell back here, the diagram).
4. Caveat: published gains from stroke input come from research models, not API calls; Excalidraw has no per-point timing, so the strokes carry order and pressure only.
5. Default: `read_canvas` keeps the image by default. Strokes become the default only if the real-data run (`eval/data/pages-v1`, `--allow-model`) shows a clear win; there is not enough evidence for strokes yet.
