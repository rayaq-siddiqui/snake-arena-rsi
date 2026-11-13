// Browser smoke test for the viewer. Usage: node tests/viz/smoke.mjs http://127.0.0.1:8765/ [screenshot.png]
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const url = process.argv[2];
const shot = process.argv[3];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: shot ? 2 : 1 });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

const tickOf = async () => Number((await page.textContent("#status")).match(/tick ([\d,]+)/)[1].replace(/,/g, ""));
const fail = async (msg) => { console.error("FAIL:", msg, errors); await browser.close(); process.exit(1); };

await page.goto(url);
await page.waitForFunction(() => /tick \d/.test(document.querySelector("#status").textContent));
if ((await page.locator("#leaderboard tbody tr").count()) !== 6) await fail("expected 6 leaderboard rows (the arena lineup)");
if (!/Hunter/.test(await page.textContent("#leaderboard"))) await fail("leaderboard lacks personality names");
if ((await page.inputValue("select[name=policy]")) !== "arena") await fail("policy select not on the lineup");
await page.waitForTimeout(1500);
const t1 = await tickOf();
if (t1 < 5) await fail(`ticks did not advance (${t1})`);

await page.click("#play"); // pause
await page.waitForTimeout(300);
const p1 = await tickOf();
await page.waitForTimeout(800);
if ((await tickOf()) !== p1) await fail("pause did not stop ticks");
await page.click("#step");
await page.waitForTimeout(200);
if ((await tickOf()) !== p1 + 1) await fail("step did not advance exactly one tick");

await page.selectOption("#speed", "max");
await page.click("#play");
await page.waitForTimeout(1500);
if ((await tickOf()) < p1 + 100) await fail("max speed did not speed up playback");

await page.fill("input[name=seed]", "7");
await page.fill("input[name=width]", "16");
await page.fill("input[name=height]", "16");
await page.fill("input[name=score_target]", "3");
await page.fill("input[name=max_ticks]", "2000");
await page.selectOption("select[name=policy]", "random_safe");
await page.click("button[type=submit]");
await page.waitForFunction(() => /seed 7/.test(document.querySelector("#status").textContent));
await page.click("#finish");
await page.waitForSelector("#banner:not(.hidden)");
const banner = await page.textContent("#banner");
if (!/wins|Tick cap|Tie/.test(banner)) await fail(`unexpected banner: ${banner}`);

if (await page.isVisible("#library-panel")) {
  await page.selectOption("#speed", "1");
  await page.waitForSelector("#lib-list button[data-entry]");
  const games = await page.locator("#lib-list button[data-entry]").count();
  if (games < 1) await fail("library lists no games");
  await page.selectOption("#lib-policy", "hunter");
  await page.waitForFunction(() => document.querySelectorAll("#lib-list button[data-entry]").length === 3);
  await page.click("#lib-list button[data-entry]");
  await page.waitForSelector("#lib-list button.current");
  await page.waitForFunction(() => /tick [1-9]/.test(document.querySelector("#status").textContent));
  await page.click("#play"); // pause
  await page.fill("#bm-note", "smoke");
  await page.click("#bookmark");
  await page.waitForSelector("#bm-list button[data-tick]");
  const mark = await page.textContent("#bm-list");
  if (!/smoke/.test(mark)) await fail(`bookmark not listed: ${mark}`);
  const markTick = Number((await page.getAttribute("#bm-list button[data-tick]", "data-tick")));
  await page.click("#new-seed");
  await page.click("#bm-list button[data-tick]");
  await page.waitForFunction((t) => new RegExp(`tick ${t.toLocaleString("en-US")} `).test(document.querySelector("#status").textContent), markTick);
  if (!/paused/.test(await page.textContent("#status"))) await fail(`bookmark did not open paused: ${await page.textContent("#status")}`);
}

if (shot) {
  await page.fill("input[name=seed]", "42");
  await page.fill("input[name=width]", "20");
  await page.fill("input[name=height]", "20");
  await page.fill("input[name=score_target]", "10");
  await page.selectOption("#speed", "max");
  await page.click("button[type=submit]");
  await page.waitForTimeout(4000);
  await page.selectOption("#speed", "5");
  await page.waitForTimeout(500);
  await page.screenshot({ path: shot });
}
if (errors.length) await fail("page errors");
console.log("OK", { firstTick: t1, banner });
await browser.close();
