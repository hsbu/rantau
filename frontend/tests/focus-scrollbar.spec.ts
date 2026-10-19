import { test, expect } from "@playwright/test";

test("clicking login whitespace does not outline the page, while keyboard skip focus stays visible", async ({ page }) => {
  for (const path of ["/student/sign-in", "/sponsor"]) {
    await page.goto(path);
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
    await page.getByRole("heading", { level: 1 }).click();
    const main = page.getByRole("main");
    expect(await main.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("none");
    await page.goto(path);
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(main).toBeFocused();
    expect(await main.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("solid");
  }
});

test("classic scrollbar space stays reserved on short and long pages", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  for (const path of ["/student/sign-in", "/sponsor"]) {
    await page.goto(path);
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
    await page.addStyleTag({ content: "::-webkit-scrollbar { width: 24px; }" });
    const geometry = () => page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      boxes: [document.querySelector('[aria-label="Rantau home"]'), document.querySelector('main'),
        document.querySelector('[aria-labelledby="sign-in-title"]')].map(element => {
        const box = element!.getBoundingClientRect(); return { x: box.x, width: box.width };
      }),
    }));
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
    const short = await geometry();
    expect(short.width).toBeLessThan(1440);
    await page.evaluate(() => {
      const filler = document.createElement("div"); filler.id = "scrollbar-probe"; filler.style.height = "3000px";
      document.body.append(filler);
    });
    expect(await page.evaluate(() => document.documentElement.scrollHeight > innerHeight)).toBe(true);
    expect(await geometry()).toEqual(short);
    await page.locator("#scrollbar-probe").evaluate(element => element.remove());
    expect(await geometry()).toEqual(short);
  }
});
