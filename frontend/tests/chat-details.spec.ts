import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

async function send(page: Page, mode: string) {
  await page.getByLabel("Message Rantau").fill(`panel:${mode}`);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByLabel("Message Rantau")).toBeEnabled();
}

test("connected quote, approval and hold panels reflect trusted records without action controls", async ({ page }) => {
  await page.goto("/student/chat");
  await send(page, "quote");
  const quote = page.getByRole("region", { name: "Quote breakdown" });
  await expect(quote).toContainText("IDR 46,025,000");
  await expect(quote).toContainText("IDR 25,000");
  await expect(quote).toContainText("Payment route");
  await expect(quote).toContainText("Rate (rounded, CNY per IDR)");
  await expect(quote).toContainText("0.00043478");
  await expect(quote).not.toContainText("mock_remit_a");
  await expect(page.getByRole("region", { name: "Tuition balance" })).toContainText("CNY 20,000.00");
  await send(page, "approved");
  await expect(page.getByRole("region", { name: "Approval status" })).toContainText("Approval recorded");
  await expect(page.getByRole("region", { name: "Approval status" })).not.toContainText("Waiting for sponsor");
  await send(page, "held");
  await expect(page.getByRole("region", { name: "Request status" })).toContainText("blocked pending separate trusted security review");
  await expect(page.getByRole("button", { name: /approve|execute|pay now|clear hold/i })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(/acct_|terms_hash|fingerprint|sponsor_balance/);
});

for (const [provider, rate, label, displayed] of [
  ["mock_remit_a", "0.0004347826086956521739130435", "Standard route", "0.00043478"],
  ["mock_remit_b", "0.000434795", "Faster route", "0.0004348"],
  ["unrecognized-provider", "0.000000001", "Payment route", "0.000000001"],
  ["mock_remit_a", "0.999999999", "Standard route", "1"],
]) {
  test(`quote display preserves ${provider} / ${rate} without exposing technical labels`, async ({ page }) => {
    await page.route("**/student/chat/api/details?*", async route => {
      const response = await route.fetch();
      const snapshot = await response.json();
      snapshot.summary.quote.provider = provider;
      snapshot.summary.quote.rate = rate;
      await route.fulfill({ response, json: snapshot });
    });
    await page.goto("/student/chat");
    await send(page, "quote");
    const quote = page.getByRole("region", { name: "Quote breakdown" });
    await expect(quote).toContainText(label);
    await expect(quote.locator("dd").nth(4)).toHaveText(displayed);
    await expect(quote).not.toContainText(provider);
  });
}

test("provider, ledger and recovery panels preserve linkage and exact state", async ({ page }) => {
  await page.goto("/student/chat");
  await send(page, "delivered");
  await expect(page.getByRole("region", { name: "Payment status" })).toContainText("Provider: Delivered");
  await expect(page.getByRole("region", { name: "Tuition balance" })).toContainText("Awaiting posting");
  await send(page, "paid");
  await expect(page.getByRole("region", { name: "Payment status" })).toContainText("posting for this particular payment is unverified");
  await send(page, "recovery");
  await expect(page.getByRole("region", { name: "Recovery steps" })).toContainText("submitted");
  await expect(page.getByRole("region", { name: "Recovery steps" })).toContainText("No missing evidence");
  await send(page, "unknown");
  await expect(page.getByRole("region", { name: "Payment status" })).toContainText("Provider: Outcome unknown");
  await expect(page.getByRole("region", { name: "Payment status" })).toContainText("Do not start a second payment");
  await send(page, "topup");
  await expect(page.getByRole("region", { name: "Tuition balance" })).toContainText("CNY 500.00");
  await expect(page.locator("body")).toContainText("current policy permits separate top-up planning");
  await expect(page.locator("body")).not.toContainText("policy does not permit a top-up");
});

test("quote expiry uses the security clock and connected panels fit mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/student/chat");
  await send(page, "offset");
  await expect(page.getByRole("region", { name: "Quote breakdown" })).not.toContainText("Expired");
  await send(page, "expired");
  await expect(page.getByRole("region", { name: "Quote breakdown" })).toContainText("Expired");
  await expect(page.getByRole("region", { name: "Approval status" })).toContainText("Approval expired");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
});

test("unavailable or invalid details clear previous cards without losing successful assistant replies", async ({ page }) => {
  await page.goto("/student/chat");
  await send(page, "quote");
  for (const mode of ["unavailable", "bad", "wrongrun"]) {
    await send(page, mode);
    await expect(page.getByLabel("Details unavailable")).toBeVisible();
    await expect(page.getByRole("region", { name: "Quote breakdown" })).toHaveCount(0);
    await expect(page.getByRole("log")).toContainText("Scoped response from the test backend");
    await expect(page.locator("body")).not.toContainText(/private diagnostic|acct_secret|123456789012|sponsor_balance/);
  }
  await send(page, "denied");
  await expect(page.getByRole("alert", { name: "Chat error" })).toContainText("cleared for privacy");
  await expect(page.getByRole("log")).not.toContainText("Scoped response from the test backend");
});

test("reset discards an in-flight detail snapshot", async ({ page }) => {
  let release: (() => void) | undefined;
  await page.route("**/student/chat/api/details?*", async route => {
    await new Promise<void>(resolve => { release = resolve; });
    await route.continue().catch(() => {});
  });
  await page.goto("/student/chat");
  await page.getByLabel("Message Rantau").fill("panel:quote");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect.poll(() => !!release).toBe(true);
  await page.getByRole("button", { name: "New chat" }).click();
  release?.();
  await expect(page.getByRole("heading", { name: "One step at a time." })).toBeVisible();
  await expect(page.getByRole("region", { name: "Quote breakdown" })).toHaveCount(0);
  await expect(page.getByRole("log")).not.toContainText("Scoped response from the test backend");
});

test("detail relay sends only the session cookie on a fixed path and rejects private fields", async ({ request }) => {
  const url = "/student/chat/api/details?conversation_id=conversation_test&run_id=run_detail_quote";
  const headers = { Cookie: "session=synthetic-test-only", "X-Actor-Id": "forged", Authorization: "Bearer synthetic-test-only" };
  const response = await request.get(url, { headers });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(await (await request.get("http://127.0.0.1:8101/inspect-details")).json()).toEqual({
    url: "/api/v1/agent/conversations/conversation_test/details?run_id=run_detail_quote", cookie: headers.Cookie,
  });
  expect((await request.get(url + "&actor_id=forged", { headers })).status()).toBe(400);
  expect((await request.get(url + "&run_id=duplicate", { headers })).status()).toBe(400);
  expect((await request.get(url, { headers: { Origin: "https://evil.example" } })).status()).toBe(403);
  expect((await request.get(url.replace("run_detail_quote", "run_detail_bad"), { headers })).status()).toBe(502);
});
