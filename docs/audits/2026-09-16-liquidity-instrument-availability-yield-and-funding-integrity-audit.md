---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-liquidity-instrument-availability-yield-funding-integrity-followup-audit"
status_as_of: "2026-09-21"
audit_started_on: "2026-09-16"
audit_completed_on: "2026-09-21"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "0aec68a5b1069995f5106d7276a1375dad0b3605"
prior_release_audit_path: "docs/audits/2026-09-14-direct-property-mortgage-amortization-and-publication-integrity-audit.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-16-liquidity-instrument-availability-yield-and-funding-integrity-audit.md"
audit_mode: "read_only_static_ui_router_service_orm_schema_migration_test_review_plus_isolated_python_and_frontend_javascript_reproductions_and_isolated_pytest_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "WealthPosition liquidity instruments, rate and availability terms, assignment and liability semantics, advisory investability, reserve and goal funding, optimizer versus deterministic/Monte-Carlo yield bases, API/UI no-op roundtrip, snapshot drift, manual/derived interest reconciliation and publication provenance"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 4
confirmed_prior_p1_extension_groups: 2
confirmed_prior_p1_ids: 3
static_register_rows_confirmed: 6
isolated_runtime_reproduction_groups_confirmed: 11
focused_existing_tests_passed: 471
focused_existing_tests_failed_after_isolation: 0
focused_existing_test_runs_confirmed: 2
isolated_frontend_javascript_executed: true
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "introduce one immutable LiquidityInstrumentModelSnapshot, one reconciled CashflowProjectionSnapshot and one AllocationRunInputManifest root hash bound to TargetAllocation, every OptimizerRun, Goal/Reserve evidence and every publication/signature/handoff; close and migrate instrument/rate/date domains plus the Positionstyp-/Assignmentmatrix under a versioned LiquidityModelPolicy; separate total, advised, tradable, reserve-eligible and goal-available principal; derive accrual, payout and release schedules once; reconcile the CMA decision basis with the position-specific reporting basis; make no-op edits semantically idempotent; preserve every effective field and source-pot provenance through API/UI/hash/React/PDF; reuse the existing exactly-once flow contract; fail closed on unknown, stale, locked, liability-misclassified or unreconciled state"
---

# Liquiditätsinstrument-/Verfügbarkeits-/Zins-/Funding-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die einunddreißigste Read-only-
Kontrollrunde. Sie wurde am 16. September 2026 auf dem unveränderten
Repository-Head `0aec68a` begonnen und nach unabhängigen Kanalgegenprüfungen
am 21. September 2026 abgeschlossen. Produktcode und Tests wurden nicht
verändert. Erst nach Abschluss der technischen Prüfung werden exakt fünf
Dokumentationspfade angepasst.

Der Audit bewertet weder marktgerechte konkrete Kontozinsen noch die Eignung
eines bestimmten Bankprodukts. Er prüft den technischen Vertrag:

1. ob Kontoguthaben, Sparkonto, Festgeld, Kassenobligation und
   Geldmarktfonds geschlossene und unterschiedliche Bedeutungen besitzen,
2. ob Rate, Bewertungszeit, Zinsbeginn, Verfügbarkeit, Fälligkeit und
   Auszahlung getrennt und valide modelliert sind,
3. ob gesperrtes Kapital nur in den fachlich zulässigen Perioden als
   investierbar, reservefähig oder zielfinanzierend gilt,
4. ob Optimizer, deterministische Projektion und Monte Carlo ihre bewusst
   unterschiedlichen Yield-Basen quantitativ reconciliable verwenden,
5. ob eine Liquiditätsposition nicht gleichzeitig Liability und Zinsertrag
   sein kann,
6. ob API, Classic UI, Drift-Hash, Advisory-Report, React und PDF denselben
   wirksamen Zustand transportieren,
7. und ob ein historisches Ergebnis aus unveränderlichen Instrumentterms und
   periodischen Principal-/Accrual-/Payout-/Availability-Serien reproduzierbar
   bleibt.

Dieser Audit ergänzt insbesondere:

1. den unmittelbar vorherigen
   [Direktimmobilien-/Hypotheken-/Amortisations-/Publikations-Integritätsaudit](2026-09-14-direct-property-mortgage-amortization-and-publication-integrity-audit.md),
2. den
   [Retirement-Income-/Pensions-/Entnahme-/Depletion-Integritätsaudit](2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md),
3. den
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
4. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
5. sowie die
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Für Aussagen über den **beobachteten Ist-Stand** gelten aktueller Code, Tests
und Migrationen zuerst. Für den **zu implementierenden Zielvertrag** gilt
dieser Audit vor den älteren Dokumenten. Bestandstests, die ein hier
reproduziertes Fehlverhalten ausdrücklich pinnen, sind Evidenz des Ist-Stands,
aber keine Norm; sie müssen mit der freigegebenen Modellmigration bewusst
ersetzt werden.

### Verhältnis zu früheren Aussagen und Findings

`PENSION-AVAILABILITY-001` hat bereits bestätigt, dass der generische
`unlocked_other_assets_rappen`-Mechanismus unter anderem
`liquidity_available_from` ignoriert. `PROPERTY-COLLATERAL-001` hat denselben
Boolean-Mechanismus für die ungekürzte externe Immobilienanrechnung
präzisiert. Dieser Audit erzeugt dafür keinen dritten generischen Finding-ID.
Er erweitert die vorhandenen P1 um den direkten Liquiditätsfall, die sofortige
Advisory-Investierbarkeit, den API-Roundtrip-Verlust und die fehlende
Hashbindung.

`PROPERTY-FLOW-DUPLICATION-001` verlangt bereits eine genau-einmal-Policy für
Miete, Zins und Amortisation. Der hier reproduzierte manuelle plus derived
Kontozins ist eine weitere Instanz dieses bestehenden P1, kein neuer
Duplikat-Finding.

`MC-CONTEXT-001`, `MC-CASHFLOW-CURRENCY-001` und
`GOAL-PUBLICATION-001` bleiben die allgemeinen Run-/Cashflow-/Goal-Verträge.
`LIQUIDITY-INSTRUMENT-MODEL-001` ist enger: Er betrifft die fehlende
instrumentbezogene Brücke zwischen dem ausdrücklich deklarierten
`cma_total_return` der Optimierung und
`zero_bucket_plus_position_interest_cashflow` der Reportingprojektion.

`LIQ-CASCADE-001` betrifft die fehlende Engine-Evidenz der
Liquiditäts-Cascade. Dieser Audit betrifft dagegen die Herkunft, Bindung und
Zeitverfügbarkeit des Kapitals, das eine Reserve oder ein Liquiditätsziel
überhaupt decken soll.

Der Audit behauptet ausdrücklich **nicht**, der Optimizer setze die
Liquiditätsrendite ebenfalls auf null. Der stochastische Optimizer übernimmt
Return und Volatilität aus der CMA. Nur die deterministische und die
Reporting-Monte-Carlo-Projektion nullen den Liquiditätsbucket und addieren den
positionsbezogenen Zinsertrag als Cashflow. Diese Dualität ist im
`model_basis` sichtbar; offen ist ihre instrument- und principalrichtige
Reconciliation.

Das verpflichtende Ziel ist genau eine ökonomische Wirkung je
Returnkomponente. Eine gemeinsame instrumentbezogene Basis ist der einfachste
Weg. Bleiben CMA-Decision und positionsbezogenes Reporting für verschiedene
Zwecke getrennt, ist stattdessen eine persistierte quantitative Bridge mit
identischem Principal, Zeitraum, Einheiten und Residualtoleranz Pflicht. Die
heutige Dualität selbst ist keine zu erhaltende Kontrolle; zu erhalten ist nur
die explizite, wahrheitsgemäße Offenlegung der tatsächlich verwendeten Basis.

Der Audit behauptet weder einen Cross-Tenant-Datenabfluss noch einen stillen
1:1-FX-Fallback im kanonischen Enginepfad. Clientzugriffe sind gescopt und
fehlende Modell-FX-Raten werden dort fail-closed behandelt.

Alle Release-Sperren in diesem Dokument sind Governance-Akzeptanzkriterien.
Sie beschreiben keine bereits durchgängig implementierte technische Sperre.

## Kurzurteil

Der aktuelle Stand darf **nicht** als konsistentes Modell für gesperrte
Einlagen, Kassenobligationen, Geldmarktfonds, reservefähige Liquidität oder
instrumentbezogene Zinserträge freigegeben werden.

Bestätigt sind vier neue P1-Verträge:

1. `liquidity_instrument`, `liquidity_interest_rate_bps` und
   `liquidity_available_from` sind API-/ORM-seitig freie Felder. Ein unbekanntes
   Instrument, `999999` Basispunkte und `not-a-date` werden akzeptiert. Das
   historische statische SQLite-Schema besitzt dagegen Enum-CHECKs, die
   Alembic-Baseline nicht. Zugleich werden alle fünf UI-Instrumente und ein
   unbekanntes Instrument als 100
   Prozent Liquiditätsbucket klassifiziert. Reportingprojektionen behandeln
   sie mit null Return/null Volatilität plus einfachem jährlichem Zins auf dem
   heutigen Principal; der Optimizer verwendet dagegen generischen
   CMA-Total-Return/-Volatilität. Laufzeit, Notice, Coupon/NAV, Credit-/Duration-
   Risiko, Accrual, Payout und Principal Release fehlen.
2. `Liquidität` darf als `Verbindlichkeit` gespeichert werden. Ihr Principal
   wird als Liability abgezogen, ein positiver Zinssatz erzeugt für denselben
   Datensatz trotzdem `Income`.
3. Ein unveränderter Classic-UI-Edit überschreibt bei externer Liquidität das
   gespeicherte Assignment `Anderes Vermögen` mit `Beratungsvermögen` und
   persistiert die Umklassifikation. Der Principal wechselt dadurch ohne
   Benutzerentscheid in den Advisory-/Optimizer-Scope. Engine-lesbare
   Legacytypen öffnen zugleich leer oder ohne gültige Kategorie.
4. Engine und Cashflow-Summary rechnen derived Kontozins ein, während
   Advisory-Report und Server-PDF keine derived Rows in ihre sichtbaren
   Cashflowlisten übernehmen. Der PDF-Pfad ergänzt zwar persistierte
   WealthInflows, aber keinen berechneten Kontozins. Der Derived-Endpoint
   liefert `origin_assignment` zwar im rohen Runtime-Dict, besitzt dafür aber
   kein Response-Schema. Der TypeScript-Vertrag lässt das Feld weg und React
   zeigt den Vermögenstopf nicht. Ein Ergebnis kann damit durch CHF 5.000 Zins
   verbessert werden, ohne diesen Treiber in der Kunden-Cashflowliste
   auszuweisen.

Zusätzlich wurden zwei Erweiterungsgruppen über drei bereits bekannte P1-IDs
im Liquiditätsfall bestätigt und um neue Evidence erweitert:

