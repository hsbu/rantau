import { test, expect } from "@playwright/test";

const origin = "http://127.0.0.1:3100";
for (const state of ["signed-out", "empty", "unavailable"]) {
  test(`Payments ${state} has a composed desktop state and a safe next step`, async ({ page, context }) => {
    if (state !== "signed-out") await context.addCookies([
      { name: "session", value: "ok", url: origin }, { name: "variant", value: state, url: origin },
    ]);
    for (const width of [1366, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/student/payments");
      const stateCard = page.getByRole("region", { name: "Payment access", exact: true });
      await expect(stateCard).toBeVisible();
      await expect(stateCard.getByRole("heading", { level: 2 })).toBeVisible();
      const action = stateCard.getByRole("link").first();
      const box = await action.boundingBox();
      expect(box!.height).toBeGreaterThanOrEqual(44);
      expect(box!.y + box!.height).toBeLessThan(768);
      expect(parseFloat(await page.getByRole("heading", { level: 1 }).evaluate(e => getComputedStyle(e).fontSize))).toBeLessThanOrEqual(44);
      await expect(page.getByRole("navigation", { name: "Page language" }).getByRole("link", { name: "English", exact: true })).toHaveAttribute("aria-current", "page");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
      if (state === "signed-out") await expect(action).toHaveAttribute("href", "/student/sign-in?next=payments");
      if (state === "unavailable") await expect(stateCard.getByRole("alert")).toContainText("Refresh status before");
      await expect(page.getByText("CNY 20,000.00", { exact: true })).toHaveCount(0);
    }
  });
}

test("Indonesian payment access and denied demo use complete state cards", async ({ page }) => {
  await page.goto("/student/payments?lang=id");
  const state = page.getByRole("region", { name: "Payment access", exact: true });
  await expect(state.getByRole("link", { name: "Masuk sebagai mahasiswa →" })).toHaveAttribute("href", "/student/sign-in?next=payments");
  await expect(page.getByRole("navigation", { name: "Page language" }).getByRole("link", { name: "Bahasa Indonesia" })).toHaveAttribute("aria-current", "page");
  await page.goto("/demo");
  await expect(page.getByRole("region", { name: "Demo access", exact: true }).getByRole("link", { name: "Return home" })).toHaveAttribute("href", "/");
  await expect(page.getByRole("button", { name: "Reset scenario" })).toHaveCount(0);
});

test("admin desktop controls have separate named groups without changing actions", async ({ page, context }) => {
  await context.addCookies([{ name: "admin", value: "ok", url: origin }]);
  await page.goto("/demo");
  for (const name of ["Scenario setup", "Simulated time", "Provider faults", "Untrusted documents"]) {
    await expect(page.getByRole("group", { name, exact: true })).toBeVisible();
  }
  const document = page.getByRole("group", { name: "Untrusted documents", exact: true });
  expect((await document.getByLabel("Body").boundingBox())!.width).toBeGreaterThan(600);
});

test("desktop sponsor review and security panels share a balanced row", async ({ page, context }) => {
  await context.addCookies([{ name: "session", value: "a".repeat(43), url: origin }]);
  for (const width of [1366, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/sponsor");
    const review = page.getByRole("region", { name: "Pending requests", exact: true });
    await expect(review.getByRole("heading", { name: "Pending requests" })).toBeVisible();
    const left = await review.boundingBox();
    const right = await page.getByRole("region", { name: "Security cases", exact: true }).boundingBox();
    expect(right!.x).toBeGreaterThan(left!.x + left!.width);
    expect(right!.y).toBe(left!.y);
  }
});

test("demo outage presents a refresh action without reporting an access error", async ({ page, context }) => {
  await context.addCookies([{ name: "admin", value: "ok", url: origin }, { name: "variant", value: "unavailable", url: origin }]);
  await page.goto("/demo");
  const state = page.getByRole("region", { name: "Demo access", exact: true });
  await expect(state.getByRole("heading", { name: "Demo is unavailable." })).toBeVisible();
  await expect(state.getByRole("link", { name: "Refresh status" })).toHaveAttribute("href", "?lang=en");
  await expect(page.getByRole("button", { name: "Reset scenario" })).toHaveCount(0);
});
