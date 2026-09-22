import { defineConfig } from "@playwright/test";

/* Responsiveness checks run against the dev server that is already up, rather
 * than starting one: the app needs the Django backend on :8000 alongside it, so
 * a Playwright-managed web server would only ever get half the stack. */
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    screenshot: "only-on-failure",
  },
});
