# Inkbridge: issues and concerns report (test session of 5 Nov 2026)

Status: input for the v4 research. Written from a live test of `main` at `d861617` (INK-060 merged) on the
user's tablet (Android 16, Firefox) and laptop (Linux, Firefox), with timing logs from the API.
Nothing in this report was fixed. "Verified" means seen in logs, the database or the code. "Hypothesis"
means not proven.

## 1. What the user is trying to get

Inkbridge exists so the user can use a handwritten canvas **daily**, with an agent that lives in the
canvas and is intelligent about it. The user's verdict after the test: it is bare bones, full of
bugs, and "I'm babysitting it, a user wouldn't do that". The core problem to solve is the missing
intelligence of an agent working inside the canvas.

## 2. Test setup (and what changed during the session)

- Tablet reached the app over LAN HTTP at `http://<laptop-ip>:5173`.
- Several server arrangements were tried: a Vite dev server on 5173 (16 MB, 54 modules uncompressed),
  a production build served by `vite preview` (0.5 MB, 13 files), two API processes at once (8000
  and 8001), and a temporary data folder (`~/inkbridge-test-data`). This caused confusion (stale tabs,
  a second API replacing the first, canvases such as "ascend" living in a throwaway database).
- **Agreed final setup, from the user:** one API (:8000), one web server (:5173, production build),
  the normal `data/` database and canvases (`default`, `08ae339063fd`), recognition on for both
  canvases (the user accepts Gemini training on their handwriting), Ask runner = `claude`, MCP
  pointed at :8000. No temp data, no second server.
- The inkbridge MCP (12 tools) connected and passed the scripted smoke check.
- Server tests: 875 pass. Web dependencies were stale (`react-markdown` missing) until `npm install`.

## 3. The ten reported issues

Each has what the user saw, what the evidence shows, and what is still unknown.

### 1. Stuck on "Saving" for a very long time
- **Verified:** the API handles a save in 10 to 75 ms. A scripted save through the preview proxy at idle
  took about 15 ms. The slow requests (up to 71 s, typically 1 to 30 s) lost their time *before* the request
  body reached the handler, so the delay is in the browser, the network or the proxy, not in the API,
  database or chunker.
- **Verified:** while the user draws on the laptop, saves still took up to 21 s end to end.
- **Hypotheses (untested):** the browser is busy rendering; requests queue behind crop uploads, question
  polling and the socket; Firefox behaviour.
- **Unknown:** where exactly the time goes. Needs timing measured inside the tablet's browser. The
  production build has no device-log sink (`/__log` is dev-only). Known ticket: INK-074.

### 2. Tablet browser gets stuck while the page loads on the laptop
- **Verified:** the Vite dev bundle is about 16 MB across 54 modules; the production build is about 0.5 MB.
- **Verified:** the web server (`vite preview`) crashed at 13:33:29 with an unhandled `ECONNRESET` from the
  `/ws` proxy (a client dropped its socket). The page was unreachable while it was down. The API stayed up.
- **Likely:** both cause "tablet stuck". The crash was most likely a tablet socket reset (sleep or Wi-Fi blip),
  which is a guess. A restart loop now hides the crash but does not fix it.

### 3. Far-apart ink became one huge chunk; chunks overlap
- **Verified (code):** the chunker joins elements whose own bounding boxes are within `k * median size` of
  each other (`chunker.py`, k = 1.5). Arrow and line elements are excluded from that step and handled by
  separate rules (short arrows merge chunks, long arrows become links).
- **Finding:** the user's arrows are pen strokes, which are `freedraw` elements, so they never reach the
  arrow rules. A long curved arrow has a bounding box stretching from the text where it starts to the
  box where it ends, so the gap to both is zero and the text, the arrow and the far box merge into one chunk.
- **Verified:** the user's two screenshots (before merging) show exactly this: "Uses goose under the hood" and
  "Agent Harness Project" box, and "enhancements" and the "My project with deloitte" box, each bridged by a long
  hand-drawn arrow. The chunk boxes of `b8d386ce2bb6` and `85e9a81e05a1` overlap.
- **Verified (database):** `default` also contains a pinned 155-element chunk of 3473 x 1796 units (a manual
  Merge result), and two chunks that overlap by 306 x 576 units. The size cap (80 x median stroke) is loose.
- **Not checked:** whether a crop of one chunk also contains the other's ink.
- **Conclusion:** the chunker has no concept of a pen-drawn arrow and no semantic or layout understanding.
  This is a design gap; retuning thresholds will not close it.

### 4. Chunk text is null; recognition does not finish
- **Cause (verified):** recognition was off in the test API because `INKBRIDGE_RECOGNIZE_DOCUMENTS` was unset,
  as the session said at the start. Also the crop images were `png_stale` (only an open browser tab uploads
  them), so there was nothing to read.
- **After the final setup:** recognition is on. Within minutes some chunks were read (6 of 19 on `default`),
  while Gemini returned 503 "high demand" for some chunks (retry every 30 s with backoff). Readings stay `null`
  for chunks whose crops are stale or while Gemini is overloaded.

### 5. "Click a deep_link; it should open ?chunk= and pan to that chunk" was not understood
- **Explanation:** every chunk returned by `read_canvas` has a `deep_link` such as
  `http://<laptop-ip>:5173/?canvas=<id>&chunk=<chunk id>`. Opening it loads that canvas and pans and
  highlights that chunk. Exported vault notes use it to jump from a paragraph back to its ink.
