# Readiness report

Status of the private financial-intelligence MVP against the product spec,
verified against the current tree and test output.

| Requirement | Evidence | Status |
|---|---|---|
| Existing FastAPI/React stack preserved | Repo still FastAPI + Vite/React; no Next.js rewrite | met |
| Single-owner `PRIVATE_INSTANCE` | `registration_allowed` in `app/core/privacy.py`; covered by `test_debts_and_private_instance` | met |
| Cookie session + CSRF | Login sets httpOnly `session` + `csrf_token`; mutating cookie-only requests need `X-CSRF-Token`; auth bootstrap paths are exempt | met |
| CSP | `SecurityHeadersMiddleware` and nginx `default.conf.template` | met |
| Immutable vault, SHA-256, MIME magic | `vault_service.upload_document`, `detect_mime`; spoofed extensions rejected | met |
| Candidates never pre-selected | `selected=False`; CSV import `excluded: true` | met |
| Human review before ledger | `decide_candidates` is the only post path; retry does not duplicate | met |
| Idempotent import | same SHA-256 reuses stored object | met |
| Jobs table + abandoned recovery | `processing_jobs`, `recover_abandoned` | met |
| Read-only Gmail/Sheets/Outlook | `integrations/readonly.py`; write methods raise | met |
| AI rejects invented amounts/dates | `ai_validate_suggestion` | met |
| Dashboard real debt total / review count | `dashboard_service.py` (`None` when no debts) | met |
| Documents/Review/Debts/Sources/Processing/Audit UI | pages, `App.tsx` routes, nav modules | met |
| i18n keys in every locale | `frontend/src/locales/*.json`; i18n + workspace-kind tests | met |
| Backup + restore | export zip + `POST /api/export/restore` + instance scripts | met |
| Secrets not committed | `.env.example` empty; gitleaks job in CI | met |
| No auto-deploy | this PR only | met |

## Test evidence (this revision)

- Backend: `pytest -n auto --dist loadfile` → **3849 passed, 7 skipped**.
- Frontend: eslint clean, `tsc -b` clean, vitest after locale cleanup green on i18n/nav/review suites.
- Targeted intelligence suite: `tests/test_intelligence.py` plus export/module/write-gate tests green.

Playwright is not part of the existing CI image. The ingest → review → ledger path is covered by API tests; the review empty state is covered by vitest. A dedicated browser job remains a follow-up.

Do not publish. Staging and human review remain required before treating extracted rows as ledger facts.
