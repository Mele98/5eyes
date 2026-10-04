---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-direct-property-mortgage-amortization-publication-integrity-followup-audit"
status_as_of: "2026-09-14"
audit_started_on: "2026-09-14"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "ae6f089df9be059ff0ea48602056f51fee8c634b"
prior_release_audit_path: "docs/audits/2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-14-direct-property-mortgage-amortization-and-publication-integrity-audit.md"
audit_mode: "read_only_static_ui_router_service_orm_schema_test_review_and_isolated_python_and_frontend_javascript_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "Direct property, valuation and rent semantics, mortgage terms and collateral links, interest and refinancing, direct and indirect amortization, reserve and goal funding, deterministic and Monte Carlo foundations, classic UI projection, advisory API, React and PDF publication"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_blockers_from_prior_audits: true
static_findings_confirmed: 11
confirmed_p1: 10
confirmed_p2: 1
isolated_runtime_reproduction_groups_confirmed: 13
focused_existing_tests_passed: 192
focused_existing_tests_failed_after_isolation: 0
initial_non_isolated_test_startup_errors: 18
initial_startup_error_cause: "shared user database migration collision on risk_assessment_answers__old; all 18 passed with isolated DB_PATH"
isolated_frontend_javascript_executed: true
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "introduce one immutable PropertyMortgageModelSnapshot bound to TargetAllocation, OptimizerRun and every publication; validate property valuation and mortgage tranche domains; reconcile exactly one source for rent, interest and amortization; make direct and indirect amortization balance-sheet consistent; bind collateral and reserve eligibility; use one canonical gross-property, liability and pledged-asset series in optimizer, deterministic analysis, Monte Carlo, UI and PDF; fail closed on stale, orphaned, ambiguous or unreconciled state"
---

# Direktimmobilien-/Hypotheken-/Amortisations-/Publikations-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die dreißigste Read-only-
Kontrollrunde. Sie wurde am 14. September 2026 auf dem unveränderten
Repository-Head `ae6f089` durchgeführt. Produktcode und Tests wurden nicht
verändert. Die fünf Dokumentationspfade werden erst nach Abschluss der
technischen Prüfung angepasst.

Der Audit bewertet nicht, wie eine konkrete Immobilie zu schätzen oder welche
Hypothek einem Kunden zu empfehlen ist. Er prüft ausschließlich, ob die
Software ihren eigenen technischen und sichtbaren Vertrag konsistent erfüllt:

1. ob Immobilienwert, Bewertungsstichtag, Nutzung und Mietertrag eindeutige,
   validierte und zeitlich getrennte Bedeutungen besitzen,
2. ob Hypothekentyp, Zinssatz, Laufzeit, Refinanzierung und
   Immobilienverknüpfung fachlich geschlossen sind,
3. ob Miete, Zins und Amortisation genau einmal und unabhängig von der
   Erfassungsreihenfolge wirken,
4. ob direkte und indirekte Amortisation bilanziell vollständig fortgeschrieben
   werden,
5. ob Reserve, Goal Funding, Optimizer, deterministische Projektion und
   Monte Carlo dieselbe Immobilien-/Schuldenbasis verwenden,
6. ob Classic UI, Advisory API, React und PDF identische Brutto-, Schulden-
   und Nettozahlen publizieren,
7. und ob ein historisches Ergebnis aus einem unveränderlichen, belegten
   Immobilien-/Hypothekenmodell reproduzierbar ist.

Dieser Audit ergänzt insbesondere:

1. den unmittelbar vorherigen
   [Retirement-Income-/Pensions-/Entnahme-/Depletion-Integritätsaudit](2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md),
2. den
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
3. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
4. den
   [Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Integritätsaudit](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md),
5. den historischen
   [Cashflow-in-Monte-Carlo-Audit](2026-06-07-cashflow-in-mc-audit.md),
6. sowie die
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code, Tests und Migrationen zuerst, danach
dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu früheren Aussagen und Findings

Die Aussage vom 20. August 2026, direkte Immobilien lägen außerhalb des
investierbaren Portfolios, verwendeten positionsspezifische Renditen und
Mietertrag werde genau einmal berücksichtigt, bleibt nur für den kanonischen
Derived-only-Happy-Path gültig. Sie gilt nicht, wenn ein semantisch gleicher
manueller Cashflow existiert, wenn ein Derived-Endpoint ausfällt oder wenn ein
anderer Projektions-/Publikationskanal eine eigene Bilanzformel verwendet.
`PROPERTY-FLOW-DUPLICATION-001` schränkt die Aussage genau in diesem Umfang
ein; die grundsätzlich externe Klassifikation der Direktimmobilie bleibt
erhalten.

`MC-CONTEXT-001`, `MC-CASHFLOW-CURRENCY-001` und
`GOAL-PUBLICATION-001` bleiben die allgemeinen Monte-Carlo-, Cashflow-/FX-
und Goal-Publikationsverträge. `PROPERTY-GOAL-BASIS-001` und
`PROPERTY-RISK-MODEL-001` erfassen enger reproduzierte Abweichungen der
Direktimmobilienbasis und erzeugen keine neuen generischen MC-Findings.

`RESERVE-PROVENANCE-001` bleibt der allgemeine Reservevertrag.
`PROPERTY-COLLATERAL-001` ist auf die konkrete 100-Prozent-Anrechnung einer
externen Immobilie ohne LTV-, Rang- oder Haircut-Vertrag begrenzt.

`DEPOT-FX-SCOPE-001`, `DEPOT-PUBLICATION-001` und die Marktpreis-/
Preiszeit-Findings betreffen tradierbare Bestände und deren Kursbasis. Dieser
Audit beansprucht nur den eigenständigen Bewertungs- und Währungsvertrag von
`WealthPosition`-Direktimmobilien und Hypotheken.

`MORT-*` bleibt vollständig für Mortalitätsfindings reserviert. Alle neuen
Hypotheken-IDs verwenden deshalb das Präfix `MORTGAGE-*`.

Der Audit behauptet weder einen Cross-Tenant-Datenabfluss noch einen Verlust
aller Immobilien-/Hypothekenfelder im Response. API-Zugriffe und ein
übergebener Link sind clientgescopt; der Response enthält die Kernfelder. Ein
gelieferter Link wird beim Schreiben auf eine aktive Immobilie desselben
Kunden geprüft und ist im modernen Input-Hash enthalten. Die Lücken betreffen
Optionalität, Lebenszyklus, Replay, Reconciliation und Publikation.

Die im Code hinterlegten 3 Prozent Refinanzierungszins und fünf Jahre
SARON-Phase werden nicht als fachlich automatisch falsch bewertet. Der Befund
ist, dass diese Annahmen code-only, nicht explizit ausgewählt, nicht als
versionierte Modellannahme gesnapshottet und nicht kanalgleich erklärt werden.

Alle Release-Sperren in diesem Dokument sind Governance-Akzeptanzkriterien.
Sie beschreiben keine bereits vorhandene technische Sperre, solange Code und
Tests eine solche Sperre nicht ausdrücklich belegen.

## Kurzurteil

Der aktuelle Stand darf **nicht** als konsistente Immobilien-/Hypotheken-
Vermögensrechnung, als belastbare Refinanzierungs- oder Amortisationsprojektion
oder als freigabefähige Nettovermögenspublikation verwendet werden.

Bestätigt sind insbesondere:

1. Manuelle und aus Positionen abgeleitete Miete bzw. Hypothekarzinsen werden
   gemeinsam addiert. Der UI-Hinweis ist nur eine Warnung. Die
   Tilgungsprüfung ist label- und reihenfolgeabhängig; ein zuerst erfasster
   manueller Tilgungsflow bleibt neben der späteren Derived-Amortisation aktiv.
2. `valuation_date` ist ein freier String und gleichzeitig Bewertungsstichtag
   sowie `valid_from` abgeleiteter Cashflows. Eine zukünftig datierte
   Immobilie steht ab Jahr null vollständig in der Bilanz, während ihre Miete
   erst später startet. Ein ungültiges Datum fällt im Timeline-Parser auf
   „kein Start“ zurück.
3. Hypothekentyp, Satz und Laufzeit sind freie bzw. unbeschränkte Felder.
   `Gemischt` läuft im Fixed-Zweig, ein String mit vierstelliger Jahrespräfix
   wird als Laufzeitjahr benutzt und ein negativer Satz wird als aktueller
   Derived-Zins verworfen.
4. Bei einer bereits abgelaufenen Festhypothek berechnet der Schedule zwar den
   3-Prozent-Refinanzierungssatz, doch der Adjustment-Pfad setzt genau diesen
   Wert fälschlich als bereits enthaltene Basis an. Im wirksamen Cashflow
   bleibt dadurch der eingegebene 1-Prozent-Satz bestehen.
5. Indirekte Amortisation bleibt nach vollständiger Deckung des
   Hypothekarbetrags als unbegrenzter Expense aktiv. Das pledged asset ist
   dagegen am Principal gedeckelt. Danach verschwindet jeder weitere Transfer
   aus der Gesamtvermögensrechnung.
