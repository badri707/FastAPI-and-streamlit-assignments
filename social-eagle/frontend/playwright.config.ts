import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'

// Runs against the already-started app (scripts/start). Uses a preinstalled Chromium if present.
const exe = process.env.PW_CHROMIUM ?? (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined)
export default defineConfig({
  testDir: './e2e',
  timeout: 15 * 60_000,
  expect: { timeout: 20_000 },
  workers: 1,
  reporter: [['list'], ['json', { outputFile: '../docs/evidence/e2e-results.json' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8787',
    viewport: { width: 1360, height: 900 },
    launchOptions: exe ? { executablePath: exe } : {},
    screenshot: 'only-on-failure',
    actionTimeout: 60_000,
    navigationTimeout: 60_000,
  },
})
