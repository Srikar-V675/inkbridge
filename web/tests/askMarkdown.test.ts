import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AnswerMarkdown } from "../src/askMarkdown.ts";

const render = (s: string) => renderToStaticMarkup(h(AnswerMarkdown, { source: s }));

describe("AnswerMarkdown", () => {
  it("drops raw html", () => {
    const o = render("<img src=x onerror=alert(1)> <script>alert(1)</script>");
    for (const bad of ["<img", "onerror", "<script"]) assert.ok(!o.includes(bad), bad);
  });
  it("drops unsafe hrefs", () => {
    assert.ok(!render("[x](javascript:alert(1))").includes("href"));
    assert.ok(!render("[x](data:text/html,hi)").includes("href"));
  });
  it("blocks remote images", () => {
    const o = render("![a](http://evil/p.png)");
    assert.ok(!o.includes("<img") && !o.includes("evil"));
  });
  it("keeps safe links with rel", () => {
    const o = render("[ok](https://example.com)");
    assert.ok(o.includes('href="https://example.com"') && o.includes('rel="noopener noreferrer"'));
  });
  it("renders a 20000-char answer fast", () => {
    const t = Date.now();
    const o = render("word <script>x</script> ".repeat(900).slice(0, 20000));
    assert.ok(Date.now() - t < 1000 && !o.includes("<script"));
  });
});