5. Die API-Antwort verliert `liquidity_available_from`. Die Classic UI lädt
   deshalb ein leeres Datum und sendet es beim nächsten Voll-Edit als `null`
   zurück; zugleich sendet sie für jede Position
   `is_available_for_goal_funding=false`. Instrument, Availability und
   Funding-Methode fehlen außerdem im aktuellen v4-Inputhash, weil dessen
   interner `_pos_v2`-Positionsencoder sie nicht bindet. Ein bis 2099
   gesperrtes Festgeld steht ab heute vollständig im
   Beratungsvermögen, erzeugt ab `valuation_date` Zins und kann als externe
   Position sofort den `unlocked_other_assets_rappen`-Pool erhöhen. Der
   gespeicherte `goal_funding_method` hat keinen fachlichen Consumer.
6. Ein manueller Zinsertrag und der aus derselben Position abgeleitete
   Zinsertrag werden gemeinsam addiert; die Oberfläche warnt nur.

Der isolierte Bestands-Gate mit 471/471 bestandenen Tests widerspricht diesen
Befunden nicht. Mehrere Tests pinnen ausdrücklich den Dual-Model-Vertrag, den
Null-Return-Reportingbucket und die warning-only-Duplikatbehandlung.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `LIQUIDITY-INSTRUMENT-MODEL-001` | P1 | neu bestätigt | Instrument, Rate und Availability besitzen keine geschlossene, dialektgleiche Domain; Sichtkonto, Festgeld, Kassenobligation und Geldmarktfonds werden instrumentagnostisch modelliert und CMA-Decision/positionsbezogene Reportingbasis sind nicht principal-/termbezogen reconciliert. |
| `LIQUIDITY-LIABILITY-001` | P1 | neu bestätigt | Eine als Liability verbuchte Liquiditätsposition kann aus demselben positiven Satz Income erzeugen. |
| `LIQUIDITY-CLASSIC-EDIT-001` | P1 | neu bestätigt | Ein No-op-Edit überschreibt externe Liquidität zu Advisory Wealth; unterstützte Legacytypen sind im Classic-Editor nicht verlustfrei wartbar. |
| `LIQUIDITY-PUBLICATION-001` | P1 | neu bestätigt | Berechneter derived Zins fehlt in Advisory-/PDF-Cashflowlisten; der rohe Endpoint liefert den Quelltopf, bindet ihn aber nicht an ein Response-Schema, und TypeScript/React lassen ihn weg. |
| `PENSION-AVAILABILITY-001` / `PROPERTY-COLLATERAL-001` | P1 | Liquiditätserweiterung bestätigt | Response, Classic-UI-Vollupdate und Drift-Hash verlieren wirksame Terms; gesperrtes Kapital kann ohne periodischen Availability-/Haircut-/Methodenvertrag sofort investierbar, reserve- oder goalwirksam werden. |
| `PROPERTY-FLOW-DUPLICATION-001` | P1 | Liquiditätserweiterung bestätigt | Manueller und derived Kontozins wirken gemeinsam; warning-only ist keine Reconciliation. |

## Positivkontrollen, die erhalten bleiben müssen

Die Reparatur darf folgende bestehende Kontrollen nicht zurückbauen:

1. `position_type` und die drei allgemeinen Assignments besitzen im Create-
   Vertrag eine geschlossene Grundvokabel.
2. `current_value_rappen` ist nichtnegativ und großzügig, aber endlich
   begrenzt; Verbindlichkeitsvorzeichen läuft über das Assignment.
3. Ein negativer Liquiditätszins wird im Derived-Happy-Path als `Expense`
   statt als verschwundener negativer Income-Betrag erzeugt.
4. Derived Flows tragen `source`, `origin_position_id`,
   `origin_position_type` und `origin_assignment` und sind nicht direkt
   persistierte, editierbare Cashflowzeilen.
5. Die Reportingprojektion setzt die generische Cashrendite auf null und
   verhindert dadurch Phantomwachstum eines echten 0-Prozent-Kontos, solange
   der explizite Zinscashflow korrekt und genau einmal wirkt.
6. Der Optimizer deklariert derzeit `cma_total_return`, das Reporting
   `zero_bucket_plus_position_interest_cashflow`. Bis zur Modellmigration darf
   diese Offenlegung nicht entfernt oder beschönigt werden. Der Zielvertrag
   darf die Basen vereinheitlichen oder explizit reconciliieren; die Tests des
   alten Dual-Modells sind dann bewusst zu ersetzen.
7. Aktive Positionen werden clientgescopt geladen; inaktive und soft-gelöschte
   Positionen werden im kanonischen Enginepfad ausgeschlossen.
8. Fremdwährungspositionen benötigen im Modellpfad eine explizite positive
   FX-Quelle; eine stille 1:1-Konvertierung ist dort nicht zulässig.
9. Der aktuelle v4-Inputhash verwendet intern den `_pos_v2`-Positionsencoder.
   Dieser bindet bereits Betrag, Assignment, Positionstyp, Currency,
   Bewertungsdatum, Liquiditätsrate und Funding-Boolean. Die fehlenden Terms
   werden additiv ergänzt.
10. Response und UI transportieren Instrument und Rate bereits; der Fix darf
    sie nicht durch ein verkürztes DTO verlieren.
11. Nach erfolgreichem Classic-Speichern ruft die UI bereits
    `markStrategyDirty(...)` auf. Der Fix muss diese Warnung erhalten und um
    serverseitige Drift-/Stale-Enforcement ergänzen.
12. Die Classic-Cashflow-UI konsumiert das rohe Derived-Dict bereits und zeigt
    `origin_assignment` als Vermögenstopf-Tag/Tooltip. Diese funktionierende
    Provenienz darf bei Einführung des Response-Schemas nicht verloren gehen.

## Tatsächlicher Liquiditäts-Datenfluss

1. Classic UI oder API erzeugt eine `WealthPosition` vom Typ `Liquidität`.
2. Pydantic prüft nur den allgemeinen Positionstyp, das allgemeine Assignment
   und den Principal. Instrument, Rate und Availability bleiben frei.
3. Die ORM speichert alle Liquiditätsfelder als String/Integer ohne
   instrumentbezogene Relation oder Laufzeitmodell.
4. `_validate_active_wealth_position_semantics()` prüft Positionstyp und
   Assignment, besitzt aber keine Liquiditätsmatrix. Nur Direktimmobilie und
   Hypothek haben spezielle Assignmentregeln.
5. `_summarize_positions()` zählt jede Advisory-Position sofort mit vollem
   Principal. `_default_weights_for_position()` ordnet jede Liquiditätsposition
   zu 100 Prozent dem Liquiditätsbucket zu.
6. `derive_wealth_cashflows()` berechnet `abs(current_value) * rate / 10000`
   jährlich. `valid_from` stammt aus `valuation_date`, nicht aus
   `liquidity_available_from`.
7. Manuelle und derived Cashflows werden gemeinsam an die Timeline übergeben;
   es gibt keine Source-Key-Reconciliation.
8. Für die Optimizer-Serie wird derived Advisory-Zins entfernt, weil der
   Optimizer Liquiditätsrendite aus der CMA erhält. Externer Zins bleibt ein
   Funding-Cashflow.
9. Deterministische und Reporting-MC-Pfade erhalten den vollen
   positionsbezogenen Zinscashflow; ihr Liquiditätsbucket hat null Return und
   null Volatilität.
10. `is_available_for_goal_funding=1` und Assignment `Anderes Vermögen`
    erhöhen den externen Unlock-Pool sofort eins zu eins. Datum und Methode
    wirken nicht.
11. Der Total-Goal-Pfad baut seine externe Funding-Serie aus allen externen
    Bruttoaktiven auf und besitzt ebenfalls keinen positionsbezogenen
    Availability-/Methodenresolver.
12. `WealthPositionResponse` entfernt Availability. Die Classic UI baut bei
    jedem Edit einen vollständigen Payload neu und überschreibt das Datum mit
    `null` sowie das Funding-Boolean mit `false`.
13. Beim Öffnen setzt die Classic UI zunächst das gespeicherte Assignment und
    überschreibt es anschließend über `showAwFields()` für jede Liquidität mit
    `Beratungsvermögen`. Der PUT persistiert diesen neuen Scope.
14. Der aktuelle v4-Inputhash verwendet den internen `_pos_v2`-
    Positionsencoder. Er bindet Rate und Boolean, aber nicht Instrument,
    Availability oder Methode.
15. Cashflow-Summary und Engine addieren derived Zins. Advisory-Report und
    Server-PDF übernehmen ihn dagegen nicht in ihre sichtbaren Listen; der
    PDF-Pfad ergänzt nur andere persistierte WealthInflows. Der rohe Derived-
    Endpoint liefert `origin_assignment`, bindet es aber nicht an ein
    Response-Schema. Der TypeScript-Vertrag deklariert das Feld nicht; die
    React-Tabelle zeigt es nicht.

Damit existieren mindestens vier Bedeutungen: aktueller Principal,
optimizerische CMA-Liquidität, positionsbezogener Reportingzins und externe
Funding-/Reservefähigkeit. Ein gemeinsamer materialisierter
Liquidity-Instrument-Snapshot existiert nicht.

## Codeanker auf dem auditierten Head

