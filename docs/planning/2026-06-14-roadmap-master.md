# 5eyes — Master-Roadmap (Standortanalyse 2026-06-14)

Frische, gerankte Master-Liste nach dem Kontroll-Audit (Vermögen → Cashflow → Ziele → Reserve/SAA → Risikoprofil → AA/MC) und dem Ausbau dieser Session (externer Zugriff, vermögensgetriebene Cashflows, SOLL/IST-Vergleich).

**Skala:** 🔴 KRITISCH/blockierend · 🟠 HOCH · 🟡 MITTEL · 🟢 NICE-TO-HAVE
**Tags:** BE Backend · FE Frontend · ENG Engine · PDF Report · DB Datenbank · SEC Security · OPS Deploy · FINMA Compliance · TAX Steuern · DATA Marktdaten · QA Tests · UX Usability · DOC Doku · REPO Repo
**Status:** [ ] offen · [~] in Arbeit · [✓] fertig · [⏸] wartet auf User-Entscheid · [⏭] verschoben
**Methodik:** überlegen → planen → umsetzen → prüfen+testen → anpassen. Pro Aufgabe Punkt-Nr nennen, danach Status updaten.

Kontroll-Audit-Fazit: Kernlogik sauber. 1 echter Bug gefunden+gefixt (Engine-Cashflow-Konsistenz), 1 Meldung präzisiert (FZK). Keine offenen Bugs in der Kernkette. Voller Lauf 3936 passed / 0 failed.

---

## 🔴 P0 — blockierend / zuerst (1–6)

