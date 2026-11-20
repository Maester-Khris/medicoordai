import { defineConfig } from "@playwright/test"

// Phone and web end-to-end tests with a stubbed backend: only the Vite dev server is started
// (no API, no Neo4j). Run: npx playwright test -c playwright.mobile.config.ts
const GEO = { latitude: 43.6629, longitude: -79.3957 } // University of Toronto
const PHONE_UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
const phone = (width: number, height: number) => ({
  viewport: { width, height }, isMobile: true, hasTouch: true, userAgent: PHONE_UA,
  permissions: ["geolocation"], geolocation: GEO,
})

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.mobile\.spec\.ts/,
  timeout: 45_000,
  fullyParallel: true,
  expect: { timeout: 15_000 }, // the five projects share one dev server and one machine
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    // Optional: point at an already installed Chromium instead of downloading one.
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
  },
  projects: [
    { name: "phone-320", use: phone(320, 568) },
    { name: "phone-360", use: phone(360, 640) },
    { name: "phone-390", use: phone(390, 844) },
    { name: "phone-landscape", use: phone(667, 375) },
    { name: "web", use: { viewport: { width: 1280, height: 800 }, permissions: ["geolocation"], geolocation: GEO } },
  ],
  webServer: {
    command: "npm run doppler-dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
