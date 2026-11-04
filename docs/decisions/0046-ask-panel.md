# 0046: Ask AI side panel (INK-049)

Status: accepted. Web only: the questions API (0035) and the `write_text` op already exist.

## Decisions

- **Renderer**: `react-markdown` (pinned exact). Raw HTML is off by default; we add `skipHtml`, replace images with plain text, force `rel="noopener noreferrer" target="_blank"` on links and allow only `http:`, `https:` and `mailto:` hrefs (`web/src/askMarkdown.ts`). No hand-written parser. `answer_md` is untrusted (0035 item 6).
- **Live updates**: poll `GET /documents/{c}/questions` every 3 s while the panel is open and a question is pending; stops on close or unmount. The WS `question.update` message exists but `OpsSocket` ignores it, and wiring it would touch shared code. Cost: a few seconds of latency on an answer.
- **Chunk chips** reuse `resolveChunk` (rejects other canvases and manual regions, follows `successor_of`). Missing, orphaned or error results show "gone". Chips of an opened answer are resolved up front (max 10), others lazily on click.
- **Note chips** show the file name only (client-side basename). A vault path never reaches the DOM.
- **Keep on canvas** sends a `write_text` op (a draft, never an edit of ink) with the answer as plain text (`plainText`: tags, links, images and markup stripped, capped at 2000 chars). Anchor is the first focus chunk, then the first chunk source, that resolves to an active chunk; none means no anchor. `op_id = keep-<question id>` (12 hex chars, valid for the op id pattern) makes a double tap one draft. A 422 retries once without anchor. Size is left to the server (0032).
- **Selection** sent with a question is the selected live non-draft elements, capped at 200 (API limit); the panel says when capped.

## Consequences

A chip for a manual region shows "gone". A huge selection covers less than the page. The Ask panel has no DOM tests (no harness); logic lives in `ask.ts` and `askMarkdown.ts` with Node tests, UI checked in a headless browser.
