import { test, expect } from "@playwright/test";

test("student and sponsor sign-in share a balanced composition on desktop and mobile", async ({ page }) => {
  for (const width of [320, 390, 768, 900, 960, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    let original;
    for (const [path, role] of [["/student/sign-in", "Student"], ["/sponsor", "Sponsor"]]) {
      await page.goto(path);
      await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
      const title = await page.getByRole("heading", { level: 1 }).boundingBox();
      const panel = page.getByRole("region", { name: `${role} sign-in`, exact: true });
      const box = await panel.boundingBox();
      expect(box).not.toBeNull();
      if (width > 900) {
        expect(box!.x).toBeGreaterThan(title!.x + title!.width);
        expect(box!.y).toBeLessThan(200);
        expect((await panel.getByRole("button", { name: "Sign in", exact: true }).boundingBox())!.y).toBeLessThan(700);
      } else {
        expect(box!.y).toBeGreaterThan(title!.y + title!.height);
      }
      const styles = await panel.evaluate(element => {
        const css = getComputedStyle(element);
        return { background: css.backgroundColor, border: css.border, radius: css.borderRadius, padding: css.padding };
      });
      const shape = { x: box!.x, width: box!.width, styles };
      original ??= shape;
      expect(shape).toEqual(original);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
    }
  }
});

test("sponsor sign-in shows only relevant controls and keeps errors inside its card", async ({ page }) => {
  await page.goto("/sponsor");
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeEnabled();
  await expect(page.getByLabel("Summary language")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Review payment requests" })).toHaveCount(0);
  await page.getByLabel("Username", { exact: true }).fill("sponsor");
  await page.getByLabel("Password", { exact: true }).fill("wrong");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const panel = page.getByRole("region", { name: "Sponsor sign-in", exact: true });
  await expect(panel.getByRole("alert")).toContainText("not accepted");
  await expect(panel.getByLabel("Password", { exact: true })).toHaveValue("");
});

test("sponsor checking and wrong-role states stay in the login composition", async ({ page }) => {
  let release!: () => void;
  const paused = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/sponsor/api/session", async route => {
    await paused;
    await route.fulfill({ json: { authenticated: true, role: "STUDENT" } });
  });
  await page.goto("/sponsor");
  const panel = page.getByRole("region", { name: "Sponsor sign-in", exact: true });
  await expect(panel.getByRole("status")).toContainText("Checking");
  await expect(page.getByLabel("Summary language")).toHaveCount(0);
  release();
  await expect(panel.getByText("This workspace is for sponsors")).toBeVisible();
  await expect(panel.getByLabel("Password", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Pending requests" })).toHaveCount(0);
});
