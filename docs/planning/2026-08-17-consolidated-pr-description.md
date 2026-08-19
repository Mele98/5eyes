# Konsolidierter PR: Stochastic-Optimizer-Produktionsdefault + Audit-Nachlauf

**Branch:** `integration/2026-08-17-consolidated` (Basis: `develop` @ `27b6f36`)
**Status:** vollständig verifiziert, lokal committed, **nicht gepusht**
**Test-Ergebnis:** Backend 5991 passed / 0 failed / 12 skipped (erwartet) / 1 xfail (bekannt, dokumentiert) — vollständiger Lauf, 23:56 Min. Frontend-Reporting-Sub-App: Typecheck sauber, 536/536 Vitest-Tests, Build erfolgreich.

Dieser Branch fasst 5 zuvor getrennt entwickelte und einzeln vollständig getestete Arbeitspakete zusammen. Jedes wurde eigenständig verifiziert (siehe verlinkte Einzel-PR-Beschreibungen), dann sauber in eine gemeinsame Basis gemergt (nur 1 Konflikt insgesamt — eine automatisch generierte Snapshot-Datei, per Regenerierung statt Konfliktseiten-Wahl gelöst) und als Ganzes nochmal vollständig getestet.

---

## 1. Stochastischer Optimizer wird Produktions-Default (Kernänderung)

Details: `docs/planning/2026-08-15-stochastic-optimizer-pr-description.md`

- `config.py`: `optimizer_mode`-Default wechselt von `'house_matrix'` auf `'stochastic'`. Der stochastische Solver ersetzt jetzt produktiv die Zielallokation bei Konvergenz; House Matrix bleibt auditierter technischer Fallback. `app_env=production` erzwingt `stochastic` per Guard.
- Mathematische Korrektheits-Fixes im Optimizer-Kern: dimensionslose Objective-Normalisierung, behobene Doppelzählung bei `cashflow_in_year`-Zielen, Zwischen-Finanzierungslücken-Check bei `outflow_stream`, momententreue Umrechnung arithmetischer CMA-Momente auf Lognormal-Parameter (unabhängig gegen Hull 2017 Kap. 14 nachgerechnet).
- Neue kanonische Fail-Closed-Semantik-Module (`goal_semantics`, `risk_assessment_semantics`, `wealth_position_semantics`, `mandate_preferences`, `mandate_model_inputs`, `cma_validation`, `calendar_horizon`, `return_moments`).
- Phase-6-Sensitivity-Endpoint (`POST .../target-allocation/sensitivity`).
- Preferences-Schema-Validatoren vervollständigt (vorher nur 2 von 8 Sektionen validiert — Tippfehler in Anlagerestriktionen blieben lautlos wirkungslos).
- Golden-Snapshot-Baseline neu eingefroren mit mathematisch verifizierten Werten (Sharpe-ähnliche Kennzahl verbessert sich durchgehend, z.B. 0.543→0.581 — Beweis für Risikokorrektur, nicht Regression).
- **Bonus-Fund während der Merge-Verifikation:** `alembic/env.py` rief `fileConfig()` ohne `disable_existing_loggers=False` auf — deaktiviert alle nicht explizit gelisteten Logger. Dieser Codepfad läuft bei **jedem Produktions-App-Start gegen Postgres** (`database.py`), war also ein latentes Risiko für kompletten Logging-Ausfall nach jedem Deploy. Vorbestehend seit `e009e36`, nichts mit diesem Merge zu tun — beim Verifikations-Lauf gefunden und mit dem Standard-Fix behoben.

## 2. A3-Pilot-Trockenlauf-Bugfixes

- `resolveReportingAppUrl()` prüfte `window.API` (immer `undefined`, `API` ist keine `window`-Property) statt der korrekten Referenz — brach den "Advisory-Report"-Button, sobald das Backend nicht auf Port 8000 lief.
- `WealthPositionCreate`: 4 von 5 lose typisierten Feldern (`pension_type`, `mortgage_type`, `mortgage_amortization_type`, `property_usage`) verursachten bei ungültigem Wert einen 500 statt sauberem 422 — jetzt gegen die exakten DB-CHECK-Constraints als `Literal[...]` validiert. `asset_subtype` bewusst als Freitext belassen (hat keinen CHECK-Constraint in der DB).
- Kontext: kompletter Live-Pilotdurchlauf (Depot+Vorsorge+Immobilie+Hypothek, AHV-Ziel, alle 6 PDF-Typen, doppelte E-Signatur, Abschluss) fand **keine Blocker** — App ist bereit für den ersten echten Piloten-Kunden.

## 3. Frontend-Monolith-Audit-Fixes

- **Compliance-relevant:** `saveAdvisoryLogEntry()` zeigte dem Berater einen grünen Erfolg, selbst wenn der Compliance-Trigger-Resolve-Call fehlschlug — der Trigger blieb dann unbemerkt offen. Jetzt echte Fehlermeldung statt falschem Erfolg. Gleiches Muster auch in `refreshWealthUI()` und `openCashflowRowEditor()` behoben.
- Drei byte-identische/äquivalente HTML-Escaping-Funktionen (`escapeHtml`, `adminPolicyEscape`, `dcEscape`, ~439+27 Aufrufstellen) auf eine konsolidiert, nach Verifikation dass kein Aufrufer von der einzigen Verhaltensdifferenz (Behandlung von `0`/`false`) betroffen ist.

