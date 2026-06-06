# End-to-End-Tests (Playwright)

Foundation-Doku fuer E2E-Tests der Sub-App + Hauptapp-Integration.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #55 (QA, 1-2 Tage Vollausbau)
**Komplementaer zu:** [MUTATION_TESTING.md](MUTATION_TESTING.md) (#106),
[PROPERTY_BASED_TESTING.md](PROPERTY_BASED_TESTING.md) (#107)

---

## Warum E2E?

vitest deckt Component-Tests ab, pytest deckt Backend-API ab.
Beides verifiziert NICHT den **Berater-End-to-End-Flow**:

1. Login -> Token im sessionStorage
2. Hauptapp oeffnet Sub-App via URL-Fragment
3. Sub-App rendert Aggregator-Report
4. Sidebar-Navigation klappt
5. PDF-Download startet
6. Kunden-Portal (U-36) read-only-Verifikation

E2E faengt Drift zwischen Layern (Auth, Routing, Render, Network).

## Library-Wahl: Playwright

- **Microsoft Playwright** (gratis, ADR-005-kompatibel)
- Cross-Browser (Chromium/Firefox/WebKit)
- Best Electron-Support unter den Mainstream-E2E-Tools
- Schneller als Cypress, weniger flaky
- TypeScript-first

Cypress war Alternative — verworfen weil Electron-Support
historisch fragil und CI-Setup komplexer.

## Setup (opt-in)

Analog U-106/U-107: KEIN package.json-Eintrag bis konkret gebraucht.

```powershell
cd 5eyes-electron\frontend\reporting
npm install --save-dev @playwright/test
npx playwright install --with-deps chromium
```

## Test-Struktur (Vorschlag)

```
5eyes-electron/frontend/reporting/
├── e2e/
│   ├── playwright.config.ts
│   ├── fixtures/
│   │   └── seed-mandate.ts        (DB-Seed via Backend-API)
│   └── specs/
│       ├── auth.spec.ts           (Login + Token-Handoff)
│       ├── navigation.spec.ts     (Sidebar + Section-Routing)
│       ├── report.spec.ts         (24 Sektionen rendern)
│       ├── pdf.spec.ts            (Download-Trigger)
│       └── client-portal.spec.ts  (U-36 read-only Path)
```

## Erst-Sprint Smoke-Tests (Folge-Sprint)

1. **Sub-App Boot:** Backend hoch + Vite-Dev hoch + Browser oeffnet
   `/mandates/test-id/report` -> Cover-Sektion sichtbar
2. **Sidebar-Click:** 5 Sektionen klicken, jede rendert
3. **Token-Reject:** ohne Token -> Login-Redirect
4. **Client-Portal:** Kunden-Login -> `/client-portal/me` zeigt eigene
   Stammdaten, kein Edit-Button

## CI-Integration (Folge-Sprint)

```yaml
# .github/workflows/e2e.yml (Vorschlag)
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - uses: actions/setup-python@v5
      - run: pip install -r 5eyes-backend/requirements.txt
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - run: python 5eyes-backend/main.py &
      - run: npm run dev &  # in reporting/
      - run: npx wait-on http://localhost:8000/health
      - run: npx wait-on http://localhost:5173
      - run: npx playwright test
      - uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: e2e/playwright-report/
```

Heute NICHT in CI (E2E-Tests existieren nicht).

## Test-Daten

- **Foundation-Example** existiert: `POST /admin/system/foundation-example`
  legt MX-FOUNDATION-01 mit vollstaendigem Mandat an
- E2E-Tests koennen das als Seed nutzen
- Cleanup: `POST /admin/system/recommendation-runs/cleanup` (U-104)
  fuer Test-Isolation

## Bewusst NICHT in Scope (U-55)

- `@playwright/test` in package.json
- Erst-Sprint Specs (sind Folge-Sprint)
- CI-Workflow `.github/workflows/e2e.yml`
- Visual-Regression-Snapshots (Chromatic — kostenpflichtig
  ADR-005-Verstoss)
- Electron-Main-Process-Tests (separater Sprint mit
  electron-playwright)
- Performance-Budget (Lighthouse) — eigener Sprint

## Folge-Sprints

1. **Erst-Sprint:** 5 Smoke-Tests aus obiger Liste
2. **CI-Workflow:** `.github/workflows/e2e.yml`
3. **Visual-Regression** ohne Chromatic (z.B. Percy.io trial oder
   self-hosted)
4. **Electron-Main-Process** Tests via electron-playwright

## Weiterfuehrendes

- [Playwright docs](https://playwright.dev)
- [Foundation-Example Endpoint](../5eyes-backend/services/foundation_example.py)
- ADR-005 — CHF 0/Jahr (Chromatic verworfen)
- Roadmap #106 (Mutation), #107 (Property), #88 (SW) —
  komplementaere QA-Strategien
