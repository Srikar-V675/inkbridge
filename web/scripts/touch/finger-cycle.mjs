// INK-180 repro and check: the "Finger draws" toggle cycle in a real browser with synthetic pointer
// events (touch and pen), a pen contact in between, and reloads. Dev tooling only, not CI.
// playwright is not a dependency: PW_DIR (default below) must contain node_modules/playwright. If
// Playwright's own Chromium is missing, executablePath falls back to /usr/bin/chromium; the build in
// ~/.cache/ms-playwright/chromium-1248 is used when present.
//
//   node scripts/touch/finger-cycle.mjs --base http://127.0.0.1:5193 --canvas <id of a canvas made with POST /documents> [--api http://127.0.0.1:8103]
//     [--expect-fixed] [--shots /tmp/claude-1000/ink180]
//
// Prints `step | observed` lines. With --expect-fixed it exits non-zero when any check fails.
import { existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => {
    if (a.startsWith("--")) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : true]);
    return acc;
  }, []),
);
const base = args.base ?? "http://127.0.0.1:5193";
const api = args.api ?? "http://127.0.0.1:8103";
const canvas = args.canvas ?? "ink180";
const expectFixed = Boolean(args["expect-fixed"]);
const shots = args.shots ?? "/tmp/claude-1000/ink180";
const pwDir = process.env.PW_DIR ?? "/home/vsrikar/.local/share/mise/installs/playwright/latest/node_modules";
const { chromium } = createRequire(join(pwDir, "package.json"))("playwright");

const pwChromium = "/home/vsrikar/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome";
const executablePath = existsSync(pwChromium) ? pwChromium : "/usr/bin/chromium";
mkdirSync(shots, { recursive: true });

const rows = [];
let failed = 0;
const log = (step, observed, ok = true) => {
  if (!ok) failed++;
  rows.push(`${ok ? "ok  " : "FAIL"} ${step} | ${observed}`);
  console.log(rows[rows.length - 1]);
};
const check = (step, observed, ok) => log(step, observed, ok);

const browser = await chromium.launch({ executablePath, args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, hasTouch: true });
const page = await ctx.newPage();
const url = `${base}/?canvas=${canvas}`;
const btn = () => page.getByRole("button", { name: "Finger draws" });
const wait = (ms) => page.waitForTimeout(ms);

async function open() {
  await page.goto(url);
  await page.waitForSelector("canvas.interactive", { timeout: 15000 });
  await btn().waitFor();
  await wait(1200);
}
async function pickPen() {
  await page.getByRole("button", { name: "Pen", exact: true }).click();
  await page.mouse.move(0, 0);
}
async function drag(pointerType, id, y0) {
  await page.evaluate(
    ({ pointerType, id, y0 }) => {
      const c = document.querySelector("canvas.interactive");
      c.setPointerCapture = () => {};
      c.releasePointerCapture = () => {};
      const fire = (type, x, y, pressure) =>
        c.dispatchEvent(
          new PointerEvent(type, { pointerType, pointerId: id, isPrimary: true, pressure, clientX: x, clientY: y, bubbles: true, cancelable: true, buttons: type === "pointerup" ? 0 : 1 }),
        );
      const x0 = 500;
      fire("pointerdown", x0, y0, pointerType === "pen" ? 0.3 : 0.5);
      for (let i = 1; i <= 6; i++) fire("pointermove", x0 + i * 20, y0 + i * 10, pointerType === "pen" ? 0.3 + i * 0.08 : 0.5);
      fire("pointerup", x0 + 120, y0 + 60, 0);
    },
    { pointerType, id, y0 },
  );
}
const view = async () => {
  await wait(700);
  return page.evaluate((c) => JSON.parse(localStorage.getItem(`inkbridge-view-${c}`) ?? "null"), canvas);
};
const elementCount = async () => {
  await wait(1800);
  const r = await fetch(`${api}/documents/${canvas}/scene`);
  const j = await r.json();
  return (j.elements ?? []).filter((e) => !e.isDeleted).length;
};
let yStep = 150;
/** Outcome of one drag: drew (count +1, view unchanged), panned (view moved, count same) or other. */
async function outcome(pointerType) {
  const v0 = await view();
  const n0 = await elementCount();
  yStep += 90;
  await drag(pointerType, pointerType === "pen" ? 3 : 7, yStep);
  const v1 = await view();
  const n1 = await elementCount();
  const moved = !v0 || !v1 || v0.scrollX !== v1.scrollX || v0.scrollY !== v1.scrollY;
  const added = n1 - n0;
  if (added > 0 && !moved) return "drew";
  if (added === 0 && moved) return "panned";
  return `other(+${added} elements, moved=${moved})`;
}
const pressed = async () => (await btn().getAttribute("aria-pressed")) === "true";
const bg = () => btn().evaluate((el) => getComputedStyle(el).backgroundColor);
const fg = () => btn().evaluate((el) => getComputedStyle(el).color);