6. Die sichtbare Classic-UI-Projektion verzinst den um alle Liabilities
   reduzierten Immobilien-„Sockel“, statt die Bruttoimmobilie und ihre
   zugehörige Schuld getrennt fortzuschreiben. Bei direkter Amortisation bleibt
   die UI-Schuld statisch und die Zahlung wirkt vermögensmindernd.
7. Der Advisory-Report addiert eine positiv gespeicherte Hypothek zum
   `Gesamtvermögen`, erkennt `Kredite` aber nur bei negativem Betrag. Das
   Schema verlangt für `current_value_rappen` nichtnegative Werte. React und
   PDF publizieren die resultierenden Zahlen unverändert.
8. Die Ziel-Liability verwendet für externe Bruttoaktiven einen CPI-Pfad,
   während deterministische und MC-Gesamtpfade die explizite
   Immobilienrendite verwenden. Ein Einjahresziel wurde im Optimizer als
   vollständig gedeckt ausgewiesen, obwohl die ökonomisch verwendete
   Immobilienserie noch 10.000 Rappen Restziel ließ.
9. Die API akzeptiert bis zu 100.000 Basispunkte bzw. 1.000 Prozent erwartete
   Jahresrendite und die Engine compoundiert diesen Wert. Die HTML-Grenze ist
   durch den benutzerdefinierten Save-Pfad nicht verlässlich erzwungen.
   Gleichzeitig wird dieselbe Immobilienserie deterministisch zu jedem
   Monte-Carlo-Pfad addiert; p10, p50 und p90 sind für den Immobilienanteil
   identisch.
10. `is_available_for_goal_funding` kann eine externe Immobilie brutto und zu
    100 Prozent gegen externen Reservebedarf anrechnen. Beleihungswert, LTV,
    Pfandrang, bestehende Schuld, Haircut und Liquidationshorizont fehlen.
11. Ein Hypothekenlink ist optional, besitzt keinen Datenbank-Fremdschlüssel
    und keinen Inbound-Delete-Guard. Eine aktive Hypothek kann nach Soft-Delete
    ihrer verknüpften Immobilie als Orphan weiterbestehen; die Engine verrechnet
    Immobilien und sämtliche Liabilities ohnehin clientweit statt linkgenau.

Der fokussierte Bestands-Gate mit 192/192 bestandenen Tests bestätigt wichtige
Teilfunktionen, schließt diese Befunde aber nicht. Mehrere Tests pinnen das
problematische Verhalten ausdrücklich: Warning-only-Duplikate, die
codebasierten 3-Prozent-/5-Jahres-Annahmen, die ungekappte indirekte
Amortisationskorrektur und die deterministische Immobilienkomponente in allen
MC-Pfaden.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `PROPERTY-FLOW-DUPLICATION-001` | P1 | bestätigt | Manuelle und abgeleitete Miete/Zinsen/Amortisation können gemeinsam und reihenfolgeabhängig doppelt wirken; die UI warnt nur. |
| `PROPERTY-VALUATION-001` | P1 | bestätigt | Ein freier `valuation_date`-String vermischt Bewertungsstichtag und Cashflow-Gültigkeit; Bewertungsprovenienz und effektive Zustände fehlen. |
| `MORTGAGE-TERMS-001` | P1 | bestätigt | Typ, Satz und Laufzeit besitzen keine geschlossene Domain; unbekannte, malformed und negative Eingaben werden unterschiedlich und ökonomisch inkonsistent interpretiert. |
| `MORTGAGE-REFINANCE-001` | P1 | bestätigt | Bei bereits abgelaufener Festhypothek stimmt der Schedule nicht mit dem tatsächlich wirksamen Zinscashflow überein; Refi-Annahmen sind nicht versioniert. |
| `MORTGAGE-INDIRECT-AMORTIZATION-001` | P1 | bestätigt | Nach dem Principal-Cap läuft der indirekte Expense weiter, während kein zusätzlicher pledged asset mehr entsteht. |
| `PROPERTY-UI-PROJECTION-001` | P1 | bestätigt | Die Classic UI verzinst Netto-Sockel und hält Schulden bei Amortisation statisch; Backend und sichtbare Projektion driften. |
| `LIABILITY-PUBLICATION-001` | P1 | bestätigt | Positive Hypothekenbeträge werden als Vermögen addiert und nicht als Kredit ausgewiesen; React und PDF übernehmen die Falschzahl. |
| `PROPERTY-GOAL-BASIS-001` | P1 | bestätigt | Optimizer-Goal-Liability nutzt CPI für externe Bruttoaktiven statt der Property-Serie der deterministischen/MC-Gesamtpfade. |
| `PROPERTY-RISK-MODEL-001` | P1 | bestätigt | 1.000 Prozent Rendite sind API-seitig zulässig; Direktimmobilien besitzen zugleich keinen expliziten stochastischen Risiko-/Korrelationsvertrag. |
| `PROPERTY-COLLATERAL-001` | P1 | bestätigt | Eine externe Immobilie kann brutto und ohne LTV/Haircut/Rang/Liquidationsvertrag externe Reserve vollständig absorbieren. |
| `MORTGAGE-LINK-001` | P2 | bestätigt | Write-time-Prüfung und Hash existieren, aber FK, Inbound-Delete-, Replay- und linkgenaue Reconciliation fehlen. |

## Positivkontrollen, die erhalten bleiben müssen

Die Reparatur darf folgende bestehende Kontrollen nicht zurückbauen:

1. `Hypothek` wird im Create-Vertrag der Zuordnung `Verbindlichkeit`
   zugewiesen; direkte Immobilien bleiben als externes anderes Vermögen
   klassifiziert.
2. `current_value_rappen` und die nominalen Miet-/Amortisationsbeträge sind
   nichtnegativ und besitzen großzügige Obergrenzen.
3. `asset_expected_return_bps` ist strict integer und muss größer als
   -100 Prozent sein; die obere Fachgrenze muss enger werden, die Typkontrolle
   bleibt.
4. Ein **übergebener** Hypothekenlink wird beim Create/Update auf eine aktive
   Immobilienposition desselben Kunden geprüft.
5. Client- und Benutzerzugriff der Router bleiben gescopt; dieser Audit hat
   keinen Cross-Tenant-Leak reproduziert.
6. Fremdwährungspositionen benötigen im kanonischen Enginepfad eine explizite,
   positive FX-Quelle; stilles 1:1 ist dort untersagt.
7. Der moderne Input-/Projektionshash bindet bereits Currency,
   Bewertungsdatum, Miete, Inflationsflag, Immobilienrendite,
   Hypothekenzins, Amortisation, Typ, Laufzeit und Link sowie effektive
   Projektionsserien.
8. Der normalisierte Amortisationsmodus und Raw-row-Enginepfad sind
   fail-closed. Direkte Amortisation ist im Backend-Happy-Path bilanziell
   neutral: sinkende Liquidität und sinkende Liability gleichen sich aus;
   eine Zahlung nach vollständiger Tilgung wird dort korrigiert.
9. Derived-only-Mietertrag wird im kanonischen Happy-Path genau einmal
   erzeugt, wenn kein semantisch gleicher manueller Flow hinzukommt.
10. Der MC-Foundation-Adapter validiert Objektform, Serienlänge und
    Nichtnegativität der Property-, Liability- und Pledged-Serien.
11. Das Response-Schema enthält die wesentlichen Immobilien- und
    Hypothekenfelder. Die Reparatur darf diese nicht durch ein verkürztes
    DTO verlieren.

## Tatsächlicher Immobilien-/Hypotheken-Datenfluss

1. Classic UI oder API erzeugt `WealthPosition` für `Immobilien` oder
   `Hypothek`.
2. Pydantic prüft Positionstyp, Assignment, Betragsgrenzen und einzelne
   Amortisationsregeln; Datum, Nutzung, Hypothekentyp, Zinssatz und Laufzeit
   bleiben weitgehend frei.
3. Der Router prüft einen gelieferten Property-Link beim Schreiben. Die
   Datenbank speichert ihn als String ohne FK.
4. `derive_wealth_cashflows()` erzeugt aus aktiven Positionen Miete,
   Hypothekarzins und Amortisation; `valuation_date` wird dabei als
   `valid_from` kopiert.
5. Manuelle und derived Cashflows werden im Enginepfad aneinandergehängt.
   Eine semantische Source-Reconciliation findet nicht statt.
6. `cashflow_timeline` aggregiert die gemeinsamen Flows jahresweise.
   Ungültige Datumsstrings werden als fehlender Start interpretiert.
7. `mortgage_interest_adjustment_series()` und
   `mortgage_amortization_adjustment_series()` korrigieren den statischen
   Basisflow für Zins-/Principal-Änderungen.
8. `_build_external_foundation_projection()` erzeugt Bruttoimmobilien-,
   Liability- und Pledged-Asset-Serien.
9. `_build_external_goal_funding_series()` ersetzt die Property-Serie für
   Goal Funding durch eine CPI-Fortschreibung externer Bruttoaktiven.
