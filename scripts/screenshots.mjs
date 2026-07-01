#!/usr/bin/env node
/**
 * Capture anonymized dashboard screenshots for the README.
 *
 * Assumes the local stack is already running:
 *   - API at http://localhost:8001
 *   - Web at http://localhost:3001
 *   - DB seeded with `scripts/seed_demo.py`
 *
 * Usage:
 *   node scripts/screenshots.mjs                 # full page
 *   node scripts/screenshots.mjs --viewport      # above-the-fold only
 *
 * Output: docs/screenshots/{portfolio,congressional,overlap,digest}.png
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(__dirname, "..", "docs", "screenshots");
const BASE = "http://localhost:3001";

const fullPage = !process.argv.includes("--viewport");

const PAGES = [
  { name: "portfolio", path: "/", title: "Portfolio Dashboard" },
  { name: "congressional", path: "/congressional", title: "Congressional Disclosures" },
  { name: "overlap", path: "/congressional/overlap", title: "Portfolio Overlap" },
  { name: "digest", path: "/digest", title: "Daily Digest" },
];

async function run() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch();

  for (const { name, path, title } of PAGES) {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2, // retina-quality for README
      colorScheme: "dark",
    });
    const url = `${BASE}${path}`;
    console.log(`  capturing ${name.padEnd(16)} ${url}`);
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });

    // Wait for the Tremor donut SVG (portfolio page) or main content to paint.
    if (name === "portfolio") {
      await page.waitForSelector("svg.recharts-surface, svg", { timeout: 10000 }).catch(() => {});
      // give the client chart a moment to render
      await page.waitForTimeout(800);
    } else {
      await page.waitForSelector("main, article, table", { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(400);
    }

    const out = resolve(OUT_DIR, `${name}.png`);
    await page.screenshot({ path: out, fullPage, type: "png" });
    await page.close();
    console.log(`    -> ${out}`);
  }

  await browser.close();
  console.log("\nDone.");
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
