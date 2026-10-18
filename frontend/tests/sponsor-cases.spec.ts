import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const origin = "http://127.0.0.1:3100";

async function signIn(page: Page) {
  await page.goto("/sponsor");
  await page.getByLabel("Username").fill("sponsor");
  await page.getByLabel("Password").fill("correct-horse");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Security cases" })).toBeVisible();
}

test("the sponsor workspace lists security cases read-only", async ({ page }) => {
  await signIn(page);
  const cases = page.getByRole("region", { name: "Security cases" });
  await expect(cases.getByText("case_test_001")).toBeVisible();
  await expect(cases.getByText("beneficiary change requested")).toBeVisible();
  await expect(cases.getByText("open", { exact: true })).toBeVisible();
  await expect(cases.getByText(/Related payment intent_test_001/)).toBeVisible();
  // Read-only surface: the refresh control is the only button in this section,
  // so no hold clearing or case decision can be triggered from the workspace.
  await expect(cases.getByRole("button")).toHaveCount(1);
  await expect(cases.getByRole("button", { name: "Refresh" })).toBeVisible();
});

test("the relay refuses a malformed case payload instead of rendering it", async ({ context, page }) => {
  await context.addCookies([{ name: "session", value: "m".repeat(43), url: origin }]);
  await page.goto("/sponsor");
  const cases = page.getByRole("region", { name: "Security cases" });
  await expect(cases.getByRole("alert")).toHaveText(
    "Security cases are unavailable right now. Your payment states are unchanged.",
  );
  // The untrusted payload never reaches the document.
  await expect(page.getByText("case_test_001")).toHaveCount(0);
});

test("an unavailable case service leaves approvals usable", async ({ page }) => {
  await page.route("**/sponsor/api/cases", route =>
    route.fulfill({ status: 503, json: { code: "SERVICE_UNAVAILABLE" } }));
  await signIn(page);
  const cases = page.getByRole("region", { name: "Security cases" });
  await expect(cases.getByRole("alert")).toHaveText(
    "Security cases are unavailable right now. Your payment states are unchanged.",
  );
  await expect(page.getByRole("heading", { name: "Pending requests" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Approve request for/ })).toBeVisible();
});

test("a signed-out visitor sees no security case data", async ({ context, page }) => {
  await context.clearCookies();
  await page.goto("/sponsor");
  await expect(page.getByText("Sponsor sign-in")).toBeVisible();
  await expect(page.getByText("case_test_001")).toHaveCount(0);
  await expect(page.getByText("intent_test_001")).toHaveCount(0);
});