| Vertrag | Codeanker |
|---|---|
| Create-/Update-Freifelder | `5eyes-backend/schemas/wealth.py:12-170` |
| Response ohne Availability | `5eyes-backend/schemas/wealth.py:173-229` |
| Persistierte Liquiditätsfelder | `5eyes-backend/models/wealth.py:51-55` |
| Allgemeine Semantik ohne Liquiditätsmatrix | `5eyes-backend/services/wealth_position_semantics.py:15-52,108-117,160-191` |
| Statischer SQLite-CHECK | `5eyes-backend/5eyes_schema_v4.0_FINAL.sql:585-592` |
| Alembic-Baseline ohne CHECK | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:697-701` |
| Instrumentagnostische Bucket-Zuordnung | `5eyes-backend/services/portfolio_engine.py:592-624` |
| Advisory-/Liability-/Unlock-Aggregation | `5eyes-backend/services/portfolio_engine.py:1874-1915` |
| Derived Liquiditätszins | `5eyes-backend/services/wealth_cashflows.py:71-77,285-350` |
| Advisory-Zins aus Solver-Cashflow entfernt | `5eyes-backend/services/portfolio_engine.py:2018-2050,5771-5798` |
| Optimizer erhält Solver-Serie | `5eyes-backend/services/portfolio_engine.py:3333-3358` |
| Reporting/MC erhält volle Serie | `5eyes-backend/services/portfolio_engine.py:3664-3717` |
| Deterministik/MC nullen Reportingbucket | `5eyes-backend/services/portfolio_engine_mc_simulation.py:522-528,1179-1184` |
| Optimizer verwendet CMA-Momente | `5eyes-backend/services/optimizer/scenario_engine.py:606-625` |
| Deklarierte Optimization-/Reportingbasis | `5eyes-backend/services/portfolio_engine.py:2650-2671,2740-2751` |
| Externe Total-Goal-Serie | `5eyes-backend/services/portfolio_engine.py:3117-3127` |
| `_pos_v2`-Positionsencoder und aktueller v4-Inputhash | `5eyes-backend/services/portfolio_engine.py:2332-2379,2501-2504,3758-3787` |
| Report-Rebuild des Unlock-Pools | `5eyes-backend/services/advisory_report.py:3161-3205` |
| Classic-UI-Instrumente und Availability | `5eyes-electron/frontend/5eyes_v2.html:4811-4833` |
| Classic-UI-Edit liest fehlendes Feld | `5eyes-electron/frontend/5eyes_v2.html:17008-17036` |
| Classic-UI überschreibt Assignment beim Öffnen | `5eyes-electron/frontend/5eyes_v2.html:9985-10010,17008-17075` |
| Classic-UI-Vollpayload | `5eyes-electron/frontend/5eyes_v2.html:23372-23412,23462-23484` |
| Untypisierter Derived-Endpoint | `5eyes-backend/routers/clients.py:336-357` |
| Classic zeigt Derived-Quelltopf | `5eyes-electron/frontend/5eyes_v2.html:23127-23144` |
| React-Derived-Typ/-Tabelle ohne Quelltopf | `5eyes-electron/frontend/reporting/src/api/types.ts:1106-1125`; `5eyes-electron/frontend/reporting/src/sections/cashflow/CashflowEditor.tsx:173-205` |
| Advisory-Cashflowliste nur aus persistierten Rows | `5eyes-backend/services/advisory_report.py:623-701` |
| Server-PDF-Cashflowevents nur aus persistierten Rows | `5eyes-backend/routers/pdf_reports.py:584-630` |
| Warning-only-Duplikat | `5eyes-electron/frontend/5eyes_v2.html:23052-23080` |
| Tests des Dual-Model-Vertrags | `5eyes-backend/tests/test_engine_cashflow_consistency.py:80-154`; `5eyes-backend/tests/test_optimizer_production_contract.py:648-680` |
| Tests des Null-Reportingbuckets | `5eyes-backend/tests/test_liquidity_flat_in_projection.py:1-89`; `5eyes-backend/tests/test_liquidity_zero_engine_lock.py:1-41` |

## `LIQUIDITY-INSTRUMENT-MODEL-001` – Freie Terms erzeugen verschiedene Datenwahrheiten

### Beobachtung

`liquidity_instrument`, `liquidity_interest_rate_bps` und
`liquidity_available_from` sind in Create und Update optionale freie Felder.
Es gibt weder Enum-/Literalbindung noch Rategrenze noch ISO-Datumsparser.
Die ORM wiederholt genau diesen freien Vertrag.

Das historische statische SQLite-Schema beschränkt Instrument und
Funding-Methode per CHECK. Die Alembic-Baseline – maßgeblich für andere
Bootstrap-/PostgreSQL-Pfade – enthält nur freie Strings. Dieselbe Payload kann
damit abhängig vom Aufbauweg akzeptiert oder abgewiesen werden.

### Isolierte Reproduktion

Der unveränderte Pydantic-Vertrag akzeptierte:

```text
assignment=Verbindlichkeit
liquidity_instrument=teleport
liquidity_interest_rate_bps=999999
liquidity_available_from=not-a-date
```

Keiner dieser Liquiditätswerte löste eine Schema-Validierung aus.

### Wirkung

Ein Tippfehler oder Import kann unbekannte Instrumente, ökonomisch absurde
Zinsen und unparsebare Availability speichern. Raw rows und unterschiedliche
DB-Bootstraps besitzen anschließend verschiedene Fachdomänen. Die Engine
interpretiert das unbekannte Instrument trotzdem als Liquiditätsbucket und
compoundiert beziehungsweise summiert Folgeeffekte, statt fail-closed zu
blockieren.

### Fixvertrag

1. Ein kanonisches Enum trennt mindestens `SIGHT_DEPOSIT`,
   `SAVINGS_NOTICE`, `TERM_DEPOSIT`, `FIXED_INCOME_SECURITY` und
   `MONEY_MARKET_FUND`. Ein Overdraft/Loan ist kein Liquiditätsasset.
2. Rate ist strict integer in einer fachlich freigegebenen, instrumentbezogenen
   Domain. Negative Sätze bleiben zulässig, extreme Werte benötigen einen
   evidencegebundenen Override oder werden abgewiesen.
3. Availability, Maturity, Notice und Valuation sind echte Datums-/Zeitfelder
   mit eindeutiger Zeitzonen- und Boundarysemantik, keine freien Strings.
4. API, ORM, Alembic, SQLite-Bootstrap, PostgreSQL und Import erzwingen
   dieselbe Domain. HTML-Auswahllisten sind Komfort, keine Sicherheitsgrenze.
5. Raw-row-/Replay-Gates validieren Bestandsdaten erneut. Ungültig oder
   unbekannt bedeutet `blocked/incomplete`, niemals sofort verfügbar.
6. Die Migration inventarisiert erst, normalisiert deterministisch und fügt
   Constraints erst nach Quarantäne unauflösbarer Zeilen hinzu.

### Pflichttests

- Create, PATCH/PUT, Import und Raw row für jedes Enum sowie unknown/null,
- Rategrenzen, negative Rate, Bool, Float, numerischer String und Extremwert,
- ISO-Datum, Leap Day, malformed, Future, Past und exakte Boundary,
- SQLite-Bootstrap und Alembic/PostgreSQL mit identischen Accept/Reject-Fällen,
- Legacyalias-Migration und Quarantäne ohne stilles Mapping.

## Vertiefung zu `LIQUIDITY-INSTRUMENT-MODEL-001` – Fünf Instrumente werden zu einem Modell

### Beobachtung

Die Classic UI bietet Kontoguthaben, Sparkonto, Festgeld,
Kassenobligation und Geldmarktfonds. `_default_weights_for_position()` ordnet
jedes davon und auch einen unbekannten Wert zu 100 Prozent dem
Liquiditätsbucket zu.

In Deterministik und Reporting-MC hat dieser Bucket null Return und null
Volatilität. Ein gesetzter Positionssatz erzeugt stattdessen jedes Jahr den
gleichen nominalen Cashflow aus heutigem Principal mal Rate. Availability,
Maturity, Ratewechsel, Day Count, Compounding, Accrual/Payout,
Wiederanlage, Kündigungsfrist, Credit-/Duration-/NAV-Risiko und Gebühren
beeinflussen diesen Flow nicht.

Der Optimizer verwendet ausdrücklich den generischen CMA-Total-Return und die
CMA-Volatilität des Ziel-Liquiditätsbuckets. Der positionsbezogene Advisory-
Zins wird deshalb nur aus seiner Solver-Cashflowserie entfernt. Das ist ein
deklarierter Dual-Model-Vertrag, aber ohne quantitative Brücke zwischen:

- heutigem positionsbezogenem Principal und Satz,
- künftigem SOLL-Liquiditätsgewicht,
- Laufzeit/Lockup des konkreten Instruments,
- CMA-Return/Volatilität,
- und der später publizierten positionsbezogenen Cashflowserie.

### Isolierte Reproduktionen

Die Bucketfunktion lieferte für alle sechs Werte exakt denselben Mix:

```text
Kontoguthaben     -> liquidity=10000 bps
Sparkonto         -> liquidity=10000 bps
Festgeld          -> liquidity=10000 bps
Kassenobligation  -> liquidity=10000 bps
Geldmarktfonds    -> liquidity=10000 bps
teleport          -> liquidity=10000 bps
```

Ein CHF-100.000-Festgeld mit 1 Prozent und Availability 2099 erhöhte das
Advisory Wealth sofort um `10000000` Rappen. Die Reportingserie erhöhte sich
ab heute um `100000` Rappen pro Jahr. Die Optimizer-Cashflowserie erhöhte sich
um `0`, weil dort die CMA-Liquiditätsrendite wirken soll. Das bedeutet nicht,
der Optimizer verwende null Yield; es belegt die nicht instrumentgebundene
Dualität.

### Wirkung

Ein kündbares Sichtkonto, ein gesperrtes Festgeld, eine kreditrisikobehaftete
Kassenobligation und ein NAV-basiertes Geldmarktfondsinvestment erhalten
dieselben Risikoeigenschaften und denselben Availability-Vertrag. Optimierung,
Zielwahrscheinlichkeit und Kundenprojektion können dadurch verschiedene
ökonomische Instrumente oder verschiedene Principals beschreiben, obwohl sie
unter einem gemeinsamen Namen erscheinen.

### Fixvertrag

1. Jede Instrumentklasse erhält ein explizites Modell:
   - Sichtkonto: sofort verfügbar, variable Rate, gegebenenfalls Staffel/
     Negativzins und Counterparty-Coverage;
   - Sparkonto/Notice: Kündigungsfrist, Limiten und variable Rate;
   - Festgeld: Start, Maturity, fixed/variable rate, Accrual, Payout und
     Principal Release;
   - Kassenobligation: Coupon/Zero-Coupon, Maturity, Credit, Duration,
     Marktwert und Reinvestment;
   - Geldmarktfonds: NAV-/Total-Return, Gebühren, Volatilität, Settlement und
     keine zusätzliche Kontozinsableitung.
2. Der Snapshot materialisiert periodisch mindestens Principal, Accrual,
   Cash-Payout, Available Funding und Risk Exposure.
3. Es gilt genau ein expliziter Yield-Modus je Komponente. CMA-Total-Return und
   positionsbezogener Zins dürfen nicht denselben Return doppelt oder gar nicht
   abbilden.
4. Falls Decision und Reporting bewusst verschiedene Zwecke behalten, liefert
   der Run eine quantitative Reconciliation: Basis-ID, Principal, Zeitraum,
   ersetzter Zins, CMA-Komponente und Residual.
5. Current-Instrumente und SOLL-Liquiditätsquote werden getrennt ausgewiesen.
   Ein heutiger Positionszins darf nicht unverändert auf einen künftig
   umallokierten Principal angewandt werden.
6. Instrumentmodell, Annahmequelle, `as_of`, Version und Coverage werden an TA,
   OptimizerRun und Publikation gebunden.

### Pflichttests

- instrumentweise Golden-Schedules für Principal, Accrual, Payout und Release,
- Festgeld vor/an/nach Maturity sowie vorzeitige Auflösung,
- Geldmarktfonds mit NAV-Return, Volatilität und Gebühren ohne Extra-Zinsflow,
- Kassenobligation mit Duration/Credit/Maturity und Marktwertänderung,
- Current-Liquidität ungleich SOLL-Liquidität,
- CMA-Return ungleich Positionsrate mit vollständiger Reconciliation,
- Optimizer, Deterministik, MC, Goal und Publication auf denselben Snapshot-
  und Serienhashs.

## `LIQUIDITY-LIABILITY-001` – Eine Liability erzeugt Zinsertrag

### Beobachtung

Der allgemeine Create-Vertrag und die UI erlauben `Liquidität` mit Assignment
`Verbindlichkeit`. Die Semantik erzwingt nur für Direktimmobilien und
Hypotheken spezielle Assignments. `_load_allocation_inputs()` zieht den
Principal deshalb als Liability ab.

`derive_wealth_cashflows()` entscheidet dagegen nur nach `position_type` und
Satz. Bei positiver Rate entsteht `Income`, unabhängig vom Liability-
Assignment.

### Isolierte Reproduktion

```text
position_type=Liquidität
assignment=Verbindlichkeit
current_value_rappen=10000000
liquidity_interest_rate_bps=100

