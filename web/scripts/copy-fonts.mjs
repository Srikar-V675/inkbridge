import { cpSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const web = new URL("../", import.meta.url);
const src = new URL("node_modules/@excalidraw/excalidraw/dist/prod/fonts", web);

/** Copy Excalidraw's own fonts to <dest>/fonts so the app serves them (INK-101, decision 0058). */
export function copyFonts(dest = fileURLToPath(new URL("public/excalidraw-assets", web))) {
  if (!existsSync(src)) throw new Error("excalidraw fonts missing: run npm ci in web/");
  cpSync(src, `${dest}/fonts`, { recursive: true });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) copyFonts();
