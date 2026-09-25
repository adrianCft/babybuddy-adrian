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
          viewport: { width, height: 900 },
        });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("http://daily.test/**", async (route) => {
          const url = new URL(route.request().url());
          if (url.pathname.endsWith(".css")) {
            await route.fulfill({ contentType: "text/css", body: fixture.css });
          } else if (url.pathname.endsWith(".js")) {
            await route.fulfill({
              contentType: "text/javascript",
              body: "window.BabyBuddy={PullToRefresh:{init(){}}};",
            });
          } else if (url.pathname.startsWith("/static/")) {
            await route.fulfill({ status: 204 });
          } else {
            const html =
              url.searchParams.get("child") === fixture.otherChild
                ? fixture.otherHtml
                : url.searchParams.get("date") === fixture.previousDate
                  ? fixture.previousHtml
                  : fixture.html;
            await route.fulfill({
              contentType: "text/html; charset=utf-8",
              body: html,
            });
          }
        });
        await page.goto(
          "http://daily.test/daily/?date=" +
            fixture.date +
            "&child=" +
            fixture.child,
        );
        await page.evaluate(
          (value) => (document.documentElement.dataset.bsTheme = value),
          theme,
        );
        assert.equal(await page.locator("[data-daily-card]").count(), 6);
        assert.equal(await page.locator(".daily-event").count(), 12);
        assert.equal(await page.locator(".daily-mark").count(), 12);
        assert.ok(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          "Page must not overflow horizontally",
        );
        const firstMark = page.locator(".daily-mark").first();
        const target = await firstMark.getAttribute("href");
        await firstMark.focus();
        await page.keyboard.press("Enter");
        assert.ok(
          page.url().endsWith(target),
          "Keyboard activation reaches event details",
        );
        assert.equal(await page.locator(target).isVisible(), true);
        if (width === 390) {
          assert.ok(
            await page
              .locator(".daily-chart")
              .evaluate((el) => el.scrollWidth > el.clientWidth),
            "Mobile chart can scroll",
          );
          await page
            .locator(".daily-chart")
            .evaluate((el) => (el.scrollLeft = 1000));
          assert.ok(
            await page
              .locator(".daily-chart")
              .evaluate((el) => el.scrollLeft > 0),
          );
        }
        if (process.env.BABYBUDDY_DAILY_SCREENSHOTS) {
          await page
            .locator(".daily-chart")
            .evaluate((el) => (el.scrollLeft = 0));
          await page.evaluate(() => scrollTo(0, 0));
          await page.screenshot({
            path: path.join(
              process.env.BABYBUDDY_DAILY_SCREENSHOTS,
              `daily-${width}-${theme}.png`,
            ),
            fullPage: true,
          });
        }
        await page.locator("[data-daily-previous]").click();
        await page.waitForURL(
          (url) => url.searchParams.get("date") === fixture.previousDate,
        );
        assert.equal(
          await page.locator("#id_date").inputValue(),
          fixture.previousDate,
        );
        assert.equal(
          await page.locator("#id_child").inputValue(),
          fixture.child,
        );
        await page.locator("#id_child").selectOption(fixture.otherChild);
        await page
          .getByRole("button", { name: "Ver día", exact: true })
          .click();
        await page.waitForURL(
          (url) => url.searchParams.get("child") === fixture.otherChild,
        );
        assert.equal(await page.locator(".daily-child h2").innerText(), "Otro");
        assert.equal(await page.locator(".daily-event").count(), 0);
        assert.deepEqual(errors, []);
        console.log(
          `PASS: daily overview, keyboard, day/child navigation, overflow (${width}px, ${theme})`,
        );
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