10. Die MC-Pfade addieren dieselbe externe Foundation-Serie zu jedem
    simulierten Finanzpfad.
11. Die Classic UI erzeugt separat eine sichtbare Projektion aus
    `wealthProjectionInputs()` und `buildCurrentWealthProjection()`.
12. Der Advisory-Report erzeugt nochmals separat Vermögenssummen; React und
    PDF rendern diese Felder ohne Liability-Reconciliation.

Damit existieren mindestens vier fachliche Rechenbasen: Derived-/Timeline,
Optimizer-Goal-Funding, Backend-Foundation/MC und Classic-UI/Advisory-
Publikation. Ein gemeinsamer, materialisierter Property-/Mortgage-Snapshot
existiert nicht.

## Codeanker auf dem auditierten Head

| Vertrag | Codeanker |
|---|---|
| Create-/Update-/Response-Domains | `5eyes-backend/schemas/wealth.py:12-230` |
| Persistierte Property-/Mortgage-Felder und String-Link | `5eyes-backend/models/wealth.py:6-60` |
| Begrenzte Positionssemantik | `5eyes-backend/services/wealth_position_semantics.py:1-160` |
| Labelbasierte Double-count-Prüfung | `5eyes-backend/routers/wealth.py:449-483` |
| Write-time-Linkprüfung | `5eyes-backend/routers/wealth.py:486-501` |
| Position Create/Update/Soft-Delete | `5eyes-backend/routers/wealth.py:504-656` |
| Rate, Typ, Laufzeit, Refi-Schedule | `5eyes-backend/services/wealth_cashflows.py:68-185` |
| Zins- und Amortisations-Adjustments | `5eyes-backend/services/wealth_cashflows.py:188-282` |
| Derived Miete/Zins/Amortisation | `5eyes-backend/services/wealth_cashflows.py:285-352` |
| Datumsparser und Jahresaggregation | `5eyes-backend/services/cashflow_timeline.py:33-40,93-157,314-339` |
| External Foundation | `5eyes-backend/services/portfolio_engine.py:905-997` |
| Abweichende Goal-Funding-Serie | `5eyes-backend/services/portfolio_engine.py:1000-1045` |
| Externe Reserveanrechnung | `5eyes-backend/services/portfolio_engine.py:1907-1915`; `5eyes-backend/services/portfolio_engine_reserve.py:285-494` |
| Manuelle plus Derived Flows | `5eyes-backend/services/portfolio_engine.py:1927-1933,5498-5503` |
| v2-Positionshash | `5eyes-backend/services/portfolio_engine.py:2364-2379` |
| Total-Goal-Liability | `5eyes-backend/services/optimizer/goal_liabilities.py:324-385` |
| MC-Foundation und Pfadkombination | `5eyes-backend/services/portfolio_engine_mc_simulation.py:385-480,1241-1478` |
| Classic Property-/Debt-Projektion | `5eyes-electron/frontend/5eyes_v2.html:6622-6725,7016-7029` |
| Warning-only-Duplikathinweis | `5eyes-electron/frontend/5eyes_v2.html:23052-23080` |
| Property-/Mortgage-Editor und Save | `5eyes-electron/frontend/5eyes_v2.html:4835-4964,23372-23455` |
| React Derived-Fetch | `5eyes-electron/frontend/reporting/src/sections/cashflow/CashflowEditor.tsx:48-60,173-203` |
| Advisory-Vermögenssummary | `5eyes-backend/services/advisory_report.py:623-701` |
| React-/PDF-Publikation | `5eyes-electron/frontend/reporting/src/pages/Ausgangslage.tsx:103-109`; `5eyes-backend/services/pdf/documents/advisory_report.py:674-683` |

## `PROPERTY-FLOW-DUPLICATION-001` – Gleicher wirtschaftlicher Flow wirkt mehrfach

### Beobachtung

Die Engine hängt manuelle und aus Positionen abgeleitete Cashflows zusammen.
Der Router blockiert nur einen Expense, dessen Label wie Tilgung aussieht,
wenn beim Schreiben bereits irgendeine aktive Hypothek existiert. Er besitzt
keinen stabilen Source-Key, keine Beziehung zur konkreten Hypothek und keine
Prüfung in Gegenrichtung. Die UI erkennt mögliche Dubletten heuristisch, lässt
sie aber ausdrücklich gemeinsam in die Projektion einfließen. React behandelt
einen Fehler des Derived-Endpoints als leere Liste.

### Isolierte Reproduktionen

1. Semantisch gleicher manueller und derived Hypothekarzins ergaben zusammen
   `400` Rappen Expense.
2. Semantisch gleicher manueller und derived Mietertrag ergaben zusammen
   `1.000` Rappen Income.
3. Zuerst angelegter manueller Tilgungsflow von `10.000` Rappen wurde
   akzeptiert. Nach Anlage der Hypothek kamen weitere `10.000` Rappen Derived-
   Amortisation hinzu; zusammen `20.000` Rappen.

Die Bestandsfälle in `test_audit_b3_mortgage_amortization.py`,
`test_cashflow_derived_integration.py` und
`test_frontend_cashflow_dupe_hint.py` sichern Teile dieses Verhaltens ab.

### Wirkung

Reserve, Liquiditätspfad, Zielerreichung, Gesamtvermögen und sichtbare
Cashflow-Summe können je nach Erfassungsreihenfolge verschieden sein. Ein
Derived-Fetch-Fehler kann die UI beruhigen, während der Backendpfad weiterhin
derived Flows einrechnet.

### Fixvertrag

1. Jeder wirtschaftliche Flow erhält einen stabilen Schlüssel, mindestens
   `source_kind`, `source_position_id`, `flow_kind`, `effective_from` und
   gegebenenfalls `tranche_id`.
2. Für Miete, Zins und Amortisation gilt genau eine explizite Policy:
   positions-derived, manual override oder fachlich begründete Addition.
3. Create, Update, Positionsanlage, Positionsänderung, Import und Replay prüfen
   dieselbe Invariante unabhängig von der Reihenfolge.
4. Die Datenbank erzwingt die gewählte Eindeutigkeit oder speichert einen
   expliziten Override mit Begründung, Autor und Zeit.
5. Bestehende Dubletten werden migriert oder quarantänisiert; keine stille
   Summation.
6. UI und React zeigen Source und Reconciliation-Status. Fällt die Derived-
   Quelle aus, ist die Projektion `unknown`, nicht „keine Derived-Flows“.

### Pflichttests

- manual-first, position-first, Update, Deactivate, React-Refetch und Replay,
- gleicher Text bei anderer Position sowie anderes Label bei gleicher Source,
- Miete, Zins, direkte und indirekte Amortisation,
- SQLite und PostgreSQL mit concurrent create,
- API-, Classic-UI-, React-, MC- und PDF-Golden-Parität.

## `PROPERTY-VALUATION-001` – Bewertungsstichtag wird zum Cashflow-Start

### Beobachtung

`valuation_date` ist ein optionaler String. Bei Derived-Flows wird derselbe
Wert als `valid_from` gesetzt. Der Property-Principal wird dagegen ab Jahr null
in die Foundation aufgenommen. Quelle, Methode, Evidenz, Eigentumsanteil,
Freshness-Policy und separate wirtschaftliche Wirksamkeit sind nicht
verpflichtend modelliert.

Der Timeline-Parser gibt bei syntaktisch ungültigem Datum `None` zurück. Das
bedeutet für wiederkehrende Flows nicht „ungültig“, sondern praktisch „kein
Start-Limit“. Eine rechtliche oder fachliche Schweizer Freshness-Frist wird in
diesem Audit ausdrücklich **nicht** erfunden; die Software braucht eine
versionierte interne Policy.

### Isolierte Reproduktionen

Eine Immobilie mit zukünftigem `valuation_date` erzeugte:

```text
property foundation: [1000000, 1000000, 1000000, 1000000, 1000000, 1000000]
derived rent:         [0, 0, 0, 0, 20000, 20000]
```

Der Principal existiert somit ab dem ersten Projektionsjahr, die aus demselben
Datensatz stammende Miete aber erst ab dem zukünftigen Jahr. Ein separater
Schema-Repro akzeptierte unter anderem `2099-not-a-date` als
`valuation_date`, `submarine` als `property_usage` und `999` als
`property_rental_inflation_linked`; jeder Nichtnullwert wirkt später truthy.

### Wirkung

Bewertung, Eigentum, Kauf/Verkauf, Nutzungsphase und Mietvertragsbeginn können
nicht auseinandergehalten werden. Resultate sind zwar gehasht, aber ihre
wirtschaftliche Zeitsemantik und Herkunft sind nicht nachvollziehbar.

### Fixvertrag

1. `valuation_as_of` ist ein echtes ISO-Datum und bezeichnet nur den
   Bewertungsstichtag.
2. `effective_from`/`effective_until` oder ein expliziter Property-State-
   Verlauf bestimmen, wann Principal und Liability zur Bilanz gehören.
3. Mietvertrag bzw. Eigennutzung erhalten eigene Gültigkeitsdaten; Nutzung ist
   ein Enum. Gemischte Nutzung benötigt Anteile statt freiem Text.
