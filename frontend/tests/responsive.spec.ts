import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";

/* Responsiveness checks for Readiness Testing.
 *
 * The sheet is deliberately wider than any screen and scrolls sideways, so the
 * test cannot simply assert "nothing is wider than the viewport" - that is true
 * of the page, but false of the table, by design. What it checks instead is that
 * the *page* never scrolls horizontally: any overflow must be contained by a
 * scroller, not pushed onto the document. That is the failure that actually
 * hurts, because it shifts the whole layout sideways on a phone.
 *
 * Fixtures (a session cookie and a share token) are written by the setup step
 * documented in tests/README.md; the suite skips rather than fails without them,
 * so it stays runnable on a machine that has no database.
 */

const FIXTURES = "C:/Users/BERNAD~1/AppData/Local/Temp/claude/pw.json";

type Fixtures = { sessionid: string; token: string; projectId: number };

function fixtures(): Fixtures | null {
  try {
    return JSON.parse(fs.readFileSync(FIXTURES, "utf8")) as Fixtures;
  } catch {
    return null;
  }
}

const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "laptop", width: 1280, height: 800 },
  { name: "desktop", width: 1920, height: 1080 },
];

/** Elements that push the document wider than the window. */
async function horizontalOverflow(page: Page) {
  return page.evaluate(() => {
    const docWidth = document.documentElement.clientWidth;
    const scrollWidth = document.documentElement.scrollWidth;
    const offenders: { tag: string; cls: string; width: number }[] = [];

    if (scrollWidth > docWidth + 1) {
      for (const el of Array.from(document.querySelectorAll<HTMLElement>("*"))) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.right <= docWidth + 1) continue;
        // Anything inside a scroller is meant to be wider than the screen.
        let node: HTMLElement | null = el.parentElement;
        let contained = false;
        while (node) {
          const overflowX = getComputedStyle(node).overflowX;
          if (overflowX === "auto" || overflowX === "scroll" || overflowX === "hidden") {
            contained = true;
            break;
          }
          node = node.parentElement;
        }
        if (contained) continue;
        offenders.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || "").toString().slice(0, 80),
          width: Math.round(r.width),
        });
      }
    }
    return { docWidth, scrollWidth, offenders: offenders.slice(0, 6) };
  });
}

test.describe("Readiness Testing is responsive", () => {
  for (const vp of VIEWPORTS) {
    test(`reviewer page at ${vp.name} (${vp.width}px)`, async ({ page }) => {
      const fx = fixtures();
      test.skip(!fx, "No fixtures: run the setup step in tests/README.md first.");

      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`/readiness/${fx!.token}`);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

      const result = await horizontalOverflow(page);
      expect(
        result.offenders,
        `page scrolls sideways at ${vp.width}px `
        + `(scrollWidth ${result.scrollWidth} > ${result.docWidth}): `
        + JSON.stringify(result.offenders),
      ).toEqual([]);
    });

    test(`main page at ${vp.name} (${vp.width}px)`, async ({ page, context }) => {
      const fx = fixtures();
      test.skip(!fx, "No fixtures: run the setup step in tests/README.md first.");

      await context.addCookies([{
        name: "sessionid", value: fx!.sessionid,
        domain: "localhost", path: "/",
      }]);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/readiness-testing");
      await expect(page.getByRole("heading", { name: "Readiness Testing" }))
        .toBeVisible();

      const result = await horizontalOverflow(page);
      expect(
        result.offenders,
        `page scrolls sideways at ${vp.width}px `
        + `(scrollWidth ${result.scrollWidth} > ${result.docWidth}): `
        + JSON.stringify(result.offenders),
      ).toEqual([]);
    });
  }

  test("the sheet scrolls sideways rather than the page", async ({ page }) => {
    const fx = fixtures();
    test.skip(!fx, "No fixtures: run the setup step in tests/README.md first.");

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/readiness/${fx!.token}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    // The table is wider than the window on purpose; its scroller absorbs that.
    const table = page.locator("table").first();
    await expect(table).toBeVisible();
    const box = await table.boundingBox();
    expect(box).not.toBeNull();

    const doc = await page.evaluate(() => ({
      client: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
    }));
    expect(doc.scroll).toBeLessThanOrEqual(doc.client + 1);
  });
});