## 4. Dynamischer RLS-Tabellen-Coverage-Guard

- `import_tenant_models()` (Postgres-RLS-Setup) war eine handgepflegte Import-Liste — ein neues Modell mit `tenant_id`-Spalte hätte unbemerkt ohne RLS-Policy ausgeliefert werden können. Läuft jetzt automatisch über alle Dateien in `models/` via `pkgutil`. Verhalten vor/nach identisch geprüft (8 Tabellen). Neuer Guard-Test inkl. Negativ-Kontrolle (legt zur Laufzeit eine absichtlich ungeschützte Tabelle an und beweist, dass der Guard sie meldet) — läuft vollständig gegen Postgres, wenn `POSTGRES_TEST_DATABASE_URL` gesetzt ist (in dieser Umgebung nicht verfügbar, daher aktuell nur SQLite-Teil ausgeführt).
- Sicherheitsaudit fand **keine echte Mandanten-Trennungslücke** (SQL-Injection nicht möglich, Connection-Pool setzt Tenant-Kontext bei jedem Checkout/Checkin zurück, kein DEK-Caching-Bug).

## 5. DSG Art. 32 — Löschanspruch-Workflow

Details: `docs/planning/2026-08-15-dsg-art32-erasure-workflow.md`

- Neuer Endpoint `POST /clients/{client_id}/erase` (Admin-only, Pflicht-Begründung).
- Zwei-Stufen-Modell: **Stufe A** (sofort geschwärzt) — Klardaten in Client/Mandat/Vermögen/Cashflows/Zielen/Vertragsdokumenten + Kunden-Login. **Stufe B** (bleibt unverändert) — FIDLEG/GwG/OR-962-pflichtige 10-Jahres-Compliance-Unterlagen.
- Audit-Log bleibt komplett unangetastet (harte SQLite-Trigger verbieten UPDATE/DELETE); die Löschung selbst wird als neuer, hash-verketteter `CLIENT_ERASE`-Eintrag protokolliert.
- **Braucht juristische Prüfung vor Live-Schaltung** (explizit im verlinkten Dokument benannt): exakte Stufe-A/B-Grenze bei Freitextfeldern, DSGVO-Frage bei deutschen Mandaten, Backup/Export-Handling.

---

## Merge-Historie (5 saubere Merges, 1 Konflikt)

```
9102255 chore: regenerate monolith inventory snapshot after final integration
719bda7 merge: DSG Art. 32 client-erasure workflow
2fe0e2a merge: dynamic RLS table-coverage guard
a4e0e02 merge: monolith audit fixes
446bffb merge: A3 pilot dry-run bugfixes         <- einziger Konflikt (Inventory-JSON, regeneriert)
902c644 fix(alembic): disable_existing_loggers=False
d1e26cb Merge codex/asset-allocation-stochastic-core
27b6f36 (develop, Ausgangspunkt)
```

## Was noch fehlt, bevor das live geht

1. **Menschliche Entscheidung:** diesen Branch tatsächlich pushen + PR auf GitHub eröffnen + nach `develop` mergen.
2. DSG-Art.-32-Workflow braucht juristisches Sign-off (siehe oben).
3. `test_account_recovery.py`s zwei Host-Header-Tests haben ein bekanntes, vorbestehendes (nicht durch diesen Branch verursachtes) zeitfensterabhängiges Flackern unter Volllast — eigener, separater Fix nötig (sicherheitsrelevanter Code, braucht testbares Rate-Limit-Engine-Refactoring).
4. RLS-Coverage-Guard vollständig erst mit echter Postgres-Instanz verifizierbar (hier nicht verfügbar) — vor Tier-2/3-Rollout nachholen.
5. **CI-Performance-Nachtrag (2026-08-18/19), GELÖST:** Das PR-Gate "Backend Tests" scheiterte 3x in Folge unter Coverage-Instrumentierung (30min@21%, 60min@39%, 120min mit 21-minütiger kompletter Stille nach 48%) — nie an einem echten Testfehler. Verdacht fiel zunächst auf `test_golden_snapshot_ch_regression.py` (rechenintensivste Monte-Carlo-Datei, nächste in der Kollektionsreihenfolge), aber lokal mit identischen `--cov`-Flags gemessen: nur 26s→37s (1.4x) für diese Datei allein, und ein voller lokaler Lauf mit denselben Flags läuft sauber durch genau diese Stelle und weit darüber hinaus (dreimal insgesamt lokal grün: zweimal ohne, einmal mit Coverage). **Schluss: Linux-CI-Runner-spezifisches Coverage-Instrumentierungsproblem, kein Code-Bug.** Fix: Coverage-Tracking aus dem blockierenden Pytest-Lauf entfernt; der PR-mergebar-Status hängt jetzt nur noch am schnellen, zuverlässig reproduzierenden Korrektheits-Lauf (~20-25min). Coverage läuft als separater `continue-on-error`-Schritt mit eigenem 60-Minuten-Timeout weiter (best-effort Artefakt-Upload) und kann PRs nicht mehr blockieren.
