# 0058: Render throttle, local fonts, pen mode

Status: accepted (INK-101). Tablet check pending.

## Decision

Three settings, all in `web/src/lib/excalidrawEnv.ts`, none touching elements:

- `window.EXCALIDRAW_THROTTLE_RENDER = true`, set in `main.tsx` before the first render (Excalidraw reads it at pointer move, React 18+). Kept only if INK-107 shows frames are no worse than before; otherwise drop the one line.
- `window.EXCALIDRAW_ASSET_PATH = <Vite base>excalidraw-assets/`. Excalidraw resolves each font against this path first and only then against its `esm.sh` fallback, so fonts come from our own server and the fallback is never reached. We cannot remove the fallback, only never hit it. A LAN tablet with no internet now renders Excalifont.
- `penMode: true` in the initial `appState` (merged with the remembered view). Touch is then ignored by drawing tools from the first touch, before any pen contact. We set `penMode` only, not `penDetected`, so the first pen contact behaves as before and the user can still toggle pen mode off.

## Fonts

`web/scripts/copy-fonts.mjs` copies `node_modules/@excalidraw/excalidraw/dist/prod/fonts` to `web/public/excalidraw-assets/fonts`, run by `predev` and `prebuild` (so `make dev-web`, `npm run dev` and CI `npm run build` all do it; Vite copies `public/` into `dist/`). A `pre` script instead of a Vite copy plugin: no new dependency, same path for dev and build. The output is git-ignored. The whole folder is served (13 MB, mostly Xiaolai CJK); trimming is a later option. It reads the installed package each run, so upgrades need no maintenance.

## Unchanged

The INK-062 patch (decision 0031) and `penFeel.test.ts` are untouched and still pass. Pressure load path (`restoreElements` before `initialData`) is untouched.

## Pending

Tablet: pen draws, finger pans, a resting palm does not draw; network panel shows no `esm.sh` request. If one finger does nothing in pen mode, a hand-tool toggle is a follow-up, not a reason to revert.