balance treatment: Liability
derived flow: Income 100000 rappen
```

Der Flow startete aus `valuation_date=2026-01-01`; ein zugleich gesetztes
`liquidity_available_from=2099-12-31` änderte ihn nicht.

### Wirkung

Ein Kontokorrentkredit oder Overdraft reduziert Nettovermögen und verbessert
gleichzeitig den jährlichen Cashflow. Reserve, Ziele und Projektion können
dadurch zu günstig erscheinen. Ein negativer Zinssatz würde umgekehrt als
Expense eines Liquiditätsassets behandelt, obwohl der Datensatz bereits eine
Liability ist. Die Signumsemantik ist nicht geschlossen.

### Fixvertrag

1. Eine Asset-Liquiditätsposition darf nicht `Verbindlichkeit` sein.
2. Overdraft, Kredit und sonstige Liability erhalten einen eigenen Typ mit
   Principal-, Zinskosten-, Limit-, Laufzeit- und Signumvertrag.
3. API, UI, Import, Raw-row-Gate und DB-CHECK verwenden dieselbe
   Positionstyp-/Assignmentmatrix.
4. Derived Flow wird aus dem kanonischen Instrument-/Liabilitytyp erzeugt,
   nicht aus Label, freiem Assignment oder Ratevorzeichen.
5. Legacyzeilen werden nicht still umbenannt. Eindeutige Fälle werden
   migriert, mehrdeutige quarantänisiert und reale Runs blockiert.
6. Publication zeigt Asset, Liability und Kosten getrennt. Der bestehende
   `LIABILITY-PUBLICATION-001`-Fixvertrag bleibt zusätzlich gültig.

### Pflichttests

- jede Positionstyp-/Assignmentkombination in API, UI und Raw row,
- positiver, null und negativer Satz für Asset und Liability,
- Principal-/Net-Worth-/Cashflow-Reconciliation,
- Legacy-Overdraft-Migration und mehrdeutige Quarantäne,
- Reserve, Optimizer, Deterministik, MC, Advisory API, React und PDF.

## `LIQUIDITY-CLASSIC-EDIT-001` – Ein No-op-Edit ändert den Vermögenstopf

### Beobachtung

Beim Öffnen einer bestehenden Position schreibt der Classic-Editor zunächst
das persistierte Assignment in das Auswahlfeld. Danach ruft er
`showAwFields(category)` auf. Diese reine Sichtbarkeitsfunktion ist jedoch
nicht rein: Für den internen UI-Key `Liquiditaet` setzt sie das Assignment
immer auf `Beratungsvermögen`.

Beim Speichern liest der vollständige PUT-Payload genau diesen mutierten
DOM-Wert und persistiert ihn. Eine extern gehaltene Liquiditätsposition mit
Assignment `Anderes Vermögen` wird daher ohne fachliche Benutzeränderung zu
Advisory Wealth. `_load_allocation_inputs()` verwendet das Assignment als
entscheidenden Scope und nimmt den Principal anschließend in
`advisory_wealth_rappen` und damit in den Optimizerpfad auf.

Der Enginevertrag akzeptiert außerdem die kanonisierten Legacywerte
`Liquiditaet`, `Bankkonto` und `Konto`. Nur der persistierte kanonische Wert
`Liquidität` durchläuft beim Öffnen die vollständige Liquiditäts-Hydration und
wird auf den UI-Key `Liquiditaet` gemappt. Der Legacywert `Liquiditaet` zeigt
zwar die Sektion, befüllt ihre Felder aber nicht; `Bankkonto` und `Konto`
zeigen gar keine Liquiditätssektion. Diese Bestandszeilen sind nicht
verlustfrei wartbar.

### Isolierte Frontend-Reproduktion

Die unveränderten Funktionen aus `5eyes_v2.html` wurden mit einem minimalen
Mock-DOM ausgeführt. Für eine gespeicherte externe Position ergab sich:

```text
stored_assignment=Anderes Vermögen
editor_assignment_after_open=Beratungsvermögen
```

Die drei vom Enginepfad unterstützten Legacywerte ergaben:

```text
legacy=Liquiditaet category=Liquiditaet label="" liquidity_section=block
legacy=Bankkonto    category=Bankkonto    label="" liquidity_section=none
legacy=Konto        category=Konto        label="" liquidity_section=none
```

Damit ist der Funktionsfehler im echten Frontend-JavaScript reproduziert.
Ein vollständiger Browser-/Electron-DOM-Lauf war nicht Bestandteil dieses
Audits und bleibt ein Pflichtgate.

### Wirkung

Ein scheinbar unveränderter Edit kann Eigentums-/Mandatsscope,
investierbares Startvermögen, Rebalancingbasis, Reserve und Zieldeckung
ändern. Dieselbe Position wird vor und nach dem UI-Roundtrip fachlich anders
behandelt, obwohl der Benutzer keinen Scopewechsel gewählt hat. Bei
Legacywerten droht zusätzlich ein leerer oder ungültiger Kategorie-Roundtrip.
Der erfolgreiche Savepfad ruft zwar `markStrategyDirty(...)` auf. Diese
clientseitige Warnung erfolgt aber erst nach der stillen Mutation und verhindert
weder den PUT noch serverseitig Rebuild oder Publikation. Die separate
Hashlücke für Instrument, Availability und Funding-Methode bleibt zusätzlich
bestehen, betrifft aber nicht das bereits gehashte Assignment selbst.

### Fixvertrag

1. Funktionen zur Feldsichtbarkeit dürfen keine fachlichen Werte setzen.
   Create-Defaults und Edit-Hydration werden vollständig getrennt.
2. Ein Default-Assignment darf nur beim Erzeugen einer neuen Position und nur
   vor einer expliziten Benutzerwahl wirken. Im Editmodus gewinnt immer der
   persistierte, validierte Wert.
3. Der Server erzwingt eine geschlossene Positionstyp-/Assignmentmatrix. Ein
   Scopewechsel benötigt einen expliziten Patch, Audit-Evidence und eine
   neue Snapshot-/Driftversion; ein impliziter UI-Default reicht nie.
4. Legacytypen werden vor UI-Nutzung deterministisch auf kanonische IDs
   migriert oder quarantänisiert. Die UI arbeitet mit stabilen IDs statt mit
   akzent- oder labelabhängigen Vergleichen.
5. Bis echte PATCH-Semantik vorhanden ist, muss ein Vollupdate jedes nicht
   bearbeitete Feld aus einer vollständigen Response exakt erhalten.
6. Die zentrale Invariante lautet: Öffnen und unverändert Speichern ist
   semantisch idempotent. Payload, Assignment, Principal-Scope und
   Snapshot-Hash bleiben identisch.
7. Ein echter Scopewechsel invalidiert abhängige TargetAllocations,
   OptimizerRuns, Reserve-/Goal-Evidence und Publikationen fail-closed.

### Pflichttests

- Browser-E2E für Create sowie No-op-Edit je gültigem Assignment,
- externe Liquidität bleibt nach Open/Save extern und außerhalb des
  Advisory-/Optimizer-Principals,
- expliziter Scopewechsel ändert Snapshot/Hash und macht abhängige Runs stale,
- `Liquidität`, `Liquiditaet`, `Bankkonto`, `Konto`, unbekannt und `null` mit
  Migrations-/Quarantäneerwartung,
- Label-/Locale-/Unicodevarianten ohne fachliche Verzweigung,
- Reload, Doppelsave, konkurrierender Edit und serverseitig abgewiesene
  ungültige Kombinationen,
- Classic UI, React, API und Raw-row-Replay auf denselben kanonischen IDs.

## `LIQUIDITY-PUBLICATION-001` – Publikation verschweigt einen Modelltreiber

### Beobachtung

`derive_wealth_cashflows()` erzeugt aus einer Liquiditätsposition einen
Zinsflow einschließlich `source`, `origin_position_id`,
`origin_position_type` und `origin_assignment`. Engine und
Cashflow-Summary rechnen diese derived Flows ein.

Der serverseitige Advisory-Report baut seine Cashflowliste dagegen aus
persistierten manuellen `Cashflow`-Rows auf. Das Server-PDF verwendet ebenfalls
diese Rows und ergänzt persistierte `WealthInflow`-Zeilen, aber keine derived
Zinsflows. Ein wirksamer derived Kontozins fehlt in beiden sichtbaren Listen
vollständig. Der
Endpoint `/cashflows-derived` besitzt zudem kein deklaratives Response-Modell;
der TypeScript-Typ lässt `origin_assignment` weg und die React-Tabelle zeigt
den Quelltopf nicht. Zwei gleich benannte Zinsflows aus Advisory- und externem
Vermögen sind damit im sichtbaren Kanal nicht zuverlässig unterscheidbar.
Die Classic-Cashflow-UI ist eine wichtige Positivkontrolle: Sie liest das rohe
Feld bereits und zeigt es als Pot-Tag/Tooltip. Der neue typisierte Vertrag muss
diese funktionierende Darstellung erhalten.

### Isolierte Backend-Reproduktion

Eine In-Memory-Datenbank mit ausschließlich einer Liquiditätsposition über
CHF 100.000 und 5 Prozent Zins, aber ohne manuellen Cashflow, lieferte:

```text
derived_count=1
derived_interest_rappen=500000
advisory_report_cashflows=[]
```

Der berechnete CHF-5.000-Zins existiert und kann Projektionen beeinflussen;
die sichtbare Advisory-Cashflowliste bleibt leer. Die temporäre Probe und ihre
isolierte Datenbank wurden anschließend entfernt.

### Wirkung

Eine Kundenprojektion kann besser ausfallen, ohne den dafür verantwortlichen
Zins in der zugehörigen Cashflowliste offenzulegen. Reviewer können Betrag,
Herkunft, Vermögenstopf und Exactly-once-Status nicht gegen die Modellserie
reconciliieren. Die Lücke verstärkt zugleich das bestehende
`PROPERTY-FLOW-DUPLICATION-001`: Ein manueller und ein derived Zins können
gemeinsam wirken, während die Publikation nur den manuellen Teil zeigt.

### Fixvertrag

1. Ein unveränderlicher `CashflowProjectionSnapshot` materialisiert manuelle,
   derived, ersetzte, verworfene und blockierte Komponenten genau einmal.
   Engine, Summary, Advisory JSON, React und PDF konsumieren dieselben Rows
   und Summen aus diesem Snapshot.
2. Das kanonische DTO enthält mindestens stabile Flow-/Source-IDs, Source-Art,
   Origin-Position, Origin-Instrument, Origin-Assignment/Vermögenstopf,
   Periode, Currency, Gross/Tax/Net, Override-/Duplicate-Status,
   Modellbasis und Snapshot-/Series-Hash.
3. Der Derived-Endpoint erhält ein striktes Response-Modell und generierte
   OpenAPI-/TypeScript-Typen. Ein Schema-/Ableitungsfehler wird als typisierter
   Fehler publiziert und nicht als leere Liste missverstanden.
4. Sichtbare Kundenkanäle kennzeichnen berechnete gegenüber manuell erfassten
   Flows und zeigen deren Quelle verständlich, ohne technische IDs zu
   verschleiern oder fachliche Provenienz zu verlieren.
5. Report und PDF dürfen keine eigene Live-Query nur auf manuellen Rows mehr
   ausführen. Rebuild bindet denselben Cashflow-Snapshot wie der Run und
   blockiert bei Drift, fehlender Provenienz oder unreconciled Duplicate.
6. Jeder manuelle oder derived Kandidat besitzt genau einen disjunkten Status:
   `accepted`, `replaced`, `suppressed_duplicate` oder `blocked`. Nur
   `accepted` trägt zur effektiven Serie bei. Sobald ein wirksamer Kandidat
   `blocked` ist, bleibt der gesamte Snapshot `blocked` und kann nicht
   publiziert, signiert oder übergeben werden.
7. Betragssemantik ist explizit: `gross_amount_rappen`, `tax_amount_rappen`
   und `fee_amount_rappen` sind nichtnegative Komponenten in der angegebenen
   Währung; `direction` ist `income` oder `expense`; `net_amount_rappen =
   gross - tax - fee` darf nicht negativ sein. Der effektive signierte Betrag
   ist `+net` für Income und `-net` für Expense. Die Periodensumme ist die
   Summe ausschließlich der `accepted`-Beträge.
8. `flow_id`/`source_id` sichern Provenienz einschließlich Source-Art,
   Position und Tranche. Ein davon getrennter kanonischer Economic-Duplicate-
   Key entscheidet über Manual-/Derived-Matches. Stable IDs und Ausgabeordnung
   werden aus kanonischen Geschäftsfeldern gebildet, niemals aus DB-Reihenfolge
   oder Renderzeit.

### Pflichttests

- nur eine Liquiditätsposition, keine manuelle Row: identischer CHF-5.000-
  Flow in Engine, Summary, Advisory JSON, Classic-Cashflow-UI, React,
  Kundenportal und jedem kundenwirksamen PDF,
- Advisory- und externe Position mit gleichem Label, aber eindeutigem
  Quelltopf und unterschiedlichem Solververtrag,
- manuell plus derived: Override-, Duplicate- und Blockzustände in allen
  Kanälen identisch,
- positive, null und negative Rate sowie Multi-Currency/FX-Provenienz,
- Response-Schema, OpenAPI und generierter TypeScript-Typ enthalten alle
  Provenienzfelder,
- Rebuild/Replay mit unverändertem Snapshot sowie Drift/Tamper mit Block,
- Frozen-/Signed-Artefakt und Handoff referenzieren denselben Snapshot,
- visuelle Classic-/React-/Portal-/PDF-Goldens einschließlich Source-, Basis-
  und as-of-Hinweis.

## Bestehende Availability-/Funding-P1 – API und UI verlieren wirksame Terms

### Beobachtung

`WealthPositionResponse` enthält Instrument, Rate, Funding-Boolean und
Funding-Methode, aber nicht `liquidity_available_from`. Die Classic UI liest
das fehlende Feld beim Öffnen des Editors als leeren String. Beim Speichern
baut sie einen vollständigen PUT-Payload und sendet den leeren Wert als
`null` zurück.

Unabhängig vom geladenen Datensatz setzt derselbe Payload
`is_available_for_goal_funding:false`. Ein per API, Import oder Seed gesetztes
Funding-Flag geht daher bei einer normalen UI-Bearbeitung verloren. Der Editor
besitzt auch kein Feld für `goal_funding_method`.

Der aktuelle v4-Inputhash bindet Positionen weiterhin über den internen
`_pos_v2`-Encoder. Dieser bindet zwar Rate und Funding-Boolean, lässt aber
Instrument, Availability und Methode aus. Eine fachlich wesentliche Änderung
kann deshalb denselben aktuellen Inputhash behalten.

### Isolierte Reproduktionen

1. Eine Response-Modellierung mit `liquidity_available_from=2099-12-31`
   enthielt das Feld im serialisierten Ergebnis nicht.
2. Folgende Änderungen erzeugten denselben aktuellen v4-Inputhash:

```text
Kontoguthaben, available 2026-01-01, method Verkauf
Geldmarktfonds, available 2099-12-31, method Ignorieren

