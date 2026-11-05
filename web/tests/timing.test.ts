import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { afterEach, describe, it, mock } from "node:test";
import { record, setTimingSink, timed, type TimingRecord } from "../src/lib/timing.ts";

const grab = () => {
  const got: TimingRecord[] = [];
  setTimingSink((r) => void got.push(r));
  return got;
};
afterEach(() => setTimingSink(() => {}));

describe("timed", () => {
  it("calls the sink once, returns the value, for sync and async functions", async () => {
    const got = grab();
    assert.equal(await timed("a", () => 5, () => ({ n: 2 })), 5);
    assert.equal(await timed("b", async () => "x"), "x");
    assert.equal(got.length, 2);
    assert.equal(got[0].name, "a");
    assert.ok(got[0].ms >= 0);
    assert.deepEqual(got[0].counts, { n: 2 });
  });

  it("rethrows errors and still reports", async () => {
    const got = grab();
    await assert.rejects(timed("e", () => { throw new Error("boom"); }), /boom/);
    assert.equal(got.length, 1);
  });

  it("records only name, ms and counts, never the result", async () => {
    const got = grab();
    await timed("big", () => ({ secret: "PRIVATE-INK-TEXT" }));
    assert.deepEqual(Object.keys(got[0]).sort(), ["counts", "ms", "name"]);
    assert.ok(!JSON.stringify(got[0]).includes("PRIVATE-INK-TEXT"));
  });

  it("a throwing sink never breaks the caller", async () => {
    setTimingSink(() => { throw new Error("sink"); });
    assert.equal(await timed("x", () => 1), 1);
    record("y", 3);
  });

  it("the default sink prints nothing", async () => {
    const log = mock.method(console, "log");
    const debug = mock.method(console, "debug");
    await timed("quiet", () => 1);
    assert.equal(log.mock.callCount() + debug.mock.callCount(), 0);
    mock.restoreAll();
  });
});

describe("dev-only sink", () => {
  it("/__log appears only in devLog.ts, and main.tsx loads it under import.meta.env.DEV", () => {
    const dir = new URL("../src/", import.meta.url);
    const files = readdirSync(dir, { recursive: true, encoding: "utf8" });
    const hits = files.filter((f) => /\.tsx?$/.test(f) && readFileSync(new URL(f, dir), "utf8").includes("/__log"));
    assert.deepEqual(hits, ["lib/devLog.ts"]);
    const main = readFileSync(new URL("main.tsx", dir), "utf8");
    const at = main.indexOf("devLog");
    assert.ok(at > main.indexOf("import.meta.env.DEV") && main.indexOf("import.meta.env.DEV") >= 0);
  });
});
