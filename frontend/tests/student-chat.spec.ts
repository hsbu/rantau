import { test, expect } from "@playwright/test";

test("Chat views keep the same tab positions when switching routes at every breakpoint", async ({ page }) => {
  for (const width of [320, 390, 600, 601, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/student/chat");
    const tabs = page.getByRole("navigation", { name: "Chat views" });
    const geometry = async () => Promise.all(["Chat", "Scenarios"].map(async name => {
      const box = await tabs.getByRole("link", { name, exact: true }).boundingBox();
      return { x: box!.x, y: box!.y, width: box!.width, height: box!.height };
    }));
    const original = await geometry();
    await tabs.getByRole("link", { name: "Scenarios", exact: true }).click();
    await expect(page).toHaveURL("/student/chat/preview");
    expect(await geometry(), `Scenarios changed the tab geometry at ${width}px`).toEqual(original);
    await tabs.getByRole("link", { name: "Chat", exact: true }).click();
    await expect(page).toHaveURL("/student/chat");
    expect(await geometry(), `Chat changed the tab geometry at ${width}px`).toEqual(original);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
  }
});

test("page scroll chains past the transcript and new replies do not pull readers away from history", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 720 });
  let release: (() => void) | undefined;
  let calls = 0;
  await page.route("**/student/chat/api", async route => {
    if (++calls === 4) await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: {
      run_id: "run_scroll", requested_action: "TUITION", tool_events: [], resources: [],
      message: Array.from({ length: 22 }, (_, index) => `Payment detail line ${index + 1}: review the original terms.`).join("\n"),
    } });
  });
  await page.goto("/student/chat");
  const log = page.getByRole("log");
  // Loading the workspace must not scroll the document down to its composer.
  await expect(page.getByRole("heading", { name: "One step at a time." })).toBeVisible();
  expect(await page.evaluate(() => scrollY)).toBe(0);
  for (let turn = 0; turn < 3; turn++) {
    await page.getByLabel("Message Rantau").fill(`Check ${turn}`);
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(page.getByLabel("Message Rantau")).toBeEnabled();
  }
  await page.getByLabel("Message Rantau").fill("Another check");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect.poll(() => calls).toBe(4);
  await log.hover();
  await page.mouse.wheel(0, -10000);
  await expect.poll(() => log.evaluate(element => element.scrollTop)).toBe(0);
  await expect(page.getByRole("button", { name: "Latest messages" })).toBeVisible();
  release?.();
  await expect(page.getByLabel("Message Rantau")).toBeEnabled();
  expect(await log.evaluate(element => element.scrollTop)).toBe(0);
  await page.getByRole("button", { name: "Latest messages" }).click();
  await expect.poll(() => log.evaluate(element => element.scrollHeight - element.scrollTop - element.clientHeight)).toBeLessThan(2);
  await page.evaluate(() => scrollTo(0, 0));
  await log.hover();
  await page.mouse.wheel(0, 1500);
  // A native wheel gesture can first consume fractional space at the inner edge.
  await expect.poll(async () => {
    await page.mouse.wheel(0, 500);
    return page.evaluate(() => scrollY);
  }).toBeGreaterThan(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => scrollTo(0, 0));
  await log.evaluate(element => { element.scrollTop = element.scrollHeight; });
  await log.hover();
  await page.mouse.wheel(0, 1500);
  await expect.poll(async () => {
    await page.mouse.wheel(0, 500);
    return page.evaluate(() => scrollY);
  }).toBeGreaterThan(0);
});

