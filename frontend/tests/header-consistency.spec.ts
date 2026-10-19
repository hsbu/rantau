import { test, expect } from "@playwright/test";

test("the brand and student navigation keep their geometry across page changes", async ({ page }) => {
  for (const width of [320, 390, 600, 601, 768, 1440, 1920]) {
    await page.setViewportSize({ width, height: 844 });
    let brandBox;
    let studentBoxes;
    for (const route of ["/student/chat", "/student/chat/preview", "/student/payments", "/student/sign-in", "/", "/sponsor", "/demo"]) {
      await page.goto(route);
      const banner = page.getByRole("banner");
      const brand = await banner.getByRole("link", { name: "Rantau home" }).boundingBox();
      brandBox ??= brand;
      expect(brand, `${route} moves the brand at ${width}px`).toEqual(brandBox);
      if (route.startsWith("/student/")) {
        const boxes = await Promise.all(["Chat", "Scenarios", "Payments", "Sign in / account"].map(name =>
          banner.getByRole("link", { name, exact: true }).boundingBox()));
        studentBoxes ??= boxes;
        expect(boxes, `${route} moves student navigation at ${width}px`).toEqual(studentBoxes);
        for (const box of boxes) {
          expect(box!.height).toBeGreaterThanOrEqual(44);
          expect(box!.x).toBeGreaterThanOrEqual(0);
          expect(box!.x + box!.width).toBeLessThanOrEqual(width);
        }
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
    }
  }
});

test("student and sponsor credential controls use the same visual and touch sizing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let original;
  for (const route of ["/student/sign-in", "/sponsor"]) {
    await page.goto(route);
    const button = page.getByRole("button", { name: "Sign in", exact: true });
    await expect(button).toBeEnabled();
    const input = page.getByLabel("Username", { exact: true });
    const style = (element: HTMLElement) => {
      const css = getComputedStyle(element);
      return { font: css.font, radius: css.borderRadius, padding: css.padding, background: css.backgroundColor,
        color: css.color, border: css.border, minHeight: css.minHeight };
    };
    const controls = [await input.evaluate(style), await button.evaluate(style)];
    original ??= controls;
    expect(controls).toEqual(original);
    expect((await input.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
});