- **Concern:** the test instruction was unclear; the flow is not discoverable in the UI.

### 6. Two drafts at once produce a conflict
- **Verified (database):** on the "ascend" canvas a `write_text` and a `draw_diagram` were created 40 ms
  apart. The text was accepted; the diagram op **expired** because the browser never confirmed drawing it in
  the wait window, while scene-save conflicts were firing. A second attempt worked.
- **Cause:** two drafts mean two scene saves racing; with a second device open they conflict (409).
  Live sync between devices does not exist (INK-063). The server did not crash.

### 7. Chunks load slowly even with about 4 chunks
- **Verified:** the chunk list endpoint answers in about 2 ms. Slowness is therefore not server-side.
- **Same suspect class as issue 1** (browser, network or proxy). Not measured on the tablet.

### 8. Panning lag is intermittent
- Not measured. Same family as issues 1, 2 and 7 (INK-074). The renderer is Excalidraw plus Inkbridge's
  own layers (overlay recompute, crop sync, socket, scene diff and hashing on change).

### 9. Draft can't be accepted: "1 not ready", even after reload
- **Verified:** a "Keep on canvas" text element (`keep-9688e38a9d13:1`) is still flagged `draft` in the saved
  scene, while the server already holds that op as `accepted`. Accept sends `PATCH /ops/{id}` and always gets
  409 "not ready" (seen in the log at 13:11:14). Reload cannot fix it because the draft flag is in the scene.
- **Likely cause:** the save that should have cleared the draft flag was lost to a conflict. Close to INK-091.
- **Note:** this state lived in the throwaway database and is not in the user's normal one.

### 10. Ask follow-up does not work when no elements are selected
- **Verified (code):** the Ask button is disabled whenever the selection is empty (`!sel.ids.length`,
  `AskPanel.tsx:169`), even for a follow-up where a parent question is set (`AskPanel.tsx:124`). The parent
  already carries its own focus, so a follow-up should not need a new selection.
- **How it happened:** the user clicked a chunk shown in one of the answers (which selects that chunk's elements),
  then lost the connection. The panel showed "Follow up on #N" but Ask stayed greyed out.
- **Unknown:** what the "lost the connection" was; not traced.

## 4. Broader product concerns (user's words, in order of importance)

1. **The agent is not intelligent.** The major goal, an agent that is intelligent inside the canvas, is missing.
   The user feels they babysit it.
2. **Drafts land randomly.** Agent drafts are stacked below each other like a page, not placed like a canvas.
   Placement does not understand the canvas.
3. **Chunking ignores real connections and meaning.** It uses geometry only; there is no semantic meaning.
   The user suggests trying **RAG** instead of (or on top of) a plain database.
4. **Ask AI has the wrong tools.** It returns things that cannot be added to the canvas, and the question and
   its answer have no connection on the canvas.
5. **Diagrams are dumb** (Mermaid flowcharts only).
6. **Performance is a key issue on the tablet.**
7. **The UI looks like bare Excalidraw.** No canvas management at all: to change canvas the user must edit the URL.
8. **The vault-export skill is not installed anywhere the user can use it.** It lives in the repo at
   `skills/inkbridge-export` but not in the user's Claude skills, so no session offers it.
   The skill must match what the user's Obsidian vault does and ideally be able to refine itself.
9. **Multi-device use is fragile:** concurrent tabs conflict (409), and one tab id was even seen on two devices.

## 5. What exists today (from the repo, for context)

Built per `CLAUDE.md`: scenes with optimistic versions, chunks with stable ids and arrow links, three hashes,
Gemini recognition worker, `check_sync`, vault export skill, agent ops queue with WebSocket drafts, MCP tools
(`read_canvas`, `get_region`, `search`, `check_sync`, `get_subgraph`, `canvas_components`, `write_text`,
`draw_diagram`, `create_canvas`, `list_questions`, `answer_question`), Ask panel, Ask runner, eval harness
(synthetic fixtures only). Not built or still open per the local ticket index: evals E4, E2/E3, E5, README,
demo video, final pass, live sync (INK-063), LAN/tablet lag fix (INK-074), restructure tickets, and
INK-089 to INK-091 (bugs) and others listed in `docs/tickets/README.md` (which is stale: it still shows
tickets such as INK-048, 049 and 076 to 091 as todo although they are merged).

## 6. Other findings worth keeping

- Saves from tab `o8bkozn1`/`jxdxr372` showed both Linux and Android user agents under one tab id: unexplained.
- Gemini returns 503 under load; the worker retries every 30 s with backoff.
- Excess servers confuse the test: one API, one web server, normal data.
- Vite's `/ws` proxy crashes on a reset socket; the web server needs to be supervised or replaced for tablet use.
- The Vite production build has no device-log sink; tablet timings need another way to be collected.

## 7. Open questions for the research

- Where exactly do the multi-second save and request delays come from on the tablet?
- Can chunking use stroke shape (is this stroke an arrow? a box? a label?) and meaning, not just distance?
- Would retrieval (RAG) over chunk readings, notes and canvas history give an agent real context?
- What should an intelligent in-canvas agent do on its own, so the user stops babysitting?
- How should drafts be placed (near the thing they relate to, in free space, readable at working zoom)?
- How should answers connect to the canvas (anchor to the asked chunk, draw links, drop-in content)?
- What does a first-class canvas manager, a non-bare UI and a tablet-fast renderer look like?
