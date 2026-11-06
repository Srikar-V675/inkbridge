import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import { copyFonts } from "../scripts/copy-fonts.mjs";

describe("copyFonts", () => {
  it("copies Excalidraw's fonts under <dest>/fonts", () => {
    const dest = mkdtempSync(join(tmpdir(), "fonts-"));
    copyFonts(dest);
    const dir = join(dest, "fonts", "Excalifont");
    assert.ok(existsSync(dir));
    assert.ok(readdirSync(dir).some((f) => f.endsWith(".woff2")));
  });
});
