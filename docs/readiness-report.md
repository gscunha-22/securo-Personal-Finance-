# Readiness report

Status of the private financial-intelligence MVP against the product spec,
verified against this tree and executed tests.

Verdict: **`pronto_para_homologacao`**

Publication remains blocked until the owner supplies live OAuth clients, runs
backup/restore on the real volume, and signs off. That is **`nao_pronto` for
publication**, not for staging review.

| Requirement | Evidence | Status |
|---|---|---|
| Existing FastAPI/React stack preserved | Repo still FastAPI + Vite/React; no Next.js rewrite | met |
| Single-owner `PRIVATE_INSTANCE` | `app/core/privacy.py`; `test_debts_and_private_instance` | met |
| Cookie session + CSRF | httpOnly `session` + `csrf_token`; mutating cookie-only requests need `X-CSRF-Token` | met |
| CSP / rate limit | `SecurityHeadersMiddleware`; upload rate limiter | met |
| Immutable vault, SHA-256, MIME magic | `vault_service.upload_document`; spoofed extensions rejected | met |
| Interpretation versions | `document_versions` (migration `092`); `interpretation_version` on document JSON | met |
| OCR never invents facts | Images without Tesseract stay `needs_ocr` with zero candidates | met |
| Parse-integrity conflict | Sum of parts vs printed total; conflict stored, process continues | met |
| Candidates never pre-selected | `selected=False`; CSV import `excluded: true` | met |
| Human review before ledger | `decide_candidates`; `human_decisions` rows; retry does not duplicate | met |
| Loan accounts | Enable Banking `LOAN` and Pluggy `LOAN` map to `loan`; treated as liability | met |
| Inferred recurrences not materialized | Repeating descriptions stay suggestions until auto-generate is confirmed | met |
| Jobs table + abandoned recovery | `processing_jobs`, `recover_abandoned`; API publishes extract/sync to Celery (`job_dispatch`) | met |
| Read-only Gmail/Sheets/Outlook | `integrations/readonly.py`; write methods raise | met |
| AI rejects invented amounts/dates | `ai_validate_suggestion` | met |
| Dashboard real numbers | Debt total `None` when empty; loan balances reduce net worth | met |
| Documents/Review/Debts/Sources/Processing/Audit UI | pages, routes, nav modules | met |
| Backup + restore | export zip + `POST /api/export/restore` + instance scripts; Neon dump + S3 vault pull executed | met |
| Secrets not committed | `.env.example` empty; gitleaks job | met |
| Playwright E2E | `e2e/tests/intelligence.spec.ts` in CI | met |
| Alembic against Postgres | CI job `alembic upgrade head` on service Postgres | met |
| Live Google/Microsoft OAuth | Connect + `/sources/callback` in code; owner must create clients | pending owner |
| Live S3 credentials | Neon bucket `securo-vault` on `us-east-2`; secrets only in console/compute env | provisioned; copy secrets to persistent compute |
| Helm / Compose Neon overlay | `values.yaml` S3 + `docker-compose.neon.yml`; Tesseract eng+por in the API image | met (code); public compute still pending owner tokens |
| Auto-deploy | Not performed | met (not done) |

## What was executed vs simulated

- Executed: API tests for vault, review, debts, jobs, MIME spoof, prompt-injection-as-description, private instance, parse integrity, OCR-without-engine, inferred recurrence, loan mapping.
- Executed in CI (when this branch runs): ruff, ty, pytest, eslint/tsc/vitest, helm, gitleaks, Alembic chain, Alembic upgrade on Postgres, Playwright Chromium against a mocked API.
- Simulated: live Gmail/Sheets/Outlook HTTP (adapters raise `NotConfiguredError` until consent). Playwright uses a mocked `/api` so the browser journey is real UI with synthetic data.
- Executed against the operator Neon project: Alembic `092`, `/api/ready` with pooled Postgres + Redis + S3, CSV upload to the vault, unselected review, approve-to-ledger, debt + renegotiation plan, authenticated file download, `scripts/backup-instance.sh` on `main`, `pg_restore` onto isolated branch `backup-restore-verify`, S3 vault pull of 3 objects.
- Not executed: production git-deploy (Vercel Git is linked; `git.deploymentEnabled` is false so Git pushes do not publish), public persistent compute (no Fly/Render/Railway token in this environment), live OAuth consent screens, ClamAV (magic-byte + script rejection instead).

## Risks still open

- JWT remains in `localStorage` for the SPA in addition to cookies.
- Bank-statement OCR quality depends on Tesseract being installed in the image.
- Enable Banking / Pluggy remain optional read-only bank sync, not the primary ingest path.

Do not treat extracted rows as ledger facts without human review.
