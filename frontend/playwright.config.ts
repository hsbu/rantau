import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests", fullyParallel: false, workers: 1, retries: 0,
  outputDir: "../.generated/playwright", reporter: "list",
  use: { baseURL: "http://127.0.0.1:3100", trace: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    { command: "node tests/mock-agent.mjs", url: "http://127.0.0.1:8101/health", reuseExistingServer: false },
    { command: "node tests/mock-finance.mjs", url: "http://127.0.0.1:8102/health", reuseExistingServer: false },
    {
      command: "npm run start", url: "http://127.0.0.1:3100", reuseExistingServer: false,
      env: { PORT: "3100", HOSTNAME: "127.0.0.1", AGENT_API_ORIGIN: "http://127.0.0.1:8101", FINANCE_API_ORIGIN: "http://127.0.0.1:8102" },
    },
  ],
});
