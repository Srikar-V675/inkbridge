import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { followScroll } from "../src/chunks/followScroll.ts";

describe("followScroll", () => {
  it("does not subscribe while inactive and subscribes when active", () => {
    let subs = 0;
    const api = {
      onScrollChange: () => {
        subs++;
        return () => {
          subs--;
        };
      },
    };
    const off = followScroll(api, false, () => {});
    assert.equal(subs, 0);
    const off2 = followScroll(api, true, () => {});
    assert.equal(subs, 1);
    off2();
    assert.equal(subs, 0);
    off();
  });

  it("passes scroll and zoom value through", () => {
    let cb: ((x: number, y: number, z: { value: number }) => void) | undefined;
    const got: unknown[] = [];
    followScroll(
      { onScrollChange: (c) => ((cb = c), () => {}) },
      true,
      (v) => got.push(v),
    );
    cb!(5, 6, { value: 2 });
    assert.deepEqual(got, [{ scrollX: 5, scrollY: 6, zoom: 2 }]);
  });
});
