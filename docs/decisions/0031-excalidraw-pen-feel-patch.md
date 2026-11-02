# 0031: Patch Excalidraw freedraw constants for pen feel

Status: accepted (INK-062). Tablet tuning pending.

## Decision

Excalidraw 0.18.1 renders freedraw outlines in `getFreeDrawSvgPath` with `thinning: 0.6, smoothing: 0.5, streamline: 0.5`. Pressure felt too strong and ink lagged. We patch `thinning` to 0.3 and `streamline` to 0.2; `smoothing` stays 0.5. `size`, `easing`, `simulatePressure` and all element data are untouched. These are starting values; final tuning needs the tablet.

Rendered only: the function reads `points`, `pressures` and `simulatePressure` and writes nothing to elements, so stored pressure is unchanged ("pressure is real" holds). `web/tests/penFeel.test.ts` checks that the patch differs from the original only in those two numbers and that the pressure data flow strings are intact.

## Mechanism

`patch-package` (devDependency, `postinstall: patch-package`) applies `web/patches/@excalidraw+excalidraw+0.18.1.patch`. Two files, one per build, both patched: `dist/dev/chunk-4FTI6OG3.js` and `dist/prod/chunk-K2UTITRG.js` (production build and preview use prod). Verified: the built bundle contains `thinning:.3,smoothing:.5,streamline:.2`.

Why a dependency: Excalidraw exposes no prop for freedraw options; forking or vendoring the bundle is far larger. Rejected: a Vite `transform` plugin that string-replaces the chunk (breaks silently when the chunk hash changes). It stays the fallback if postinstall proves problematic.

Risks:
- `npm ci --omit=dev` or `--ignore-scripts` skips or breaks the patch; nothing here uses them (CI and the Makefile do full installs). No `|| true`: a failing patch must fail loudly.
- Chunk names are content hashes, so the patch is bound to exactly 0.18.1.
- Vite caches pre-bundled deps in `web/node_modules/.vite`; if a dev run shows old behaviour, delete that folder.

## Upgrading Excalidraw

`npm install` of a new version makes patch-package fail or warn. Regenerate: re-edit the constants in the new `getFreeDrawSvgPath` (grep `thinning`) in both dev and prod chunks, run `npx patch-package @excalidraw/excalidraw`, delete the old patch file, update the chunk names and constants in `penFeel.test.ts`, and re-test on the tablet. The test fails if the patch is silently absent.
