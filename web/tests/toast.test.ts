import assert from "node:assert/strict";
import { describe, it, mock } from "node:test";
import { scheduleDismiss, TOAST_MS } from "../src/ui/toast.ts";

describe("toast timer", () => {
  it("dismisses after exactly 6000 ms", () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      let calls = 0;
      scheduleDismiss(() => calls++);
      mock.timers.tick(5999);
      assert.equal(calls, 0);
      mock.timers.tick(1);
      assert.equal(calls, 1);
      assert.equal(TOAST_MS, 6000);
    } finally {
      mock.timers.reset();
    }
  });

  it("cancel prevents the call", () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      let calls = 0;
      const cancel = scheduleDismiss(() => calls++);
      cancel();
      mock.timers.tick(10000);
      assert.equal(calls, 0);
    } finally {
      mock.timers.reset();
    }
  });
});