async function expectState(step, want, touchWants) {
  const p = await pressed();
  check(`${step}: aria-pressed`, String(p), p === want);
  const o = await outcome("touch");
  check(`${step}: touch drag`, o, o === touchWants);
}

await open();
await pickPen();

// A. fresh state
await expectState("A fresh", false, "panned");

// B. on
await btn().click();
await expectState("B on", true, "drew");
const onColour = await bg();
log("B on colour", `bg ${onColour} fg ${await fg()}`);
await page.screenshot({ path: join(shots, "topbar-on.png"), clip: { x: 0, y: 0, width: 1280, height: 80 } });

// C. pen contact, then touch must still draw
await drag("pen", 3, 600);
await wait(300);
{
  const o = await outcome("touch");
  check("C on after pen contact: touch drag", o, o === "drew");
}

// D. off, mouse stays over the button (a tablet leaves :hover stuck)
await btn().click();
{
  const p = await pressed();
  check("D off: aria-pressed", String(p), p === false);
  const offHover = await bg();
  log("D off+hover colour", `bg ${offHover} fg ${await fg()}`);
  check("D on colour differs from off+hover", `${onColour} vs ${offHover}`, onColour !== offHover);
  const o = await outcome("touch");
  check("D off: touch drag", o, o === "panned");
  await page.mouse.move(0, 0);
  await wait(200);
  const offPlain = await bg();
  log("D off plain colour", `bg ${offPlain}`);
  check("D on colour differs from plain off", `${onColour} vs ${offPlain}`, onColour !== offPlain);
  await page.screenshot({ path: join(shots, "topbar-off.png"), clip: { x: 0, y: 0, width: 1280, height: 80 } });
}

// E. pen contact with the setting off keeps a finger panning
await drag("pen", 3, 650);
await wait(300);
{
  const o = await outcome("touch");
  check("E off after pen contact: touch drag", o, o === "panned");
}

// F. reload in each state
await open();
await pickPen();
await expectState("F reload off", false, "panned");
await btn().click();
await drag("pen", 3, 700);
await wait(300);
await open();
await pickPen();
await expectState("F reload on", true, "drew");
await btn().click();
await open();
await pickPen();
await expectState("F reload off again", false, "panned");

// G. the same cycle with a touch tap on the button
async function tap() {
  const box = await btn().boundingBox();
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
}
await tap();
await expectState("G tap on", true, "drew");
await drag("pen", 3, 720);
await wait(300);
await tap();
await expectState("G tap off", false, "panned");
{
  const c = await bg();
  log("G colour after touch tap off", `bg ${c}`);
  check("G colour after touch tap differs from on", `${onColour} vs ${c}`, c !== onColour);
}

await browser.close();
console.log(failed ? `\n${failed} check(s) failed` : "\nall checks passed");
if (expectFixed && failed) process.exit(1);