- [⏸] **1.** [REPO] Session-Arbeit committen + PR. **Lösung:** `git branch --show-current` prüfen → Feature-Branch `feat/cashflow-aa-vergleich-2026-06` anlegen → in logischen Commits (extern-zugriff / cashflows / aa-vergleich / audit-fix) committen → PR gegen develop. Wartet auf Branch-Entscheid des Users.
- [ ] **2.** [REPO] Merge-Koordination mit Codex. **Lösung:** Vor Merge prüfen, welche geteilten Dateien Codex angefasst hat (5eyes_v2.html, schemas/users.py, portfolio_engine.py); Snapshot `python scripts/audit_html_monolith.py` nach jedem HTML-Merge neu generieren; Reihenfolge: grüne Suite zuerst.
- [⏸] **3.** [FE/ENG] Crash-Wurzelfix „Maximum call stack". **Lösung:** Symptom bereits abgefangen (`__chartStep`-Netz). Für Wurzel: User liefert Konsolenzeile `CHART_RENDER_FAILED [step]` → exakte rekursierende Funktion fixen (Punkt-Fix). Wartet auf User-Input.
- [ ] **4.** [QA] Browser-/Electron-Visual-Smoke der Hauptapp. **Lösung:** Checkliste abarbeiten: Login→2FA→Mandat→Cashflow (AUTO-Zeilen)→Strategie berechnen→SOLL/IST-Pop-up→Hover-Sync→PDF. Automatisierung als #79.
- [ ] **5.** [SEC] HttpOnly-Cookie-Migration statt JWT in localStorage. **Lösung:** Token in HttpOnly+Secure+SameSite-Cookie; CSRF-Token-Pattern; FE-API-Layer umstellen; Breaking-Change → eigener Sprint mit Migrationspfad. (KRITISCH-Rest aus altem #7.)
- [✓] **6.** [QA] Determinismus-Check der neuen IST-Risikometriken. **Erledigt 2026-06-14:** `test_engine_cashflow_consistency.py` — current_* vorhanden, symmetrisch zu target_*, ≥0, über zwei Läufe identisch.

## 🟠 P1 — echter Multi-Firma-/Externbetrieb (Hosting · Tenant · Compliance · Security) (7–30)

- [⏸] **7.** [DB] Provider-Entscheid Postgres-Hosting. **Lösung:** Infomaniak (Genf) vs. Exoscale (Lausanne) — CH-Residenz, Kosten, Managed-Postgres. Wartet auf User.
- [ ] **8.** [DB] Postgres-Adapter verifizieren. **Lösung:** SQLAlchemy ist DB-agnostisch; `DATABASE_URL` einführen, SQLite-spezifische Stellen (ensure_runtime_columns, PRAGMA, sqlite3.backup) hinter Dialekt-Switch; Test-Matrix SQLite+Postgres.
- [ ] **9.** [DB/SEC] Row-Level-Security-Policies. **Lösung:** Pro mandantenführender Tabelle `CREATE POLICY tenant_isolation USING (tenant_id = current_setting('app.tenant_id'))`; `SET app.tenant_id` pro Connection im Request-Scope (Middleware/Session-Hook). Macht ein vergessenes App-Filter physisch wirkungslos.
- [ ] **10.** [DB] `tenant_id` NOT NULL nach Backfill. **Lösung:** Unter Postgres sauber per Migration (ALTER … SET NOT NULL) nach `ensure_tenant_backfill`; SQLite-Limitierung entfällt.
- [ ] **11.** [DB/SEC] Per-Tenant-Encryption-Key (at-rest). **Lösung:** Key-Hierarchie (Master-KEK → per-Tenant-DEK), Postgres-TDE oder App-Level-Feldverschlüsselung für PII; Key-Rotation dokumentieren.
- [ ] **12.** [OPS] CH-VPS-Setup. **Lösung:** `docs/deploy/` (Caddyfile + systemd-Unit vorhanden) auf CH-VPS ausrollen, Let's-Encrypt-TLS, Cloudflare davor (WAF/DDoS/Rate-Limit-Edge), `app_env=production` (aktiviert Config-Guards).
- [ ] **13.** [SEC] Secret-Management. **Lösung:** SECRET_KEY/DB_KEY/SMTP aus Vault oder verschlüsselter Env, nie Default; Rotation; Production-Guard (vorhanden) erzwingt non-default.
- [ ] **14.** [OPS] Monitoring/Alerting. **Lösung:** Health-Endpoint + Uptime-Check, Fehlerquoten-/Latenz-Alerts, Login-Fail-Spikes; Logaggregation (request_id vorhanden).
- [ ] **15.** [OPS] Off-Site-Backup-Replikation (CH). **Lösung:** bestehenden Backup-Scheduler um verschlüsselte Off-Site-Kopie (zweites CH-RZ) erweitern; Restore-Drill dokumentieren.
- [✓] **16.** [FINMA] AVV-Template (Auftragsverarbeitungsvertrag). **Erledigt 2026-06-15:** `docs/compliance/avv-template.md` — Rollen je Tier, Pflichten, TOM-Anhang, Unterauftragsverarbeiter, CH-Datenstandort. Vom Betreiber rechtlich zu prüfen.
- [✓] **17.** [FINMA] FINMA-Outsourcing-Anzeige (RS 2018/3). **Erledigt 2026-06-15:** `docs/compliance/finma-outsourcing-anzeige.md` — Wesentlichkeits-/Tier-Matrix, Trigger (erster Echt-Tenant T2/T3), Prozess-Checkliste, Anzeige-/Inventar-Vorlage.
- [✓] **18.** [FINMA] DSFA (Datenschutz-Folgenabschätzung) Operator. **Erledigt 2026-06-15:** `docs/compliance/dsfa-datenschutz-folgenabschaetzung.md` — Bearbeitung, Risiken (Mandanten-Übergriff als Hauptrisiko), TOM, Restrisiko je Tier, revDSG Art. 22/23.
- [ ] **19.** [SEC] Externer Pentest vor erstem Echt-Tenant. **Lösung:** Beauftragung; Fokus Auth/Tenant-Isolation/öffentliche Endpoints; Findings als Sprint.
- [ ] **20.** [SEC] Globales Rate-Limiting am Edge. **Lösung:** Cloudflare-Rules + App-seitiges Throttling auf alle schreibenden/öffentlichen Endpoints (über Login/Invite hinaus).
- [ ] **21.** [FINMA] Audit-Log tenant-partitioniert + Streaming. **Lösung:** Audit-Log um Tenant-Partition/Index ergänzen, optional Export-Stream (SIEM); Retention pro Tenant.
- [ ] **22.** [SEC] Client-Portal expliziter Tenant-Check. **Lösung:** ✓ bereits ergänzt (`get_linked_client_for_user_or_404` prüft user.tenant_id==client.tenant_id) — im Postgres-RLS-Modell zusätzlich absichern.
- [✓] **23.** [OPS] Provisioning-/Onboarding-Ops-Runbook. **Erledigt 2026-06-15:** `docs/deploy/provisioning-runbook.md` — Tenant anlegen → Admin einladen → 2FA → Quota → Verifikations-Checkliste → Betrieb → Offboarding (revDSG-Export). Verweist auf `allow_real_client_data`-Gate.
- [ ] **24.** [OPS] Lizenz-/Quota-Enforcement. **Lösung:** tenants.quotas auswerten (max User/Mandate), Soft-/Hard-Limits, Hinweis-UI.
- [ ] **25.** [SEC] 2FA-Recovery-Codes. **Lösung:** Beim 2FA-Enrollment Backup-Codes generieren (Hash speichern), Recovery-Flow falls Authenticator verloren.
- [ ] **26.** [BE] E-Mail-Versand aktiv schalten. **Lösung:** SMTP-Zugang in `start-external.ps1`/Env setzen (Code fertig, `services/mailer.py`); Invite verschickt dann direkt.
- [ ] **27.** [BE] Passwort-Reset-Flow (Self-Service). **Lösung:** Token-basiert wie Invite (sha256, Ablauf, single-use) + E-Mail; Endpoint + Frontend-Maske.
- [ ] **28.** [SEC] Session-/Token-TTL + Refresh. **Lösung:** Kurze Access-Token-TTL + Refresh-Token-Rotation; bestehende Token-Wandering-Schutz beibehalten.
- [ ] **29.** [OPS] Staging→Prod-Promotion-Pfad. **Lösung:** `promote_operator.py` erweitern, Daten-Klassifizierungs-Sperre (allow_real_client_data, Codex) als Gate vor Echtdaten.
- [ ] **30.** [DOC] Domain/Branding-Entscheid (z.B. app.5eyes.ch). **Lösung:** Domain registrieren, TLS-Cert, CI-Theme des Intro-Screens. Wartet teils auf User.

## 🟡 P2 — Fachlogik · Engine · Produkt (31–62)

- [✓] **31.** [ENG] Hypothek-Amortisation baut Schuld in Projektion ab. **Fachlogik (User 2026-06-14):** direkt→Schuld abbauen, indirekt→bleibt; Satz aktuell bis Ablauf/5J-SARON, danach 3%. **A ERLEDIGT:** `mortgage_interest_schedule()` (pure). **B ERLEDIGT (Engine):** `mortgage_interest_adjustment_series` additiv auf `cashflow_projection_series_rappen` an BEIDEN Engine-Ladestellen → SOLL/IST-Strategiekurven+MC+Reserve reflektieren Amortisation/Refi. Tests grün. **B-2 ERLEDIGT:** Client-Endpoint `/cashflow-projection` rechnet die Anpassung jahresweise ein → Cashflow-Seiten-Kurve identisch zur Strategie. Tests: direkt sinkt, indirekt konstant. → **#31 vollständig (A+B+B-2).**
- [✓] **32.** [ENG] Hypothek-Laufzeitende. **Durch #31 gelöst (User-Entscheid):** kein Stopp am maturity_date, sondern Refinanzierung mit 3% (Fix nach Ablauf, SARON nach 5J) — in `mortgage_interest_schedule` umgesetzt.
- [ ] **33.** [ENG] `goal_scope`="Gesamtvermögen" engine-seitig. **Lösung:** Ziele mit Scope Gesamtvermögen gegen total_wealth statt advisory bewerten (heute bewusst Metadaten); Risiko der Wachstumsannahmen externer Assets dokumentieren.
- [ ] **34.** [ENG] Miete inflationsindexiert (optional). **Lösung:** Pro Immobilie Flag „Miete inflationsgebunden"; abgeleiteter Mietertrag dann is_inflation_linked=1.
- [✓] **35.** [FE/ENG] Sharpe-/Rendite-Risiko-Kennzahl im Vergleich. **Erledigt 2026-06-15:** Zeile „Rendite/Risiko (Sharpe)" je Spalte SOLL/IST in der Kennzahlen-Tabelle = (P50-Rendite − risk-free 80 bps = liquidity_return_bps) / MC-1J-Vola, Besser/Schlechter-Färbung. Test `test_frontend_sollist_metrics.py`.
- [ ] **36.** [FE/ENG] Ziel-Erfolgswahrscheinlichkeit SOLL vs IST. **Lösung:** MC-Erreichungswahrscheinlichkeit je Ziel für beide Pfade nebeneinander.
- [✓] **37.** [FE] Best/Worst-Endwert je Spalte. **Erledigt 2026-06-15:** Zeilen „Endwert optimistisch (P90)" + „Endwert pessimistisch (P10)" je Spalte SOLL/IST (letztes Element der target/current_p90/p10_series_rappen), Besser-Färbung. Test `test_frontend_sollist_metrics.py`.
- [ ] **38.** [BE/UX] Doppelerfassungs-Warnung Cashflow. **Lösung:** Beim manuellen Anlegen prüfen, ob ein abgeleiteter Posten gleicher Art existiert → Hinweis (kein Hard-Block, User wählte „beide zeigen").
- [ ] **39.** [TAX] Steuer in Netto-Rendite/Cashflow. **Lösung:** Vermögens-/Einkommenssteuer-Schätzung (CH-Plugin vorhanden) in Cashflow-Projektion als wiederkehrende Ausgabe optional einrechnen.
- [ ] **40.** [TAX] Weitere Länder via SDK (FR/US/IT/DE/AT). **Lösung:** Tax-SDK (vorhanden, `services/tax/sdk.py`) — pro Land Plugin nach Conformance-Contract; inhouse oder externes pip-Paket.
- [ ] **41.** [ENG] Engine-Hardening P2 (aus 3-Phasen-Plan). **Lösung:** offenen Punkt P2 des CTO-Audits umsetzen (siehe Engine-Hardening-Plan), mit Pinned-Tests.
- [ ] **42.** [ENG] Engine-Hardening P3. **Lösung:** dito P3.
- [ ] **43.** [ENG] Engine-Hardening P4. **Lösung:** dito P4.
- [ ] **44.** [ENG] Engine-Hardening P5. **Lösung:** dito P5.
- [ ] **45.** [ENG] Sub-Asset-Klassen-Tiefe im Optimizer. **Lösung:** Intra-Bucket-Allokation (CH-Equity ↔ EM-Equity etc.) mit Block-Diagonal-Korrelation (sub_class_intra_correlation vorhanden) ausbauen.
- [ ] **46.** [ENG] Tax-aware Optimizer-Objective. **Lösung:** Nach-Steuer-Rendite in die Zielfunktion (optional, opt-in).
- [ ] **47.** [ENG] Currency-aware Optimizer. **Lösung:** FX-Risiko/Hedging-Kosten in Scenario-Engine; base_currency-Konsistenz (FXRateSource vorhanden).
- [ ] **48.** [ENG] Stochastic-Optimizer als Default prüfen. **Lösung:** Shadow-Comparison-Aggregat (Methodology §4) auswerten → ab ≥3 Mandaten + GREEN-Mehrheit Default-Switch erwägen (opt-in OPTIMIZER_MODE).
- [ ] **49.** [ENG] Rebalancing-Trigger-Konsistenz. **Lösung:** Re-Balancing nur via Eignungsprüfung/Kundenmeldung (Anlagephilosophie) — sicherstellen, dass keine automatische Markt-Timing-Logik aktiv ist.
- [ ] **50.** [DATA] Marktdaten-Provider-Health-Dashboard. **Lösung:** bestehende HealthState + Provider-Validierung in Admin-UI sichtbar machen.
- [ ] **51.** [DATA] CMA-Werte-Pflegeprozess. **Lösung:** Kapitalmarktannahmen versionieren, konservative Defaults (Maxime tieferer Wert), Quelle/Datum dokumentieren.
- [ ] **52.** [ENG] Vermögensverzehr-Sockel verfeinern. **Lösung:** Immobilie indexiert (sockelIndexBps), verzehrbares Finanzvermögen mit konservativer Drawdown-Rendite; an Leart geeicht.
- [✓] **53.** [FE] Cashflow-Editor: abgeleitete Posten „im Vermögen bearbeiten"-Sprung. **Erledigt 2026-06-15:** AUTO-Zeile ist klickbar (wenn `origin_position_id` bekannt) → `jumpToWealthPosition()` navigiert zu Seite «Vermögen» (`go('vg')`), scrollt zur Position (`.wr[data-posid]`) und hebt sie kurz hervor. Test `test_frontend_derived_cashflow_jump.py`.
- [ ] **54.** [BE] Wealth-Inflows-UI vervollständigen. **Lösung:** Erbschaft/Bonus/3b/Verkaufserlös als first-class FE-Eingabe (Modell vorhanden), Marker im Chart.
- [ ] **55.** [ENG] Mehrjahres-Cashflow-Editor (Phasen). **Lösung:** Lohn endet/AHV beginnt sauber (valid_until inklusiv beachten), Verzehrphasen modellieren.
- [ ] **56.** [FINMA] Kostenausweis Ex-ante (#67). **Lösung:** Codex-Auftrag — Ex-ante-Kosten im PDF/Endpoint, konservative CMA, keine Dritt-Marken. Status bei Codex.
- [ ] **57.** [PDF] SOLL/IST-Vergleich + Risiko-Kennzahlen ins PDF. **Lösung:** die neue Zwei-Spalten-Tabelle als PDF-Sektion rendern (nach Codex-PDF-Cluster abstimmen).
- [ ] **58.** [PDF] SOLL-only-Refactor Sektionen 8/9/10 (alt #4). **Lösung:** IST aus den Strategie-Sektionen entfernen wo Backtesting greift; abstimmen mit Codex.
- [ ] **59.** [ENG] Goal-Liability-Doppelzählung Endkontrolle. **Lösung:** sicherstellen, dass Ziel-Ausgaben und manuelle/abgeleitete Cashflows nicht doppelt als Outflow zählen (Audit sagt getrennt — Regressionstest pinnen).
- [ ] **60.** [BE] Cashflow-Währung im UI/Hover. **Lösung:** Multi-Currency-Cashflows mit FX-Konvertierung anzeigen (Engine konvertiert bereits via FXRateSource).
- [ ] **61.** [ENG] Reserve-Erklärbarkeit im Report. **Lösung:** Reserve-Herleitung (near-term-shortfall, Ziel-Reserve, SAA-Cap, externe Reserve) als Berater-Narrativ ausweisen.
- [✓] **62.** [QA] Property-/Fuzz-Tests Cashflow-Annualisierung. **Erledigt 2026-06-14:** `test_cashflow_annualization_properties.py` (27 Tests) — Frequenz×Fenster, valid_until-inklusiv, Out-of-Window=0, einmalig, Monotonie, Inflations-Skalierung.

## 🟡 P3 — FE-Monolith-Migration (ADR-008) · Reporting (63–78)

- [ ] **63.** [FE] Migration Track 2: Profiling-Workflow → React. **Lösung:** Schema-First + React-Page + Tests + Wiring + Drift-Test (Migration-Pattern aus ADR-008).
- [ ] **64.** [FE] Migration: Goal-Wizard → React. **Lösung:** dito.
- [ ] **65.** [FE] Migration: Mandate-Edit → React. **Lösung:** dito.
- [ ] **66.** [FE] Migration: CRM/Stammdaten → React. **Lösung:** dito.
- [ ] **67.** [FE] Migration: Asset-Allocation-Edit → React. **Lösung:** dito (inkl. SOLL/IST-Charts als Komponente).
- [ ] **68.** [FE] Migration: Cashflow-Editor → React. **Lösung:** dito (inkl. abgeleitete Posten read-only).
- [ ] **69.** [FE] Migration Track 3: App-Shell. **Lösung:** Routing/Auth/Shell zuletzt; Monolith ablösen.
- [ ] **70.** [FE] Monolith-Snapshot-Disziplin. **Lösung:** nach jeder HTML-Änderung `audit_html_monolith.py`; Drift-Test grün halten (bereits etabliert).
- [ ] **71.** [PDF] Two-Pass echte Seitenzahlen + TOC-Hyperlinks. **Lösung:** Render mit echten Seiten statt Estimates; TOC verlinkt.
- [ ] **72.** [PDF] Page-Range-Anzeige pro Sektion im TOC. **Lösung:** „S. 4–6" statt Einzelseite.
- [ ] **73.** [FE] Reporting-Sub-App: SOLL/IST-Vergleich-Page. **Lösung:** die neue Vergleichslogik auch in der React-Reporting-App.
- [ ] **74.** [FE] Dark-Mode Hauptapp. **Lösung:** CI-Variablen (var(--…)) sind vorhanden; Theme-Switch + persistente Präferenz.
- [ ] **75.** [UX] Intro/Loading-Screen CI-themebar. **Lösung:** Cooperate-Identity-Hook (Farben/Logo per Tenant), bestehender Intro-Screen.
- [ ] **76.** [UX] Admin-Menü-Redesign (Auftrag 2026-06-10). **Lösung:** 17 Sektionen System-Administration auditieren (works vs placeholder) + userfriendlicher gruppieren.
- [ ] **77.** [FE] Logo/Branding final (alt #92). **Lösung:** Inline-SVG-Wordmark vorhanden; finalen Asset/CI-Entscheid des Users einarbeiten. Wartet auf User.
- [✓] **78.** [DOC] User-Doku / Berater-Handbuch. **Erledigt 2026-06-15:** `docs/handbook/berater-handbuch.md` — Workflow SD→CF/Ziele→RP→SAA→PO, Strategie lesen (P90/P10/Sharpe), SOLL/IST-Vergleich + PNG, Horizont, Prinzipien, externer Zugriff/2FA, Compliance-Bezug.

## 🟢 P4 — QA · CI · OPS-Härtung (79–95)

- [ ] **79.** [QA] Playwright/E2E der Hauptapp. **Lösung:** Headless-Browser-Test Login→Strategie→Charts→PDF; in CI.
- [ ] **80.** [QA] End-to-End EXE-Build in CI. **Lösung:** GH-Actions baut Electron-EXE + Smoke (PDF-Request gegen gepackte App).
- [ ] **81.** [QA] Visual-Regression der Charts. **Lösung:** Screenshot-Diff SOLL/IST-Pop-up + Kennzahlen-Tabelle.
- [ ] **82.** [QA] CI-Security-Gate erweitern. **Lösung:** ✓ vorhanden (scripts/security_gate.py); neue Tenant/Auth-Tests konsequent eintragen (Meta-Test schützt).
- [ ] **83.** [QA] Performance-Budget Aggregator/Engine. **Lösung:** Laufzeit-Wall pro Strategie-Berechnung + Aggregator (SELECT-Budget) als Test.
- [ ] **84.** [QA] Last-/Concurrency-Test Multi-Tenant. **Lösung:** parallele Requests verschiedener Tenants → keine Cross-Leaks, keine DB-Locks.
- [ ] **85.** [OPS] CI-Lint (ruff/black/mypy) Gate. **Lösung:** statische Analyse als PR-Gate; schrittweise Typisierung.
- [ ] **86.** [QA] Mutations-Test der Risiko-/Cashflow-Formeln. **Lösung:** gezielte Mutationen müssen Tests rot machen (Test-Stärke verifizieren).
- [ ] **87.** [OPS] Reproduzierbare Dev-Umgebung. **Lösung:** requirements gepinnt (segno ergänzt), optionale Lockfile/venv-Doku.
- [✓] **88.** [QA] Contract-Tests current_*-Felder. **Erledigt 2026-06-14:** test_engine_cashflow_consistency prüft alle target_/current_-Risikofelder im MC-Payload (vorhanden/symmetrisch).
- [ ] **89.** [OPS] Log-Rotation + LOG_DIR-Prod. **Lösung:** LOG_DIR konfigurierbar (vorhanden); Rotation/Retention in Prod.
- [ ] **90.** [DB] alembic-Erstmigration scharf schalten. **Lösung:** opt-in dokumentiert (#41 alt) → Baseline-Migration + init_db-Switch create_all↔alembic.
- [ ] **91.** [QA] Daten-Klassifizierungs-Sperre testen. **Lösung:** allow_real_client_data=false-Gate (Codex) mit CI-Test absichern, in security_gate aufnehmen.
- [✓] **92.** [OPS] Health-/Readiness-Endpoints. **Bereits vorhanden (verifiziert 2026-06-14):** routers/health.py — /health/live (Liveness), /health/ready (DB-Check, 503 bei Outage), /health/db.
- [ ] **93.** [QA] Regressionstest SOLL/IST-Achsen-Sync. **Lösung:** headless DOM-Harness: gleiche Labels + gleiche y-min/max nach syncAaProjectionAxisScales.
- [✓] **94.** [QA] Regressionstest abgeleitete Cashflows in beiden Engine-Pfaden. **Erledigt 2026-06-14:** `test_engine_cashflow_consistency.py` — Quellen-Guard (beide Pfade enthalten derive_wealth_cashflows) + Verhaltensprobe (Hypothek erhöht recurring_expense im Generate-Pfad).
- [✓] **95.** [DOC] ADR-Refresh. **Erledigt 2026-06-15:** ADR-007 (Multi-Tenancy jetzt AKTIV, App-Level umgesetzt; RLS/Postgres/Encryption offen) + ADR-009 (T1–T5 + externer Zugriff + Compliance-Vorlagen erledigt; Infra-Schicht offen) je um Ist-Stand-Block ergänzt.

## 🟢 P5 — Politur · Doku · Nice-to-have (96–110)

- [ ] **96.** [UX] Tooltip-Caret-Position im Cross-Hover feinjustieren. **Lösung:** falls Tooltip leicht verrutscht: Position auf oberste Linie/zentriert klemmen.
- [✓] **97.** [UX] Mehrwert-Delta im Pop-up. **Erledigt 2026-06-14:** prominentes Banner oben im SOLL/IST-Pop-up — „Beratungs-Mehrwert bis <Jahr>: +CHF X (Hauptszenario SOLL gegenüber heutigem Mix)", grün/warn-farbig.
- [✓] **98.** [UX] Kennzahlen-Tabelle: farbliche Besser/Schlechter-Markierung. **Erledigt 2026-06-14:** `_colorBetter()` färbt SOLL-Zelle grün/warn je Kennzahl (Ertrag höher=besser, Risiko tiefer=besser), aus Roh-MC-Werten.
- [✓] **99.** [UX] Cashflow-Liste: Gruppierung (Erwerb/Vorsorge/Wohnen). **Erledigt 2026-06-15:** holistische Lebensbereich-Gruppen (Erwerb → Vorsorge → Wohnen → Kapital & Vermögen → Lebenshaltung → Sonstiges) in zufluss/abfluss mit Zwischentotal je Gruppe; abgeleitete Posten via Herkunft (Hypothek/Immobilie→Wohnen, Liquidität→Kapital) korrekt einsortiert; manuelle Drag-Reihenfolge bleibt innerhalb der Gruppe erhalten (sortCashflowsByStoredOrder vor Bucketing). `cashflowLifeArea()`/`renderCashflowGroups()`. Test `test_frontend_cashflow_grouping.py`.
- [✓] **100.** [UX] Empty-States/Onboarding-Hints. **Erledigt 2026-06-15:** gemeinsamer Helper `journeyEmptyHint()` macht die singulären Journey-Leerzustände (Ziele, Cashflow Ein-/Ausgaben) FÜHREND — sie nennen, was zu erfassen ist und warum es für Strategie/Vermögensverzehr zählt. (Vermögens-Bucket-Leerzustände bewusst knapp gelassen, da pro Kategorie wiederholt.) Test `test_frontend_empty_states.py`.
- [ ] **101.** [UX] firm-admin eigene Tenant-Branding-Vorschau. **Lösung:** Logo/Farben pro Firma in Team-UI.
- [✓] **102.** [DOC] Memory-/Roadmap-Konsolidierung. **Erledigt 2026-06-15:** Dieses Dokument (`2026-06-14-roadmap-master.md`) ist die **aktuelle Master-Referenz**; die alte 110er-Roadmap (2026-05-28) gilt als historisch/abgelöst. Status-Tracking erfolgt nur noch hier + in den Memory-Dateien.
- [ ] **103.** [REPO] Tote/temporäre Dev-Harnesses entfernen. **Lösung:** repro.js, seed_leart.py etc. aufräumen oder klar als dev markieren.
- [✓] **104.** [UX] Druck-/Export der Vergleichsgrafik. **Erledigt 2026-06-15:** Button „⤓ PNG exportieren" im SOLL/IST-Pop-up → `exportSollIstComparePng()` rendert beide Charts (SOLL links, IST rechts) + Titel + Mehrwert-Banner auf ein weisses Canvas und lädt es als `SOLL-IST-Vergleich-<Name>.png`. Test `test_frontend_sollist_metrics.py`.
- [ ] **105.** [UX] Barrierefreiheit Charts. **Lösung:** aria-Labels/Tabellen-Fallback für Screenreader.
- [ ] **106.** [DATA] ETF-Scraper-Robustheit. **Lösung:** justetf/swissfunddata-Fallbacks + Health-Alerts (vorhanden) überwachen.
- [✓] **107.** [BE] Invite-Resend-Rate-Limit. **Erledigt 2026-06-14:** resend_invite drosselt pro Ziel-User (login_attempt_guard, 429+Retry-After). Test grün.
- [✓] **108.** [UX] 2FA-Setup: „Secret kopieren"-Button. **Erledigt 2026-06-14:** Copy-Button neben dem Text-Secret (`do2faCopySecret`, clipboard) + Erfolgs-/Fehlermeldung.
- [✓] **109.** [DOC] Disaster-Recovery-Plan. **Erledigt 2026-06-15:** `docs/deploy/disaster-recovery-plan.md` — RTO/RPO-Matrix, Backup-Strategie, Restore-Prozedur, **Pflicht-Restore-Drill** (quartalsweise, mit Protokoll-Tabelle), Rollen/Eskalation.
- [ ] **110.** [UX] Performance-Wahrnehmung: Skeletons/Spinner. **Lösung:** Ladezustände für Strategie-Berechnung + Charts (teilweise vorhanden) vereinheitlichen.

---

**Sofort-empfohlene Reihenfolge:** #1 (committen) → #3 (Crash-Zeile vom User) → #7/#8/#9 (Postgres+RLS, sobald Provider klar) → #31 (Amortisations-Abbau, autonom machbar) → #16–#19 (Compliance vor Echtdaten). Engine-Hardening (#41–#48) und FE-Migration (#63–#69) laufen als eigene Sprint-Cluster.
