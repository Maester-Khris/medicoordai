import { existsSync, readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { expect, test, type Page } from "@playwright/test"
import { BACKEND_LOG } from "../playwright.config"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Disposable Supabase test account (dev_personal only) created by
// backend/scripts/eval_seed/create_eval_test_accounts.py — gitignored,
// same account the v1 agent-driven E2E used.
const [testAccount] = JSON.parse(
  readFileSync(
    path.resolve(__dirname, "../../backend/scripts/eval_seed/eval_test_accounts.json"),
    "utf-8",
  ),
) as { email: string; password: string }[]

const TORONTO = { latitude: 43.6532, longitude: -79.3832 }

function logLength(): number {
  return existsSync(BACKEND_LOG) ? readFileSync(BACKEND_LOG, "utf-8").length : 0
}

function logSince(offset: number): string {
  return existsSync(BACKEND_LOG) ? readFileSync(BACKEND_LOG, "utf-8").slice(offset) : ""
}

async function sendMessage(page: Page, text: string) {
  await page.getByPlaceholder("Describe how you feel…").fill(text)
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().includes("/chat/message") && r.status() === 200, {
      timeout: 20_000,
    }),
    page.keyboard.press("Enter"),
  ])
  return response
}

test.beforeEach(async ({ page, context }) => {
  await context.grantPermissions(["geolocation"])
  await context.setGeolocation(TORONTO)

  await page.goto("/app")
  await page.getByText("Sign in", { exact: true }).click()

  const modal = page.locator(".fixed.inset-0.z-50")
  await modal.getByPlaceholder("you@example.com").fill(testAccount.email)
  await modal.getByPlaceholder("••••••••").fill(testAccount.password)
  await modal.getByRole("button", { name: "Sign in", exact: true }).last().click() // modal has a "Sign in" tab + the submit button

  await expect(page.getByPlaceholder("Describe how you feel…")).toBeEnabled({ timeout: 15_000 })
})

test("live Neo4j GraphRAG match routes to a real recommendation", async ({ page }) => {
  const before = logLength()
  await sendMessage(page, "angina")
  expect(logSince(before)).toContain("graph_context_matched")

  // Same emergency-bypass trigger the v1 artifact confirmed
  // (backend/llm/prompts.py TRIAGE_SYSTEM_PROMPT): chest pain + dyspnea forces
  // severity=emergent immediately, so the turn count needed to reach
  // TriageCard is deterministic instead of depending on LLM pacing.
  await sendMessage(page, "it started about an hour ago")
  await sendMessage(page, "I'm also having trouble breathing and feel dizzy")

  await expect(page.getByText(/EMERGENT|URGENT|MODERATE|NON-URGENT/)).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.getByText("Call 911 immediately")).toBeVisible()
})

test("benign symptom completes triage without a GraphRAG match", async ({ page }) => {
  const before = logLength()
  await sendMessage(page, "I stubbed my toe on the coffee table")
  expect(logSince(before)).not.toContain("graph_context_matched")

  await expect(page.getByText(/EMERGENT|URGENT|MODERATE|NON-URGENT/)).toBeVisible({
    timeout: 20_000,
  })
})
