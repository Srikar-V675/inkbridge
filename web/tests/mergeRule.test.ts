import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { winsOver } from "../src/sync/mergeRule.ts";
import { mergeScenes } from "../src/sync/sceneSync.ts";

type Side = { version: number | null; nonce: number | null };
type Row = { name: string; incoming: Side; current: Side; wins: boolean };
// The same table the server test reads (server/tests/data/merge_rules.json): one rule, two tests.
const table: Row[] = JSON.parse(
  readFileSync(new URL("../../server/tests/data/merge_rules.json", import.meta.url), "utf8"),
);
const stamp = (s: Side) => ({ version: s.version ?? undefined, versionNonce: s.nonce ?? undefined });

describe("shared merge rule table", () => {
  for (const row of table) {
    it(row.name, () => {
      assert.equal(winsOver(stamp(row.incoming), stamp(row.current)), row.wins);
    });
  }
});

describe("mergeScenes uses the shared rule", () => {
  it("a tie goes to the lower nonce whichever side holds it", () => {
    const a = { id: "x", version: 5, versionNonce: 10, tag: "A" };
    const b = { id: "x", version: 5, versionNonce: 20, tag: "B" };
    assert.equal((mergeScenes([b], [a])[0] as { tag: string }).tag, "A");
    assert.equal((mergeScenes([a], [b])[0] as { tag: string }).tag, "A");
  });
});
