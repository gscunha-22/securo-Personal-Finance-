# Readiness report

Status of the private financial-intelligence MVP against the product spec.
Updated as evidence is collected.

| Requirement | Evidence | Status |
|---|---|---|
| Existing FastAPI/React stack preserved | Repo layout unchanged; no Next.js rewrite | pending tests |
| Single-owner `PRIVATE_INSTANCE` | `app/core/privacy.py` `registration_allowed` | pending tests |
| Cookie session + CSRF | `SecurityHeadersMiddleware`, login cookies | pending tests |
| CSP | nginx templates + API middleware | pending tests |
| Immutable vault, SHA-256, MIME magic | `vault_service.upload_document`, `detect_mime` | pending tests |
| Candidates never pre-selected | `selected=False`; CSV import `excluded: true` | pending tests |
| Human review before ledger | `decide_candidates` is the only post path | pending tests |
| Idempotent import | same SHA-256 reuses stored object | pending tests |
| Jobs table + abandoned recovery | `processing_jobs`, `recover_abandoned` | pending tests |
| Read-only Gmail/Sheets/Outlook | `integrations/readonly.py` | pending tests |
| AI rejects invented amounts/dates | `ai_validate_suggestion` | pending tests |
| Dashboard real debt total / review count | `dashboard_service.py` | pending tests |
| Documents/Review/Debts/Sources/Processing/Audit UI | pages + routes + nav modules | pending tests |
| i18n keys in every locale | `frontend/src/locales/*.json` | pending tests |
| Backup + restore | export zip + `/api/export/restore` + instance scripts | pending tests |
| Secrets not committed | `.env.example` empty; gitleaks in CI | pending tests |
| No auto-deploy | this PR only | met |

Playwright browser e2e is not in the existing CI image. API tests cover the
ingest → review → ledger path. Frontend vitest covers catalog, i18n and
auth. A dedicated Playwright job remains a follow-up once a browser service
is part of CI.
