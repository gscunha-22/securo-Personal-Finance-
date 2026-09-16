import { test, expect, type Page, type Route } from '@playwright/test'

const USER = {
  id: '11111111-1111-1111-1111-111111111111',
  email: 'owner@example.com',
  is_active: true,
  is_superuser: true,
  is_verified: true,
  is_2fa_enabled: false,
  preferences: {
    language: 'en',
    currency_display: 'USD',
    onboarding_completed: true,
  },
}

const WORKSPACE = {
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Personal',
  kind: 'personal',
  is_archived: false,
  default_currency: 'USD',
  locale: 'en',
  tax_jurisdiction: null,
  icon: null,
  color: null,
  created_at: '2026-01-01T00:00:00Z',
  created_by_user_id: USER.id,
  managed_by_user_id: null,
  role: 'owner',
  enabled_modules: [
    'transactions',
    'accounts',
    'import',
    'reports',
    'documents',
    'review',
    'debts',
    'sources',
    'processing',
    'audit',
  ],
}

const ACCOUNT = {
  id: '33333333-3333-3333-3333-333333333333',
  user_id: USER.id,
  name: 'Checking',
  display_name: 'Checking',
  type: 'checking',
  balance: 0,
  currency: 'USD',
  current_balance: 0,
  is_closed: false,
}

type Doc = {
  id: string
  document_type: string
  status: string
  origin: string
  filename: string
  mime: string
  sha256: string
  byte_size: number
  interpretation_version: number
  created_at: string
}

type Candidate = {
  id: string
  document_id: string
  selected: boolean
  status: string
  description: string
  amount: string
  currency: string
  competence_date: string
  payment_date: string | null
  txn_type: string
  payee: string | null
  locator: string | null
  confidence: string
  duplicate_of_transaction_id: string | null
  suggested_category: string | null
  suggestion_rationale: string | null
  suggestion_confidence: string | null
  posted_transaction_id: string | null
}

