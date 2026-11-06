import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { backTo, navigate, onLinkClick, subscribe, titleHint } from "../src/lib/nav.ts";

function fakeWin(pathname = "/", search = "") {
  const listeners = new Map<string, Array<() => void>>();
  const calls: string[] = [];
  const boom = (name: string) => () => {
    throw new Error(`location.${name} would reload the page`);
  };
  // A real history stack: entries with url and state, an index, forward entries dropped on push.
  const stack: Array<{ url: string; state: unknown }> = [{ url: pathname + search, state: null }];
  let index = 0;
  const win = {
    location: { pathname, search, origin: "http://tab", assign: boom("assign"), replace: boom("replace"), reload: boom("reload") },
    history: {
      pushState: (state: unknown, _t: string, url: string) => {
        calls.push("push " + url);
        stack.splice(index + 1);
        stack.push({ url, state });
        index = stack.length - 1;
        apply(url);
      },
      replaceState: (state: unknown, _t: string, url: string) => {
        calls.push("replace " + url);
        stack[index] = { url, state };
        apply(url);
      },
      back: () => {
        calls.push("back");
        if (index === 0) return;
        index -= 1;
        apply(stack[index].url);
        (listeners.get("popstate") ?? []).forEach((f) => f());
      },
      get state() {
        return stack[index].state;
      },
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
  return {
    win: win as never,
    calls,
    urls: () => stack.map((e) => e.url),
    index: () => index,
    here: () => win.location.pathname + win.location.search,
    fire: (t: string) => (listeners.get(t) ?? []).forEach((f) => f()),
  };
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

describe("backTo and history", () => {
  it("owner sequence: canvas, home, archived, Back lands on home", () => {
    const f = fakeWin("/", "?canvas=default");
    backTo("/", f.win); // no previous entry: pushes
    navigate("/?view=archived", {}, f.win);
    (f.win as unknown as Window).history.back();
    assert.equal(f.here(), "/");
    assert.deepEqual(f.urls(), ["/?canvas=default", "/", "/?view=archived"]);
    assert.equal(f.index(), 1);
  });
  it("backTo steps back when the entry before is the target", () => {
    const f = fakeWin("/", "?canvas=default");
    backTo("/", f.win);
    navigate("/?view=archived", {}, f.win);
    backTo("/", f.win);
    assert.equal(f.urls().length, 3);
    assert.equal(f.index(), 1);
    assert.equal(f.here(), "/");
  });
  it("backTo pushes when the previous entry is not the target", () => {
    const f = fakeWin("/", "?canvas=a");
    navigate("/?canvas=b", {}, f.win);
    backTo("/", f.win);
    assert.equal(f.urls().length, 3);
    assert.equal(f.here(), "/");
  });
  it("home, canvas, home via backTo, canvas, Back lands on home without skipping", () => {
    const f = fakeWin("/", "");
    navigate("/?canvas=a", {}, f.win);
    backTo("/", f.win);
    assert.equal(f.here(), "/");
    assert.equal(f.urls().length, 2);
    navigate("/?canvas=b", {}, f.win);
    (f.win as unknown as Window).history.back();
    assert.equal(f.here(), "/");
  });
  it("remembers the title hint per entry, refuses other canvases, plain navigate has none", () => {
    const f = fakeWin();
    navigate("/?canvas=a", { hint: { canvas: "a", title: "Ink A" } }, f.win);
    assert.equal(titleHint("a", f.win), "Ink A");
    assert.equal(titleHint("b", f.win), null);
    navigate("/?canvas=b", {}, f.win);
    assert.equal(titleHint("b", f.win), null);
  });
  it("replace keeps prev", () => {
    const f = fakeWin("/", "");
    navigate("/?canvas=a", {}, f.win);
    navigate("/?canvas=b", { replace: true }, f.win);
    backTo("/", f.win);
    assert.equal(f.urls().length, 2);
    assert.equal(f.here(), "/");
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