hash_equal=true
```

### Wirkung

Ein reiner UI-Edit kann eine Sperre oder eine Fundingfreigabe unbemerkt
ändern. Gleichzeitig erkennt die Strategy-Drift fachlich relevante
Instrument-/Availability-/Methodenänderungen nicht zuverlässig. Eine alte
Allocation kann neben neuen Live-Terms weiter als passend erscheinen.

### Fixvertrag

1. Create, Update, Response, TypeScript und UI transportieren sämtliche
   effektiven Liquiditätsterms symmetrisch.
2. Der UI-Edit verwendet echten PATCH-Semantik oder lädt und erhält alle
   Felder. Nicht sichtbare Felder dürfen nicht mit Defaultwerten überschrieben
   werden.
3. `liquidity_available_from` und Funding-Methode erhalten sichtbare,
   verständliche Controls mit `unknown/incomplete` statt leer=sofort, sofern
   der Vertrag keine Sofortverfügbarkeit belegt.
4. Eine neue Snapshotversion bindet Instrument, Terms, Availability-Schedule,
   Funding-Methode, Ratequelle und alle materialisierten Serien.
5. Alte Hashversionen bleiben lesbar, sind aber für neue reale
   Finalisierung/Publikation nicht ausreichend.
6. Drift wird vor Rebuild, PDF, Signatur und Handoff serverseitig geprüft.

### Pflichttests

- POST→GET→PUT/PATCH→GET mit jedem Feld und explizitem `null`,
- Classic-UI-Edit eines per API angelegten Festgelds ohne Datenverlust,
- Funding true/false und jede Methode ohne Defaultüberschreibung,
- Hashänderung pro einzeln geändertem wirksamen Feld,
- Legacy-Hash als `incomplete/stale`, nicht current,
- Replay, Tamper, React-/PDF-Snapshot-ID und Browser-E2E.

## Bestehende P1-Erweiterung – Availability und Funding

### Beobachtung

Advisory-Positionen werden allein aufgrund des Assignments vollständig in
`advisory_wealth_rappen` aufgenommen. Das betrifft auch ein Festgeld, dessen
`liquidity_available_from` Jahrzehnte in der Zukunft liegt. Ein externer
Datensatz mit Funding-Boolean wird unabhängig von Datum, Instrument und
Methode vollständig in `unlocked_other_assets_rappen` aufgenommen.

`goal_funding_method` besitzt außerhalb Schema, Model und Beispieldaten keinen
fachlichen Consumer. `Verkauf`, `Belehnung`, `Ignorieren` und `Automatisch`
wirken daher im Enginepfad identisch. Der Total-Goal-Pfad verwendet außerdem
externe Bruttoaktiven ohne positionsbezogenen Availability-Resolver.

### Isolierte Reproduktionen

```text
Festgeld CHF 100000, available 2099-12-31, advisory:
  advisory_wealth_delta=10000000 rappen
  reporting_interest_delta=[100000,100000,100000]
  optimizer_interest_cashflow_delta=[0,0,0]

Festgeld CHF 200000, available 2099-12-31, external, funding=true:
  unlocked_other_assets_delta=20000000 rappen
