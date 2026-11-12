# Frontend map (`web/src/`)

React 19 + Vite, Excalidraw 0.18. `/` is the canvases home; a canvas opens with `/?canvas=<document id>`; `?canvas=<id>&chunk=<chunk id>` is the contract shared with vault notes (`lib/route.ts`). In-app switching uses `pushState` (`lib/nav.ts`). The Vite dev server on `:5173` is for development; daily use is the built app served by the API on `:8000`.

| Folder | Role |
|---|---|
| `main.tsx` | Entry point |
| `app/` | `Root` (home or one canvas), `App.tsx` (mounts Excalidraw, wires load, sync, overlay, ops socket, crop sync), `Shell` slots (top bar, tool rail, zoom, status), `railStore`, `shell.css`; touch routing (`touchInput`, `touchRouting`, `TouchLayer`, `fingerDraws`: one finger pans, two pinch-zoom, only the pen draws, palm rejection, "Finger draws" toggle); UI size S/M/L (`uiScale*`, `UiSizeControl`); `WorkingDot` (pulsing lime dot while an agent works); `PaperDots` |
| `app/props/` | The one card per rail tool: shapes picker plus the 280 px properties card (`PropsCard`, `propsLogic`, `propsStore`); never opens for pen, highlighter or eraser |
| `home/` | Canvases home: Continue, Recent, All, Archived, search, rename, pin, duplicate, archive with Undo (`Home`, `CanvasMenu`, `homeApi`, `homeLogic`) |
| `sync/` | `sceneSync.ts` (load, autosave, per-element merge via `mergeRule.ts`), `journal.ts` (IndexedDB device journal) and `sender.ts` (overlapping uploader), `liveDelta.ts` (applies `scene.delta` without touching undo), `opsSocket.ts` (WebSocket client), `cropSync.ts` (PNG crops for stale chunks), `chunkRefresh.ts` (one coalesced refetch signal), `loadClock.ts`, `startupGate.ts` (defers socket and crop sync until the canvas has painted) |
| `chunks/` | Chunk fetch, deep-link focus, toggleable overlay with 44 px tabs (`ChunkOverlay`, `chunks`, `chunkView`, `followScroll`), tap-to-select Merge/Split (`overrides.ts`), `JumpNotice` |
| `drafts/` | Draft store (`draftStore`), drawing ops (`drawOp`, `drafts`, Mermaid via `mermaid-to-excalidraw`), graph layout, per-draft pills (`DraftPills`, `draftPills`), draft tray and bar (`DraftBar`), tether to the anchor (`Tether`), Accept/Reject/Unaccept (`resolve.ts`), pan-to-draft (`draftView`) |
| `ask/` | Ask panel on the `Panel` primitive: list and thread views, safe markdown, source chips, Draw as diagram, streamed answers (`AskPanel`, `AskThread`, `AskList`, `ask.ts`, `threads.ts`) |
| `offers/` | Offer chips, popovers, Focus toggle, attention frames (`OfferLayer`, `offerStore`, `attention`); inert unless the server has offers on |
| `ink/` | Pen-sample collector (`penSamples`) feeding the patched freedraw handler, and the fast ink layer (`fastInk`, `FastInk`; decision 0076) |
| `ui/` | Primitives `Button`, `IconButton`, `Chip`, `Badge`, `Panel`, `Card`, `Toast`, `StatusDot`, and the dev-only `Kit` page (`/?kit=1`) |
| `styles/` | `tokens.css` (generated from `DESIGN.md` with `npm run tokens`), `fonts.css`, Instrument Sans in `fonts/` |
| `lib/` | `route`, `nav`, `status` (tiny external store for the save badge), `view` (per-device scroll/zoom memory), `timing` and dev-only `devLog`, `deviceLog`, `stalls`, `probe`, `measure`, `excalidrawEnv`, `changeGate` |

Other pieces
- `web/patches/@excalidraw+excalidraw+0.18.1.patch` (`patch-package` on `postinstall`): freedraw `thinning` 0.6 -> 0.3, `streamline` 0.5 -> 0.2, plus the pen-sample and pointerup hooks for full-rate samples; stored `pressures` untouched (decisions 0031, 0076).
- `web/scripts/copy-fonts.mjs` copies the Excalidraw fonts into `web/public`; `web/scripts/perf/` and `web/perf/` are the INK-174 lag harness (dev tooling).
- Rules in `DESIGN.md`: lime `#D4F23A` is the agent and only the agent; every touch target 44 px or larger (`Chip` is the one 36 px exception); no hex outside `tokens.css`. `web/tests/designRules.test.ts` enforces them.

Tests: `web/tests/*.test.ts` (about 57 files) run with Node's built-in runner (`npm test`), no framework.

Pressure rule: freedraw keeps `pressures` and `simulatePressure=false`; run `restoreElements` before `initialData`.
