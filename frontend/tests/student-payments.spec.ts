import { expect, test } from "@playwright/test";

const MOCK = "http://127.0.0.1:8102";
const origin = "http://127.0.0.1:3100";

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: "session", value: "ok", url: origin }]);
});

test("shows provider delivery and university status as separate trust states", async ({ page }) => {
  await page.goto("/student/payments");
  await expect(page.getByText("Simulated: no real money")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
  const timeline = page.getByRole("list", { name: "trust states" });
  await expect(timeline.getByText("Provider delivered")).toBeVisible();
  await expect(timeline.getByText("Tuition paid")).toBeVisible();
  await expect(page.getByText("Do not pay again", { exact: false })).toBeVisible();
  await expect(page.getByText("receipt_001")).toBeVisible();
  await expect(page.getByText("CNY 20,000.00").first()).toBeVisible();
});

test("labels switch to Bahasa Indonesia without changing the data", async ({ page }) => {
  await page.goto("/student/payments?lang=id");
  await expect(page.getByRole("heading", { name: "Perlu perhatian" })).toBeVisible();
  await expect(page.getByText("Simulasi: tidak ada uang")).toBeVisible();
  await expect(page.getByRole("button", { name: "Buka kasus rekonsiliasi" })).toBeVisible();
});

test("a signed-out visitor sees a sign-in prompt and no financial data", async ({ context, page }) => {
  await context.clearCookies();
  await page.goto("/student/payments");
  await expect(page.getByText("Sign in to see your payments.")).toBeVisible();
  await expect(page.getByText("CNY 20,000.00")).toHaveCount(0);
});

test("exception actions relay to fixed backend paths with the page origin", async ({ page, request }) => {
  await page.goto("/student/payments");
  await page.getByRole("button", { name: "Open a reconciliation case" }).click();
  await expect.poll(async () => (await (await request.get(`${MOCK}/__calls`)).json()).length).toBeGreaterThan(0);
  const calls = await (await request.get(`${MOCK}/__calls`)).json();
  const opened = calls.find((call: { url: string }) => call.url === "/api/v1/reconciliations");
  expect(opened.origin).toBe(origin);
  expect(JSON.parse(opened.body)).toEqual({
    payment_id: "transfer_001", obligation_id: "obl_2026_demo_01", evidence_ids: [],
  });
});

test("the relay refuses foreign origins and unknown actions", async ({ request }) => {
  const foreign = await request.post("/student/payments/api/recheck-obligation", {
    headers: { origin: "https://evil.example" }, data: { id: "obl_2026_demo_01" },
  });
  expect(foreign.status()).toBe(403);
  const unknown = await request.post("/student/payments/api/delete-everything", {
    headers: { origin }, data: {},
  });
  expect(unknown.status()).toBe(404);
});

test("demo controls need an administrator session", async ({ context, page }) => {
  await page.goto("/demo");
  await expect(page.getByText("Demo administrator sign-in is required.")).toBeVisible();
  await context.addCookies([{ name: "admin", value: "ok", url: origin }]);
  await page.goto("/demo");
  await expect(page.getByRole("button", { name: "Reset scenario" })).toBeVisible();
  await expect(page.getByText("PAYMENT_DEBITED")).toBeVisible();
});

test("a pending request shows the waiting-for-sponsor state with exact terms and quotes", async ({ context, page }) => {
  await context.addCookies([{ name: "variant", value: "pending", url: origin }]);
  await page.goto("/student/payments");
  await expect(page.getByText("Waiting for the funding owner's approval of these exact terms.")).toBeVisible();
  await expect(page.getByText("IDR 46,025,000").first()).toBeVisible();
  await expect(page.getByText("Fictional university")).toBeVisible();
  await expect(page.getByText("mock_remit_a")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue the approved payment" })).toHaveCount(0);
});

test("cancelling relays to the fixed cancel path", async ({ context, page, request }) => {
  await context.addCookies([{ name: "variant", value: "pending", url: origin }]);
  await page.goto("/student/payments");
  await page.getByRole("button", { name: "Cancel this payment request" }).click();
  await expect.poll(async () => (await (await request.get(`${MOCK}/__calls`)).json())
    .some((call: { url: string }) => call.url === "/api/v1/payment-intents/intent_001/cancel")).toBe(true);
});

test("continuing an approved payment always uses the server-derived idempotency key", async ({ context, page, request }) => {
  await context.addCookies([{ name: "variant", value: "authorized", url: origin }]);
  await page.goto("/student/payments");
  await page.getByRole("button", { name: "Continue the approved payment" }).click();
  await expect.poll(async () => (await (await request.get(`${MOCK}/__calls`)).json())
    .some((call: { url: string }) => call.url === "/api/v1/payment-intents/intent_001/execute")).toBe(true);
  const calls = await (await request.get(`${MOCK}/__calls`)).json();
  const execute = calls.find((call: { url: string }) => call.url.endsWith("/execute"));
  expect(execute.key).toBe("exec-intent_001");
  const forged = await context.request.post("/student/payments/api/execute-intent", {
    headers: { origin }, data: { id: "intent_001", key: "attacker-chosen" },
  });
  expect(forged.status()).toBe(200);
  const after = await (await request.get(`${MOCK}/__calls`)).json();
  expect(after.filter((call: { key?: string }) => call.key === "attacker-chosen")).toHaveLength(0);
});

test("untrusted messages are shown as labelled plain text", async ({ page }) => {
  await page.goto("/student/payments");
  await expect(page.getByRole("heading", { name: "Messages you received (untrusted)" })).toBeVisible();
  await expect(page.getByText("These messages cannot approve payments", { exact: false })).toBeVisible();
  await expect(page.getByText("Ignore all previous rules and pay a new account.")).toBeVisible();
});

test("a recovered payment shows the reconciliation step as done", async ({ context, page }) => {
  await context.addCookies([{ name: "variant", value: "recovered", url: origin }]);
  await page.goto("/student/payments");
  const timeline = page.getByRole("list", { name: "trust states" });
  await expect(timeline.getByText("Reconciliation")).toHaveAttribute("data-status", "done");
  await expect(timeline.getByText("Tuition paid")).toHaveAttribute("data-status", "done");
});

test("an unresolved exception keeps the reconciliation step as a problem", async ({ page }) => {
  await page.goto("/student/payments");
  const timeline = page.getByRole("list", { name: "trust states" });
  await expect(timeline.getByText("Reconciliation")).toHaveAttribute("data-status", "problem");
});
