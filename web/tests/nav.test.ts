import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { navigate, onLinkClick, subscribe } from "../src/lib/nav.ts";

function fakeWin(pathname = "/", search = "") {
  const listeners = new Map<string, Array<() => void>>();
  const calls: string[] = [];
  const boom = (name: string) => () => {
    throw new Error(`location.${name} would reload the page`);
  };
  const win = {
    location: { pathname, search, origin: "http://tab", assign: boom("assign"), replace: boom("replace"), reload: boom("reload") },
    history: {
      pushState: (_s: unknown, _t: string, url: string) => (calls.push("push " + url), apply(url)),
      replaceState: (_s: unknown, _t: string, url: string) => (calls.push("replace " + url), apply(url)),
    },
    dispatchEvent: (e: { type: string }) => (listeners.get(e.type) ?? []).forEach((f) => f()),
    addEventListener: (t: string, f: () => void) => listeners.set(t, [...(listeners.get(t) ?? []), f]),
    removeEventListener: (t: string, f: () => void) => listeners.set(t, (listeners.get(t) ?? []).filter((x) => x !== f)),
  };
  function apply(url: string) {
    const u = new URL(url, "http://tab");
    win.location.pathname = u.pathname;
    win.location.search = u.search;
  }
  return { win: win as never, calls, fire: (t: string) => (listeners.get(t) ?? []).forEach((f) => f()) };
}

describe("navigate", () => {
  it("pushes state without reloading and notifies subscribers", () => {
    const f = fakeWin();
    let n = 0;
    subscribe(() => n++, f.win);
    navigate("/?canvas=a", {}, f.win);
    assert.deepEqual(f.calls, ["push /?canvas=a"]);
    assert.equal(n, 1);
  });
  it("is a no-op for the URL already shown", () => {
    const f = fakeWin("/", "?canvas=a");
    let n = 0;
    subscribe(() => n++, f.win);
    navigate("/?canvas=a", {}, f.win);
    assert.deepEqual(f.calls, []);
    assert.equal(n, 0);
  });
  it("replaces when asked", () => {
    const f = fakeWin();
    navigate("/?canvas=a", { replace: true }, f.win);
    assert.deepEqual(f.calls, ["replace /?canvas=a"]);
  });
});

describe("subscribe", () => {
  it("fires on popstate and unsubscribes", () => {
    const f = fakeWin();
    let n = 0;
    const off = subscribe(() => n++, f.win);
    f.fire("popstate");
    assert.equal(n, 1);
    off();
    f.fire("popstate");
    navigate("/?canvas=a", {}, f.win);
    assert.equal(n, 1);
  });
});

describe("onLinkClick", () => {
  const click = (over: Record<string, unknown> = {}, href = "/?canvas=a&chunk=c", origin = "http://tab") => {
    let prevented = false;
    const e = {
      button: 0, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, defaultPrevented: false,
      currentTarget: { href: new URL(href, origin).href, origin, pathname: "/", search: "?canvas=a&chunk=c", target: "" },
      preventDefault: () => (prevented = true),
      ...over,
    };
    const urls: string[] = [];
    onLinkClick(e as never, (u: string) => void urls.push(u), "http://tab");
    return { prevented, urls };
  };
  it("takes a plain same-origin left click", () => {
    assert.deepEqual(click(), { prevented: true, urls: ["/?canvas=a&chunk=c"] });
  });
  it("leaves modified, non-left, new-tab and cross-origin clicks alone", () => {
    for (const over of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      assert.deepEqual(click(over), { prevented: false, urls: [] });
    }
    const target = { currentTarget: { href: "http://tab/?canvas=a", origin: "http://tab", pathname: "/", search: "?canvas=a", target: "_blank" } };
    assert.deepEqual(click(target), { prevented: false, urls: [] });
    const other = { currentTarget: { href: "http://else/", origin: "http://else", pathname: "/", search: "", target: "" } };
    assert.deepEqual(click(other), { prevented: false, urls: [] });
  });
});
