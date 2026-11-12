# Prompt for Opus 5.5: research Inkbridge and write v4 specs

You are researching and redesigning **Inkbridge** (this repo) so its owner can use it **every day**.
Read this whole prompt first. Everything below is what the owner told me; treat each point as a
requirement for the research, not as background.

## The owner's problem, in their words

- Inkbridge is a handwritten canvas (Excalidraw) wired into a markdown vault, with MCP agents.
- "It feels like I'm **babysitting** it. A user wouldn't do that." It does not feel intelligent.
- "The **intelligence of having an agent in your canvas** is missing, which is the major issue I'm trying
  to solve for myself."
- "I want to be able to use this **daily**."
- "It doesn't even seem like something I'd use daily at this rate. Everything is bare bones and there are lots of issues."
- The UI is "barebones, bare Excalidraw". There is no way to manage canvases; "why must I go to the URL to change canvas?"
- Drafts: "The placement is random and I don't like it." They land stacked down like a page, not placed like a canvas.
- Chunking: "is not taking into picture proper connections; **semantic meaning is missing**." The owner suggests
  that **RAG might work better than a plain DB** for this.
- Ask AI: "doesn't have the right tools and seems to be giving me stuff that **can't be added to the canvas**.
  The answer and the question have no connection in the canvas."
- Diagrams: "a bit dumb."
- Performance: "**a key issue on the tablet**."
- The vault skill (`skills/inkbridge-export`) "must be in line with what **my Obsidian vault does**". It should be
  something that can **refine itself**, but still stay in line with the vault. It is not installed in any of the
  owner's sessions today.
- Reference for ideas: **penecho** (owner's word; research what it is and what it does well, and use it for ideas, not copying).

## Operating setup the owner wants (do not change)

- One API, one web server, the normal `data/` database and canvases (`default`, `08ae339063fd`), no temporary data.
- Recognition (Gemini) **on**; the owner does not mind training on their own handwriting.
- Ask runner = `claude` (Claude Code headless). Vendor-neutral pull path must still exist.
- Tablet over LAN HTTP (not a secure context). Android 16, Firefox. Laptop is Linux.

## What to read first (in this repo)

- `CLAUDE.md` (architecture, invariants, workflow, current state).
- **`docs/v4-research/issues-report.md`** (detailed evidence from the test session; the ten
  numbered issues and broader concerns). Treat verified items as facts and hypotheses as unproven.
- `docs/decisions/` (0004 to 0056; 0043 is unused). `docs/mcp-tools.md`, `docs/vault-note-format.md`.
- Code: `server/src/inkbridge/chunker.py`, `placement.py`, `ask_runner.py`, `recognition_worker.py`, `api/`,
  `db/`, `mcp/`; `web/src/` (App, ChunkOverlay, DraftBar, AskPanel, cropSync, sceneSync, opsSocket).
- The vault skill `skills/inkbridge-export/` and the owner's vault (hub note
  `wiki/projects/Inkbridge.md` in `~/Documents/kaizen`; conventions of the obsidian-second-brain skill in
  `~/.claude/skills/obsidian-second-brain`).
- Spec of record **v3** https://claude.ai/artifact/FkyFV1UySxqfC9oFEYb1P1 and technical reference **v3**
  https://claude.ai/artifact/1uMmVHEyuvb2uS5Dgutaqy (read them with the Artifact tool, action `read`).
  `docs/project-doc.html` is v1 history only. `docs/tickets/` is local and untracked; read its README for ticket history.

## Research questions

Answer each with evidence from the code or from sources you cite. Separate **verified** from **hypothesis**.

1. **Gaps, idea-wise.** What is missing from the Inkbridge idea so that it can be a daily tool? Compare with
   penecho and with comparable products (handwriting canvases with AI, agent-in-canvas tools, ink-to-notes tools).
