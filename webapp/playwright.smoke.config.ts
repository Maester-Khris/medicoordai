import { defineConfig } from "@playwright/test"

// Runs against an already-deployed site (preview or production). No local servers are started.
//   SMOKE_BASE_URL=https://<preview>.vercel.app npm run test:smoke
const baseURL = process.env.SMOKE_BASE_URL
if (!baseURL) throw new Error("SMOKE_BASE_URL is not set")

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.smoke\.spec\.ts/,
  timeout: 120_000,
  retries: 1,
  use: {
    baseURL,
    trace: "retain-on-failure",
    viewport: { width: 1280, height: 800 },
    permissions: ["geolocation"],
    geolocation: { latitude: 43.6629, longitude: -79.3957 }, // University of Toronto, inside the demo area
  },
})
