import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:3100";

test("all pages share a brand and a working keyboard skip destination", async ({ page }) => {
  for (const path of ["/", "/student/sign-in", "/student/chat", "/student/chat/preview", "/student/payments", "/sponsor", "/demo"]) {
    await page.goto(path);
    await expect(page.getByRole("link", { name: "Rantau home", exact: true })).toHaveAttribute("href", "/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main")).toBeFocused();
  }
});

test("Payments has a return route and denied demo access has a heading and home destination", async ({ page }) => {
  await page.goto("/student/payments");
  await expect(page.getByRole("navigation", { name: "Chat views" }).getByRole("link", { name: "Chat", exact: true })).toHaveAttribute("href", "/student/chat");
  await page.goto("/demo");
  await expect(page.getByRole("heading", { level: 1, name: "Demo" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Return home" })).toHaveAttribute("href", "/");
});

for (const path of ["/student/sign-in", "/sponsor"]) {
  test(`${path} explains missing fields and focuses the first error without logging in`, async ({ page }) => {
    let logins = 0;
    page.on("request", request => { if (request.url().endsWith("/sponsor/api/login")) logins++; });
    await page.goto(path);
    const submit = page.getByRole("button", { name: "Sign in", exact: true });
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(page.getByLabel("Username", { exact: true })).toBeFocused();
    await expect(page.getByLabel("Username", { exact: true })).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByText("Enter your username.", { exact: true })).toBeVisible();
    await page.getByLabel("Username", { exact: true }).fill("student");
    await submit.click();
    await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
    await expect(page.getByText("Enter your password.", { exact: true })).toBeVisible();
    expect(logins).toBe(0);
  });
}

for (const lang of ["en", "id"]) {
  test(`cancellation confirms the selected request and sends nothing on back (${lang})`, async ({ page, context }) => {
    await context.addCookies([{ name: "session", value: "ok", url: origin }, { name: "variant", value: "pending", url: origin }]);
    let calls = 0;
    await page.route("**/student/payments/api/cancel-intent", route => { calls++; return route.fulfill({ json: {} }); });
    await page.goto(`/student/payments?lang=${lang}`);
    const cancel = page.getByRole("button", { name: lang === "id" ? "Batalkan permintaan pembayaran ini" : "Cancel this payment request", exact: true });
    await cancel.click();
    const dialog = page.getByRole("dialog", { name: lang === "id" ? "Batalkan permintaan pembayaran?" : "Cancel payment request?" });
    await expect(dialog).toContainText("IDR 46,025,000");
    await expect(dialog).toContainText("Fictional university");
    await dialog.getByRole("button", { name: lang === "id" ? "Kembali" : "Go back", exact: true }).click();
    expect(calls).toBe(0);
    await cancel.click();
    await dialog.getByRole("button", { name: lang === "id" ? "Konfirmasi pembatalan" : "Confirm cancellation", exact: true }).click();
    await expect.poll(() => calls).toBe(1);
    await expect(dialog).not.toBeVisible();
  });
}

test("scenario reset confirms its target and allows backing out without a request", async ({ page, context }) => {
  await context.addCookies([{ name: "admin", value: "ok", url: origin }]);
  let calls = 0;
  await page.route("**/demo/api/reset", route => { calls++; return route.fulfill({ json: {} }); });
  await page.goto("/demo");
  await page.getByRole("button", { name: "Reset scenario", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Reset this scenario?" });
  await expect(dialog).toContainText("Happy path");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "Reset scenario", exact: true }).click();
  await dialog.getByRole("button", { name: "Confirm reset", exact: true }).click();
  await expect.poll(() => calls).toBe(1);
});

for (const failure of ["network", "http"]) {
  test(`uncertain payment ${failure} failure gives a safe next step without retry`, async ({ page, context }) => {
    await context.addCookies([{ name: "session", value: "ok", url: origin }, { name: "variant", value: "authorized", url: origin }]);
    let calls = 0;
    await page.route("**/student/payments/api/execute-intent", route => {
      calls++;
      return failure === "network" ? route.abort("failed") : route.fulfill({ status: 502, json: {} });
    });
    await page.goto("/student/payments");
    const execute = page.getByRole("button", { name: "Continue the approved payment", exact: true });
    await execute.click();
    await expect(page.locator("main").getByRole("alert")).toContainText("could not confirm");
    await expect(page.locator("main").getByRole("alert")).not.toContainText("No payment was sent");
    await expect(page.getByRole("button", { name: "Check current status", exact: true })).toBeVisible();
    await expect(execute).toBeDisabled();
    expect(calls).toBe(1);
  });
}

test("demo transport errors are visible and never automatically repeated", async ({ page, context }) => {
  await context.addCookies([{ name: "admin", value: "ok", url: origin }]);
  let calls = 0;
  await page.route("**/demo/api/tick", route => { calls++; return route.abort("failed"); });
  await page.goto("/demo");
  await page.getByRole("button", { name: "University tick", exact: true }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("could not confirm");
  await expect(page.getByRole("button", { name: "University tick", exact: true })).toBeDisabled();
  expect(calls).toBe(1);
});

test("Indonesian payment presentation has language metadata and readable route/status labels", async ({ page, context }) => {
  await context.addCookies([{ name: "session", value: "ok", url: origin }, { name: "variant", value: "unpaid", url: origin }]);
  await page.goto("/student/payments?lang=id");
  await expect(page.locator("main")).toHaveAttribute("lang", "id");
  await expect(page.getByRole("columnheader", { name: "Rute", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Rute simulasi A", exact: true })).toBeVisible();
  await context.addCookies([{ name: "variant", value: "", url: origin }]);
  await page.reload();
  await expect(page.locator("main")).not.toContainText("DELIVERED");
});

test("sponsor confirmation uses explicit China time and localized confirmation text", async ({ page, context }) => {
  await context.addCookies([{ name: "session", value: "a".repeat(43), url: origin }]);
  await page.goto("/sponsor");
  await expect(page.getByText(/Request expires/)).toContainText("UTC+08:00");
  await page.getByLabel("Summary language").selectOption("id");
  await page.getByRole("button", { name: "Approve request for Fictional university •••• DEMO", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveAttribute("lang", "id");
  await expect(dialog).toContainText("Anda mengizinkan upaya pembayaran");
  await expect(dialog.getByRole("button", { name: "Kembali", exact: true })).toBeVisible();
});

test("mobile readers can jump to payment details and return to the composer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/student/chat/preview");
  await page.getByRole("link", { name: "View payment details", exact: true }).click();
  await expect(page.getByRole("complementary")).toBeFocused();
  await page.getByRole("link", { name: "Back to message", exact: true }).click();
  await expect(page.getByLabel("Message Rantau")).toBeFocused();
});