```

Die Null-Differenz der Optimizer-Cashflowserie bedeutet nur, dass dort die
CMA-Yield-Basis verwendet wird; sie beweist keine korrekte Sperrfrist.

### Gemeinsamer Fixvertrag

1. Ein periodischer Liquiditäts-Resolver mit einer generischen
   Cross-Asset-Schnittstelle liefert getrennt:
   `total_principal`, `advised_principal`, `tradable_now`,
   `reserve_available[t]` und `goal_available[t]`.
2. Eligibility, Methode, Datum, Notice, Maturity, Kosten, Steuer, Haircut und
   realisierbarer Anteil bilden einen konsistenten Vertrag.
3. `goal_funding_method` steuert ausschließlich Goal Funding. Reservefähigkeit
   besitzt eine getrennte Policy und darf nicht implizit aus dieser Methode
   abgeleitet werden.
4. Die Methoden wirken deterministisch:

| Methode | `goal_available[t]` | Reservewirkung |
|---|---|---|
| `Ignorieren` | immer 0 | ausschließlich nach separater Reservepolicy |
| `Verkauf` / Redemption | erst ab Settlement; netto nach Kosten/Steuern/Penalty; Principal sinkt gleichzeitig | nur falls separat reservefähig |
| `Belehnung` | nur belegte Netto-Kreditproceeds nach LTV, Rang, Haircut, Kosten und Zinsvertrag; der Asset-Principal bleibt bestehen und eine Liability entsteht | nur falls separate Reservepolicy Kreditproceeds zulässt |
| `Automatisch` | persistierte Auswahl einer versionierten Fundingpolicy; keine Laufzeitheuristik | separat ausgewiesen |

5. Boolean-/Methodenkonflikte sind fail-closed: `false` plus eine wirksame
   Methode sowie `true` ohne auflösbare Methode/Policy werden inventarisiert
   und quarantänisiert. `Automatisch` darf erst nach persistierter
   Policyentscheidung zu einer konkreten Methode werden.
6. Gesperrter Advisory-Principal kann unter Verwaltung stehen, ist aber nicht
   automatisch ab Jahr null frei rebalancierbar. Der Optimizer erhält die
   nicht handelbare Sleeve als Constraint oder separaten Foundationpfad.
7. Reserve, Goal, Optimizer, Report-Rebuild und Publikation konsumieren
   dieselbe materialisierte Serie.
8. Diese Runde liefert Liquiditäts-Evidence für `PENSION-AVAILABILITY-001` und
   `PROPERTY-COLLATERAL-001`, schließt sie aber nicht. Ein späterer generischer
   Cross-Asset-Vertrag muss zusätzlich Vorsorgeauszahlung/Steuer und Property-
   LTV/Rang/Lien/Haircut abdecken; bis dahin bleiben beide Findings offen.

### Zusätzliche Pflichttests der Extension

- `available_from` vor, exakt an und nach jeder Perioden-/Settlementboundary,
- Boolean × Methode × Reservepolicy als vollständige Konfliktmatrix,
- `Ignorieren`, `Verkauf`, `Belehnung` und `Automatisch` mit expliziten
  Principal-/Liability-/Kosten-/Steuererwartungen,
- Advisory-Principal ungleich tradable/goal/reserve Principal,
- Generate, Rebuild, Goal, Reserve, Optimizer, Summary, alle
  Publikationskanäle, Signatur und Handoff auf identischen Serienhashs,
- SQLite/PostgreSQL-Migration von widersprüchlichen Legacywerten sowie
  concurrent Position-/Policyupdate mit Block statt Mixed Snapshot.

## Bestehende P1-Erweiterung – genau ein Zinsertrag

### Beobachtung und Reproduktion

Manuelle Cashflows und aus Positionen abgeleitete Zinserträge werden gemeinsam
in die Timeline gegeben. Bei einem manuellen CHF-1.000-Zinsertrag und einem
identischen derived CHF-1.000-Zinsertrag ergab die isolierte Serie:

```text
[200000, 200000, 200000] rappen
```

Die UI-Warnung verhindert die Summation nicht. Der Test
`test_frontend_cashflow_dupe_hint.py` verlangt ausdrücklich warning-only.

### Gemeinsamer Fixvertrag

Der bestehende `PROPERTY-FLOW-DUPLICATION-001`-Vertrag wird unverändert
wiederverwendet: stabiler Source-Key, explizite Derived-/Manual-Override-
Policy, reihenfolgeunabhängige Prüfung, Migration/Quarantäne und
kanalgleicher Reconciliation-Status. Für Liquidität lautet der Schlüssel
mindestens `position_id + interest_component + effective_period + currency`.

Pflichtfälle sind Manual-first und Derived-first, Update, Deaktivierung,
Import, Migration, Replay sowie zwei konkurrierende Duplicate-Kandidaten. Sie
laufen auf SQLite und echtem PostgreSQL und vergleichen Engine, Summary,
Classic UI, React, Portal, PDF, Frozen-/Signed-Artefakt und Handoff.

## Zielbild: getrennte Instrument-, Cashflow- und Run-Snapshots

### `LiquidityInstrumentModelSnapshot`

Ein Run besitzt genau einen Instrument-Snapshot mit geordneten
`LiquidityInstrumentPositionSnapshot`-Kindzeilen. Er ist allein Eigentümer
von Terms, Schedules und derived **Kandidaten**, nicht von manuellen Rows oder
deren Reconciliation. Pro Position enthält er mindestens:

- Snapshot-, Position-, Client-, Mandats- und gegebenenfalls Konto-ID,
- kanonischen Instrument- und Liabilitytyp sowie Assignment,
- `total`, `advised`, `tradable`, `reserve_eligible` und `goal_eligible` als
  getrennte Scopes,
- Principal, Currency, FX-Quelle/-Version/-as-of und Valuation-as-of,
- Contract start, effective from, Notice, Maturity und Settlement,
- Rateart fixed/variable/indexed, Referenzindex, Spread, Ratequelle/-as-of,
- Day Count, Compounding, Accrual, Payoutfrequenz und Reinvestment,
- Partial withdrawals, Limiten, Penalty/Kosten und Steuerbezug,
- Bewertungsmethode und Marktwert/NAV, falls relevant,
- Return-/Vol-/Correlation-Modell samt Quelle und Version,
- Counterparty-/Deposit-Coverage für Konten,
- Credit/Duration für Kassenobligationen,
- NAV-, Fee- und Settlementvertrag für Geldmarktfonds,
- `principal_series_rappen`, `accrued_interest_series_rappen`,
  `cash_payout_series_rappen`, `tradable_series_rappen`,
  `reserve_available_series_rappen`, `goal_available_series_rappen` und
  `risk_exposure_series_rappen`,
- geordnete derived Cashflowkandidaten mit stabiler Source-ID,
- Optimization-/Reporting-Basis-ID und quantitative Bridge,
- Datenquelle, Evidence, Autor, Freshness, Policyversion sowie Payload-,
  Terms- und Series-Hash.

### `CashflowProjectionSnapshot`

Dieser Run-Snapshot referenziert den Instrument-Snapshot-Hash und ist allein
Eigentümer des effektiven Cashflowledgers. Er enthält manuelle und derived
Kandidaten, disjunkten Status, Economic-Duplicate-Key, Override-Evidence,
Origin-Assignment/Vermögenstopf, native und Basiswährung, Gross/Tax/Fee/Net,
effektive signierte Beträge, kanonische Reihenfolge, periodische Serie und
Ledgerhash. Renderer erhalten keine parallele Live-Query.

### `AllocationRunInputManifest`

Ein Root-Manifest referenziert exakt einen Liquidity-Instrument-Snapshot und
einen Cashflow-Snapshot sowie die bereits erforderlichen CMA-, FX-, Tax-,
Goal-, Preference-, Code- und Konfigurationskomponenten. Der Root-Hash ist die
einzige Identität des vollständigen Run-Inputs.

### Lifecycle, Bindung und Hashvertrag

1. Alle drei Artefakte besitzen `draft`, `blocked` oder `final`. Nur `final`
   ist unveränderlich und darf Generate-Ergebnisse, Rebuild, Publikation,
   Signatur oder Handoff tragen. `blocked` enthält Fehlercodes/Evidence, aber
   keine freigabefähigen Zahlen.
2. Jede finale TargetAllocation, jeder Production-, Shadow- oder
   House-Matrix-OptimizerRun, jede Goal-/Reserve-Evidence sowie jedes Advisory-
   JSON, Classic-/React-/Portal-Artefakt, kundenwirksame PDF, Frozen-/Signed-
   Artefakt und Handoff besitzt einen nicht-null FK auf genau ein Root-
   Manifest. Mehrere Outputs desselben atomaren Runs dürfen dasselbe Manifest
   referenzieren; unterschiedliche Runs teilen nie eine mutable Instanz.
3. Generate liest Recordversionen, baut Draft-Snapshots und prüft dieselben
   Versionen unmittelbar vor atomarer Finalisierung erneut. Jede concurrent
   Änderung führt zu Conflict/Retry; es wird kein gemischtes Manifest final.
4. Kanonische Serialisierung ist UTF-8-JSON mit schemafixen Feldnamen,
   lexikographisch sortierten Object-Keys und fachlich definierter
   Arrayordnung über stabile IDs. Hash ist SHA-256 über Schema-/Policyversion
   und kanonischen Payload. Der Root-Hash bindet die geordneten
   Komponentenhashes; Renderzeit, Transportheader und Auditzeitstempel gehören
   nicht zum Businesshash.
5. Ein semantischer No-op darf einen separaten Auditlogeintrag erzeugen, aber
   weder Businesshash/Snapshotversion ändern noch abhängige Runs stale setzen.
   Jede echte fachliche Änderung erzeugt neue Komponenten- und Root-Hashes.
6. Historical replay liest ausschließlich das finale Manifest und seine
   Komponenten. Kein Renderer lädt Live-Positionen, aktuelle CMA/FX/Policy
   oder heutige Fundingmethoden nach.

## Claude-Implementierungsplan

### Phase 0 – Falsch-positive Nutzung stoppen

1. Vor realer Generate-/Rebuild-/PDF-/Signatur-/Handoff-Nutzung blockieren:
   unknown Instrument, malformed Datum, fehlende Pflichtterms, Asset als
   Liability, zukünftige Sperre ohne Resolver und unreconciled Duplicate.
2. `WealthPositionResponse` sofort um Availability ergänzen und den Classic-
   UI-Vollupdate so ändern, dass unsichtbare Felder nicht überschrieben werden.
   `showAwFields()` darf kein Assignment mehr mutieren; No-op-Edit bleibt
   semantisch idempotent.
3. Advisory-Report und PDF dürfen derived Modelltreiber nicht länger
   verschweigen. Bis ein gemeinsamer Cashflow-Snapshot existiert, muss eine
   fehlende kanalgleiche Reconciliation realen Output blockieren.
4. Bestehende Allocations nach Änderung wirksamer Liquiditätsterms als stale/
   incomplete markieren. Keine automatische Freigabe alter Hashversionen.

### Phase 1 – Geschlossene Domain und Legacy-Inventar

1. Vor Migration folgende Legacyklassen inventarisieren:

| Legacywert | Zielklasse | Fehlende Terms / Defaultpolitik |
|---|---|---|
| `Kontoguthaben` | `SIGHT_DEPOSIT` | sofort nur mit belegtem Vertrag; Ratequelle/Counterparty ergänzen |
| `Sparkonto` | `SAVINGS_NOTICE` | fehlende Notice/Limit = incomplete, nicht sofort |
| `Festgeld` | `TERM_DEPOSIT` | fehlende Start-/Maturity-/Payoutterms = incomplete |
| `Kassenobligation` | `FIXED_INCOME_SECURITY` | fehlende Coupon-/Maturity-/Creditterms = incomplete |
| `Geldmarktfonds` | `MONEY_MARKET_FUND` | NAV-/Fee-/Settlement-/Riskmodell erforderlich |
| `NULL` oder unbekannt | Quarantäne | keine stille Heuristik |
| Assignment `Verbindlichkeit` | Quarantäne oder explizite Liabilitymigration | nur mit belegtem Overdraft-/Loanvertrag |

2. Ungültige Daten, unmögliche Raten und widersprüchliche Fundingmethoden
   reporten; keine irreversible Massenkorrektur nach Label.
3. Erst nach Backfill/Quarantäne identische Pydantic-, ORM-, Alembic- und
   DB-Constraints aktivieren.
4. Downgrade-/Rollbackplan und Migrationsmetriken dokumentieren.

### Verbindliche Termmatrix vor Codeänderung

Die endgültigen Feldnamen dürfen technisch anders lauten; die folgende
Semantik ist jedoch Mindestvertrag. `required` bedeutet: fehlt der Wert oder
seine Evidence, bleibt der Snapshot `blocked`. `forbidden` bedeutet: ein
nicht-null Wert ist kein still ignoriertes Extra, sondern ein Domainfehler.

| Typ | Required | Optional/bedingt | Forbidden beziehungsweise getrennt |
|---|---|---|---|
| `SIGHT_DEPOSIT` | Principal, Currency, Valuation-as-of, Counterparty, Rate-Modus, Ratequelle/-as-of, Settlement | Staffel, Gebühren, Coverage | Maturity/Coupon/NAV-Return; Notice muss 0 sein |
| `SAVINGS_NOTICE` | zusätzlich Notice, Withdrawal-Limit/-Periode | variable Rate-Reset, Penalty | sofortige Vollverfügbarkeit ohne belegte Ausnahme |
| `TERM_DEPOSIT` | Contract-Start, Maturity, fixed/variable Ratevertrag, Day Count, Compounding, Accrual/Payout, Settlement | vorzeitige Redemption samt Penalty | MMF-NAV-/Vol-Modell; Release vor Settlement ohne Event |
| `FIXED_INCOME_SECURITY` | Security-/Issuer-ID, Marktwert und Valuation-as-of, Coupon/Yield, Maturity, Credit, Duration, Settlement | Call/Put, Accrued Interest | Behandlung als risikoloses Bankkonto oder zusätzlicher Kontozins auf Marktwert |
| `MONEY_MARKET_FUND` | Fund-/Share-Class-ID, NAV/-as-of, Total-Return-/Vol-/Correlationquelle, TER, Settlement | Ausschüttungsschedule | `liquidity_interest_rate_bps` als zusätzlicher Derived-Zins auf NAV |
| `OVERDRAFT` / `LOAN` | eigener Liabilitytyp, Principal/Limit, Sollzins, Ratequelle, Kosten, Laufzeit/Review, Currency | variable Rate-Reset, Sicherheiten | Asset-Assignment oder positiver Assetzinsertrag |

Assettypen erlauben nur `Beratungsvermögen` oder `Anderes Vermögen`;
Liabilitytypen nur `Verbindlichkeit`. `NULL`, unbekannte Typen oder
widersprüchliche Felder werden quarantänisiert.

Numerische Rate-, Notice-, Settlement-, Coverage- und Overridegrenzen gehören
in ein versioniertes, fachlich freigegebenes `LiquidityModelPolicy`-Artefakt.
Der Audit erfindet dafür keine unbelegte Marktschwelle. Ein Implementierungs-
PR darf aber nicht mit offenen Grenzen mergen: Die Policyfixture muss exakte
Min/Max-/Boundarywerte enthalten, und Tests prüfen `min-1/min/min+1` sowie
`max-1/max/max+1`. Ein Override benötigt Policy-ID, Antragsteller, Begründung,
Approver, Evidence, Gültigkeitsbereich und Ablaufzeit; fehlt eines davon, wird
er abgewiesen.

Variable Raten benötigen eine geordnete Resetserie mit Indexwert, Spread,
Fixing-as-of und Effective-from. Zwei Resets mit gleicher Effective-Time oder
eine Lücke ohne vertragliche Carry-Regel blockieren. Ein freies Feld oder der
jeweils aktuelle Marktwert darf historische Perioden nicht rückwirkend ändern.

### Verbindlicher Schedule-/Accounting-Vertrag

1. `valuation_as_of` ist der t0-Anker. Vertragliche Events werden auf
   Kalendertagebene erzeugt und erst danach in Engineperioden
   `[period_start, period_end)` aggregiert. Ein Event exakt auf
   `period_end` gehört zur nächsten Periode. Das Root-Manifest bindet
   `horizon_years`; daraus entstehen exakt `horizon + 1` Principalstände und
   `horizon` Flowintervalle. Date-only-Vertragsterms verwenden eine gebundene
   Contract-Timezone/Kalender-ID, technische Instants UTC.
2. Maturity allein setzt Principal nicht frei. Erst das gemäß expliziter
   Business-Day- und Settlementregel bestimmte Release-Event verschiebt ihn
   von locked zu tradable/goal/reserve. Fehlt eine erforderliche Kalender-
   oder Roll-Konvention, bleibt das Instrument `blocked`.
3. Day Count, Compounding, Capitalization, Payout und Reinvestment sind
   getrennt. Capitalized Interest erhöht Principal; Payout erzeugt Cashflow;
   Reinvestment erzeugt ein belegtes Transfer-Event. Dieselbe Komponente darf
   nie gleichzeitig Principal und Cash erhöhen.
4. Principal Conservation gilt pro Instrument und Periode:
   `opening + contributions + capitalized_interest - redemption - loss =
   closing`. Ein Release reduziert den gebundenen Principal und erhöht Cash/
   Funding exakt um Nettoerlös; Kosten, Steuer und Penalty bleiben eigene
   Komponenten.
5. Native-Currency-Ledger und Basiswährung werden beide gespeichert. Principal
   verwendet die zum Valuation-as-of gebundene FX-Quelle, Events die für ihren
   Effective-Zeitpunkt gebundene Quelle. Es wird mit Decimal statt Float
   gerechnet; Roundingmodus und Rundungszeitpunkt sind Policybestandteil und
   werden genau einmal beim Ledgerposting angewandt.
6. MMF-/Security-NAV-Return und stochastische CMA-/MC-Pfade bleiben
   Risikokomponenten. Nur vertragliche Ausschüttungen sind Cashflows. Ein
   erwarteter Total Return darf nicht zusätzlich als nominaler Zinsflow
   materialisiert werden.
7. Die quantitative Bridge publiziert je Periode und Currency mindestens
   `current_instrument_principal`, `target_liquidity_principal`,
   `position_accrual_or_nav_return`, `cma_total_return_component`,
   Transfer/Turnover, ausgewählte Modellkomponente und Delta. Für
   deterministische Ledgers ist der unerklärte Residual nach kanonischer
   Rundung exakt 0 Rappen; stochastische Kennzahlen verwenden eine explizite,
   versionierte numerische Toleranz.
8. Ein verpflichtendes Golden-Fixture hält CHF 100.000 Principal, 1 Prozent
   positionsbezogenen Jahreszins und 2 Prozent CMA-Total-Return konstant. Die
   Bridge weist 100.000 Rappen Positionskomponente, 200.000 Rappen CMA-
   Komponente und 100.000 Rappen Delta aus. Je nach gebundenem Current-/Target-
   Scope wirkt genau eine ausgewählte Komponente; 300.000 Rappen wären ein
   harter Double-count-Fehler. Ein separates Term-Deposit-Fixture prüft 5
   Prozent auf CHF 100.000: 500.000 Rappen Accrual/Payout gemäß Vertrag und
   10.000.000 Rappen Principal-Release erst am Settlement, nie davor.

### Phase 2 – Snapshot-Schema und kanonischer Schedule-Resolver

1. Zuerst werden Instrument-/Cashflow-Snapshot und Root-Manifest inklusive
   Lifecycle, FK-, Serialisierungs- und Hashvertrag migriert.
2. Eine reine, versionierte Funktion erzeugt aus validierten Instrumentterms alle
   Principal-/Accrual-/Payout-/Availability-/Riskserien.
3. Datumsboundary, Day Count, Ratewechsel, Maturity und Release werden nur
   dort berechnet.
4. Der Resolver ist unabhängig von UI-Labels und DB-Reihenfolge.
5. Invalid oder incomplete liefert einen typisierten Blockzustand, niemals
   still null oder sofort verfügbar.
6. Golden-Fixtures materialisieren zunächst Draft-/Blocked-Snapshots und erst
   nach Version-Recheck ein finales Instrument-Snapshot.

### Phase 3 – Cashflow-Reconciliation und Root-Manifest

1. Derived Kandidaten aus dem Instrument-Snapshot und manuelle Kandidaten
   werden deterministisch klassifiziert und in genau ein effektives Ledger
   reconciliiert.
2. Manual/derived Reconciliation schließt den bestehenden
   `PROPERTY-FLOW-DUPLICATION-001`-Vertrag für alle Zinskomponenten.
3. Das Root-Manifest bindet finale Instrument-/Cashflow-, CMA-, FX-, Tax-,
   Goal-, Preference-, Code- und Config-Hashes.
4. Ein atomarer Version-Recheck finalisiert alle drei Artefakte gemeinsam oder
   keines davon.

### Phase 4 – Consumer, Decision-/Reporting-Brücke und Kanäle

1. Optimizer, Deterministik, MC, Reserve und Goals konsumieren die
   materialisierten Serien und dasselbe Root-Manifest.
2. Der Optimizer erhält nicht handelbare Sleeves als Constraint, nicht als
   frei umallokierbaren Startcash.
3. Je Instrument ist Return genau einmal NAV/Total-Return, Accrual oder
   Cash-Payout. Unterschiedliche Decision-/Reportingbasen erhalten die
   persistierte quantitative Bridge.
4. Create/Update/Response/TypeScript/UI sind verlustfrei symmetrisch.
5. Advisory API, Classic Cashflow UI, React, Kundenportal und jedes
   kundenwirksame PDF zeigen Instrument, Availability, Fundingbasis,
   Yieldbasis, Cashflowquelle, Coverage, Snapshot-/Manifest-ID und as-of
   identisch.
6. Historical replay liest nur Snapshotdaten; keine Live-Position, Current-CMA
   oder heutige Fundingmethode darf einen alten Run verändern.

### Phase 5 – Dialekt-, Browser- und Releaseabnahme

1. SQLite und echtes PostgreSQL erhalten dieselben Domain-/Constrainttests.
2. Browser-E2E prüft Reload/Edit/Save, semantischen No-op,
   Availabilitygrenzen, Fundingmethoden und alle Cashflowkanäle.
3. Replay-/Tamper-Tests ändern jedes Feld und erwarten Drift oder Block.
4. Engine-/Summary-/JSON-/Classic-/React-/Portal-/PDF-/Signed-/Handoff-
   Goldens vergleichen Beträge, Reihenfolge, Root-/Serienhash, Manifest-ID und
   Modellbasis.
5. Concurrent Position-/Policy-/Manual-Flow-Update gegen Generate/Rebuild darf
   kein gemischtes Snapshotset publizieren.

## Invarianten für die Implementierung

1. `available_amount[t] <= principal[t]` für jede Position und Periode.
2. `tradable_now` ist nicht automatisch gleich `advised_principal`.
3. `goal_funding_method=Ignorieren` liefert null Goal Funding; Reservewirkung
   wird ausschließlich von der separaten, versionierten Reservepolicy bestimmt.
4. Ein Asset erzeugt keinen Liabilitykostenflow; eine Liability erzeugt keinen
   Assetzinsertrag.
5. Jede Yieldkomponente besitzt genau einen Ursprung und wirkt je Kanal genau
   einmal.
6. Änderung von Instrument, Rate, Ratequelle, Datum, Maturity, Notice,
   Fundingmethode oder einer materialisierten Serie ändert den Snapshot-Hash.
7. Ein API-/UI-Roundtrip ohne fachliche Änderung erzeugt dieselbe kanonische
   Businessrepräsentation und denselben Businesshash. Transport-, Updated-at-
   und Auditzeitstempel sind davon getrennt.
8. Eine Feldsichtbarkeitsfunktion mutiert niemals Assignment oder andere
   persistierte Fachwerte; ein No-op-Edit ist semantisch idempotent.
9. Jeder effektiv eingerechnete Cashflow besitzt eine sichtbare, kanalgleiche
   Provenienzzeile; kein Modelltreiber darf nur in der Berechnung existieren.
10. Optimizer und Reporting verwenden denselben Snapshot; unterschiedliche
   mathematische Basen besitzen eine persistierte Reconciliation.
11. Instrument-Snapshot, Cashflow-Snapshot und Root-Manifest besitzen klar
    getrennte Ownership; kein Feld hat zwei schreibende Sources of Truth.
12. Unknown, invalid, stale, incomplete oder ein `blocked`-Cashflowkandidat
    kann keinen grünen
   Compliance-/Readiness-Zustand erzeugen.
13. Rebuild, PDF, Signatur und Handoff dürfen keinen neueren Live-Zustand in
    einen historischen Run mischen.

## Nicht ausreichende Scheinfixes

Claude soll folgende punktuelle Änderungen ausdrücklich **nicht** als
Abschluss behandeln:

- nur `liquidity_available_from` zum Response hinzufügen,
- nur ein HTML-`min`/`max` an das Zinsfeld setzen,
- unbekannte Instrumente pauschal zu `Kontoguthaben` mappen,
- `available_from` gleichzeitig als Zinsbeginn, Maturity und Auszahlung
  verwenden,
- jedes Festgeld aus dem Gesamtvermögen entfernen statt nur seine
  Tradability/Fundingfähigkeit periodisch zu beschränken,
- CMA-Liquiditätsreturn zusätzlich zum positionsbezogenen Zinsertrag addieren,
- den positionsbezogenen Zinsertrag aus allen Kanälen entfernen, ohne externe
  Positionen und Bestandskonten zu modellieren,
- Geldmarktfonds wegen des Namens als risikoloses Bankkonto behandeln,
- Funding-Boolean in der UI immer auf false setzen,
- Assignment in einer Show/Hide-Funktion oder aus dem Positionstyp ableiten,
- nur den Derived-Endpoint anzeigen, während Advisory/PDF weiter ausschließlich
  manuelle Rows publizieren,
- `origin_assignment` nur im TypeScript-Typ ergänzen, ohne einen gemeinsamen
  Cashflow-Snapshot und kanalgleiche Summen,
- nur Tests umbenennen, ohne Migration, Snapshot und Kanalparität,
- oder den Governance-Hold als technisch erzwungen dokumentieren, bevor die
  serverseitigen Gates existieren.

## Acceptance-Checkliste

- [ ] Geschlossene instrumentbezogene API-/DB-Domain in SQLite und PostgreSQL
- [ ] Freigegebene `LiquidityModelPolicy` mit exakten Bounds/Overrides
- [ ] Strikte Positionstyp-/Assignmentmatrix einschließlich Liabilitytypen
- [ ] Verlustfreier API-/Classic-UI-/React-Roundtrip
- [ ] No-op-Edit je Assignment ist semantisch idempotent
- [ ] Periodische Principal-/Accrual-/Payout-/Tradable-/Funding-/Riskserien
- [ ] Festgeld-Maturity, Sparkonto-Notice, Kassenobligation und MMF fachlich getrennt
- [ ] Advisory Wealth, tradable start wealth und external funding getrennt
- [ ] Availability vor/an/nach Boundary in Generate, Rebuild und Report identisch
- [ ] Exactly-once-Zinsflow einschließlich Manual Override und disjunktem Status
- [ ] Jeder effektive derived Flow in Engine, Summary, Classic UI, Advisory
      JSON, React, Portal und jedem PDF sichtbar
- [ ] Cashflowquelle und Vermögenstopf kanalgleich nachvollziehbar
- [ ] CMA-/Position-Yield quantitativ reconciliert
- [ ] Hashsensitivität für jedes wirksame Feld und jede Serie
- [ ] Legacyinventar, deterministische Migration und Quarantäne
- [ ] Instrument-/Cashflow-Snapshot und Root-Manifest mit eindeutiger Ownership
- [ ] Nicht-null Manifest-FK an TA, jedem Run, Goal, Reserve, Publication,
      Signed Artifact und Handoff
- [ ] API, Classic UI, React, Portal und PDF zeigen identische IDs/Beträge/Basis
- [ ] Replay-/Tamper-/Stale-Gates fail-closed
- [ ] Concurrent Update/Generate publiziert keinen gemischten Zustand
- [ ] Echter Browser und echtes PostgreSQL abgenommen
- [ ] Produktweiter Regression-Gate grün
- [ ] Governance-Hold erst nach technischer Enforcement-Evidence aufgehoben

## Claude-/GPT-Startcheckliste

Vor Implementierung in dieser Reihenfolge arbeiten:

1. Diesen Audit vollständig lesen und die vier neuen IDs nicht mit den zwei
   Erweiterungsgruppen über drei bestehende P1-IDs vermischen.
2. Zuerst rote Contracttests für Domain, Liability, No-op-Edit, Publikation,
   Roundtrip, Hash und Availability schreiben.
3. Danach Legacyinventar und Migrationsentscheidung erzeugen; unbekannte Daten
   nicht automatisch raten.
4. API/ORM/Alembic/static SQL gemeinsam ändern, nicht einzeln.
5. Snapshot-/Manifest-Schema, Lifecycle, FKs, kanonische Serialisierung und
   Hashvertrag vor dem ersten Consumer implementieren.
6. Den Schedule-Resolver als reine Funktion implementieren und instrumentweise
   Golden-Schedules sichern.
7. Den bestehenden `PROPERTY-FLOW-DUPLICATION-001`-Fix wiederverwenden und
   den `CashflowProjectionSnapshot` materialisieren.
8. Den bestehenden Dual-Model-Vertrag bewusst entscheiden: instrumentbezogen
   vereinheitlichen oder vollständig reconciliieren; nicht versehentlich beide
   Yields addieren.
9. Erst danach `_load_allocation_inputs`, Rebuild, Reserve, Goal, Optimizer,
   Deterministik, MC, API/UI/Portal/PDF/Signatur/Handoff auf Root-Manifest und
   Snapshotserien umstellen; alte Live-Nachrechnungen entfernen.
10. SQLite-, PostgreSQL-, Browser-, Replay-, Tamper-, Concurrency- und
    Golden-Tests ausführen und Evidence im Folge-Handoff ablegen.

Empfohlene Code-Reihenfolge:

1. Policy-ADR/Fixture, `schemas/wealth.py` und Domain-Schemas,
2. Snapshot-/Manifest-Schemas und `models/wealth.py` plus Alembic-Migration,
   FK-Vertrag und Legacy-Report,
3. `services/wealth_position_semantics.py`,
4. neuer reiner `services/liquidity_instruments.py`-Resolver,
5. `services/wealth_cashflows.py`, Source-Reconciliation und
   `CashflowProjectionSnapshot`,
6. Root-Manifest-Finalisierung und danach `services/portfolio_engine.py` plus
   Reserve/Goal/Optimizer-Adapter,
7. `services/portfolio_engine_mc_simulation.py`,
8. Router/Response/TypeScript/Classic UI einschließlich No-op-Edit-Vertrag,
9. Advisory JSON, Classic Cashflow UI, React, Portal, alle PDFs und
   Frozen-/Signed-Artefakt,
10. serverseitige Finalisierungs-/Signatur-/Handoff-Gates.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

```text
branch: codex/asset-allocation-stochastic-core
HEAD:   0aec68a5b1069995f5106d7276a1375dad0b3605
tracked status: clean
```

`git status` meldete weiterhin nur Warnungen für historische,
ACL-geschützte `.pytest*`-Verzeichnisse. Sie wurden weder betreten noch
verändert. Deshalb wird kein global sauberer Dateisystemzustand behauptet.

### Isolierte Runtime-Reproduktionen

Temporäre, anschließend entfernte Python- und Frontend-JavaScript-Proben
bestätigten elf Gruppen:

1. freie Instrument-/Rate-/Date-Werte sowie die ansonsten gültige, für
   Liquidität aber widersprüchliche Liability-Kombination akzeptiert,
2. positive Rate einer Liability als Income,
3. Availability fehlt im Response,
4. Instrument-/Availability-/Methodenänderung ohne Hashänderung,
5. alle bekannten und ein unbekanntes Instrument im selben 100-Prozent-Bucket,
6. manueller plus derived Zins ergibt doppelte Serie,
7. Festgeld bis 2099 sofort im Advisory Wealth und Reportingzins,
8. externes Festgeld bis 2099 sofort vollständig im Unlock-Pool,
9. Classic-No-op-Edit überschreibt `Anderes Vermögen` mit
   `Beratungsvermögen`,
10. die Engine-Legacytypen `Liquiditaet`, `Bankkonto` und `Konto` öffnen im
    Classic-Editor mit leerem Label beziehungsweise ohne Liquiditätssektion,
11. derived CHF-5.000-Zins existiert, während die Advisory-Cashflowliste ohne
    manuelle Row leer bleibt.

Produktcode und Tests wurden dabei nicht verändert. Die echten Funktionen aus
dem Frontend-Monolithen wurden isoliert mit Mock-DOM ausgeführt; ein echter
Browser-/Electron-DOM-Lauf wurde nicht behauptet. Temporäre Skript-, DB- und
Basetemp-Artefakte wurden nach Pfadprüfung innerhalb des Workspace entfernt.

### Fokussierter Bestands-Gate

Mit isoliertem `DB_PATH` und isoliertem `--basetemp` wurden 22 einschlägige
Dateien ausgeführt:

```text
tests/test_wealth_cashflows.py
tests/test_engine_cashflow_consistency.py
tests/test_liquidity_flat_in_projection.py
tests/test_liquidity_zero_engine_lock.py
tests/test_frontend_verzehr_liquidity.py
tests/test_frontend_cashflow_dupe_hint.py
tests/test_wp500_wealth_position_null_int.py
tests/test_mandate_api_contracts.py
tests/test_total_wealth_allocation.py
tests/test_advisory_report.py
tests/test_advisory_report_pdf.py
tests/test_sprint_b_batch2.py
tests/test_sprint_b_batch3.py
tests/test_liquidity_hard_cap_in_fallback.py
tests/test_optimizer_objective_constraints.py
tests/test_allocation_preferences_fail_closed_contracts.py
tests/test_foundation_demo_purge.py
tests/test_data_classification_gate.py
tests/test_frontend_cashflow_grouping.py
tests/test_frontend_sollist_metrics.py
tests/test_house_matrix_risk_budget_consistency.py
tests/test_risk_matrix_data_foundation.py
```

Ergebnis:

```text
471 passed, 2 warnings in 131.79s
```

Die Warnungen waren eine bestehende `datetime.utcnow()`-Deprecation und der
bereits bekannte nicht beschreibbare `.pytest_cache`; kein Test schlug fehl.

Eine unabhängige Fact-QA wiederholte am 20. September 2026 exakt dieselben 22
Dateien mit isoliertem `DB_PATH`, `LOG_DIR` und `--basetemp` sowie
deaktivierten Python-Bytecode-Schreibvorgängen und bestätigte erneut:

```text
471 passed, 2 warnings in 150.53s
```

Die abweichende Laufzeit ist normale Ausführungsvarianz; Testmenge, Resultat
und Warnungsklassen waren identisch. Auch dieser Recheck veränderte weder
Produktcode noch Tests.

### Warum der grüne Gate die Findings nicht schließt

Der Gate belegt unter anderem Derived-Negativzins, FX-Schutz,
Null-Reportingbucket, vorhandene Basisdisclosure und stabile Bestandskanäle.
Er enthält aber keine vollständigen Instrumentterms, keinen periodischen
Availability-Resolver, keine Liabilitymatrix, keinen verlustfreien
Availability-Roundtrip und keine instrumentbezogene CMA-/Position-
Reconciliation. Mehrere Tests verlangen das heute problematische Verhalten
ausdrücklich und müssen nach einer fachlich freigegebenen Modelländerung
bewusst ersetzt werden.

### Nicht ausgeführte Prüfungen

- kein echter Browser-/Electron-DOM-Lauf,
- keine visuelle Classic-/React-/Portal-/PDF-Golden-Abnahme,
- kein echtes PostgreSQL-/Constraint-/Concurrency-Gate,
- kein produktiver Multiworker-/Schedulerlauf,
- keine externe Bank-/Marktdatenquelle,
- keine Freigabe konkreter fachlicher Rate-/Riskgrenzen.

Diese Grenzen sind Teil der Acceptance-Checkliste und keine stillschweigende
Freigabe.

## Dokumentationsmanifest und Commitvertrag

Diese Runde darf exakt folgende fünf Pfade ändern:

1. `docs/audits/2026-09-16-liquidity-instrument-availability-yield-and-funding-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Vor Commit sind mindestens auszuführen:

