// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn
//
// Load the dashboard in Chromium (Playwright), visit every tab, collect
// console errors.  Prints one JSON line; run_functional.py reads it.
// URL, SHOTS and CHROMIUM (an executable, optional) come from the
// environment.
const { chromium } = require("playwright");

(async () => {
  const url = process.env.URL || "http://127.0.0.1:8099/";
  const shots = process.env.SHOTS || ".";
  const out = { errors: [], tabs: [], connected: false, status: "" };
  const options = process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {};
  const browser = await chromium.launch(options);
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("console", (msg) => { if (msg.type() === "error") out.errors.push(msg.text()); });
  page.on("pageerror", (err) => out.errors.push(String(err)));
  await page.goto(url, { waitUntil: "load" });
  await page.waitForTimeout(3000);
  out.status = await page.evaluate(() => {
    const el = document.getElementById("status");
    return el ? `${el.dataset.state}: ${el.title}` : "no status element";
  });
  out.connected = out.status.startsWith("live");
  for (const tab of ["live", "films", "series", "history", "settings"]) {
    await page.goto(`${url}#${tab}`);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${shots}/web-${tab}.png` });
    out.tabs.push(`${tab}:${await page.evaluate(() => document.body.innerText.length)}`);
  }
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  phone.on("pageerror", (err) => out.errors.push(String(err)));
  await phone.goto(`${url}#live`);
  await phone.waitForTimeout(3000);
  await phone.screenshot({ path: `${shots}/web-phone-live.png` });
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((err) => { console.log(JSON.stringify({ errors: [String(err)], tabs: [] })); });