4. Bewertung speichert Quelle, Methode, Evidence-Referenz, Currency,
   Eigentums-/Haushaltsanteil und eine versionierte Freshness-Entscheidung.
5. Ungültig, in der Zukunft ohne erklärten Zustand, stale oder widersprüchlich
   führt vor Berechnung/Publikation zu einem expliziten Blocker.
6. Update, Import und Legacy-Migration dürfen `currency` nicht still verlieren;
   aktuell fehlt `currency` im `WealthPositionUpdate`-Schema.

### Pflichttests

- ungültiges ISO-Datum, Zukunftsbewertung, Kauf/Verkauf im Horizont,
- Mietbeginn vor/nach Eigentumsbeginn und gemischte Nutzung,
- stale/current gemäß konfigurierter Policy,
- Teil-/Haushaltseigentum und Currency-Update,
- Snapshot-Replay und kanalgleiche `unknown`-/Blocker-Publikation.

## `MORTGAGE-TERMS-001` – Freie Terms werden still unterschiedlich interpretiert

### Beobachtung

`mortgage_type`, `mortgage_interest_rate_bps` und
`mortgage_maturity_date` besitzen keine geschlossene fachliche Domain. Die
Schedule-Hilfe erkennt SARON/variabel über Substring; alles andere fällt in
den Fixed-Zweig. `_year_of()` akzeptiert jeden String, dessen erste vier
Zeichen Ziffern sind.

Der Basisbetrag wird vorzeichenbehaftet berechnet. `derive_wealth_cashflows()`
verwirft für Hypotheken jedoch Beträge `<= 0`, während der Schedule den
negativen Satz weiterführt. Daraus kann beim späteren Refi-Cutover eine
Adjustment-Ausgabe entstehen, obwohl der heutige Cashflow vollständig fehlt.

### Isolierte Reproduktionen

Das Create-Schema akzeptierte:

```text
mortgage_type: teleport
mortgage_interest_rate_bps: -999999
mortgage_maturity_date: 2027-not-a-date
```

Weitere Repros bestätigten:

```text
malformed/fixed schedule: [-100, -100, 300, 300]
SARON schedule:           [80, 80, 80, 80, 80, 300, 300]
negative derived count:   0
negative schedule:        [-1000, 3000]
negative effective:       [0, -4000]
```

`Gemischt` wird nicht ignoriert, sondern als non-SARON/Fixed behandelt. Ein
String wie `2030-not-a-date` wird nicht verworfen, sondern als Jahr 2030
verwendet.

### Wirkung

Der gleiche gespeicherte Term kann in Basisflow, Adjustment und UI
unterschiedlich wirken. Tippfehler oder unbekannte Produkte werden nicht
sichtbar abgewiesen. Negative Zinsen werden weder als Gutschrift noch als
explizit unzulässig konsistent behandelt.

### Fixvertrag

1. Hypothekentyp ist ein versioniertes Enum; gemischte Produkte bestehen aus
   expliziten Tranchen.
2. Zinssatz besitzt eine dokumentierte fachliche Range und eine ausdrückliche
   Negative-rate-Policy.
3. Laufzeit ist ein valides ISO-Datum; Produktart und Laufzeitpflicht werden
   gemeinsam validiert.
4. Baseline, Schedule, Adjustment, Cashflow und Publikation verwenden dieselbe
   signierte Zinssemantik.
5. Unbekannte Legacywerte werden migriert/quarantänisiert und blockieren bis
   zur Entscheidung; kein stiller Fixed-Fallback.
6. UI-Constraints sind nur Ergonomie. Der API-/Domainvertrag ist maßgeblich.

### Pflichttests

- Enum-Matrix Fixed/SARON/Variable/Tranche und unknown,
- malformed, fehlende und bereits abgelaufene Laufzeit,
- Range-Grenzen und Negative-rate-Policy,
- Create, Update, Import, Rebuild und Snapshot-Replay,
- identischer Baseline-/Schedule-/Adjustment-/UI-/PDF-Wert.

## `MORTGAGE-REFINANCE-001` – Abgelaufene Hypothek bleibt effektiv beim Altsatz

### Beobachtung

`mortgage_interest_schedule()` wechselt für eine abgelaufene Festhypothek
gemäß der codeinternen Regel auf `REFINANCE_RATE_BPS`. Die Adjustment-Funktion
setzt aber
`schedule[0]` als „heute bereits im Cashflow enthaltene“ Basis an. Der
tatsächlich abgeleitete Basisflow verwendet weiterhin den gespeicherten
Originalsatz. Ist die Laufzeit schon vor `start_year` abgelaufen, sind diese
beiden Basen verschieden und die erforderliche Korrektur wird null.

### Isolierte Reproduktion

Für Principal `1.000.000` Rappen, eingegebenen Satz 1 Prozent, Laufzeit 2025
und Projektionsstart 2026 ergab sich:

```text
schedule:     [30000, 30000]
derived base: [-10000, -10000]
adjustment:   [0, 0]
effective:    [-10000, -10000]
```

Der Schedule behauptet somit 3 Prozent, der wirksame Cashflow bleibt bei
1 Prozent.

### Wirkung

Liquiditätsbedarf, Reserve, verfügbare Mittel, Goal Funding und Projektion
können ab Jahr null mit dem falschen Zins rechnen. Der moderne Input-/
Projektionshash macht den Fehler reproduzierbar, belegt aber nicht, welche
Refi-Annahme fachlich gewählt und sichtbar erklärt wurde.

### Fixvertrag

1. Der Basisflow muss aus derselben kanonischen Schedule-Serie wie jede
   Jahreskorrektur stammen; keine implizite `schedule[0]`-Gleichsetzung.
2. Bereits abgelaufene Terms benötigen vor Berechnung einen expliziten
   Refinance-State oder einen fail-closed Blocker.
3. Refi-Annahme speichert ID, Version, Quelle, `as_of`, Currency, Szenario und
   Freigabestatus; 3 Prozent/5 Jahre dürfen nur als explizit ausgewählte
   Modellannahme wirken.
4. API, UI und PDF publizieren Altsatz, Ablauf, Anschlussannahme und
   Sensitivität kanalgleich.

### Pflichttests

- Ablauf vor, auf und nach `start_year`,
- Fixed ohne Ablauf, SARON-Cutover und mehrere Tranchen,
- direkter Principal-Abbau vor/nach Refi,
- Basis plus Adjustment exakt gleich Schedule,
- Refi-Parameterwechsel erzeugt neuen Snapshot/Run und invalidiert stale
  Publikationen.

## `MORTGAGE-INDIRECT-AMORTIZATION-001` – Zahlung läuft nach dem Asset-Cap weiter

### Beobachtung

Indirekte Amortisation reduziert den Hypothekar-Principal bewusst nicht. Der
Foundation-Pfad baut stattdessen ein pledged asset auf und deckelt es mit
`min(principal, annual_amortization * year)`. Der wiederkehrende Derived-
Expense wird aber ausdrücklich nicht gedeckelt. Nach Erreichen des Principals
verlässt weiter Liquidität die Finanzserie, ohne dass Liability sinkt oder
pledged asset steigt.

Der bestehende Testvertrag prüft nur einen kurzen Vor-Cap-Zeitraum und pinnt
die ungekappte Adjustment-Funktion. Er beweist deshalb nicht die bilanzielle
Identität über den vollständigen Horizont.

### Isolierte Reproduktion

Ein normalisierter Fall mit Principal `100` und indirekter Jahreszahlung `50`
ergab:

```text
liability series: [100, 100, 100, 100, 100]
pledged series:   [0, 50, 100, 100, 100]
combined total:   [100, 100, 100, 50, 0]
```

Bis zum Principal-Cap ist der Transfer vermögensneutral. Danach fällt das
Gesamtvermögen weiter, obwohl der synthetische Gegenwert unverändert bleibt.
Ein zweiter Repro mit Principal 100.000, 20.000 Jahreszahlung und acht Jahren
zeigte denselben Post-Cap-Verlust.

### Wirkung

Lange Horizonte, Reserve und Zielerreichung werden nach vollständiger
synthetischer Deckung systematisch zu niedrig ausgewiesen. Ohne Beziehung zu
einer realen verpfändeten 3a-/Vorsorgeposition ist zusätzlich nicht belegbar,
ob das synthetische pledged asset den echten Vertrag korrekt repräsentiert.

### Fixvertrag

1. Pro Periode gilt eine explizite Bilanzidentität:
   `cash_out = liability_reduction + pledged_asset_increase + disclosed_cost`.
2. Ist das wirtschaftliche Ziel erreicht, stoppt die Zahlung oder fließt in
   ein explizites, weiterwachsendes Asset. Ein Betrag darf nicht verschwinden.
3. Principal, pledged balance und Zahlung werden tranchengenau und in derselben
   Currency fortgeschrieben.
4. Ein reales verpfändetes Asset wird referenziert oder der synthetische
   Modellcharakter wird explizit gesnapshottet. Doppelzählung mit einer separat
   erfassten Vorsorgeposition ist auszuschließen.
