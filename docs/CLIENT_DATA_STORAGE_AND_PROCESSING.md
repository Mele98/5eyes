# Client Data Storage And Processing

This note summarizes where 5Eyes currently stores and processes customer data in the technical stack.

## 1. Data Sources

- Customer master data, profiling answers, wealth positions, cashflows, goals, review artifacts and recommendation metadata are entered via the Electron frontend and sent to the backend API.
- Market data, product metadata and identifier mappings come from external providers and are kept separate from customer-identifying data.

## 2. Primary Storage

- Main application data is stored in the backend database defined by `DB_PATH`.
- Database access is configured in:
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\config.py`
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\database.py`
- The backend supports SQLCipher at-rest encryption.
- Production is now blocked unless `APP_ENV=production`, `DB_USE_SQLCIPHER=true` and a non-empty `DB_KEY` are configured.

## 3. Authentication And Session Handling

- Backend access tokens are signed with `SECRET_KEY`.
- Electron stores tokens via `safeStorage` where available.
- Browser/dev fallback stores tokens only in `sessionStorage`, not `localStorage`.
- Relevant files:
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\services\auth.py`
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-electron\main.js`
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-electron\frontend\5eyes_v2.html`

## 4. Access Control

- Customer and mandate access is scoped to the authenticated adviser unless the user has global admin rights.
- Review dashboards and recommendation routes are also scoped.
- Relevant files:
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\services\auth.py`
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\routers\clients.py`
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\routers\review.py`

## 5. Logs, Diagnostics And Support Bundles

- Support bundles redact secrets and only include redacted recent log excerpts.
- Raw full logs are no longer attached automatically to support bundles.
- Relevant files:
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\services\maintenance.py`
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\routers\system.py`

## 6. Risk Questionnaire Data

- Risk questionnaire answers are persisted as risk assessments in the backend database.
- The scoring logic is implemented server-side in:
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend\services\risk_scoring.py`
- The frontend now maps the questionnaire to the same Fachlogik thresholds before saving:
  - `C:\5eyes\5eyes_stage9_release_ready\5eyes-electron\frontend\5eyes_v2.html`

## 7. Remaining Go-Live Requirements

- Replace the default `SECRET_KEY`.
- Set a dedicated encrypted `DB_PATH`.
- Enable SQLCipher with a managed `DB_KEY`.
- Define operational retention/deletion rules for backups and support bundles.
- Confirm the incident-response process for EDÖB/FINMA reporting outside the app.

## 8. Operational Interpretation

- Development mode can still run unencrypted for local build/test workflows.
- Real customer production data should only be processed with SQLCipher enabled and non-default secrets configured.
