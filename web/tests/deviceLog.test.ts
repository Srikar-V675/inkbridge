import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createDeviceLog, deviceId, deviceLogEnabled } from "../src/lib/deviceLog.ts";

const fakeStorage = () => {
  const m: Record<string, string> = {};
  return {
    getItem: (k: string) => m[k] ?? null,
    setItem: (k: string, v: string) => void (m[k] = v),
    removeItem: (k: string) => void delete m[k],
  };
};

describe("createDeviceLog", () => {
  it("flush posts a JSON array once and is quiet when empty", () => {
    const posts: string[] = [];
    const log = createDeviceLog({ device: "abc", post: (b) => void posts.push(b), now: () => 1000 });
    log.add({ name: "scene.save", ms: 12, counts: { bytes: 3 } });
    log.flush();
    log.flush();
    assert.equal(posts.length, 1);
    assert.deepEqual(JSON.parse(posts[0]), [{ device: "abc", name: "scene.save", ms: 12, t: 1000, counts: { bytes: 3 } }]);
  });

  it("flushes by itself at max records", () => {
    const posts: string[] = [];
    const log = createDeviceLog({ device: "abc", post: (b) => void posts.push(b), max: 2 });
    log.add({ name: "a", ms: 1, counts: {} });
    assert.equal(posts.length, 0);
    log.add({ name: "b", ms: 1, counts: {} });
    assert.equal(posts.length, 1);
  });

  it("copies named fields only", () => {
    const posts: string[] = [];
    const log = createDeviceLog({ device: "abc", post: (b) => void posts.push(b) });
    log.add({ name: "a", ms: 1, counts: {}, text: "PRIVATE-INK-TEXT" } as never);
    log.flush();
    assert.ok(!posts[0].includes("PRIVATE-INK-TEXT"));
  });
});

describe("deviceId", () => {
  it("is stable across calls and survives a throwing storage", () => {
    const s = fakeStorage();
    const id = deviceId(s);
    assert.match(id, /^[a-z0-9]{8}$/);
    assert.equal(deviceId(s), id);
    const bad = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
    assert.match(deviceId(bad as never), /^[a-z0-9]{8}$/);
  });
});

describe("deviceLogEnabled", () => {
  it("is switched by the URL and remembered", () => {
    const s = fakeStorage();
    assert.equal(deviceLogEnabled("", s), false);
    assert.equal(deviceLogEnabled("?devicelog=1", s), true);
    assert.equal(deviceLogEnabled("", s), true);
    assert.equal(deviceLogEnabled("?devicelog=0", s), false);
    assert.equal(deviceLogEnabled("", s), false);
    assert.equal(deviceLogEnabled("?probe=1", fakeStorage()), true);
  });
});
