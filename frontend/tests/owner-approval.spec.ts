import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:3100";
const mock = "http://127.0.0.1:8102";
for (const lang of ["en", "id"]) {
  test(`student reviews exact own-account terms and confirms once (${lang})`, async ({ page, context, request }) => {
    await context.addCookies([{ name: "session", value: "ok", url: origin }, { name: "variant", value: "ownpending", url: origin }]);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/student/payments?lang=${lang}`);
    await expect(page.getByRole("heading", { name: lang === "id" ? "Menunggu persetujuan Anda" : "Waiting for your approval" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: lang === "id" ? "Bayar dari" : "Pay from" })).toHaveValue("acct_idr_stu_01");
    const trigger = page.getByRole("button", { name: lang === "id" ? "Setujui dari rekening saya" : "Approve from my account" });
    const before = (await (await request.get(`${mock}/__calls`)).json()).length;
    await trigger.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("IDR 46,025,000");
    await expect(dialog).toContainText("IDR 25,000");
    await expect(dialog).toContainText("CNY 20,000.00");
    await dialog.getByRole("button", { name: lang === "id" ? "Kembali" : "Go back", exact: true }).click();
    expect((await (await request.get(`${mock}/__calls`)).json()).length).toBe(before);
    await trigger.click();
    await dialog.getByRole("button", { name: lang === "id" ? "Konfirmasi persetujuan" : "Confirm approval", exact: true }).click();
    await expect.poll(async () => (await (await request.get(`${mock}/__calls`)).json()).slice(before).length).toBe(1);
    const [call] = (await (await request.get(`${mock}/__calls`)).json()).slice(before);
    expect(call.url).toBe("/api/v1/student/approvals/approval_own/decision");
    expect(call.origin).toBe(origin);
    expect(JSON.parse(call.body)).toEqual({ decision: "APPROVED", terms_hash: "a".repeat(64) });
  });
}

test("student approval relay rejects forged roles, malformed terms and foreign Origin", async ({ request }) => {
  const path = "/student/payments/api/owner-decision";
  const body = { id: "approval_own", decision: "APPROVED", terms_hash: "a".repeat(64) };
  const headers = { Origin: origin, Cookie: "session=ok" };
  expect((await request.post(path, { headers, data: { ...body, actor_id: "sponsor" } })).status()).toBe(400);
  expect((await request.post(path, { headers, data: { ...body, terms_hash: "fake" } })).status()).toBe(400);
  expect((await request.post(path, { headers: { ...headers, Origin: "https://foreign.example" }, data: body })).status()).toBe(403);
});

test("demo shows observed run separately from the next reset selection without mutation", async ({ page, context, request }) => {
  await context.addCookies([{ name: "session", value: "ok", url: origin }, { name: "admin", value: "ok", url: origin }]);
  const before = (await (await request.get(`${mock}/__calls`)).json()).length;
  await page.goto("/demo");
  await expect(page.getByRole("region", { name: "Active scenario" })).toContainText("tuition_missing_reference · Run 7");
  await expect(page.getByRole("combobox", { name: "Scenario", exact: true })).toHaveValue("tuition_happy_path");
  expect((await (await request.get(`${mock}/__calls`)).json()).length).toBe(before);
});