5. Direkte und indirekte Amortisation verwenden denselben periodischen
   Reconciliation-Rahmen, aber ihre unterschiedliche Schuldenwirkung bleibt
   sichtbar.

### Pflichttests

- exakter Cap, Teilzahlung am Cap, Over-Cap und mehrere Post-Cap-Jahre,
- direkte versus indirekte Amortisation und Wechsel des Modus,
- mehrere Hypothekentranchen, FX und Rundung,
- reales versus synthetisches pledged asset ohne Doppelzählung,
- Identität in Optimizer, Deterministik, MC, UI, API und PDF.

## `PROPERTY-UI-PROJECTION-001` – Sichtbare UI rechnet eine andere Bilanz

### Beobachtung

`wealthProjectionInputs()` summiert Immobilien zunächst brutto, zieht danach
jedoch sämtliche Liabilities clientweit ab und bildet daraus einen
nichtnegativen Property-Sockel. `buildCurrentWealthProjection()` verzinst
diesen Nettosockel. Die Liability selbst wird im sichtbaren Verlauf nicht
tranchengenau reduziert. Ein Amortisations-Cashflow mindert deshalb die
liquide Komponente, ohne dass die zugehörige Schuld synchron sinkt.

Das betrifft die lokale Classic-UI-Projektion. Der Main-Engine-Foundation-Pfad
zieht Liabilities grundsätzlich ab und cappt direkte Tilgung; diese positive
Kontrolle darf nicht auf den lokalen UI-Pfad übertragen werden.

### Isolierte Frontend-JavaScript-Reproduktionen

Die echte Funktion wurde isoliert aus dem HTML ausgeführt:

```text
property appreciation
  startRappen: 200000
  sockelRappen: 200000
  UI series:      [200000, 220000]
  backend series: [200000, 300000]

direct amortization
  startRappen: 300000
  sockelRappen: 200000
  consumableRappen: 100000
  UI series:      [300000, 200000]
  backend series: [300000, 300000]
```

Der erste Fall zeigt die Abweichung zwischen verzinstem Nettosockel und
getrennter Bruttoimmobilien-/Liability-Serie. Der zweite zeigt, dass eine
bilanziell neutrale direkte Tilgung in der sichtbaren UI 100.000 Rappen
Vermögen vernichtet.

### Wirkung

Berater und Kunde können im sichtbaren Chart eine andere Entwicklung sehen als
Optimizer, Backend-Analyse oder MC. Der Unterschied ist weder als alternative
Basis gekennzeichnet noch rechnerisch reconciliert.

### Fixvertrag

1. Die UI konsumiert die kanonischen serverseitigen Property-, Liability- und
   Pledged-Serien; keine lokale Parallelformel für freigaberelevante Zahlen.
2. Bruttoimmobilie, zugehörige Hypothek und Nettovermögen bleiben als getrennte
   Komponenten sichtbar.
3. Nur verknüpfte Mortgage-Tranchen beeinflussen die konkrete Immobilie;
   andere Schulden dürfen nicht ihren Wachstumsprincipal reduzieren.
4. Direkte Amortisation reduziert Cash und Liability synchron bis zum Payoff-
   Cap. Indirekte Amortisation folgt der dokumentierten Identität.
5. Fehlt Link, Quelle oder Series-Evidence, zeigt die UI `unknown` oder einen
   Blocker statt einer lokal rekonstruierten Falschpräzision.

### Pflichttests

- positive, null und negative Immobilienrendite,
- direkte Tilgung vor, am und nach Payoff,
- nicht hypothekarische Liability neben Immobilie,
- mehrere Immobilien und Tranchen,
- Browser-Golden gegen denselben serverseitigen Snapshot,
- Classic UI, React, API und PDF auf Rappen gleich.

## `LIABILITY-PUBLICATION-001` – Hypothek erscheint als zusätzliches Vermögen

### Beobachtung

Das gültige Datenmodell speichert auch Liabilities mit nichtnegativem
`current_value_rappen`; die Richtung folgt aus `assignment`. Die serverseitige
Advisory-Summary addiert jedoch jeden Betrag zu `gesamtvermoegen`. Als
`kredite` erfasst sie nur einen negativen Betrag, wenn der Positionstyp einen
Kreditbegriff enthält. Diese Bedingung kann für regulär schema-valide
Hypotheken nicht erfüllt werden.

React `Ausgangslage` und das Advisory-PDF rendern die erzeugten Summary-Felder
unverändert. Der Befund ist auf diesen Advisory-Report-/Publikationspfad
begrenzt; die Main Engine und andere Monolith-Bilanzen ziehen Liabilities in
ihren kanonischen Pfaden grundsätzlich ab.

### Isolierte Reproduktion

Für eine Immobilie von `1.000.000` Rappen und eine gültige Hypothek von
`800.000` Rappen publizierte die Summary:

```text
gesamtvermoegen_rappen: 1800000
immobilien_rappen:      1000000
kredite_rappen:               0
korrektes Nettovermögen: 200000
```

Die Hypothek wird also einmal als positives Vermögen addiert und zugleich in
der sichtbaren Kreditzeile ausgelassen.

### Wirkung

Ausgangslage, PDF und mögliche nachgelagerte Beratungsevidenz können das
Nettovermögen um das Doppelte des Hypothekarbetrags überschätzen. Brutto,
Schuld und Netto sind nicht rechnerisch abstimmbar.

### Fixvertrag

1. Das Vorzeichen folgt ausschließlich der kanonischen Klassifikation bzw.
   `assignment`, nicht dem gespeicherten Betragsvorzeichen oder Labeltext.
2. Publiziert werden getrennt `gross_assets`, `liabilities` und
   `net_wealth = gross_assets - liabilities`.
3. Immobilien- und Hypothekensummen besitzen dieselbe Currency-/FX-
   Bewertungsbasis und denselben `as_of`-Zeitpunkt.
4. Advisory API, React und PDF erhalten dasselbe typisierte Objekt und dieselbe
   Reconciliation-Evidence.
5. Fehlende Coverage, Currency oder Klassifikation blockiert die Zahl; kein
   stilles Null für Kredite.

### Pflichttests

- schema-valide positive Hypothek und andere positive Liabilities,
- mehrere Assets/Liabilities, null, FX und Rundung,
- Brutto-/Liability-/Netto-Identität,
- JSON-/React-/PDF-Golden auf Rappen gleich,
- fehlende/stale Grundlage als `unknown`, nicht als null.

## `PROPERTY-GOAL-BASIS-001` – Goal Funding und Gesamtpfad verwenden andere Basen

### Beobachtung

`_build_external_foundation_projection()` wächst die Direktimmobilie mit
`asset_expected_return_bps`. `_build_external_goal_funding_series()` verwendet
für die externe Bruttobasis stattdessen CPI und ignoriert die bereits erzeugte
`property_series_rappen`. `_build_wealth_target()` zieht diese zweite Serie vom
Total-Goal ab.

Der Backendpfad versieht diese Varianten bereits mit `model_basis`-/Basis-IDs.
Damit ist die Wahl nicht vollständig verborgen. Offen bleibt jedoch, dass die
entscheidungserhebliche Goal-Deckung und die kundenorientierte Total-Projektion
verschiedene ökonomische Basen verwenden, ohne kanalgleiche Reconciliation und
Statusfolge. Unterschiedliche Modelle sind nur zulässig, wenn sie explizit
benannt, begründet, gesnapshottet und in der Publikation abstimmbar sind.

### Isolierte Reproduktion

Immobilie `1.000.000` Rappen, Immobilienrendite 0 Prozent, CPI 2 Prozent,
Einjahres-Totalziel `1.010.000` Rappen:

```text
property foundation:       [1000000, 1000000]
optimizer external series: [1000000, 1020000]
optimizer residual target: 0
residual on property basis: 10000
```

In einem normalisierten Mehrjahresfall standen Property `[100, 110, 121]`
und CPI-Basis `[100, 102, 104]` gegenüber.

### Wirkung

Ein Ziel kann in der Allocation-Entscheidung als gedeckt gelten, obwohl der
im Total-Chart oder MC verwendete Immobilienpfad es nicht deckt – oder
umgekehrt. Score, Reserve, Zielstatus und Publikation sind nicht aus einer
einzigen Basis ableitbar.

### Fixvertrag

1. Eine kanonische Property-/Liability-/Pledged-Serie ist Default für Goal,
   Reserve, Optimizer, Deterministik und MC.
2. Ist eine konservative Goal-Funding-Basis fachlich gewollt, wird sie als
   eigene Policy mit ID, Version und Reconciliation zur Published-Basis
   gespeichert und sichtbar benannt.
3. Goal-Resultat speichert verwendete Basis-ID, Snapshot-ID, Zieljahrwert und
   Restliability; kein nachträgliches Rekonstruieren aus aktuellen Positionen.
4. Status-/Score-/Probability-Claims dürfen nur publiziert werden, wenn
   Decision- und Publication-Basis gleich oder explizit reconciliert sind.

### Pflichttests

