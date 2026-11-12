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
if ((await page.locator("#leaderboard tbody tr").count()) !== 5) await fail("expected 5 leaderboard rows");
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
await page.click("button[type=submit]");
await page.waitForFunction(() => /seed 7/.test(document.querySelector("#status").textContent));
await page.click("#finish");
await page.waitForSelector("#banner:not(.hidden)");
const banner = await page.textContent("#banner");
if (!/wins|Tick cap|Tie/.test(banner)) await fail(`unexpected banner: ${banner}`);

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
