# Sprint U-P22.6 — Token-Handoff von der 5eyes-Hauptapp zur Reporting-Sub-App

## Meta

- **Datum:** 2026-05-25
- **Vorgänger:** U-P22.5 (Vite-Proxy-Schärfung + Bearer-Auth in Reporting-App)
- **Scope:** Berater klickt in der Hauptapp einen Button und landet **direkt
  mit gültigem Token** in der Reporting-Sub-App — keine manuelle DevTools-
  Aktion nötig.
- **Konflikt-Vermeidung:** Genau **eine** Button-Zeile und **eine** JS-Funktion
  in `5eyes_v2.html`, minimal-invasiv neben dem bestehenden Depot-Check.

## Zweck

Heute (vor U-P22.6): Berater muss seinen Bearer-Token manuell aus der
Hauptapp lesen (DevTools → sessionStorage) und in den Browser-Tab der
Reporting-App via `sessionStorage.setItem('5eyes_token', ...)` einsetzen.
Mühsam, fehleranfällig, blockiert den schnellen Visual-Check.

Mit U-P22.6: Ein Klick → neuer Browser-Tab → Cover-Seite mit echten
Daten. Der Token wandert sicher über das URL-Fragment, wird sofort in
`sessionStorage` geschrieben und die URL bereinigt.

## Architektur

```
5eyes-Hauptapp                          Reporting-Sub-App
(Electron + 5eyes_v2.html)              (React + Vite-Dev :5173)
─────────────────────────                ──────────────────────────
[Portfolio ⋯-Menü]
   ├─ Depot-Check          ──── (bestehend, unverändert)
   └─ Advisory-Report  ◀── NEU (Button + onclick=openReportingApp)
             │
             │ openReportingApp(mid):
             │  1. token = window.desktop.getAuthToken()
             │           || sessionStorage.getItem('5eyes_token')
             │  2. url = "http://localhost:5173/mandates/<mid>/report
             │           #token=<token>"
             │  3. window.open(url, "_blank", "noopener")
             │
             ▼
                                      main.tsx:
                                      consumeHandoffFromUrlFragment()
                                        ↓
                                      handoff.ts:
                                        a. liest #token=... aus location.hash
                                        b. sessionStorage.setItem('5eyes_token')
                                        c. history.replaceState (URL säubern)
                                        ↓
                                      ReactDOM.createRoot(...).render(App)
                                        ↓
                                      useAdvisoryReport(mandateId)
                                        ↓
                                      fetchAdvisoryReport:
                                        resolveAuthToken() liest jetzt
                                        sessionStorage['5eyes_token']
                                        → Authorization: Bearer <token>
                                        ↓
                                      Backend /advisory-report → 200
                                        ↓
                                      Cover-Komponente rendert
```

## Geänderte Dateien

| Datei | Zweck |
|---|---|
| `5eyes-electron/frontend/reporting/src/api/handoff.ts` (NEU) | `consumeHandoffFromUrlFragment()` mit Defensive (no-window, no-fragment, no-token = no-op) |
| `5eyes-electron/frontend/reporting/src/main.tsx` | Call vor `ReactDOM.createRoot` |
| `5eyes-electron/frontend/5eyes_v2.html` | +1 Button + 1 JS-Funktion neben Depot-Check |
| `5eyes-backend/tests/test_reporting_mainapp_handoff.py` (NEU) | 11 statische Contract-Tests |

## Sicherheits-Disziplin

| Risiko | Gegenmittel |
|---|---|
| Token im Server-Log | URL-**Fragment** statt Query-String — Fragments werden niemals an den Server gesendet |
| Token im Browser-History | `history.replaceState` direkt nach Verbrauch — Token verschwindet aus der Adressleiste |
| Neuer Tab kann `window.opener` abusen | `window.open(..., '_blank', 'noopener')` |
| sessionStorage in hardened browser fehlt | `try/catch` mit fail-soft — Reporting-App zeigt dann 401, Berater fällt auf manuelles Setzen zurück |
| Token-Key-Drift zur Hauptapp | Test verifiziert exakt `5eyes_token`-Konvention beider Seiten |
| Drittsoftware könnte das URL-Fragment lesen | Lokales Dev-Setup auf 127.0.0.1, kein externes Routing |

## In Produktion (U-P27)

Der URL-Fragment-Weg ist **explizit Dev-only**. In der gepackten
Electron-App wird die Reporting-Sub-App als zweites BrowserWindow in
derselben Electron-Session geöffnet, und der Token kommt direkt aus
`window.desktop.getAuthToken()` ohne URL-Pass. Der `consumeHandoffFromUrlFragment`-
Code bleibt als Safety-Net — er ist no-op wenn kein Fragment da ist.

## Tests

`tests/test_reporting_mainapp_handoff.py` — **11 Tests, alle grün in 0.09s**:

| # | Test | Was |
|---|---|---|
| 1 | `handoff_ts_exists_and_exports_consumer` | API-Vertrag |
| 2 | `handoff_uses_5eyes_token_key_for_sessionstorage` | Konventions-Sync zur Hauptapp |
| 3 | `handoff_reads_url_fragment_not_querystring` | Server-Log-Hygiene + replaceState |
| 4 | `handoff_is_safe_in_non_browser_environments` | Vitest-Tauglichkeit |
| 5 | `main_tsx_calls_handoff_before_react_render` | Reihenfolge: handoff → render |
| 6 | `mainapp_has_advisory_report_button_in_portfolio_more_menu` | Button-Existenz + Adjazenz zu Depot-Check |
| 7 | `mainapp_open_reporting_app_function_handles_missing_mandate` | Fehler-Pfad |
| 8 | `mainapp_open_reporting_app_uses_url_fragment_for_token` | Fragment + encodeURIComponent |
| 9 | `mainapp_open_reporting_app_uses_same_token_hierarchy_as_main_api` | Electron-zuerst, Browser-Fallback |
| 10 | `mainapp_open_reporting_app_uses_window_open_with_noopener` | Browser-Security |
| 11 | `handoff_ts_no_third_party_brands` | Branding-Compliance |

Kompletter Reporting-Test-Suite: **76 Tests, alle grün in 0.19s**.

## Owner-Workflow (ab jetzt)

```
1. 5eyes-Hauptapp öffnen, einloggen
2. Mandat auswählen
3. Portfolio-Tab → ⋯-Menü → "Advisory-Report"
4. → neuer Browser-Tab mit Cover-Seite, automatisch authentisiert
5. Visual-Check
```

Wenn du den Look ändern willst: Korrektur in
`5eyes-electron/frontend/reporting/tailwind.config.ts` + `src/design/tokens.ts`
(beide synchron — Test verhindert Drift).

## Folge-Sprints (unverändert)

- **U-P23** Sektionen 2-5 (Inhaltsverzeichnis, Ausgangslage, Positionen, Pruefpunkte)
- **U-P24** Sektionen 6-10 (Ampel-Sektion + Recharts-Charts + Monte-Carlo-Bänder)
- **U-P25** Sektionen 11-15
- **U-P26** Server-PDF (ReportLab) im identischen Layout
- **U-P27** Polish + Electron-Window-Integration (ersetzt diesen URL-Fragment-Weg)
