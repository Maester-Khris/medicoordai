import { defineConfig } from "@playwright/test"
import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Backend stdout+stderr is captured here so the test can grep for the
// `graph_context_matched` log line (backend/services/llm_agent.py) — that
// line, not the LLM's prose, is the oracle for "GraphRAG actually fired."
export const BACKEND_LOG = path.resolve(__dirname, "e2e/.tmp/backend.log")

// Assumes `doppler setup` has already been run once in backend/ (see
// Makefile's `dev-py` target) and that config has NEO4J_URI/USERNAME/PASSWORD
// wired up — required for GRAPH_RAG_PROVIDER=neo4j to construct at all.
export default defineConfig({
  testDir: "./e2e",
  testIgnore: /.*\.smoke\.spec\.ts/,
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `mkdir -p ${path.dirname(BACKEND_LOG)} && doppler run -- uvicorn main:app --port 8000 > ${BACKEND_LOG} 2>&1`,
      cwd: path.resolve(__dirname, "../backend"),
      url: "http://localhost:8000/docs",
      env: { GRAPH_RAG_PROVIDER: "neo4j" },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run doppler-dev",
      cwd: __dirname,
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