2. **Gaps, code-wise.** What in the current code blocks that goal? Start from the evidence list below.
3. **An intelligent agent in the canvas.** What should an agent do without being told (notice, link, propose,
   place, ask)? What tools, context and triggers does it need so the owner stops babysitting? Design the loop.
4. **Chunking and semantics.** Chunking today is geometric (bounding-box proximity, `k = 1.5`). Pen-drawn arrows are
   `freedraw` strokes, so they bridge distant ink into one huge chunk (see issue 3 in the report, with screenshots
   described). Research stroke-level understanding (arrow vs box vs label vs text), semantic grouping, and
   **RAG** (retrieval over readings, notes and canvas history) versus the current database. Say what to keep.
5. **Drafts and placement.** Design placement that understands the canvas (near the related chunk, in free space,
   readable at working zoom, not stacked like a page), and a draft lifecycle that cannot get stuck (see issues 6 and 9).
6. **Ask AI.** Which tools should Ask have so answers can be added to the canvas and connect to the question
   (anchor to the asked chunk, draw links, drop-in content)? Fix the follow-up design (issue 10).
7. **Diagrams.** Mermaid flowcharts only today. What would make diagrams smart (layout, types, editing
   existing diagrams, linking to ink)?
8. **Tablet performance.** Find the real cause of multi-second request delays, "Saving" that sticks, slow chunk
   load and intermittent pan lag (issues 1, 2, 7, 8; INK-074). Include the Vite `/ws` proxy crash. Propose how to
   measure on the tablet and what architecture (serving, sync, rendering) would be fast there.
9. **UI and canvas management.** A non-bare UI: canvas switcher and manager, navigation, chunk and answer
   presentation, draft review. Propose designs, with tablet ergonomics in mind.
10. **Vault alignment.** How should the vault skill match the owner's Obsidian vault and be able to refine itself?
    Include how it gets installed where the owner's sessions can use it.
11. **Multi-device and multi-tab.** Conflicts (409), live sync (INK-063), one tab id seen on two devices.

## Evidence you must account for (verified in the test session)

- Server saves take 10 to 75 ms, but requests lost 1 to 71 s before reaching the handler: the delay is client,
  network or proxy side. Unknown where.
- The Vite dev bundle is 16 MB (54 modules); the production build is 0.5 MB (13 files).
- `vite preview` crashed on an unhandled `ECONNRESET` from the `/ws` proxy; the page was unreachable until restart.
- Chunker merged far-apart ink through long `freedraw` arrows; a pinned 155-element chunk of 3473 x 1796 units
  and overlapping chunk boxes exist on `default`.
- An agent draft got stuck: server op `accepted`, element still `draft` in the saved scene, Accept returns 409 "not ready".
- A `write_text` and a `draw_diagram` sent together raced; the diagram op expired.
- The Ask follow-up button is disabled with no selection (`AskPanel.tsx:169`) although the parent has focus.
- Gemini returns 503 "high demand" intermittently; the worker backs off and retries.
- `docs/tickets/README.md` is stale (shows merged tickets as todo).

## Deliverables

1. **A new v4 artifact for the project spec** and **a new v4 artifact for the technical reference** (both with
   the Artifact tool; start from the v3 content and rewrite it for v4). Include the intelligent-agent loop,
   semantic chunking and retrieval design, draft placement and lifecycle, Ask with canvas tools, diagrams,
   tablet performance plan, UI and canvas management, and the vault skill. State what is kept, changed or dropped
   from v3, and why.
2. A short research summary: gaps found (idea and code), sources, what you verified and what you did not.
3. **Do not create tickets.** The owner reads the v4 artifacts first and will approve before tickets are written.

## Rules

- Do not change code, commit, push or open PRs. Do not touch the owner's data or servers.
- Never add Co-Authored-By or any attribution line (repo rule).
- No guessing: cite sources, name the file and line for code claims, mark hypotheses.
- Keep the owner's invariants unless you argue clearly for changing one: user ink is never edited by an agent;
  the backend never writes the vault; hash allow-lists; recognition never blocks drawing.
