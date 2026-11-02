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