```text
git diff --check
git diff --stat
git status --short
```

Danach müssen Registerzahlen, Reprogruppen, Testzahl, Manifest und
Releaseentscheidung unabhängig gegengeprüft werden. Der Dokumentcommit wird
nicht als auditierten Produkt-Head ausgegeben; seine Auflösung erfolgt über
den im Frontmatter beschriebenen `git log`-Befehl.

## Releaseentscheidung

**Blockiert.** Es gibt keinen neuen P0. Vier neue P1 und zwei bestätigte
Erweiterungsgruppen über drei bestehende P1-IDs verhindern jedoch eine
belastbare Freigabe von Liquiditätsinstrument-, Availability-, Funding-,
Yield- und darauf beruhenden
Goal-/Reserve-/Optimizer-/MC-/Publikationsaussagen.

Freigabe ist erst vertretbar, wenn `LiquidityInstrumentModelSnapshot`,
`CashflowProjectionSnapshot` und `AllocationRunInputManifest`, die
geschlossene Domain/Policy und Migration, der periodische Availability-/
Funding-Resolver, die Exactly-once-Flow-Reconciliation, die
instrumentbezogene Decision-/Reporting-Brücke und die kanalgleiche
Manifestbindung vollständig implementiert und auf SQLite, echtem PostgreSQL,
Browser, API, Classic UI, React, Portal, allen PDFs, Signatur und Handoff
abgenommen sind.

Der Governance-Hold ist derzeit nicht in allen Runtimekanälen serverseitig
erzwungen. Genau diese technische Sperre ist Teil der Abnahme und darf nicht
allein durch Dokumentation als erledigt gelten.