- Property-Rendite kleiner/gleich/größer CPI und negative Rendite,
- Advisory- versus Total-Scope,
- direkte/indirekte Amortisation im Zieljahr,
- Basis-ID/Hash bei Änderung von CPI oder Property-Annahme,
- Optimizer-/Deterministik-/MC-/UI-/PDF-Reconciliation.

## `PROPERTY-RISK-MODEL-001` – Extremrendite trifft deterministische Total-MC

### Beobachtung

Das API-Schema erlaubt `asset_expected_return_bps` bis einschließlich
`100000`, also 1.000 Prozent pro Jahr. Der Classic-Editor zeigt zwar eine
HTML-Grenze, sein eigener Save-Pfad ruft aber keine verlässliche native
`checkValidity()`-/`reportValidity()`-Sperre vor dem API-Aufruf auf. Die Engine
compoundiert den akzeptierten Wert.

Die externe Immobilienserie ist zugleich deterministisch und wird identisch zu
jedem MC-Finanzpfad addiert. Dieser deterministische Vertrag ist in
Bestandstests ausdrücklich gepinnt und nicht allein automatisch ein Bug. P1
entsteht aus der Kombination einer extrem offenen Return-Domain mit
kundenorientierten Total-MC-/Quantilclaims ohne Property-spezifische Risiko-,
Korrelations-, Illiquiditäts- oder Sensitivitätsevidenz.

### Reproduktion und Bestandsevidenz

Eine Position mit 1.000 Prozent Rendite ergab:

```text
[100, 1100, 12100, 133100]
```

`test_external_direct_property_total_paths_contract.py` pinnt zudem, dass die
externe Property-Komponente in MC für p10, p50 und p90 denselben Pfad besitzt.
Die angezeigten Total-Quantile enthalten damit stochastische Finanzanlagen,
aber keine stochastische Unsicherheit des Immobilienwerts.

### Wirkung

Ein API-/Importwert kann die Vermögens- und Goal-Basis explosionsartig
dominieren. Total-MC kann zugleich eine Quantilpräzision suggerieren, die
Bewertungs-, Objekt-, Liquiditäts- und Korrelationsrisiko der Immobilie nicht
abbildet.

### Fixvertrag

1. API, Import, Raw-row-/Replay-Gate und UI erzwingen dieselbe fachlich
   begründete Rendite-Domain; Extremwerte benötigen einen dokumentierten
   Override oder werden abgewiesen.
2. Ein versioniertes Property-Risk-Modell definiert mindestens Drift,
   Volatilität/Szenarien, Korrelation, Illiquidität und Bewertungsunsicherheit –
   oder erklärt ausdrücklich, warum Property deterministisch ausgeschlossen
   und separat sensitisiert wird.
3. Total-MC benennt Coverage und Modellgrenze. Property-only-p10/p50/p90 dürfen
   nicht als echte Quantile erscheinen, wenn kein Property-Risikomodell wirkt.
4. Return-/Risk-Policy, Quelle, Version und `as_of` werden im Snapshot und in
   der Publikation gebunden.

### Pflichttests

- API-/Update-/Import-/Raw-row-Grenzen und bool/float/string,
- negative, null, plausible und extreme Compounding-Werte,
- Property-only und gemischtes Portfolio mit Quantil-/Sensitivity-Disclosure,
- Korrelation/Szenariowechsel erzeugt neuen Run,
- UI/API/PDF zeigen identische Coverage und Basis.

## `PROPERTY-COLLATERAL-001` – Boolean wird zu 100 Prozent Reservefähigkeit

### Beobachtung

`is_available_for_goal_funding` nimmt jede passende externe Position in
`unlocked_other_assets_rappen` auf. Dieser generische Mechanismus gilt für
jedes freigegebene `Anderes Vermögen`; die Property-spezifische Lücke ist,
dass dabei Bruttoimmobilien ohne Net-of-mortgage-/Verwertungsmodell wirken.
Die Reservefunktion absorbiert damit
externen Reservebedarf Rappen für Rappen. Für eine Direktimmobilie existieren
in diesem Pfad weder LTV, bestehende Liens, Rang, Haircut, Verkaufs-/
Belehnungsmodus, Kosten, Steuer, Liquidationsdauer noch Bewertungsfreshness.

Die Classic UI setzt das Flag für Immobilien im normalen Editorpfad nicht
automatisch. Der Befund behauptet deshalb nicht, jeder UI-Fall erhalte diese
Gutschrift. API, Import, bestehende Daten oder andere Schreibpfade können den
gültigen Boolean jedoch setzen; die Engine behandelt ihn dann wie sofort
liquide 100-Prozent-Deckung.

### Isolierte Reproduktion

Bei identischem Reservebedarf ergab der isolierte Enginefall:

```text
ohne Immobiliengutschrift: (reserve_needed=100000, external_reserve=100000)
mit Bruttoimmobilie:        (reserve_needed=100000, external_reserve=0)
```

Die vollständige Bruttogutschrift erfolgte ohne Hypothekenabzug oder
Collateral-Parameter.

### Wirkung

Eine illiquide oder bereits belastete Immobilie kann kurzfristigen
Liquiditätsbedarf vollständig „decken“. Dadurch können Reserve, SAA und
Zielerreichung zu optimistisch werden.

### Fixvertrag

1. Das Boolean wird durch einen expliziten Funding-Modus ersetzt:
   `none`, `sale`, `pledge`, gegebenenfalls `partial`.
2. Verkauf verwendet Net Proceeds nach Anteil, Schuld, Kosten, Steuer,
   Haircut und Realisationszeit. Belehnung verwendet freigegebenen
   Belehnungswert, Rang, bestehende Liens, LTV und Drawdown-Horizont.
3. Collateral-Berechnung ist link-/tranchengenau, Currency- und
   valuation-as-of-konsistent.
4. Stale, fehlende oder orphaned Evidenz ergibt keine Gutschrift.
5. Reserve- und Goal-Funding-Gutschrift werden getrennt modelliert; eine
   langfristig mögliche Verwertung ist nicht automatisch heutige Liquidität.

### Pflichttests

- Brutto versus Netto nach bestehender Hypothek,
- Verkauf versus Belehnung und Teilverwertung,
- LTV/Haircut/Rang, Kosten/Steuer, Zeit und FX,
- stale/missing valuation und orphaned link,
- Boolean-Legacy-Migration ohne automatische 100-Prozent-Freigabe.

## `MORTGAGE-LINK-001` – Referenz wird nur beim Schreiben geprüft

### Beobachtung

Ein gelieferter `mortgage_linked_property_id` wird beim Create/Update korrekt
auf eine aktive Immobilienposition desselben Kunden geprüft. Das Feld ist aber
optional und als freier String ohne Datenbank-Fremdschlüssel gespeichert. Beim
Soft-Delete oder Deaktivieren einer Immobilie wird nicht nach aktiven
Hypotheken gesucht. Bestands-, Import- und Replaypfade besitzen keinen
gleichwertigen Referential-Integrity-Gate.

Dieser P2-Befund ist eng auf Referenzlebenszyklus und Provenienz begrenzt. Die
finanziellen Folgen clientweiter Verrechnung stehen in
`PROPERTY-UI-PROJECTION-001` und `PROPERTY-COLLATERAL-001`.

### Isolierte Reproduktion

1. Eine gültig verknüpfte Property und Hypothek wurden erzeugt.
2. Die Property wurde über den normalen Router soft-deleted.
3. Danach war `property_deleted=true`, die Hypothek blieb aktiv und enthielt
   weiterhin die ID der gelöschten Property.

Der positive Write-time-Guard wurde dabei nicht umgangen; der Orphan entstand
erst durch einen erlaubten Lebenszyklusübergang.

### Wirkung

Collateral-, Reporting- oder spätere linkgenaue Modelle können nicht sicher
entscheiden, welche Schuld zu welchem aktiven Objekt gehört. Ein erfolgreicher
Write beweist nicht die Gültigkeit zum Run- oder Publikationszeitpunkt.

### Fixvertrag

1. Normalisierte Mortgage-Tranche-/Property-Relation mit Datenbank-FK oder
   gleichwertig erzwungener, dialektgleicher Integrität.
2. Linkpflicht wird fachlich entschieden; fehlender Link ist explizit
   `unallocated`, nicht still globale Zuordnung.
3. Delete/Deactivate verlangt vorher Re-link, Cascade-Entscheidung oder
   expliziten Blocker.
4. Vor Run, Rebuild, Replay und Publikation wird die aktive Relation erneut
   geprüft und in den Snapshot materialisiert.
5. PUT-Omission, explizites `null`, Legacydaten und mehrere Tranchen besitzen
   eindeutige Semantik.

### Pflichttests

- fremder Kunde, falscher Typ, inactive, deleted und unbekannte ID,
- PUT omission/null, Deactivate/Delete, Re-link und Reactivate,
- mehrere Hypotheken je Property und mehrere Properties,
- Legacy-Migration, Replay und Tamper,
- gleicher Client/Tenant über mehrere Mandate sowie negativer
  Same-Tenant-/Wrong-Mandate-Fall,