test("Chat and Scenarios tabs switch views without sharing fixture state", async ({ page }) => {
  await page.goto("/student/chat/preview");
  const tabs = page.getByRole("navigation", { name: "Chat views" });
  await expect(tabs.getByRole("link", { name: "Scenarios", exact: true })).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: /Help me pay my tuition/ }).click();
  await expect(page.getByRole("region", { name: "Tuition balance" })).toBeVisible();
  await tabs.getByRole("link", { name: "Chat", exact: true }).click();
  await expect(page).toHaveURL("/student/chat");
  await expect(tabs.getByRole("link", { name: "Chat", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByLabel("Sample scenario")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Tuition balance" })).toHaveCount(0);
  await expect(page.getByRole("log")).not.toContainText("remaining tuition is");
  await tabs.getByRole("link", { name: "Scenarios", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/student/chat/preview");
  await expect(page.getByLabel("Sample scenario")).toBeVisible();
  await expect(page.getByRole("heading", { name: "One step at a time." })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(tabs.getByRole("link", { name: "Chat", exact: true })).toBeVisible();
  await expect(tabs.getByRole("link", { name: "Scenarios", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
});

test("tuition clarification, exact quote and waiting do not execute or expose account IDs", async ({ page }) => {
  const apiCalls: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/")) apiCalls.push(request.url()); });
  await page.goto("/student/chat/preview");
  await page.getByRole("button", { name: /Help me pay my tuition/ }).click();
  await expect(page.getByRole("log")).toContainText("own funding or sponsor-owned funding");
  await page.getByRole("button", { name: /Use sponsor funding/ }).click();
  const quote = page.getByRole("region", { name: "Quote breakdown" });
  await expect(quote).toContainText("IDR 46,025,000");
  await expect(quote).toContainText("IDR 25,000");
  await expect(quote).toContainText("CNY 20,000.00");
  await page.getByRole("button", { name: /Show the sample approval request/ }).click();
  await expect(page.getByRole("region", { name: "Approval status" })).toContainText("Waiting for sponsor");
  await expect(page.getByRole("button", { name: /approve|execute|pay now/i })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(/acct_idr_01|par_001|synthetic-beneficiary-fingerprint|approval_demo_001/);
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("region", { name: "Quote breakdown" })).toHaveCount(0);
  await page.getByRole("button", { name: /Help me pay my tuition/ }).click();
  await expect(page.getByRole("log")).toContainText("own funding or sponsor-owned funding");
  expect(apiCalls).toEqual([]);
});

test("provider delivery stays separate from university posting; recovery and shortfall remain safe", async ({ page }) => {
  await page.goto("/student/chat/preview");
  await page.getByLabel("Sample scenario").selectOption("posting");
  await page.getByRole("button", { name: /Has my tuition been credited/ }).click();
  await expect(page.getByRole("region", { name: "Payment status" })).toContainText("Provider: Delivered");
  await expect(page.getByRole("region", { name: "Tuition balance" })).toContainText("Awaiting posting");
  await expect(page.getByRole("region", { name: "Tuition balance" })).toContainText("CNY 20,000.00");
  await page.getByLabel("Sample scenario").selectOption("recovery");
  await page.getByRole("button", { name: /Help with a missing payment reference/ }).click();
  await expect(page.getByRole("region", { name: "Recovery steps" })).toContainText("Bank receipt");
  await page.getByLabel("Sample scenario").selectOption("shortfall");
  await page.getByRole("button", { name: /credited amount is lower/ }).click();
  await expect(page.getByRole("region", { name: "Tuition balance" })).toContainText("CNY 500.00");
  await expect(page.getByRole("log")).toContainText("does not permit a top-up");
});

test("expired quotes and unknown provider outcomes show a safe next step", async ({ page }) => {
  await page.goto("/student/chat/preview");
  await page.getByLabel("Sample scenario").selectOption("expired");
  await page.getByRole("button", { name: /Review this quote/ }).click();
  await expect(page.getByRole("region", { name: "Quote breakdown" })).toContainText("Expired");
  await expect(page.getByRole("region", { name: "Safe next step" })).toContainText("Get a fresh quote");
  await page.getByLabel("Sample scenario").selectOption("unknown");
  await page.getByRole("button", { name: /Check my payment status/ }).click();
  await expect(page.getByRole("region", { name: "Safe next step" })).toContainText("Do not start a second payment");
});

test("mobile chat fits, keyboard send works and reset discards an in-flight result", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/student/chat/preview");
  await expect(page.getByLabel("Message Rantau")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
  await page.getByLabel("Message Rantau").fill("Pay my tuition");
  await page.getByLabel("Message Rantau").press("Enter");
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("heading", { name: "One step at a time." })).toBeVisible();
  await expect(page.getByRole("log")).not.toContainText("remaining tuition");
  await page.getByLabel("Message Rantau").fill("New draft");
  await page.getByLabel("Message Rantau").press("Shift+Enter");
  await expect(page.getByLabel("Message Rantau")).toHaveValue("New draft\n");
});

test("connected chat keeps conversation IDs stable, resets them, renders text without HTML", async ({ page }) => {
  const ids: string[] = [];
  await page.route("**/student/chat/api", async route => {
    const body = route.request().postDataJSON();
    ids.push(body.conversation_id);
    expect(Object.keys(body).sort()).toEqual(["conversation_id", "message"]);
    await route.fulfill({ json: { run_id: "run_test", message: '<img src=x onerror="alert(1)"> acct_private sk-exampleprivate 123456789012 student@example.org', requested_action: "TUITION", tool_events: [], resources: [] } });
  });
  await page.goto("/student/chat");
  for (const text of ["Pay tuition", "Use sponsor funding"]) {
    await page.getByLabel("Message Rantau").fill(text);
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(page.getByLabel("Message Rantau")).toBeEnabled();
  }
  expect(ids[0]).toBe(ids[1]);
  await expect(page.getByRole("log").locator("img")).toHaveCount(0);
  await expect(page.getByRole("log")).not.toContainText(/acct_private|sk-exampleprivate|123456789012|student@example.org/);
  await page.getByRole("button", { name: "New chat" }).click();
  await page.getByRole("button", { name: /Help me pay my tuition/ }).click();
  await expect(page.getByLabel("Message Rantau")).toBeEnabled();
  expect(ids[2]).not.toBe(ids[0]);
});

test("unavailable, malformed and expired-session responses fail visibly without retries", async ({ page }) => {
  let status = 503;
  let calls = 0;
  await page.route("**/student/chat/api", async route => {
    calls++;
    await route.fulfill({ status, json: status === 200 ? { message: "incomplete" } : { detail: "private server diagnostic" } });
  });
  await page.goto("/student/chat");
  await page.getByRole("button", { name: /Help me pay my tuition/ }).click();
  await expect(page.getByRole("alert", { name: "Chat error" })).toContainText("check its status in Payments before retrying");
  expect(calls).toBe(1);
  status = 200;
  await page.getByLabel("Message Rantau").fill("Try status");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("alert", { name: "Chat error" })).toContainText("unreadable response");
  status = 401;
  await page.getByLabel("Message Rantau").fill("Another check");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("alert", { name: "Chat error" })).toContainText("cleared for privacy");
  await expect(page.getByRole("log")).not.toContainText("Another check");
  await expect(page.locator("body")).not.toContainText("private server diagnostic");
  expect(calls).toBe(3);
});

test("server relay forwards only session cookie and bounded message; blocks claimed identity and foreign origins", async ({ request }) => {
  const headers = { Origin: "http://127.0.0.1:3100", Cookie: "session=synthetic-test-only", "X-Actor-Id": "forged", Authorization: "Bearer synthetic-test-only" };
  const body = { message: "Status check", conversation_id: "conversation_test" };
  const response = await request.post("/student/chat/api", { headers, data: body });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const received = await (await request.get("http://127.0.0.1:8101/inspect")).json();
  expect(received).toEqual({ body, cookie: "session=synthetic-test-only", origin: headers.Origin });
  expect((await request.post("/student/chat/api", { headers, data: { ...body, actor_id: "forged" } })).status()).toBe(400);
  expect((await request.post("/student/chat/api", { headers: { Origin: "https://untrusted.example" }, data: body })).status()).toBe(403);
  const denied = await request.post("/student/chat/api", { headers, data: { ...body, message: "expired-session" } });
  expect(denied.status()).toBe(401);
  expect(await denied.text()).not.toContain("private diagnostic");
});
