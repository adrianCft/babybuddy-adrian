const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.BABYBUDDY_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

(async () => {
  const browser = await chromium.launch({
    channel: process.env.BABYBUDDY_BROWSER || "msedge",
    headless: true,
  });
  try {
    for (const width of [390, 1280]) {
      for (const theme of ["light", "dark"]) {
        const page = await browser.newPage({
          viewport: { width, height: 1000 },
        });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("http://growth.test/**", async (route) => {
          const url = new URL(route.request().url());
          if (url.pathname.endsWith(".css"))
            return route.fulfill({
              contentType: "text/css",
              body: fixture.css,
            });
          if (url.pathname.endsWith(".js"))
            return route.fulfill({
              contentType: "text/javascript",
              body: "window.BabyBuddy={PullToRefresh:{init(){}}};",
            });
          if (url.pathname.startsWith("/static/"))
            return route.fulfill({ status: 204 });
          return route.fulfill({
            contentType: "text/html; charset=utf-8",
            body: url.pathname.includes("growth")
              ? fixture.growth
              : fixture.summary,
          });
        });
        for (const kind of ["summary", "growth"]) {
          await page.goto(`http://growth.test/${kind}/`);
          await page.evaluate(
            (value) => (document.documentElement.dataset.bsTheme = value),
            theme,
          );
          assert.ok(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth,
            ),
            `${kind} overflow (${width})`,
          );
          if (kind === "summary") {
            assert.equal(await page.locator("[data-period-card]").count(), 4);
            assert.equal(await page.locator("tbody tr").count(), 30);
            assert.equal(
              await page.locator("[data-routine-forecast]").count(),
              4,
            );
            assert.ok(
              (
                await page.locator("tbody a").first().getAttribute("href")
              ).includes("/daily/"),
            );
          } else {
            assert.equal(await page.locator("svg[role=img]").count(), 3);
            await page.locator("details summary").first().focus();
            await page.keyboard.press("Enter");
            assert.equal(
              await page.locator("[data-growth-settings]").isVisible(),
              true,
            );
            assert.equal(
              await page.locator("select[name=weight_unit]").inputValue(),
              "kg",
            );
            await page.locator("details summary").first().click();
          }
          if (process.env.BABYBUDDY_GROWTH_SCREENSHOTS)
            await page.screenshot({
              path: path.join(
                process.env.BABYBUDDY_GROWTH_SCREENSHOTS,
                `${kind}-${width}-${theme}.png`,
              ),
              fullPage: true,
            });
          assert.deepEqual(errors, []);
          console.log(`PASS: ${kind}, ${width}px, ${theme}`);
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
