# 0064: Design tokens and UI primitives

Status: accepted (INK-160). Owner check of the `?kit=1` page on the tablet pending.

## Decision

`DESIGN.md` front matter is the contract and `web/src/styles/tokens.css` is generated from it by `web/scripts/design-tokens.mjs` (`cd web && npm run tokens`). The committed file is the artefact: it is not hooked into `predev` or `prebuild`, and `web/tests/designTokens.test.ts` fails when the file and `buildTokensCss(DESIGN.md)` differ.

Naming scheme, all on `:root`:

- `--color-<name>`, `--radius-<name>`, `--space-<name>` straight from `colors`, `rounded`, `spacing`.
- `--type-<name>-<family|size|weight|line-height|tracking>` from `typography`. Families are emitted with a fallback: `"Instrument Sans", system-ui, sans-serif` (Caveat gets `cursive`).
- `--component-<name>-<prop>` from `components`, with the prop kebab-cased. A `{colors.x}`, `{rounded.x}` or `{spacing.x}` reference becomes `var(--color-x)` and so on; a `{typography.x}` reference is skipped (the `--type-*` variables already carry it).
- `--shadow-popover`: a constant in the generator (`0 10px 28px rgba(46, 45, 43, 0.16)`), because the shadow only exists in the DESIGN.md prose (Elevation & Depth) and an unknown front matter key risks `@google/design.md lint`.

No YAML dependency: the front matter is flat (maps and scalar leaves), so a 20-line indentation reader parses it.

## Font

Instrument Sans (latin subset, one variable woff2 for weights 400 to 600, SIL OFL, licence beside it) lives in `web/src/styles/fonts/` and is loaded by `styles/fonts.css` with a relative `url()`. The ticket said `web/public/fonts`, but `inkbridge/api/web.py` serves only `/assets`, `/` and `/favicon.svg`, so a file under `public/` would 404 in `make serve`, the daily mode. Vite hashes a file imported from CSS into `dist/assets/`, which the API already serves, and dev behaves the same. No request goes to Google (a test checks the sources and `index.html`).

Follow-up, not fixed here: `/excalidraw-assets/` (decision 0058) has the same gap under `make serve`.

## Primitives

Eight plain React components in `web/src/ui/`: `Button` (primary, secondary, quiet), `IconButton`, `Chip`, `Badge`, `Panel`, `Card`, `Toast` (6 s, `scheduleDismiss` in `toast.ts`), `StatusDot`. One CSS file each, class names `ink-*`, colours and sizes only through tokens, charcoal focus ring. Rules in `web/tests/designRules.test.ts`, each with a sensitivity check on a synthetic input:

- No hex colour outside `tokens.css`. Four pre-v4 files still hold inline hex (`app/App.tsx`, `ask/AskPanel.tsx`, `chunks/ChunkOverlay.tsx`, `drafts/DraftBar.tsx`, including overlay blue and orange that are not palette colours). They are listed as `LEGACY` and later screen tickets rebuild them. The test also fails when a listed file no longer has hex, so the list can only shrink.
- `.ink-button` and `.ink-icon-button` are 44 px or taller; only `Button`, `IconButton`, `Chip` (and the kit) render a raw `<button>`, so nothing interactive escapes the check.
- `Chip` is the one 36 px target (it sits beside ink, DESIGN.md Layout).
- Lime (the variable and every token that resolves to it) appears only in `Chip.css` and `Badge.css`.
- No shadow or gradient in `ui/*.css` except `Toast.css`.

## Kit

`?kit=1` shows the primitives and the tokens, only under `import.meta.env.DEV` (the dynamic import is folded away in a production build; `grep ink-kit web/dist` finds nothing). Swatches, pens and the proportions bar are built at runtime from `tokens.css?raw`, so no lime variable is named outside `tokens.css`, `Chip.css`, `Badge.css`.

## Unchanged

No server change, no migration, no new dependency, no CLAUDE.md invariant touched. `DESIGN.md` gains one sentence on regenerating the tokens; no token value changed.

## Pending

Owner: compare `?kit=1` with the "Palette and components" board (swatches, type, button, chip and badge look); 44 px feel on the tablet; Instrument Sans renders on the tablet with no network request to Google.
