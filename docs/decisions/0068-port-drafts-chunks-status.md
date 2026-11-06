# 0068: Port drafts, chunk overlay and save status to the app shell

Status: accepted (INK-162). Owner checks pending: tablet and laptop visual sign-off against the Draft, Accepted and Rejected boards (tray, draft card, toasts, top bar status); tablet feel of the 44 px chunk tab beside ink (chips over the rail at x 16 to 76); a real offline run (stop the API while drawing, expect the alarm status).

## Context

INK-117 put the canvas in the shell (decision [0066](0066-app-shell.md)) but left `DraftBar`, `ChunkOverlay`, the jump notice and the save badge in their pre-v4 look, and its "Known gaps" noted that those overlays render below the rail and top bar because `.ink-shell__canvas` is its own stacking context. This ticket ports them. Behaviour does not change: `drafts/resolve.ts`, `draftView.ts`, `chunks/overrides.ts`, `chunks.ts` and `sceneSync.ts` are untouched.

## Decision

1. **Overlays leave the canvas stacking context.** `Shell` takes an `overlays?: ReactNode` prop rendered in `.ink-shell__overlays` (z-index 6, `pointer-events: none`) after the rail and zoom control; the top bar rises to z-index 7. Children set their own `pointer-events`. Layer contract (bottom to top): paper 0, canvas 1 (Excalidraw and `AskPanel`, INK-161's), rail and zoom 5, overlays 6 (chunk overlay, draft bar, jump notice), top bar 7. Chunk chips over the rail and the draft tray are now tappable. The `AskPanel` top offset stays INK-161's; if it must sit above the overlays it should move into this layer.
2. **Save status mapping** (`statusView` in `lib/status.ts`):

   | SaveState | Tone | Label |
   | --- | --- | --- |
   | `saved` | quiet check | Saved |
   | `dirty`, `saving` | soft-ink dot | Saving… |
   | `conflict` | soft-ink dot | Merging changes… |
   | `loading` | none | Loading… |
   | `retry` | alarm dot | Ink only in memory: do not close this tab |
   | `error` | alarm dot | the error's own detail, else the same risk line |

   Nothing persists ink on the device yet (the outbox is a later ticket; `sceneSync` only backs up on a conflict), so `retry` is honestly the alarm. The soft-ink "Kept on this device, sending when the network is back" view exists behind `statusView(status, onDevice = true)` and is unreachable until that ticket passes `true`. The old `": 123 ms"` detail moved to the `title` attribute.
3. **No Undo on toasts.** `applyVerdict`, `acceptOp` and `rejectOp` have no undo, so toasts carry no action until INK-115 and the "Open thread" / "View thread" links are not rendered. The Reject toast reads "Draft removed." (the board's "The answer stays in the thread." would be false until threads exist). A toast shows only when `ResolveSummary.done` is not empty; `done` lists the ops whose PATCH succeeded (checked in `patchEach`, `patchAccepted`, `retryAccept`), so a failed accept never toasts success.
4. **The jump notice is a `Toast`** with a Dismiss action and a 20 s duration; the dashed ghost box stays tied to the notice being open.
5. **The chunk tab is 44 px tall** (was 32), a smaller charcoal pill inside it. Chunk colours are tokens only: soft-ink outlines, charcoal selection, never the agent colour or a pen colour. The Chunks toggle moved from the overlay to the top bar `chunks` slot; a small store (`chunks/chunkView.ts`) shares on/off and the per-turn-on `session` (which stops a stale chunk list showing on re-open) between the toggle and the overlay. The "(N)" count is gone.
6. **Draft card per selected draft**: Draft badge, kind line, text preview (text drafts only, matched through `draftOpId`, never the tag alone), Accept and Reject. The tray's inline per-selection buttons are gone; the tray has Jump (oldest unseen draft, else the first), Accept all and Reject all.
7. `App.tsx` stays in the `LEGACY` hex list: the crop export still passes a literal white background (the crop path is out of scope). `DraftBar.tsx` and `ChunkOverlay.tsx` left the list.

## Consequences

- `App` hunks: the `<Shell>` call gains `chunks` and `overlays`; the `Notice` function is deleted; `AskPanel` is still a child of `Shell`.
- `color-mix()` is used for the tray hover and the selected-chunk wash (Chrome 111+, Firefox 113+); untested on the tablet browser.
- `retry` shows the alarm on every short network blip until the outbox ticket exists; chosen for honesty over softer wording.
- A 44 px chunk tab adds a larger dead zone above each chunk while the overlay is on; revisit after the tablet session.
