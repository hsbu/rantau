import { expect, test, type Page } from "@playwright/test";

const origin = "http://127.0.0.1:3100";
const viewports = [
  { width: 320, height: 568 }, { width: 390, height: 844 },
  { width: 768, height: 1024 }, { width: 1024, height: 768 },
  { width: 1440, height: 900 }, { width: 1920, height: 1080 },
  { width: 844, height: 390 },
];

async function fitsPage(page: Page) {
  expect(await page.evaluate(() => ({
    viewport: innerWidth, content: document.documentElement.scrollWidth,
  }))).toEqual({ viewport: page.viewportSize()!.width, content: page.viewportSize()!.width });
}

for (const path of ["/", "/student/sign-in", "/student/chat", "/student/chat/preview", "/sponsor", "/student/payments", "/demo"]) {
  test(`${path} fits phone, tablet, desktop and landscape viewports`, async ({ page }) => {
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await page.goto(path);
      await expect(page.locator("main")).toBeVisible();
      await fitsPage(page);
    }
  });
}

for (const variant of ["unpaid", "pending", "authorized", "held", "partial", "recovered"]) {
  test(`payment ${variant} preserves terms inside a narrow page`, async ({ page, context }) => {
    const actions: string[] = [];
    page.on("request", request => { if (request.method() === "POST") actions.push(request.url()); });
    await context.addCookies([
      { name: "session", value: "ok", url: origin },
      { name: "variant", value: variant, url: origin },
    ]);
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/student/payments");
      await expect(page.getByText("CNY 20,000.00").first()).toBeVisible();
      await fitsPage(page);
      if (variant === "pending" && width === 390) await page.screenshot({ path: "../.generated/responsive-payments.png", fullPage: true });
    }
    expect(actions).toEqual([]);
  });
}

test("quote and audit tables scroll within the page and support keyboard access", async ({ page, context }) => {
  await context.addCookies([
    { name: "session", value: "ok", url: origin },
    { name: "variant", value: "unpaid", url: origin },
    { name: "admin", value: "ok", url: origin },
  ]);
  await page.setViewportSize({ width: 320, height: 568 });
  for (const [path, name] of [["/student/payments", "Simulated quotes (total cost compared)"], ["/demo", "Redacted audit trail (current run)"]]) {
    await page.goto(path);
    await fitsPage(page);
    const region = page.getByRole("region", { name, exact: true });
    await expect(region.getByRole("table")).toBeVisible();
    await region.focus();
    await expect(region).toBeFocused();
    expect(await region.evaluate(e => e.scrollWidth > e.clientWidth)).toBe(true);
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => region.evaluate(e => e.scrollLeft)).toBeGreaterThan(0);
  }
});

for (const language of ["en", "id"]) {
  test(`sponsor confirmation stays reachable on short screens (${language})`, async ({ page, context }) => {
    await context.addCookies([{ name: "session", value: "a".repeat(43), url: origin }]);
    const decisions: string[] = [];
    page.on("request", request => {
      if (request.url().includes("/decision")) decisions.push(request.url());
    });
    await page.setViewportSize({ width: 320, height: 400 });
    await page.goto("/sponsor");
    await page.getByLabel("Summary language").selectOption(language);
    await page.getByRole("button", { name: "Approve request for Fictional university •••• DEMO", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: language === "id" ? "Setujui permintaan ini?" : "Approve this request?" });
    await expect(dialog).toBeVisible();
    const confirm = dialog.getByRole("button", { name: language === "id" ? "Konfirmasi persetujuan" : "Confirm approval", exact: true });
    await confirm.scrollIntoViewIfNeeded();
    const box = await confirm.boundingBox();
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(400);
    if (language === "id") await page.screenshot({ path: "../.generated/responsive-sponsor-dialog.png" });
    await dialog.getByRole("button", { name: "Go back" }).click();
    await expect(dialog).not.toBeVisible();
    expect(decisions).toEqual([]);
    await fitsPage(page);
  });
}

test("mobile text inputs remain readable and chat composer fits a normal phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/student/sign-in", "/sponsor", "/student/chat", "/student/chat/preview"]) {
    await page.goto(path);
    await expect(page.locator("input, textarea").first()).toBeVisible();
    const fonts = await page.locator("input, textarea").evaluateAll(elements => elements.map(e => parseFloat(getComputedStyle(e).fontSize)));
    expect(fonts.every(size => size >= 16)).toBe(true);
    if (path.includes("chat")) {
      const send = await page.getByRole("button", { name: "Send message" }).boundingBox();
      expect(send!.y + send!.height).toBeLessThanOrEqual(844);
    }
  }
});

test("authenticated sponsor and demo controls fit the viewport matrix without submitting actions", async ({ page, context }) => {
  await context.addCookies([
    { name: "session", value: "a".repeat(43), url: origin },
    { name: "admin", value: "ok", url: origin },
  ]);
  const actions: string[] = [];
  page.on("request", request => { if (request.method() === "POST") actions.push(request.url()); });
  for (const path of ["/sponsor", "/demo"]) {
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await page.goto(path);
      await expect(page.getByRole("button", { name: path === "/demo" ? "Reset scenario" : "Approve request for Fictional university •••• DEMO", exact: true })).toBeVisible();
      await fitsPage(page);
    }
  }
  expect(actions).toEqual([]);
});

test("long untrusted messages wrap without hiding their text or widening the page", async ({ page, context }) => {
  await context.addCookies([
    { name: "session", value: "ok", url: origin },
    { name: "variant", value: "longdocument", url: origin },
  ]);
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/student/payments");
  await expect(page.locator("pre")).toHaveText("Unbroken".repeat(500));
  await fitsPage(page);
  expect(await page.locator("pre").evaluate(e => e.scrollWidth <= e.clientWidth)).toBe(true);
});
