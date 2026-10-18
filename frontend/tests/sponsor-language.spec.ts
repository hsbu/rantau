import { test, expect } from "@playwright/test";

test("Indonesian sponsor summaries preserve amounts, terms and explicit confirmation", async ({ page, context }) => {
  await context.addCookies([{ name: "session", value: "a".repeat(43), domain: "127.0.0.1", path: "/", httpOnly: true }]);
  let decisions = 0;
  await page.route("**/sponsor/api/approvals/*/decision", async route => {
    decisions++;
    expect(route.request().postDataJSON()).toEqual({ decision: "APPROVED", terms_hash: "b".repeat(64) });
    await route.fulfill({ status: 409, json: { code: "AUTHORITY_CONFLICT" } });
  });
  await page.goto("/sponsor");
  await page.getByLabel("Summary language").selectOption("id");
  await expect(page.getByText("Total pendebitan", { exact: true })).toBeVisible();
  await expect(page.getByText("IDR 20,150,000", { exact: true })).toBeVisible();
  await expect(page.getByText("CNY 8,900.00", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../.generated/a07-sponsor-summary.png", fullPage: true });
  expect(decisions).toBe(0);
  await page.getByRole("button", { name: "Approve request for Fictional university •••• DEMO", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Setujui permintaan ini?");
  await expect(page.getByRole("dialog")).toContainText("tidak memindahkan dana");
  await page.screenshot({ path: "../.generated/a07-sponsor-confirmation.png", fullPage: true });
  expect(decisions).toBe(0);
  await page.getByRole("button", { name: "Konfirmasi persetujuan", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("changed or expired");
  expect(decisions).toBe(1);
  await page.getByLabel("Summary language").selectOption("en");
  await expect(page.getByText("Total debit", { exact: true })).toBeVisible();
  await expect(page.getByText("IDR 20,150,000", { exact: true })).toBeVisible();
});
