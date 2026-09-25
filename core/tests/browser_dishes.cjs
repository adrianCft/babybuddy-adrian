// Run via the optional Django browser test with BABYBUDDY_PLAYWRIGHT_MODULE set.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require(process.env.BABYBUDDY_PLAYWRIGHT_MODULE);
const fixture = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

(async () => {
  const browser = await chromium.launch({
    channel: process.env.BABYBUDDY_BROWSER || "msedge",
    headless: true,
  });
  try {
    for (const width of [390, 1280]) {
      const page = await browser.newPage({ viewport: { width, height: 850 } });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      let saved = 0;
      await page.route("http://babybuddy.test/**", async (route) => {
        if (route.request().url().endsWith("/dishes/quick-add/")) {
          const body = route.request().postData();
          assert.ok(body.includes("Plato desde selección"));
          assert.ok(body.includes('name="foods"'));
          saved++;
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              id: 900,
              name: "Plato desde selección",
              foods: [fixture.apple, fixture.oats],
            }),
          });
        } else if (route.request().url().endsWith("/foods/quick-add/")) {
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({ id: 901, name: "Nuevo ingrediente" }),
          });
        } else {
          await route.fulfill({
            contentType: "text/html; charset=utf-8",
            body: fixture.html,
          });
        }
      });
      await page.goto("http://babybuddy.test/");
      const selectedCount = () =>
        page.locator("[data-food-selected] input:checked").count();
      const checkbox = (id) =>
        page.locator(`input[name="foods"][value="${id}"]`);
      assert.equal(
        await selectedCount(),
        1,
        "Existing ingredient appears above the list",
      );
      assert.equal(
        await page.locator("[data-dish-applied] button").innerText(),
        "Plato histórico ×",
      );
      await page.locator("[data-food-search]").fill("avena");
      assert.equal(
        await checkbox(fixture.apple).isVisible(),
        true,
        "Search preserves selected foods",
      );
      await checkbox(fixture.oats).check();
      assert.equal(await selectedCount(), 2);
      await checkbox(fixture.oats).focus();
      await page.keyboard.press("Space");
      assert.equal(
        await selectedCount(),
        1,
        "Keyboard deselection returns ingredient to list",
      );
      await page
        .locator("[data-dish-picker]")
        .selectOption(String(fixture.dish));
      await page.locator("[data-dish-add]").click();
      assert.equal(await selectedCount(), 2, "Recipe selects all ingredients");
      await page
        .locator("[data-dish-picker]")
        .selectOption(String(fixture.sharedDish));
      await page.locator("[data-dish-add]").click();
      assert.equal(
        await selectedCount(),
        2,
        "Shared ingredients are not duplicated",
      );
      await page
        .locator("[data-dish-picker]")
        .selectOption(String(fixture.dish));
      await page.locator("[data-dish-add]").click();
      assert.equal(
        await page.locator("[data-dish-applied] button").count(),
        3,
        "Repeated dish is not duplicated",
      );
      await checkbox(fixture.oats).uncheck();
      assert.equal(
        await selectedCount(),
        1,
        "Meal ingredients remain individually editable",
      );
      await page.locator("[data-dish-applied] button").last().click();
      assert.equal(
        await selectedCount(),
        1,
        "Removing name preserves ingredients",
      );
      await checkbox(fixture.oats).check();
      await page.locator("[data-dish-save-panel] summary").click();
      await page.locator("[data-dish-new-name]").fill("Plato desde selección");
      await page.locator("[data-dish-save]").click();
      await page.waitForFunction(() =>
        document.querySelector('[data-dish-picker] option[value="900"]'),
      );
      assert.equal(saved, 1);
      assert.ok(
        JSON.parse(
          await page.locator("[data-dish-names]").inputValue(),
        ).includes("Plato desde selección"),
      );
      // The new ingredient must remain visible even with a nonmatching search.
      await page.locator("[data-food-quick-add-open]").click();
      await page.locator("[data-food-new-name]").fill("Nuevo ingrediente");
      await page.locator("[data-food-quick-add-submit]").click();
      await page.waitForFunction(() =>
        document.querySelector('[data-food-selected] input[value="901"]'),
      );
      await page.waitForFunction(
        () =>
          !document
            .querySelector("[data-food-quick-add-modal]")
            .classList.contains("show"),
      );
      assert.equal(await selectedCount(), 3);
      assert.equal(await checkbox(901).isVisible(), true);
      assert.equal(
        await page.locator("[data-food-selected-count]").innerText(),
        "3",
      );
      assert.ok(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "No horizontal overflow",
      );
      assert.deepEqual(errors, []);
      console.log(
        `PASS: dish selection, shared foods, history, search, keyboard, quick creation (${width}px)`,
      );
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