- SQLite-FK-Konfiguration und echte PostgreSQL-Constraints.

## Zielbild: `PropertyMortgageModelSnapshot`

Ein Digest allein genügt nicht als fachlicher Nachweis. Der moderne Input-Hash
deckt bereits viele Felder und effektive Serien ab; erhalten bleiben muss diese
Tamper-Evidence. Zusätzlich benötigt jeder `TargetAllocation`, jeder
`OptimizerRun` und jede freigegebene Publikation ein materialisiertes,
rekonstruierbares Objekt mindestens mit:

### Property

- Property-ID, Client-/Mandatskontext und Owner-/Household-Anteil,
- Bruttowert, Currency und Bewertungszeitpunkt,
- Bewertungsquelle, Methode, Evidence-Referenz und Freshness-Policy/-Verdict,
- `effective_from`/`effective_until` bzw. versionierter Property-State,
- Nutzung mit Anteilen,
- Mietvertrag mit Brutto-/Netto-Miete, Indexation, Start, Ende und Source-ID,
- Return-/Risk-Modell-ID mit Version, Quelle, `as_of`, Drift,
  Volatilität/Szenarien, Korrelation und Illiquiditätsbehandlung.

### Mortgage tranche

- Tranche-ID, Property-/Collateral-Link und Bank,
- Principal, Currency, Produkt-Enum, aktueller Satz und Laufzeit,
- direkte/indirekte Amortisationsart, Betrag und Schedule,
- Refinance-Policy-ID, Version, Quelle, `as_of` und Szenario,
- Collateral-Rang, LTV, Haircut, bestehende Liens und Verwertungsmodus,
- periodische Interest-, Principal-, Pledged-Asset- und Cost-Komponenten.

### Reconciliation und Provenienz

- stabile Origin-IDs für manual/derived Miete, Zins und Amortisation,
- gewählte Duplicate-/Override-Policy und gegebenenfalls Approval-Evidence,
- kanonische Property-, Liability-, Pledged-Asset- und Net-Wealth-Serie,
- Goal-/Reserve-/Optimizer-/MC-Basis-ID und explizite Reconciliation,
- Code-, Schema-, Modell-, Parameter- und FX-Versionen,
- Input-, Komponenten-, Serien- und Gesamthashes,
- Coverage-/Freshness-/Integrity-Verdicts,
- identische Snapshot-ID in API, Classic UI, React, PDF, Signatur und Handoff.

Der Snapshot ist append-only. Eine Änderung von Bewertung, Eigentumsanteil,
Miete, Term, Refi-Policy, Amortisation, Link, Collateral-Policy, Property-Risk-
Modell oder FX erzeugt einen neuen Snapshot und invalidiert stale
Entscheidungen/Publikationen. Ein alter Run muss ohne Zugriff auf mutable
Current-Rows vollständig replaybar bleiben.

## Remediation-Reihenfolge

### Phase 0 – Falsch-positive Publikation stoppen

1. Advisory-Summary muss gültige Liabilities korrekt ausweisen und Netto
   reconciliieren.
2. Unreconciled manual/derived Flows, ungültige Terms, expired Mortgage ohne
   Refi-State, Orphans und fehlende Bewertungsbasis blockieren neue
   freigaberelevante Berechnungen.
3. Classic UI/React/PDF zeigen `unknown`/Blocker, wenn kanonische Serien oder
   Snapshot-Evidence fehlen.
4. Der Governance-Hold muss operativ gelten; der heutige Code erzwingt ihn
   noch nicht vollständig serverseitig.

### Phase 1 – Strikte Domain und Migration

1. Echte Datumsfelder und getrennte Valuation-/Effectivity-Semantik.
2. Enums für Nutzung, Mortgage-Produkt, Amortisation und Funding-Modus;
   strikte Boolean-/Rate-/Return-Domains.
3. Normalisierte Property-/Mortgage-Tranchenrelation und Lifecycle-Guards.
4. Inventar aller Legacywerte; deterministische Migration oder Quarantäne mit
   reason code. Keine stillen Defaults.

### Phase 2 – Eine Cashflow- und Bilanzidentität

1. Stabiler Origin-Key und genau eine Flow-Source je wirtschaftlichem Event.
2. Kanonischer Mortgage-Schedule für Basis, Refi und Adjustments.
3. Direkte und indirekte Amortisation periodisch reconciliieren.
4. Property-/Liability-/Pledged-/Net-Serien zentral erzeugen und versionieren.

### Phase 3 – Goal, Reserve und Risiko

1. Goal Funding und Total-Publikation teilen eine Basis oder publizieren eine
   explizite, gesnapshotte Reconciliation.
2. Collateral verwendet Net Proceeds/Belehnungswert statt Boolean=Brutto.
3. Property-Risk-/Sensitivity-Modell mit ehrlicher MC-Coverage.
4. Snapshot an TA, Run, Goal Analysis und Reserve Evidence binden.

### Phase 4 – Kanalparität und Abnahme

1. Classic UI entfernt die lokale freigaberelevante Parallelformel.
2. API, React, PDF, Signatur und Handoff verwenden dieselbe Snapshot-ID und
   dieselben Rappenwerte.
3. SQLite-/PostgreSQL-, Browser-, Replay-, Tamper-, Migration-, Concurrency-
   und Golden-Tests ausführen.
4. Erst danach Releaseentscheidung neu treffen; kein Abschluss nur aufgrund
   grüner Happy-Path-Tests.

## Acceptance-Checkliste

Ein Implementierungsstand schließt diesen Audit erst, wenn **alle** folgenden
Punkte belegt sind:

- [ ] Alle elf Finding-IDs besitzen Codefix, Negativtest und Traceability.
- [ ] Ungültige Datums-, Nutzungs-, Mortgage-Type-, Rate-, Maturity- und
      Return-Werte fail-closed.
- [ ] `valuation_as_of` und Cashflow-/Ownership-Effectivity sind getrennt.
- [ ] Bewertung besitzt Source, Methode, Currency, Owner Share und
      Freshness-Verdict.
- [ ] Ein Property-/Mortgage-State im Projektionshorizont ist zeitlich
      eindeutig.
- [ ] Miete, Zins und Amortisation wirken je wirtschaftlicher Source genau
      einmal, unabhängig von Erfassungsreihenfolge.
- [ ] Derived-Fetch-Ausfall erscheint als `unknown`/Blocker.
- [ ] Basiszins plus Adjustment ist in jedem Jahr exakt der Mortgage-Schedule.
- [ ] Bereits abgelaufene Mortgage verwendet expliziten Refi-State oder
      blockiert.
- [ ] Refi-Parameter sind auswählbar, versioniert, gesnapshottet und sichtbar.
- [ ] Direkte Amortisation reduziert Cash und Liability synchron bis zum Cap.
- [ ] Indirekte Amortisation erfüllt in jedem Jahr die Bilanzidentität und
      verliert nach dem Cap keinen Wert.
- [ ] Ein reales und ein synthetisches pledged asset werden nie doppelt gezählt.
- [ ] Property-/Mortgage-Link bleibt bei Update, Delete, Deactivate, Replay und
      Publikation gültig.
- [ ] Ein fehlender Mortgage-Link ist explizit `unallocated`; eine
      normalisierte Relation oder gleichwertige, dialektgleiche
      Datenbankintegrität verhindert Orphans auf SQLite und PostgreSQL.
- [ ] Goal/Reserve verwenden link- und tranchengenaue Werte.
- [ ] Collateral-Gutschrift berücksichtigt Schuld, LTV, Rang, Haircut, Kosten,
      Steuer, FX und Zeit.
- [ ] Ein Boolean kann nicht mehr 100 Prozent Bruttoimmobilie sofort liquide
      machen.
- [ ] Goal-Decision- und Published-Basis sind gleich oder explizit
      reconciliert und gleich gekennzeichnet.
- [ ] Property-Risk-/Sensitivity-Coverage und MC-Grenzen sind sichtbar.
- [ ] Extreme Return-Werte werden domainseitig abgewiesen oder approved.
- [ ] Bruttoassets minus Liabilities ergibt exakt Nettovermögen.
- [ ] Advisory API, Classic UI, React und PDF publizieren dieselben Werte.
- [ ] Fehlende Liability-/Valuation-Coverage wird nie als null ausgegeben.
- [ ] `PropertyMortgageModelSnapshot` ist materialisiert, append-only und an
      TA/Run/Publikation gebunden.
- [ ] Jeder relevante Input-/Policywechsel erzeugt neuen Hash und stale state.
- [ ] Ein alter Run ist ohne mutable Current-Rows replaybar.
- [ ] Legacydaten sind migriert oder quarantänisiert.
- [ ] SQLite und PostgreSQL erzwingen dieselben fachlichen Invarianten.
- [ ] Concurrent Create/Update/Delete kann keine Dublette oder Orphan erzeugen.
- [ ] Browser-/API-/PDF-Golden und Tampertests sind grün.
- [ ] Frühere Blocker und Positivkontrollen bleiben geschlossen bzw. erhalten.
- [ ] Der reale Release-Hold wurde nach dokumentierter Evidence neu bewertet.

