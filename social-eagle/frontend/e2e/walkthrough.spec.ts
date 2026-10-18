import { expect, test, type Page } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))

// Owner walkthrough through the real UI against the running app (synthetic evaluation data, real local AI).
const DATA = process.env.E2E_DATA_DIR ?? join(HERE, '..', '..', 'data')
const USER = process.env.E2E_USER ?? 'owner'
const PASS = process.env.E2E_PASSWORD ?? 'evaluation-owner-2026'
const SHOTS = join(HERE, '..', '..', 'docs', 'evidence', 'screenshots')
const shot = (page: Page, name: string) => page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true })

test.describe.configure({ mode: 'serial' })
const STATE = join(HERE, '..', 'test-results', 'owner-state.json')
// Sign in once (the login endpoint is rate-limited to 5 attempts/minute) and reuse the session cookie.
test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage({ storageState: { cookies: [], origins: [] }, baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8787' })
  await login(page)
  await page.context().storageState({ path: STATE })
  await page.close()
})
test.use({ storageState: STATE })
async function signIn(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Community overview' })).toBeVisible()
}
const nav = (page: Page, name: string) => page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name, exact: true })

async function login(page: Page) {
  await page.goto('/')
  await expect(page.getByText('Evaluation — synthetic community data')).toBeVisible()
  const tokenFile = join(DATA, 'enrollment.token')
  if (existsSync(tokenFile)) {
    await page.getByLabel('Enrollment token').fill(readFileSync(tokenFile, 'utf8').trim())
    await page.getByLabel('Username').fill(USER)
    await page.getByLabel(/Password/).fill(PASS)
    await page.getByRole('button', { name: 'Create admin account' }).click()
  } else {
    await page.getByLabel('Username').fill(USER)
    await page.getByLabel(/Password/).fill(PASS)
    await page.getByRole('button', { name: 'Sign in' }).click()
  }
  await expect(page.getByRole('heading', { name: 'Community overview' })).toBeVisible()
}

test('overview, members, notes and segments', async ({ page }) => {
  await signIn(page)
  await expect(page.getByText('Active members')).toBeVisible()
  await shot(page, '01-overview')
  await nav(page, 'Members').click()
  await page.getByLabel('Search name, ID or email').fill('Kavya Iyer')
  await page.getByRole('button', { name: 'Search' }).click()
  await page.getByRole('link', { name: 'Kavya Iyer' }).first().click()
  await expect(page.getByText('Lessons marked complete')).toBeVisible()
  await page.getByRole('tab', { name: 'Notes & tags' }).click()
  const note = `E2E ${Date.now()}: silent learner, consider a check-in call.`
  await page.getByLabel('Internal note (not visible to the member)').fill(note)
  await page.getByRole('button', { name: 'Add note' }).click()
  await expect(page.locator('div', { hasText: new RegExp(`^${note}$`) }).first()).toBeVisible()
  await expect(page.getByLabel('Internal note (not visible to the member)')).toHaveValue('')
  await shot(page, '02-member-detail')
  await nav(page, 'Members').click()
  await page.getByRole('button', { name: /Silent learners/ }).click()
  await expect(page.getByText(/Segment Silent learners/)).toBeVisible()
  await shot(page, '03-segment')
})

test('support inbox and thread', async ({ page }) => {
  await signIn(page)
  await nav(page, 'Support inbox').click()
  await page.getByLabel('Filter text').fill('ad test')
  await expect(page.getByRole('link', { name: 'How many days should an ad test run?' })).toBeVisible()
  await shot(page, '04-inbox')
  await page.getByRole('link', { name: 'How many days should an ad test run?' }).click()
  await expect(page.getByText(/SYNTHETIC record in the local simulator/)).toBeVisible()
  await shot(page, '05-thread')
})

