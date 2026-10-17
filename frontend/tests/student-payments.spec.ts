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
