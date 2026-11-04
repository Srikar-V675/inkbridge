# 0034: Eval input representation (E1, INK-051)

Status: accepted (INK-051). Code: `eval/evalkit/arms.py` (payloads, `arm_read`, `ArmNoisy`),
`eval/evalkit/experiments.py` (`run_input_repr`), `eval/run.py`; tests
`server/tests/test_eval_arms.py`. Result: `eval/results.md` (synthetic only, default unchanged).

1. **Payloads come from real code, only the model is simulated.** `build_payload` reads the
   page's own elements and the chunk box, so token counts are measured from the payload that
   would be sent. Image tokens are the documented estimate `ceil(w*h/750)` of the padded crop
   (`PAD = 8`, `IMAGE_SCALE = 1.0`). Stroke tokens are `ceil(len(text)/4)`. A real run replaces
   both with the API's usage metadata, and a real reader's own `tokens` and `cost_usd` are kept.
2. **Fixed across arms and printed in the section.** Image scale 1.0, stroke width 2 and a stroke
   budget of 1500 tokens. Compact strokes are freedraw elements that intersect the chunk box
   (skipping `isDeleted` and `customData.draft`), in array order, with points as integer offsets
   from the chunk origin and pressure quantised to one digit 0-9. Decimation reuses
   `inkbridge.imaging.decimate_strokes`, which keeps pressures paired 1:1; it starts at
   `budget*4/8` points and halves until the text fits. Excalidraw has no per-point timing, so
   order and pressure are the only temporal signal.
3. **Fallbacks are explicit and counted.** `image+strokes` falls back to image only when a chunk
   has no strokes (for example a diagram's shapes) or when even the minimum decimation exceeds the
   budget; `fell back` counts these, and the fallback chunk is read at the image rate. The
   `strokes` arm has no image to fall back to: it drops trailing strokes until the text fits, and
   records a miss (empty reading, counted in `no input`) when nothing is left. The arm stays
   honest instead of being quietly rescued by an image.
4. **Simulated readers are the only ones that may skip `read_arm`.** A real reader implements
   `read_arm(page, chunk, payload)` and sees the strokes. Any other non-simulated reader is
   refused by `run_input_repr`, because it would silently score every arm as image-only. The
   `ArmNoisy` reader (`arms-noisy:image=R,image+strokes=R,strokes=R`) is the self-test: it corrupts
   text at each arm's rate, seeded per arm, page and chunk.
5. **Synthetic only; default unchanged.** The committed table uses `synthetic-v1` with simulated
   noise, so it proves the harness and nothing about handwriting. `read_canvas` keeps the image by
   default. Strokes become the default only if a real run on `eval/data/pages-v1` with
   `--allow-model` shows a clear win. The price (`PRICE_PER_MTOK_IN`, 0.30 USD per million input
   tokens) is a placeholder until that run.

**Known bias.** `decimate_strokes` drops later strokes when there are very many tiny ones, so the
strokes arm is biased low on dense pages. The real run should report the share of strokes dropped.
