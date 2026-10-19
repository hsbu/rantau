import { expect, test } from "@playwright/test";

test("assistant replies render spaced paragraphs, numbered routes and safe citations", async ({ page }) => {
  await page.route("**/student/chat/api", async route => route.fulfill({ json: {
    run_id: "run_reply", requested_action: null, tool_events: [], resources: [],
    message: "**Your tuition options**\n\nChoose a route below.\n\n1. **Standard route**\nTotal: IDR 46,025,000.\n\n2. **Faster route**\nTotal: IDR 46,050,000.\n\n- University receives CNY 20,000.00.\n- Approval is required.\n\nSay `confirm tuition` to save the request.\n\n[University notice](https://iczu.zju.edu.cn/notice.html)\n\n[Unsafe link](https://evil.example/pay)\n\n<img src=x onerror=alert(1)> [Bad](javascript:alert(1))",
  } }));
  await page.goto("/student/chat");
  await expect(page.getByText("No real funds move in this workspace.", { exact: false })).toBeVisible();
  await page.getByLabel("Message Rantau").fill("Show my routes");
  await page.getByRole("button", { name: "Send message" }).click();
  const log = page.getByRole("log");
  await expect(log.locator("strong").first()).toHaveText("Your tuition options");
  await expect(log.locator("ol")).toHaveCount(2);
  await expect(log.locator("ol").nth(1)).toHaveAttribute("start", "2");
  await expect(log.locator("ul > li")).toHaveCount(2);
  const bullets = log.locator("ul > li");
  expect(await log.locator("ul").evaluate(element => getComputedStyle(element).listStyleType)).toBe("disc");
  const first = await bullets.nth(0).boundingBox();
  const second = await bullets.nth(1).boundingBox();
  expect(second!.y).toBeGreaterThan(first!.y + first!.height);
  await expect(log.locator("code")).toHaveText("confirm tuition");
  await expect(log.getByRole("link")).toHaveCount(1);
  await expect(log.getByRole("link", { name: "University notice" })).toHaveAttribute("rel", "noopener noreferrer");
  await expect(log.locator("img,script")).toHaveCount(0);
  await expect(log).toContainText("<img src=x onerror=alert(1)>");
  await expect(log).not.toContainText(/simulat/i);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.body.clientWidth)).toBe(true);
});
