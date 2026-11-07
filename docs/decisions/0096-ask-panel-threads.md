# 0096: Ask panel threads and answers on the canvas (INK-134)

- `canvas_text` is a column on `questions` (migration 0015): the agent's 1 to 3 sentence summary for the canvas card, at most 600 characters. Without it Keep on canvas uses the first paragraph of the answer, capped at 300, run through `plainText` (agent text stays untrusted).
- `relation` (`answer`, `diagram`, `relates`) lives in the op payload, no column. `question_id` is stored in the existing `agent_ops.question_id` column and in the payload. It must be a question of the same canvas (422 `question_not_found` otherwise), and `relation` needs it; the existing-ink guard still runs first. With a `question_id` and no `relation` the server stores `answer`.
- Add to note is copy only: the backend never writes the vault. LAN HTTP is not a secure context, so the clipboard API is used only when available and a hidden textarea with `execCommand("copy")` is the fallback.
- Draw as diagram sends the answer's own first `flowchart`/`graph` Mermaid block as a `draw_diagram` op (`op_id` `diagram-<id>`), with no model call. The button shows only when such a block exists.
- Obsidian source chips link `obsidian://open?file=<note name>`; only the file name reaches the DOM, never the vault path (decision 0046 kept).
- "Open thread" on a draft card passes the op's `question_id`; the panel opens the thread holding that question (a follow-up resolves to its root). Threads with an open draft show a "Draft waiting" badge, and the open thread's ink gets an outline (`GlowBox`). The glow lives in `Badge.css` because lime is allowed only in `Chip` and `Badge`.
- Deferred: a per-question op limit (needs the task queue), pins from question to ink, runner draft tools.
