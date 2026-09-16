# Private instance

How to run this app as a single-owner financial intelligence instance.

## Identity

Set `PRIVATE_INSTANCE=true`. After the first user exists, public registration is refused. Browser sessions use an httpOnly `session` cookie plus a readable `csrf_token` cookie (`X-CSRF-Token` on mutating requests). JWT bearer still works for tests and non-browser clients.

## Vault

Upload statements, spreadsheets, OFX/QIF/CSV/PDF, or images. Originals are stored once by SHA-256. Magic bytes decide MIME; a `.csv` name does not override binary content. Images without Tesseract stay `needs_ocr` and never invent amounts or dates.

Each extraction writes a `document_versions` row. If a printed total disagrees with the sum of extracted lines, a `document_conflicts` row is stored and processing continues for human review.

## Review

Import candidates start unselected. Approve, reject or defer item by item. Revert unposts ledger rows and keeps the audit trail. Retrying a job does not duplicate candidates with the same idempotency key.

Inferred recurrences are suggestions (`confirmed: false`). They do not create recurring bills until a person confirms auto-generation in the recurring screen.

## Connectors

Scopes, when the owner supplies OAuth clients:

- Gmail: `gmail.readonly`
- Sheets: `spreadsheets.readonly`
- Outlook: `Mail.Read`

Write methods raise. Tokens are encrypted at rest and never logged.

## Jobs

`processing_jobs` is the source of truth. Celery is the runner. Abandoned locks are recovered. Statuses: queued, running, waiting_review, completed, partially_completed, failed, cancelled.

## Backup

- Workspace zip: `GET /api/export/backup` (metadata; not original bytes or OAuth refresh tokens)
- Additive restore: `POST /api/export/restore` (never posts candidates)
- Instance: `scripts/backup-instance.sh` / `scripts/restore-instance.sh`

## Health

- `/api/health` — process is up
- `/api/ready` — Postgres, Redis and storage

## Do not publish until

Live OAuth consent works, backup/restore has been run on the real volume, and the Playwright plus API journeys are green on that deploy. See `docs/readiness-report.md`.