test('lab question → real AI auto-reply → published in local thread', async ({ page }) => {
  await signIn(page)
  // Auto-replies respect quiet hours (23:00–07:00 IST). Move the test clock into daytime first if needed.
  const status = await page.request.get('/api/system/status').then(r => r.json())
  const hhmm = /(\d{2}):(\d{2}) IST/.exec(status.clock.local)
  if (hhmm) {
    const mins = Number(hhmm[1]) * 60 + Number(hhmm[2])
    if (mins < 7 * 60 + 5 || mins >= 22 * 60) {
      const advance = ((10 * 60 - mins) + 24 * 60) % (24 * 60)
      const csrf = await page.request.get('/api/auth/status').then(r => r.json()).then(j => j.csrf)
      await page.request.post('/api/system/clock/advance', { data: { advance_minutes: advance }, headers: { 'X-CSRF-Token': csrf } })
    }
  }
  await nav(page, 'Evaluation lab').click()
  const title = `Captions on reels? (e2e ${Date.now()})`
  await page.getByLabel('Title').fill(title)
  await page.getByLabel('Body').fill('Do I really need captions on my short videos? Editing them takes a long time.')
  await page.getByRole('button', { name: 'Post question' }).click()
  await expect(page.getByText(/Question posted in the simulator/)).toBeVisible()
  await nav(page, 'Discussions').click()
  await page.getByLabel('Full-text search').fill('e2e')
  await page.getByRole('button', { name: 'Search' }).click()
  await page.getByRole('link', { name: title }).click()
  await expect.poll(async () => {
    await page.reload()
    await page.getByRole('heading', { name: title }).waitFor({ timeout: 60_000 })
    return page.getByText('Automated answer from Eagle Assistant').count()
  },
    { timeout: 10 * 60_000, intervals: [5000] }).toBeGreaterThan(0)
  await expect(page.getByText(/verified|sent/).first()).toBeVisible()
  await shot(page, '06-auto-reply-thread')
})

test('progress change updates member report', async ({ page }) => {
  await signIn(page)
  const before = await page.request.get('/api/members?q=Rohan%20Desai').then(r => r.json())
  const id = before.rows[0].id
  const p0 = await page.request.get(`/api/members/${id}`).then(r => r.json())
  await nav(page, 'Evaluation lab').click()
  await page.locator('#pm').fill('syn-mem-scn-commenter')
  const done = new Set<string>(p0.progress.filter((c: any) => c.accessible).flatMap((c: any) => c.lesson_states.filter((l: any) => l.completed).map((l: any) => l.title)))
  const todo = p0.progress.filter((c: any) => c.accessible).flatMap((c: any) => c.lesson_states.filter((l: any) => !done.has(l.title)).map((l: any) => l.title))
  const catalog = await page.request.get('/api/lab/catalog').then(r => r.json())
  const lesson = catalog.lessons.find((l: any) => todo.includes(l.title))
  await page.locator('#pl').selectOption(lesson.upstream_id)
  await page.getByRole('button', { name: 'Apply progress' }).click()
  await expect(page.getByText(/Progress event recorded and synced/)).toBeVisible()
  await page.goto(`/members/${id}`)
  const p1 = await page.request.get(`/api/members/${id}`).then(r => r.json())
  expect(p1.profile.lessons_marked_complete).toBe(p0.profile.lessons_marked_complete + 1)
  await page.getByRole('tab', { name: 'Progress' }).click()
  await shot(page, '07-progress-updated')
})

test('owner chat answers from calculated metrics', async ({ page }) => {
  await signIn(page)
  await nav(page, 'Owner chat').click()
  await page.getByRole('button', { name: 'How many members joined in the last 14 days?' }).click()
  await expect(page.locator('.chat-msg.assistant .ai-box, .chat-msg.assistant .notice').first()).toBeVisible({ timeout: 10 * 60_000 })
  await shot(page, '08-owner-chat')
})

test('pause switch, reports and knowledge', async ({ page }) => {
  await signIn(page)
  await nav(page, 'System & settings').click()
  await page.getByRole('button', { name: 'Pause all automation' }).click()
  await expect(page.getByText('AUTOMATION PAUSED')).toBeVisible({ timeout: 30_000 })
  await shot(page, '09-paused')
  await page.getByRole('button', { name: 'Resume automation' }).click()
  await expect(page.getByText('Resumed.')).toBeVisible()
  await nav(page, 'Reports').click()
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'support.csv' }).click()])
  expect(download.suggestedFilename()).toContain('social-eagle-support')
  await shot(page, '10-reports')
  await nav(page, 'Knowledge').click()
  await page.getByLabel('Question').fill('minimum daily budget per ad set')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page.getByText('Paid Ads FAQ').first()).toBeVisible()
  await shot(page, '11-knowledge')
  await nav(page, 'Review queue & actions').click()
  await shot(page, '12-review-queue')
})