async function installApi(page: Page) {
  const documents: Doc[] = []
  const candidates: Candidate[] = []
  const jobs: Array<Record<string, unknown>> = []
  let authed = false

  const json = (route: Route, status: number, body: unknown) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (path === '/api/admin/registration-status' && method === 'GET') {
      return json(route, 200, { enabled: false })
    }
    if (path === '/api/auth/oidc/config' && method === 'GET') {
      return json(route, 200, { enabled: false, provider_name: 'OIDC', local_auth_enabled: true })
    }
    if (path === '/api/admin/default-colors' && method === 'GET') {
      return json(route, 200, { light: null, dark: null })
    }
    if (path === '/api/setup/status' && method === 'GET') {
      return json(route, 200, { has_users: true })
    }
    if (path === '/api/auth/login' && method === 'POST') {
      authed = true
      return json(route, 200, { access_token: 'e2e-token', token_type: 'bearer' })
    }
    if (path === '/api/users/me' && method === 'GET') {
      if (!authed) return json(route, 401, { detail: 'Not authenticated' })
      return json(route, 200, USER)
    }
    if (path === '/api/workspaces' && method === 'GET') {
      return json(route, 200, [WORKSPACE])
    }
    if (path === '/api/accounts' && method === 'GET') {
      return json(route, 200, [ACCOUNT])
    }
    if (path === '/api/documents' && method === 'GET') {
      return json(route, 200, documents)
    }
    if (path === '/api/documents' && method === 'POST') {
      const doc: Doc = {
        id: '44444444-4444-4444-4444-444444444444',
        document_type: 'transaction_export',
        status: 'waiting_review',
        origin: 'upload',
        filename: 'stmt.csv',
        mime: 'text/csv',
        sha256: 'abc',
        byte_size: 64,
        interpretation_version: 1,
        created_at: '2026-01-10T00:00:00Z',
      }
      if (!documents.find((row) => row.id === doc.id)) {
        documents.push(doc)
        candidates.push({
          id: '55555555-5555-5555-5555-555555555555',
          document_id: doc.id,
          selected: false,
          status: 'pending',
          description: 'Grocery market',
          amount: '42.50',
          currency: 'USD',
          competence_date: '2026-01-10',
          payment_date: '2026-01-10',
          txn_type: 'debit',
          payee: null,
          locator: 'csv:row:2',
          confidence: '1.0000',
          duplicate_of_transaction_id: null,
          suggested_category: 'grocery',
          suggestion_rationale: 'Matched a known grocery keyword in the description.',
          suggestion_confidence: '0.7000',
          posted_transaction_id: null,
        })
        jobs.push({
          id: '66666666-6666-6666-6666-666666666666',
          job_type: 'extract_document',
          status: 'waiting_review',
          attempts: 1,
          error: null,
          created_at: '2026-01-10T00:00:00Z',
          started_at: '2026-01-10T00:00:00Z',
          finished_at: '2026-01-10T00:00:01Z',
        })
      }
      return json(route, 201, doc)
    }
    if (path === '/api/review/candidates' && method === 'GET') {
      const status = url.searchParams.get('status')
      const rows = status ? candidates.filter((row) => row.status === status) : candidates
      return json(route, 200, rows)
    }
    if (path === '/api/review/decisions' && method === 'POST') {
      const body = request.postDataJSON() as { candidate_ids: string[]; decision: string }
      for (const id of body.candidate_ids) {
        const row = candidates.find((item) => item.id === id)
        if (!row) continue
        if (body.decision === 'approve') {
          if (!row.posted_transaction_id) {
            row.posted_transaction_id = '77777777-7777-7777-7777-777777777777'
          }
          row.status = 'imported'
          row.selected = true
        }
      }
      return json(route, 200, { updated: body.candidate_ids.length, posted: 1 })
    }
    if (path === '/api/jobs' && method === 'GET') {
      return json(route, 200, jobs)
    }
    if (path.startsWith('/api/jobs/') && path.endsWith('/retry') && method === 'POST') {
      return json(route, 200, jobs[0] ?? {})
    }
    if (path === '/api/documents/44444444-4444-4444-4444-444444444444/file' && method === 'GET') {
      if (!authed) return json(route, 401, { detail: 'Not authenticated' })
      return route.fulfill({ status: 200, contentType: 'text/csv', body: 'date,amount\n' })
    }
    if (method === 'GET') {
      return json(route, 200, [])
    }
    return json(route, 200, {})
  })
}

test('login, upload, review without preselection, approve, reload, retry', async ({ page }) => {
  await installApi(page)
  await page.goto('/login')
  await page.getByLabel('Email').fill('owner@example.com')
  await page.getByLabel('Password').fill('secret-password')
  await page.getByRole('button', { name: 'Login', exact: true }).click()
  await page.waitForURL(/^(?!.*\/login).*$/)

  await page.goto('/documents')
  await expect(page.getByText('No documents yet', { exact: false })).toBeVisible()
  const fileInput = page.locator('input[type="file"]')
  await fileInput.setInputFiles({
    name: 'stmt.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('date,description,amount,type\n2026-01-10,Grocery market,42.50,debit\n'),
  })
  await expect(page.getByText('stmt.csv')).toBeVisible()

  await page.goto('/review')
  const box = page.getByRole('checkbox')
  await expect(box).toHaveCount(1)
  await expect(box).not.toBeChecked()
  await box.check()
  await page.getByRole('combobox').selectOption(ACCOUNT.id)
  await page.getByRole('button', { name: 'Approve selected' }).click()
  await expect(page.getByText('Nothing waiting', { exact: false })).toBeVisible()

  await page.reload()
  await expect(page.getByText('Nothing waiting', { exact: false })).toBeVisible()

  await page.goto('/processing')
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
})

test('unauthenticated browser cannot download a vault file', async ({ page }) => {
  await installApi(page)
  const response = await page.request.get('/api/documents/44444444-4444-4444-4444-444444444444/file')
  expect(response.status()).toBe(401)
})
