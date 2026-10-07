import path from "node:path";
import { defineConfig } from "@playwright/test";

// Start the real stack with run-local.py first. Artifacts stay outside Git.
export default defineConfig({
  testDir: "./e2e",
  outputDir: path.resolve(process.env.E2E_OUTPUT_DIR ?? "../../.cache/phase-2d/browser-results"),
  timeout: 180_000,
  expect: { timeout: 90_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: process.env.E2E_REPORT ?? "../../.cache/phase-2d/browser-report.json" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    browserName: "chromium",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "laptop", use: { viewport: { width: 1280, height: 720 } } },
    { name: "tablet", use: { viewport: { width: 768, height: 1024 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
});
