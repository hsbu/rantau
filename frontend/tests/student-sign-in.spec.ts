import { test, expect } from "@playwright/test";

test("student sign-in uses the existing cookie relay and fixed Chat destination", async ({ page, context }) => {
  const requests: Record<string, unknown>[] = [];
  page.on("request", request => {
    if (request.url().endsWith("/sponsor/api/login")) requests.push(request.postDataJSON());
  });
  await page.goto("/student/sign-in?next=https://untrusted.example");
  await page.getByLabel("Username", { exact: true }).fill("student");
  await page.getByLabel("Password", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL("/student/chat");
  expect(Object.keys(requests[0]).sort()).toEqual(["password", "username"]);
  const cookie = (await context.cookies()).find(item => item.name === "session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
  await page.getByRole("link", { name: "Sign in / account" }).click();
  await expect(page.getByText("You’re signed in as a student.")).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  expect((await context.cookies()).find(item => item.name === "session")).toBeUndefined();
});

test("Payments return target is fixed and sponsor credentials cannot enter student workspace", async ({ page }) => {
  await page.goto("/student/sign-in?next=payments");
  await page.getByLabel("Username", { exact: true }).fill("sponsor");
  await page.getByLabel("Password", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("This session belongs to another workspace.", { exact: false })).toBeVisible();
  await expect(page).toHaveURL("/student/sign-in?next=payments");
  await expect(page.getByRole("link", { name: "Continue to Payments" })).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill("student");
  await page.getByLabel("Password", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL("/student/payments");
});

test("failed login clears passwords, stays accessible on mobile and does not expose diagnostics", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/student/sign-in");
  await page.getByLabel("Username", { exact: true }).fill("student");
  for (const password of ["wrong", "throttled"]) {
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
    await expect(page.locator("body")).not.toContainText("private diagnostic");
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("uncertain session does not automatically repeat login", async ({ page }) => {
  let calls = 0;
  await page.route("**/sponsor/api/session", route => route.fulfill({ status: 503, json: {} }));
  page.on("request", request => { if (request.url().endsWith("/sponsor/api/login")) calls++; });
  await page.goto("/student/sign-in");
  await expect(page.getByRole("status")).toContainText("Your session could not be checked");
  await expect(page.getByLabel("Password", { exact: true })).toHaveCount(0);
  expect(calls).toBe(0);
});