## Claude-/GPT-Startcheckliste

Claude, GPT oder ein anderer Umsetzungsagent muss vor Änderungen:

1. diesen Audit vollständig lesen,
2. danach den Audit vom 13. September 2026 und die hier abgegrenzten Goal-,
   Reserve-, MC-, Depot- und Basisdokumente lesen,
3. den tatsächlichen Head und alle Codeanker erneut prüfen,
4. die elf IDs unverändert in Commits, Tests und Abschlussbericht verwenden,
5. zuerst einen Legacy-Daten- und Migrationsplan erstellen,
6. `PropertyMortgageModelSnapshot` sowie die periodische Bilanzidentität vor
   UI-Patches spezifizieren,
7. keinen Labelregex-, HTML-only-, Current-row- oder rein kosmetischen Fix als
   Abschluss akzeptieren,
8. keine Behauptung von Cross-Tenant-Leak, vollständigem Response-Verlust oder
   bereits vorhandenem Server-Hard-Gate übernehmen,
9. 3 Prozent/5 Jahre als zu versionierende Modellannahme behandeln, nicht ohne
   fachliche Entscheidung entfernen,
10. die vorhandene Link-Write-Prüfung, FX-Fail-closed-Logik, Hashabdeckung,
    direkte Payoff-Kappung und MC-Series-Validierung bewahren,
11. jeden Fix mit Negativ-, Replay-, Cross-Channel- und PostgreSQL-Test belegen,
12. am Ende eine Finding-Matrix `geschlossen/offen/teilweise` mit
    Commit-, Test- und Migrationsnachweis aktualisieren.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

```text
branch: codex/asset-allocation-stochastic-core
HEAD: ae6f089df9be059ff0ea48602056f51fee8c634b
tracked changes: none
```

`git status` konnte mehrere bereits vorhandene, ACL-geschützte
`.pytest*`-Verzeichnisse nicht lesen. Deshalb wird keine globale
Worktree-Cleanliness behauptet. Diese historischen Verzeichnisse wurden weder
betreten noch geändert noch entfernt.

### Isolierte Runtime-Reproduktionen

Es wurden 13 reproduzierbare Gruppen ohne Produktcodeänderung ausgeführt:

1. Schemaakzeptanz freier Property-/Mortgage-Werte,
2. manual plus derived Rent/Zins,
3. reihenfolgeabhängige Tilgung und Router-Orphan,
4. zukünftige Valuation versus Cashflow-Start,
5. Fixed-/SARON-/malformed-Maturity-Schedules,
6. bereits abgelaufene Festhypothek: Schedule versus effektiver Cashflow,
7. Negative-rate Derived-/Adjustment-Abweichung,
8. indirekte Amortisation nach Principal-Cap,
9. 1.000-Prozent-Property-Compounding,
10. echte Classic-UI-Funktionsausführung für Property/Amortisation,
11. Property- versus CPI-Goal-Basis,
12. Bruttoimmobilie als vollständige externe Reservegutschrift,
13. Advisory-Report-Liability-Publikation.

Die temporären Harness-Dateien, isolierten Datenbanken und neu erzeugten
Testverzeichnisse wurden nach Auflösung und Workspace-Pfadprüfung entfernt.

### Fokussierter Bestands-Gate

Der erste fachliche Lauf über die relevanten Property-, Mortgage-, Cashflow-,
Goal-, Reserve-, MC-, UI- und Advisory-Testdateien lieferte zunächst
`118 passed, 18 errors`. Alle 18 Fehler entstanden beim TestClient-Startup in
einer gemeinsam verwendeten Benutzerdatenbank durch die Migrationstabelle
`risk_assessment_answers__old`; es waren keine Assertion-Fehler.

Die 18 Fälle wurden mit isoliertem `DB_PATH` und deaktiviertem Scheduler erneut
ausgeführt:

```text
18 passed, 1 warning in 15.56s
```

Damit waren die ersten 136 ausgewählten Fälle fachlich grün. Ein zweiter,
disjunkter Gate über Engine-Cashflow-Konsistenz, Goal Liabilities, Total-MC,
Runtime-Linkverträge und Advisory-Summary lieferte:

```text
56 passed in 26.48s
```

Gesamte fokussierte Evidenz dieser Runde:

```text
192 passed
0 failed after isolation
```

Ein unabhängiger Agenten-Spotcheck reproduzierte die fünf Kernfälle Refi,
indirekte Amortisation, Goal-Basis, Classic-UI-Projektion und
Liability-Publikation exakt. Sein zusätzlicher, inhaltlich überlappender
Testlauf lieferte `62 passed` und einen Setup-Fehler auf dem gesperrten globalen
Pfad `C:\Users\Emanuele\AppData\Local\Temp\pytest-of-Emanuele`. Betroffen war
`test_ausgangslage_wealth_summary_aggregates_positions`; derselbe Testknoten
bestand im isolierten 56er-Gate. Der WinError-5-Fall wird deshalb transparent
als Infrastrukturhinweis dokumentiert, aber nicht als Produktfehler oder
zusätzlicher bestandener, disjunkter Test gezählt.

Dies ist kein vollständiger Backend-, Electron-, Browser- oder
PostgreSQL-Release-Gate. Der letzte dokumentierte vollständige Backend-Gate
aus dem vorherigen Audit bleibt `6074 passed, 0 failed`; er wurde auf diesem
Head nicht erneut ausgeführt.

### Warum der grüne Gate die Findings nicht schließt

- Double-count-Tests akzeptieren manual plus derived bzw. warning-only.
- Mortgage-Schedule-Tests pinnen 3 Prozent, fünf Jahre und die ungekappte
  indirekte Adjustment-Behandlung.
- Der Indirect-Foundation-Test endet vor der entscheidenden Post-Cap-Phase.
- Der MC-Test verlangt ausdrücklich dieselbe Property-Serie in p10/p50/p90.
- Advisory-Report-Tests besitzen keinen schema-validen Liability-Fall.
- Es fehlen expired-at-start, negative-rate, delete-orphan, extreme-return,
  Goal-basis-divergence und Cross-Channel-Net-Wealth-Negativtests.

### Nicht ausgeführte Prüfungen

- kein vollständiger Backend-/Electron-Release-Gate auf diesem Dokumentcommit,
- keine echte PostgreSQL-/FK-/Concurrency-Abnahme,
- kein vollständig gestarteter Browser-/Electron-E2E,
- keine PDF-Pixel-/Golden-Sichtprüfung,
- keine Legacy-Produktionsdatenmigration,
- keine fachliche Freigabe eines Valuation-, Refi-, Collateral- oder
  Property-Risk-ParameterSets.

Diese Grenzen reduzieren nicht die Gültigkeit der isolierten Repros, begrenzen
aber jede Aussage über vollständige Releasebereitschaft.

## Dokumentationsmanifest und Commitvertrag

Diese Runde darf genau folgende fünf Dokumentationspfade verändern:

1. `docs/audits/2026-09-14-direct-property-mortgage-amortization-and-publication-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Produktcode, Migrationen und Tests bleiben unverändert. Vor Commit sind
mindestens auszuführen:

```text
git diff --check
git diff --name-only
rg -n "PROPERTY-|MORTGAGE-|LIABILITY-PUBLICATION-001|PropertyMortgageModelSnapshot" docs
git status --short --branch
```

Die Dokumentcommit-ID wird nicht in dieselbe Datei hineingeschrieben, weil das
einen selbstreferenziellen Hash erzeugen würde. Sie ist extern reproduzierbar
mit:

```text
git log -1 --format=%H -- docs/audits/2026-09-14-direct-property-mortgage-amortization-and-publication-integrity-audit.md
```

## Releaseentscheidung

Die reale Nutzung für Immobilien-/Hypothekenberatung, Goal Funding,
Reserve-/Risikoclaims und entsprechende API-/UI-/React-/PDF-/Signatur-/
Handoff-Publikationen bleibt **governance-seitig blockiert**.

Der heutige Runtimepfad erzwingt diese Sperre nicht vollständig. Eine Freigabe
ist erst vertretbar, wenn:

1. alle zehn P1-Verträge und der P2-Referenzvertrag umgesetzt oder mit
   dokumentierter, fachlich akzeptierter Restabweichung entschieden sind,
2. der materialisierte `PropertyMortgageModelSnapshot` die kanonische Bilanz-
   und Modellbasis an Entscheidung und Publikation bindet,
3. genau-einmal-Cashflows, Terms, Refi, direkte/indirekte Amortisation,
   Collateral, Goal-Basis, Risikomodell und Nettovermögen nachweislich
   reconciliieren,
4. API, Classic UI, React, PDF, Signatur und Handoff dieselben Werte und
   dieselbe Snapshot-ID verwenden,
5. und alle Acceptance-Punkte auf SQLite sowie echter PostgreSQL-/Browser-/
   PDF-Zielumgebung belegt sind.

Dieser Audit schließt keinen früheren Releaseblocker.
