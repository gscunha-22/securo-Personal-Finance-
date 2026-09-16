# Implementation plan: private financial intelligence

This is the working plan for evolving this FastAPI/React app into a private,
single-owner financial intelligence instance. The second repository in the
workspace is a **conceptual** reference only. No names, brands, visual tokens,
UI copy or code from that product are copied here.

## Decisions

- Keep the existing stack (FastAPI, SQLAlchemy 2 async, Alembic, React 19 +
  Vite, PostgreSQL, Redis, Celery). Do not rewrite to Next.js.
- `PRIVATE_INSTANCE` defaults to false so existing registration tests stay
  valid. Operators turn it on for a single-owner deploy.
- Dual auth: existing JWT bearer (tests and non-browser clients) plus httpOnly
  `session` cookie and a readable `csrf_token` cookie. CSRF is enforced when a
  session cookie is present without an `Authorization` header.
- Document vault stores immutable originals (SHA-256, magic-byte MIME, size
  cap, script rejection). Extraction writes **unselected** import candidates.
  The ledger does not change until a human approves rows.
- CSV import review starts with every row excluded (`excluded: true`).
- Read-only adapters for Gmail (`gmail.readonly`), Sheets
  (`spreadsheets.readonly`) and Outlook (`Mail.Read`). Write methods raise.
- AI suggestion schema accepts category/payee/description/rationale/confidence
  and **rejects** invented amounts or dates.
- Dashboard debt total is `None` when there are no debts, never a fake zero.
- Recurring auto-generation is not flipped globally for existing bills. The
  recurring form starts with auto-generate **off** so a newly typed bill stays
  a suggestion until confirmed. Inferred document rows never create
  `recurring_transactions`.
- Loan accounts are first-class (`loan`). Enable Banking `LOAN` and Pluggy
  `LOAN` map to that type and count as liabilities.
- Interpretation versions live in `document_versions`. Parse-integrity
  conflicts are stored and sent to review instead of aborting the job.
- Secrets stay in environment variables. `.env.example` lists empty keys.

## Domain added

- Vault: `stored_objects`, `vault_documents`, `document_versions`,
  `document_extractions`, `extracted_fields`, `import_candidates`,
  `human_decisions`, `document_conflicts`
- Sources: `source_connections`, `sync_cursors`, `email_messages`
- Jobs: `processing_jobs`, `job_attempts`
- Audit: `audit_events`, `app_notifications`
- Debts: `debts`, `debt_installments`, `debt_payments`, plus renegotiation
  cash/offers

Migrations: `090_intelligence_vault.py`, `091_debt_renegotiation.py`,
`092_document_interpretation.py`.

## UI

Personal workspaces gain modules: documents, review, debts, sources,
processing, audit. Routes live under `/documents`, `/review`, `/debts`,
`/sources`, `/processing`, `/audit`. The dashboard surfaces pending review
and outstanding debts without inventing a zero.

## Backup and restore

- Workspace JSON zip (`GET`/`POST /api/export/backup`) includes debts, vault
  metadata, candidates, jobs and audit events. It does **not** include original
  file bytes or OAuth refresh tokens.
- Additive restore: `POST /api/export/restore` reinserts missing debts. It
  never posts candidates to the ledger.
- Instance restore of Postgres + attachment volume:
  `scripts/backup-instance.sh` and `scripts/restore-instance.sh`.

## Integrations

OAuth clients are optional. Until they are configured, Sources shows
`not_configured` and the required read-only scopes. No payment or transfer
API is implemented.

## Tests and CI

- Behavioral coverage: `backend/tests/test_intelligence.py`
- Frontend: module/nav catalog, locales, page empty states
- E2E: Playwright Chromium in `e2e/` (login, upload, unselected review, approve, reload, retry, unauthenticated file download)
- CI: ruff/ty/pytest, Alembic chain, `alembic upgrade head` on service Postgres, eslint/tsc/vitest, helm, gitleaks, Playwright

## Baseline (this revision)

- Backend slice: `pytest tests/test_intelligence.py tests/test_providers_enable_banking.py tests/test_providers_pluggy.py` → **67 passed** after the expire_all fix (68 including the recurrence case).
- `ruff check` on the changed modules: clean. `ty check` on the changed modules: clean.
- Frontend: `eslint` on touched files clean; `tsc -b` clean; `vitest run src/locales/i18n.test.ts` → **60 passed**.
- Full historical pytest (~3800) and Playwright Chromium run in CI on this branch.

Do not auto-deploy. Operators review staging before treating extracted rows
as ledger facts. See `docs/readiness-report.md`.
