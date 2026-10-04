---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-alternative-custom-asset-valuation-tradability-publication-integrity-followup-audit"
status_as_of: "2026-09-21"
audit_started_on: "2026-09-21"
audit_completed_on: "2026-09-21"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "5efea8634363982ed3a8372ea8e0591804a663e2"
prior_release_audit_path: "docs/audits/2026-09-16-liquidity-instrument-availability-yield-and-funding-integrity-audit.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-21-alternative-custom-asset-valuation-tradability-and-publication-integrity-audit.md"
audit_mode: "read_only_static_ui_router_service_orm_schema_migration_test_review_plus_isolated_python_reproduction_and_isolated_pytest_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "Alternative and Custom WealthPosition classification, subtype and assignment semantics, valuation provenance and freshness, liquidity and tradability, risk and return basis, funding eligibility, API/UI roundtrip, input hash, depot analytics, advisory/PDF publication and downstream snapshot provenance"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 4
confirmed_prior_p1_extension_groups: 2
confirmed_prior_p1_ids: 6
static_register_rows_confirmed: 6
isolated_runtime_harnesses_confirmed: 1
isolated_runtime_checks_confirmed: 12
focused_existing_tests_passed: 535
focused_existing_tests_skipped: 1
focused_existing_tests_failed_after_isolation: 0
focused_existing_test_runs_confirmed: 2
isolated_frontend_javascript_executed: false
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "introduce one immutable AlternativeAssetModelSnapshot with typed subtype terms, one evidence-backed AlternativeValuationSnapshot and one periodized AlternativeTradabilitySchedule under the existing AllocationRunInputManifest; close and migrate Alternative/Custom/subtype/assignment/valuation/liquidity domains; remove or explicitly compose Custom instead of inventing a default portfolio; separate current-holding valuation and risk from target-SAA assumptions; either govern asset_expected_return_bps as an effective model input or remove the claim that it drives simulation; preserve every effective field through API/UI/hash/publication; reuse the existing cross-asset availability, liability, illiquidity-limit and publication contracts; fail closed on unknown, stale, unvalued, locked, liability-misclassified, unbound or unreconciled state before generation, finalization, PDF, signature and handoff"
---

# Alternative-/Custom-Asset-, Bewertungs-, Handelbarkeits- und Publikations-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die zweiunddreißigste Read-only-
Kontrollrunde. Sie wurde am 21. September 2026 auf dem unveränderten
Repository-Head `5efea8634363982ed3a8372ea8e0591804a663e2` durchgeführt.
Produktcode und Tests wurden nicht verändert. Erst nach Abschluss der
technischen Prüfung werden exakt fünf Dokumentationspfade angepasst.

Der Audit bewertet weder die Marktattraktivität konkreter Private-Equity-
Fonds, Edelmetalle, Kryptowerte oder Sammlerstücke noch gibt er eine
Anlageempfehlung. Er prüft ausschließlich den technischen Vertrag:

1. ob `position_type="Alternative"` und `position_type="Custom"` geschlossene,
   nachvollziehbare Bedeutungen besitzen,
2. ob Subtyp, Bewertungsbasis, Liquidierbarkeit, Standort/Verwahrer,
   Rendite- und Risikomodell wirksam, valide und reproduzierbar sind,
3. ob eine aktuelle Bewertung von Versicherungswert, Selbstschätzung und
   historischem Gutachten fachlich getrennt bleibt,
4. ob illiquide oder gebundene Werte nur periodengerecht als handelbar,
   reservefähig oder zielfinanzierend gelten,
5. ob ein aktueller Bestand nicht aus Ziel-SAA-Annahmen oder einem erfundenen
   Custom-Mischportfolio modelliert wird,
6. ob API, Classic UI, Engine, Depot-Check, Advisory-Report und PDF denselben
   Positionstyp, dieselbe Bewertung und dieselbe Liquidität verwenden,
7. und ob jeder wirksame Fachwert im unveränderlichen Run- und
   Publikationssnapshot gebunden ist.

Der Audit ergänzt insbesondere:

1. den unmittelbar vorherigen
   [Liquiditätsinstrument-/Verfügbarkeits-/Zins-/Funding-Integritätsaudit](2026-09-16-liquidity-instrument-availability-yield-and-funding-integrity-audit.md),
2. den
   [Direktimmobilien-/Hypotheken-/Amortisations-/Publikations-Integritätsaudit](2026-09-14-direct-property-mortgage-amortization-and-publication-integrity-audit.md),
3. den
   [Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Integritätsaudit](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md),
4. den
   [Anlagepräferenz-/ESG-/Exclusion-/Recommendation-Constraint-Integritätsaudit](2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md),
5. sowie die
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Für Aussagen über den **beobachteten Ist-Stand** gelten aktueller Code, Tests
und Migrationen zuerst. Für den **zu implementierenden Zielvertrag** gilt
dieser Audit vor älteren Dokumenten. Bestandstests, die heutige Default- oder
Hashsemantik pinnen, sind Evidenz des Ist-Stands und keine Freigabenorm.

### Verhältnis zu vorhandenen Findings

Dieser Audit erzeugt keinen neuen generischen Availability-, Liability-,
Illiquiditätslimit- oder Depot-Publikationsvertrag:

- `PENSION-AVAILABILITY-001` und `PROPERTY-COLLATERAL-001` decken bereits ab,
  dass ein Funding-Boolean keinen periodischen Verkaufs-, Belehnungs-,
  Haircut- oder Settlementvertrag ersetzt.
- Der Runde-31-Vertrag verlangt bereits getrennte Serien für `advised`,
  `tradable`, `reserve_available` und `goal_available`.
- `PREF-LIMIT-001` verlangt bereits einen finalen Verdict über tatsächlich
  wirksame illiquide Positionen und nicht nur über Zielbausteine.
- `LIABILITY-PUBLICATION-001` verlangt bereits `gross_assets`,
  `liabilities` und `net_wealth` statt positiver Liability-Beträge als Asset.
- `DEPOT-VERDICT-001` und `DEPOT-PUBLICATION-001` verlangen bereits eine
  vollständige, aktuelle Ist-Bewertung und kanalgleiche Provenienz.

Neu und enger sind die fehlende Alternative-/Custom-Typsemantik, das
Alternative-spezifische Bewertungsmodell, der erfundene Custom-Mix sowie der
Alternative-spezifische Roundtrip-/Publikationsverlust. Diese vier Probleme
erhalten eigene IDs. Die genannten Cross-Asset-Verträge werden nur um neue
Evidence erweitert.

Alle Release-Sperren in diesem Dokument sind Governance-Akzeptanzkriterien.
Sie beschreiben keine bereits lückenlos implementierte technische Sperre.

## Kurzurteil

Der aktuelle Stand darf **nicht** als konsistente Beratungs-, Optimierungs-
oder Publikationsbasis für Alternative- oder Custom-Vermögenspositionen
freigegeben werden.

Bestätigt sind vier neue P1-Verträge:

1. **`ALTERNATIVE-INSTRUMENT-MODEL-001`:** API und ORM akzeptieren freie
   Subtypen, freie Liquiditäts- und Bewertungsbegriffe sowie erwartete
   Renditen bis 1.000 Prozent. Das statische SQLite-Schema kennt teilweise
   CHECK-Domains, die Alembic-Baseline nicht. Unabhängig von Subtyp und
   deklarierter Rendite wird jede Alternative-Position zu 100 Prozent in den
   generischen Alternatives-Bucket gelegt. Dessen aktuelle Projektion erhält
   die Ziel-Suballocation-/CMA-Momente; der positionseigene Subtyp und die als
   simulationswirksam bezeichnete Rendite steuern die Position nicht.
2. **`ALTERNATIVE-VALUATION-001`:** Ein positiver Betrag, ein freies Datum und
   Begriffe wie Selbstschätzung, Versicherungswert oder Marktpreis reichen als
   vollständige Bewertung. Bewertungsquelle, Objekt-/Anteilidentität,
   Preisquelle, Beleg, Fair-Value-Abgrenzung, Freshness, Confidence, Kosten und
   Haircut fehlen. Stale oder nicht marktwertgleiche Werte fließen ohne
   Readiness-Verdict in Vermögen, Engine und Publikation.
3. **`CUSTOM-CLASSIFICATION-001`:** Dasselbe `Custom`-Asset erscheint im
   Editor als Alternative, in Classic UI und Engine als fest erfundenes
   50/20/10/5/15-Mischportfolio und im Server-PDF als 100 Prozent Liquidität.
   Der Editor sendet beim Speichern zwar `position_type="Alternative"`, das
   Update-Schema verwirft dieses Feld jedoch; die persistierte Position bleibt
   `Custom`. Damit existieren gleichzeitig drei unvereinbare Wahrheiten.
4. **`ALTERNATIVE-PUBLICATION-001`:** `asset_location` fehlt im API-Response,
   obwohl es gespeichert und von der UI erwartet wird. Ein Edit öffnet es leer
   und kann es löschen. Null-/Legacywerte werden als Private Equity, liquide
   unter 30 Tagen und Marktpreis materialisiert. Subtyp, Liquidität,
   Bewertungsmethode und Standort fehlen im Positionshash; ausgerechnet die
   für Alternative wirkungslose Rendite ist enthalten. Advisory-/PDF-Kanäle
   publizieren keine vollständige Bewertungs-/Liquiditätsprovenienz.

Zusätzlich sind zwei Erweiterungsgruppen über sechs bestehende P1-IDs mit
neuer Alternative-/Custom-Evidence bestätigt:

5. `PENSION-AVAILABILITY-001`, `PROPERTY-COLLATERAL-001` und
   `PREF-LIMIT-001`: illiquide oder gebundene Alternative-Positionen können
   durch ein Boolean vollständig und sofort für Goal-/Reservezwecke aktiviert
   werden; der finale Illiquiditätsverdikt betrachtet nur Ziel-Private-Equity,
   nicht den tatsächlichen Bestand.
6. `LIABILITY-PUBLICATION-001`, `DEPOT-VERDICT-001` und
   `DEPOT-PUBLICATION-001`: Alternative/Custom dürfen als positive Liability
   gespeichert werden, können im Report dennoch als Vermögen erscheinen und
   erzeugen Alternative-Ampeln bzw. Kundenpublikationen ohne vollständige
   Ist-Bewertungs- und Klassifikationsbasis.

Es wurde **kein neuer P0** bestätigt. Alle früheren offenen P0/P1 bleiben
unverändert offen.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `ALTERNATIVE-INSTRUMENT-MODEL-001` | P1 | neu bestätigt | Freie/dialektdriftende Alternative-Terms, generischer Bucket und zielbasierte CMA-Momente ersetzen einen subtyp- und positionsrichtigen Return-/Riskvertrag; das sichtbare Renditefeld ist für Alternative inert. |
| `ALTERNATIVE-VALUATION-001` | P1 | neu bestätigt | Betrag, freies Datum und Methodenlabel ersetzen Quelle, Evidence, Freshness, Fair Value, Confidence, Kosten und Haircut; unbewertete oder stale Positionen erhalten kein Readiness-Verdict. |
| `CUSTOM-CLASSIFICATION-001` | P1 | neu bestätigt | Custom wird je nach Consumer als Alternative, fixes 50/20/10/5/15-Portfolio oder Liquidität behandelt; Update und UI lösen die persistierte Ambiguität nicht. |
| `ALTERNATIVE-PUBLICATION-001` | P1 | neu bestätigt | API/UI verlieren Standort und materialisieren Default-Fakten; der Hash lässt wirksame Alternative-Terms aus und Kundenkanäle publizieren keine vollständige Bewertungs-/Liquiditätsprovenienz. |
| `PENSION-AVAILABILITY-001` / `PROPERTY-COLLATERAL-001` / `PREF-LIMIT-001` | P1 | Alternative-/Custom-Erweiterung bestätigt | Ein Boolean kann den vollen Principal ohne Settlement/Haircut aktivieren; tatsächliche illiquide Bestände sind nicht Teil des finalen Limits. |
| `LIABILITY-PUBLICATION-001` / `DEPOT-VERDICT-001` / `DEPOT-PUBLICATION-001` | P1 | Alternative-/Custom-Erweiterung bestätigt | Positive Liabilities, Surrogatklassifikation und unvollständige Alternative-Evidence können Vermögenssumme, Verdict und Publikation verfälschen. |

## Positivkontrollen, die erhalten bleiben müssen

Die Reparatur darf folgende vorhandene Schutzmechanismen nicht zurückbauen:

1. Create akzeptiert nur die kanonischen Top-Level-Typen und Assignments.
2. Hypotheken müssen Liability und Direktimmobilien externes Vermögen sein.
3. `current_value_rappen` ist nicht negativ und besitzt eine großzügige
   Obergrenze.
4. Explizite Depot-Allokationen müssen in Create 10.000 Basispunkte ergeben.
5. Fremdwährungen werden im kanonischen Enginepfad über dieselbe FX-Basis
   umgerechnet; fehlende Modell-FX-Raten sollen fail-closed bleiben.
6. Alternative Wertsteigerung wird heute bewusst nicht zusätzlich als
   Cashflow abgeleitet. Diese Exactly-once-Absicht ist richtig; offen ist der
   fehlende positionsrichtige Return-/Riskvertrag.
7. Der bestehende v2/v3/v4-Hash bleibt als historischer Verifikationsanker
   lesbar. Er darf nicht rückwirkend semantisch umdefiniert werden.
8. Der `maxIlliquid`-Mechanismus deckelt im Zielportfolio den als illiquide
   registrierten Private-Equity-Baustein. Diese Kontrolle bleibt erhalten und
   wird um tatsächliche Bestände und weitere registrierte illiquide Typen
   ergänzt.

## Tatsächlicher Datenfluss und die Divergenz

| Schritt | Alternative | Custom | Verlust/Erfindung |
|---|---|---|---|
| API Create | geschlossener Top-Level-Typ, aber freie Fachfelder | als Top-Level-Typ erlaubt | keine subtype-spezifische Required-/Forbidden-Matrix |
| API Update | Fachfelder erlaubt, `position_type` fehlt | Typ kann nicht explizit migriert werden | gesendeter Typ wird standardmäßig ignoriert |
| API Response | vier Fachfelder, aber kein `asset_location` | gleich | gespeicherter Standort fehlt |
| Classic Editor | Alternative-Maske | als Alternative-Maske geöffnet | Nullwerte werden zu PE/liquide/Marktpreis; Standort leer |
| Classic Projektion | 100 % alternatives | 50 % Aktien, 20 % Bonds, 10 % Immobilien, 5 % Alternatives, 15 % Liquidität | nicht belegter Defaultmix |
| Backend Summary | 100 % alternatives | derselbe 50/20/10/5/15-Mix | nicht belegter Defaultmix |
| Depot-Check | generisch alternatives; UI-Liquiditätsvokabular meist nicht erkannt | Fallback liquidity | widersprüchliche Buckets/Tiers |
| Server-PDF | alternatives | Fallback liquidity | Custom wird als Cash publiziert |
| Inputhash | Return enthalten; Subtyp/Liquidität/Methode/Standort fehlen | gleich | false positive und false negative Drift |
| Advisory-/PDF-Evidence | Betrag/Top-Level-Bucket | Betrag/Fallback-Bucket | keine Valuation-/Tradability-/Coverage-Evidence |

Der Kernfehler ist keine einzelne falsche Mappingzeile. Es fehlt ein
gemeinsames, versioniertes Fachobjekt, das **Identität, Bewertung,
Handelbarkeit, Modellbasis und Publikationsbasis** derselben Position
unveränderlich bindet.

## Codeanker auf dem auditierten Head

| Vertrag | Codeanker |
|---|---|
| Create-Typen/Assignments und freie Alternative-Felder | `5eyes-backend/schemas/wealth.py:12-69` |
| Update ohne `position_type`, freie Alternative-Felder | `5eyes-backend/schemas/wealth.py:112-162` |
| Response ohne `asset_location` | `5eyes-backend/schemas/wealth.py:173-229` |
| ORM-Spalten ohne fachliche Constraints | `5eyes-backend/models/wealth.py:46-50` |
| Statisches SQLite-Schema mit partiellen CHECKs | `5eyes-backend/5eyes_schema_v4.0_FINAL.sql:576-584` |
| Alembic-Baseline ohne diese CHECKs | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:692-696` |
| Semantikmatrix beschränkt nur Immobilie/Hypothek | `5eyes-backend/services/wealth_position_semantics.py:35-52,160-191` |
| Backend-Defaultgewichte Alternative/Custom | `5eyes-backend/services/portfolio_engine.py:592-624` |
| Engine-validiert Alternative-Terms nicht | `5eyes-backend/services/portfolio_engine.py:706-750` |
| Advisory-/Liability-/Unlock-Aggregation | `5eyes-backend/services/portfolio_engine.py:1874-1915` |
| Positionshash enthält Return, nicht Subtyp/Liquidität/Methode/Standort | `5eyes-backend/services/portfolio_engine.py:2332-2379` |
| Generische Alternatives-CMA und Subasset-Momente | `5eyes-backend/services/portfolio_engine_cma.py:298-405`; `5eyes-backend/services/portfolio_engine.py:1209-1215` |
| Current und Target verwenden dieselben gewichteten Bucket-Momente | `5eyes-backend/services/portfolio_engine_mc_simulation.py:483-572` |
| Ziel-Illiquiditätscap auf registrierte Suballocations | `5eyes-backend/services/portfolio_engine_house_matrix.py:820-875` |
| Depot-Liquiditätstier und unbekannter Typ-Fallback | `5eyes-backend/services/depot_check.py:106-133,176-193` |
| Server-PDF-Bucket und Custom-Fallback | `5eyes-backend/routers/pdf_reports.py:133-154,192-245` |
| Advisory-Vermögenssumme und Kreditheuristik | `5eyes-backend/services/advisory_report.py:651-701` |
| PDF-Vermögensübersicht ohne Alternative-Evidence | `5eyes-backend/services/pdf/components/vermoegensuebersicht.py:1-92` |
| Classic-Alternative-Form und UI-Claim | `5eyes-electron/frontend/5eyes_v2.html:4769-4784,4900-4935` |
| Classic Alternative/Custom-Edit und Defaults | `5eyes-electron/frontend/5eyes_v2.html:16970-17066` |
| Classic Beschreibung nur für Alternative | `5eyes-electron/frontend/5eyes_v2.html:17389-17416` |
| Classic Alternative-Payload | `5eyes-electron/frontend/5eyes_v2.html:23372-23449` |
| Classic Alternative-/Custom-Projektionsmix | `5eyes-electron/frontend/5eyes_v2.html:6599-6617` |
| Bestandstests ohne Alternative-Roundtrip-/Custom-Paritätsvertrag | `5eyes-backend/tests/test_depot_illiquid_classification.py`; `5eyes-backend/tests/test_wealth_cashflows.py`; `5eyes-backend/tests/test_audit_z6_anchors.py` |

## `ALTERNATIVE-INSTRUMENT-MODEL-001` – Deklarierte Fachfelder steuern kein positionsrichtiges Modell

### Beobachtung

`asset_subtype`, `asset_liquidity`, `asset_valuation_method` und
`asset_location` sind in Pydantic und ORM freie Strings. Nur das historische
statische SQLite-DDL begrenzt Liquiditäts- und Methodenlabels; die Alembic-
Baseline tut dies nicht. Create/Update akzeptieren deshalb je nach
Installationspfad unterschiedliche Domains.

`asset_expected_return_bps` erlaubt Werte größer als -100 Prozent bis
einschließlich 1.000 Prozent. Die UI bezeichnet das Feld als „Für Simulation
und Prognose“. Für `position_type="Alternative"` wird es jedoch weder als
Cashflow noch als eigener positionsbezogener Return verwendet. Die Position
wird zu 100 Prozent dem Bucket `alternatives` zugeordnet. Deterministische und
Monte-Carlo-Pfade nutzen für Current und Target dieselben aus der Ziel-
Suballocation gewichteten Bucket-Momente. Ohne Suballocation fällt der
Alternatives-Bucket auf die generische Gold-CMA zurück.

Damit können Kunst, Krypto, physisches Gold, Private Equity und Hedgefonds
denselben Modellpfad erhalten. Umgekehrt kann eine Änderung des sichtbaren
Renditefelds zwar den Inputhash ändern, ohne das Ergebnis der Positionssummary
zu verändern.

### Isolierte Reproduktion

Ein temporärer, nach der Prüfung wieder entfernter Python-Harness importierte
die produktiven Schemas und Enginehelfer. Er bestätigte:

```text
asset_subtype              = "beliebig"       -> akzeptiert
asset_expected_return_bps  = 100000            -> akzeptiert (1.000 %)
asset_liquidity            = "teleportierbar" -> akzeptiert
asset_valuation_method     = "Orakel"         -> akzeptiert
asset_location             = "Tresor"         -> akzeptiert

Alternative bucket weights = 0/0/0/10000/0
Custom bucket weights      = 5000/2000/1000/500/1500

Alternative-Return geändert:
  PortfolioSummary vorher == nachher
  Inputhash vorher != nachher
```

Die Zahlenreihenfolge ist Aktien/Obligationen/Immobilien/Alternatives/
Liquidität. Die Reproduktion bewertet nicht, welcher Return fachlich richtig
wäre. Sie belegt nur, dass das deklarierte Feld keine entsprechende
positionsbezogene Wirkung besitzt.

### Wirkung

- Current-Portfolio-Risiko kann aus Ziel-SAA-Annahmen statt aus dem
  tatsächlichen Asset abgeleitet werden.
- Ein Kunstwerk kann Gold-, Hedgefonds- oder PE-Risikomomente erben, ohne dass
  diese Zuordnung gespeichert oder publiziert wird.
- 1.000 Prozent erwartete Rendite kann als plausibles UI-Fachdatum gespeichert
  werden, obwohl sie keinen erklärten Modellvertrag besitzt.
- Ein Run kann wegen einer inerten Renditeänderung driften, während wirksame
  Liquiditäts- oder Bewertungsänderungen unbemerkt bleiben.
- Ein Berater kann die Prognosewirkung des Felds nicht aus UI, API oder Report
  nachvollziehen.

### Fixvertrag

1. Eine versionierte `AlternativeAssetPolicy` definiert geschlossene
   Top-Level-Typen, Subtypen, Assignments und zulässige Felder.
2. Jeder Subtyp besitzt eine registrierte Modellklasse. Unbekannt/Other ist
   entweder ein explizit zusammengesetztes Custom-Modell oder `blocked`; nie
   ein stiller Default.
3. Aktueller Bestand und Ziel-SAA bleiben getrennt:
   - `current_holding_model` bewertet genau das gehaltene Asset,
   - `target_allocation_model` bewertet den vorgeschlagenen SAA-Baustein,
   - eine explizite Bridge erklärt jede Aggregation.
4. `asset_expected_return_bps` wird entweder:
   - entfernt bzw. als rein informatives Szenariofeld eindeutig benannt, oder
   - mit Quelle, as-of, Methodik, Version, Volatilität, Korrelation,
     Bewertungsunsicherheit und Gültigkeitsbereich zu einem wirksamen,
     gehashten Modellinput gemacht.
5. Die Engine darf kein alternatives Asset nur aufgrund des Top-Level-Typs
   mit Gold-/Zielportfolio-Momenten fortschreiben.
6. Die Asset-/Liability-Matrix verbietet `Alternative`/`Custom` als
   `Verbindlichkeit`; ein wirtschaftlicher Schuldvertrag erhält einen eigenen
   Liability-Typ mit Principal, Kosten, Laufzeit und Signum.
7. SQLite, PostgreSQL, Pydantic, ORM-Migration und Frontend verwenden dieselbe
   kanonische Domain oder denselben Registry-Key.

### Pflichttests

1. unbekannter Subtyp, Liquiditätscode oder Bewertungsmethode -> `422` bzw.
   blockierte Legacyposition;
2. jede registrierte Modellklasse besitzt Required-/Forbidden-Feldtests;
3. Kunst/Gold/Krypto/PE/Hedgefonds erzeugen nur bei explizit gleicher
   Modellbasis gleiche Momente;
4. Current-Holding-Momente ändern sich nicht durch eine reine Änderung der
   Target-Suballocation;
5. ein wirksamer Return-/Riskinput ändert Ergebnis und Root-Hash;
6. ein rein informatives Feld ändert weder Ergebnis noch Business-Hash;
7. keine Alternative-/Custom-Assetposition kann als positive Liability
   gespeichert oder als Assetreturn gerechnet werden;
8. SQLite-/PostgreSQL-Domainparität und Legacy-Quarantäne sind abgedeckt.

## `ALTERNATIVE-VALUATION-001` – Ein Methodenlabel ersetzt keine belastbare Bewertung

### Beobachtung

Die Position besitzt `current_value_rappen`, `currency`, ein freies
`valuation_date`, ein freies `asset_valuation_method` und einen freien
Standorttext. Es fehlen mindestens:

- eindeutige Objekt-, Fonds-, Beteiligungs- oder Tokenidentität,
- Eigentums-/Anteil- oder Mengenbasis,
- native Bewertungswährung und FX-as-of,
- Preis-/Gutachter-/NAV-/Marktdatenquelle,
- Evidence-Referenz und Ersteller,
- `valuation_as_of` als validiertes Datum mit Future-Date-Sperre,
- Methodenpolicy und Abgrenzung Fair Value vs. Versicherungswert,
- Freshness-Schwelle und Freshness-Verdict,
- Confidence/Range, Bewertungsunsicherheit, Verkaufskosten und Haircut,
- gegebenenfalls Commitment, unfunded amount, Capital Calls, Side Pockets,
  Gates, Zustand oder Echtheitsnachweis.

Die Engine aggregiert jeden positiven Betrag sofort in Advisory- oder
Gesamtvermögen. Es existiert kein Alternative-Valuation-Readiness-Gate vor
Optimizer, Goal, Reserve, Report oder PDF. Ein Versicherungswert kann deshalb
wie ein realisierbarer Marktwert wirken; eine alte Selbstschätzung wie ein
aktueller NAV.

### Wirkung

- Vermögen, Risikobasis, Reserve- und Goal-Coverage können auf nicht
  realisierbaren oder stale Werten beruhen.
- Brutto-, Netto- und verfügbare Werte sind nicht unterscheidbar.
- Eine spätere Korrektur ist nicht reproduzierbar, weil Quelle und Evidence
  fehlen.
- Kundenpublikationen können einen präzisen CHF-Betrag zeigen, obwohl die
  Bewertung nur grob, alt oder für Versicherungszwecke erstellt wurde.
- Handoff und Trade-/Liquidationsplanung besitzen keine belastbare
  Verkaufspreis- oder Settlementbasis.

### Fixvertrag

Ein unveränderlicher `AlternativeValuationSnapshot` wird je Position und
Bewertungsstichtag erzeugt. Mindestfelder:

```text
snapshot_id, schema_version, position_id, client_id, tenant_id
asset_model_id, asset_identity, ownership_or_quantity
native_currency, gross_value, fx_rate_id, value_in_mandate_currency
valuation_method_code, valuation_source_id, evidence_refs[]
valuation_as_of, received_at, freshness_policy_id, freshness_status
fair_value_status, confidence_or_range, uncertainty_bps
estimated_sale_cost_bps, liquidity_haircut_bps, net_realisable_value
coverage_status, blocking_reasons[], created_at, business_hash
```

Regeln:

1. Versicherungswert ist nicht automatisch Fair Value.
2. Selbstschätzung bleibt als solche sichtbar und kann je Policy nur
   informationswirksam sein.
3. Future-Date, fehlende Quelle, stale Evidence oder unzulässige Methode
   blockieren fachlich betroffene Runs und Publikationen.
4. Freshness ist subtype- und use-case-spezifisch: reine Vermögensübersicht,
   Risikomodell, Goal-Funding und konkrete Liquidation dürfen unterschiedliche
   Schwellen haben; der strengste betroffene Consumer entscheidet.
5. Haircut, Kosten und Steuern werden nicht im Bruttowert versteckt. Gross,
   valuation-adjusted und net realisable bleiben separat reconciliable.
6. Audit-Timestamps dürfen den Business-Hash nicht verändern; fachliche
   Bewertung, Evidence, as-of und Haircut müssen ihn verändern.

### Pflichttests

1. malformed/future `valuation_as_of` -> blockiert;
2. stale NAV/Gutachten -> definierter `stale`-Status und keine stille
   Freigabe;
3. Versicherungswert != Fair Value;
4. Menge × Preis × FX reconciliert zum gespeicherten Wert;
5. Ownership/Commitment/Unfunded und Nettoverkaufswert reconciliert;
6. Source-/Evidence-/Methodenänderung ändert Business-Hash;
7. reine `created_at`-Änderung lässt Business-Hash stabil;
8. API, UI, Report und PDF zeigen denselben Wert, Stichtag, Methode,
   Freshnessstatus und Snapshot-Hash.

## `CUSTOM-CLASSIFICATION-001` – Custom besitzt drei widersprüchliche Wahrheiten

### Beobachtung

`Custom` ist als API-Top-Level-Typ erlaubt. Die Classic UI besitzt jedoch
keine eigene Custom-Kategorie. Sie öffnet eine Custom-Position in der
Alternative-Maske. Beim Speichern erzeugt der Payload-Builder
`position_type="Alternative"`; `WealthPositionUpdate` deklariert dieses Feld
nicht und Pydantic ignoriert es standardmäßig. Die persistierte Zeile bleibt
deshalb `Custom`.

Die Consumer interpretieren sie unterschiedlich:

- `_default_weights_for_position` und `inferPositionBucketMixBps` erfinden
  50 % Aktien, 20 % Obligationen, 10 % Immobilien, 5 % Alternatives und
  15 % Liquidität.
- `_bucket_from_position_type` kennt Custom nicht und fällt im Depot-Check auf
  Liquidität zurück.
- `_bucket_key` im Server-PDF kennt Custom nicht; der Aufrufer fällt ebenfalls
  auf Liquidität zurück.
- Die UI zeigt dem Benutzer dagegen die Alternative-Maske und Alternative-
  Fachfelder.

### Isolierte Reproduktion

Der produktive Update- und Mappingvertrag ergab:

```text
WealthPositionUpdate(position_type="Alternative")
  .model_dump(exclude_unset=True) == {}

Backend/Classic Custom weights:
  equities=5000, bonds=2000, real_estate=1000,
  alternatives=500, liquidity=1500

Server-PDF:
  _bucket_key("Custom") is None
  effective fallback == "liquidity"
```

### Wirkung

- Dasselbe Vermögen besitzt je nach Bildschirm/PDF andere Anlageklasse,
  Rendite, Volatilität und Liquidierbarkeit.
- Ein no-op Edit löst die Ambiguität nicht; er kann sie mit neu
  materialisierten Alternative-Defaults weiter verschärfen.
- Ist-/Soll-Abweichung, Risiko, maxIlliquid, Reserve und Goal-Funding können
  consumerabhängig divergieren.
- Ein PDF kann Custom als Cash ausweisen, während die Engine 85 Prozent davon
  als nichtliquide bzw. riskantere Buckets modelliert.

### Fixvertrag

Es gibt nur zwei zulässige Lösungswege:

1. **Custom abschaffen/migrieren:** Jede Legacyposition wird deterministisch
   einem registrierten Assetmodell zugeordnet oder quarantänisiert.
2. **Custom explizit modellieren:** Die Position enthält eine vollständige,
   benannte Zusammensetzung mit exakt 10.000 Basispunkten sowie eigene
   Valuation-/Tradability-/Riskprovenienz je Bestandteil.

Nicht zulässig ist ein universeller Defaultmix. Eine Migration darf nur mit
belegter Information erfolgen; sonst lautet der Status `incomplete` oder
`blocked`. Update wird als echtes PATCH implementiert oder erhält einen
expliziten, autorisierten Typmigrationsbefehl mit vorher/nachher Evidence,
Version und Revalidation aller subtype-spezifischen Felder.

### Pflichttests

1. Custom ohne explizite Composition -> blockiert/quarantänisiert;
2. Composition summiert exakt 10.000 Basispunkte;
3. API, Classic, React, Engine, Depot und PDF erzeugen denselben Bucketmix;
4. no-op Edit erhält Typ, Felder, Hash und Ergebnis byte-/semantikgleich;
5. Typmigration ist explizit, auditierbar und atomar;
6. unbekannter Typ fällt nie auf Liquidität oder einen Mischportfoliodefault;
7. Legacy-Inventory und Dry-run-Migrationsreport sind vollständig;
8. ein fehlender Bestandteil blockiert statt Restgewicht zu erfinden.

## `ALTERNATIVE-PUBLICATION-001` – Roundtrip, Hash und Kundenkanäle tragen nicht dieselbe Wahrheit

### Beobachtung

`asset_location` wird gespeichert und im Classic Editor gelesen, fehlt aber
im `WealthPositionResponse`. Beim Öffnen bleibt das Feld deshalb leer; das
Vollpayload kann den vorhandenen Wert mit `null` überschreiben.

Für Alternative/Custom setzt der Editor bei fehlenden Werten still:

- `Private Equity / Beteiligung`,
- `Liquide (< 30 Tage)`,
- `Marktpreis`.

Diese Werte sind keine reinen Darstellungsdefaults. Sie behaupten Subtyp,
Handelbarkeit und Bewertungsmethode und können beim Speichern zu persistenten
Fakten werden. Ein unbekannter Legacy-Selectwert kann seinerseits zu leer/
`null` werden.

Der Positionsencoder `_pos_v2`, den der aktuelle v4-Snapshothash nutzt,
bindet `asset_expected_return_bps`, lässt aber `asset_subtype`,
`asset_liquidity`, `asset_valuation_method` und `asset_location` aus. Die
isolierte Reproduktion bestätigte zugleich:

```text
Subtyp + Liquidität + Methode + Standort geändert -> gleicher Inputhash
nur Alternative-Return geändert                  -> anderer Inputhash
Alternative PortfolioSummary vorher/nachher      -> gleich
```

Depot-Liquidität verwendet die englischen Codes `daily`, `weekly`,
`monthly`, `illiquid`, `unknown`. Das UI speichert deutsche Vertragswerte.
Bei einem Kunstwerk ergaben sowohl `Illiquid (> 180 Tage)` als auch
`Liquide (< 30 Tage)` den generischen Alternatives-Fallback `monthly`.
Bei Private Equity gewinnt dagegen die Textheuristik `illiquid`, selbst wenn
die Position als liquide markiert ist.

Kundenkanäle transportieren Betrag und Grobbucket, aber keine vollständige
Kette aus Objektidentität, Bewertungsquelle/-methode/-as-of/-freshness,
Liquiditätsvertrag, Nettoverkaufswert, Coverage, Modellbasis und Root-Hash.

### Wirkung

- Datenverlust kann als erfolgreicher no-op Edit erscheinen.
- Ein Ergebnis bleibt unter demselben Hash, obwohl Handelbarkeit oder
  Bewertungsmethode fachlich geändert wurden.
- Umgekehrt kann ein unwirksames Feld einen unnötigen Drift auslösen.
- UI, Depot-Ampel und PDF können sich gegenseitig widersprechen, ohne dass
  der Nutzer die Abweichung erkennt.
- Historische Reports lassen sich nicht aus dem ausgewiesenen Snapshot
  reproduzieren.

### Fixvertrag

1. Create-, PATCH-/Update- und Response-DTO sind für alle wirksamen Felder
   verlustfrei und symmetrisch.
2. Editor-Placeholder sind keine Persistenzdefaults. Fehlend bleibt fehlend
   und wird sichtbar als `incomplete` behandelt.
3. Ein kanonischer Registry-Code ersetzt UI-/Sprachlabels. Übersetzung erfolgt
   nur an der Darstellungsschicht.
4. Das bestehende `AllocationRunInputManifest` erhält Referenzen und Hashes
   auf Assetmodell, Bewertung und Tradability-Schedule.
5. Der Business-Hash enthält **alle und nur** fachlich wirksamen Daten. Ein
   semantischer no-op behält denselben Hash; jede wirksame Änderung erzeugt
   einen neuen.
6. Historische Hashversionen bleiben verifizierbar, dürfen für neue
   Alternative-Finalisierung aber als `legacy_incomplete` gelten.
7. API, Classic, React, Portal, Advisory-Report, PDF, Signed Artifact und
   Handoff lesen denselben eingefrorenen Snapshot statt live neu zu mappen.
8. Jede Publikation zeigt mindestens Valuation-as-of, Methode, Freshness,
   Liquiditätsklasse/Verfügbarkeit, Coverage-/Blockerstatus, Snapshot-ID und
   Root-Hash oder weist die Analyse explizit als nicht verfügbar aus.

### Pflichttests

1. `asset_location` und jedes andere wirksame Feld roundtrippen exakt;
2. no-op PATCH/PUT ändert weder Daten, Typ, Ergebnis noch Business-Hash;
3. fehlende Werte werden nicht zu PE/liquide/Marktpreis materialisiert;
4. deutsche UI-Labels und kanonische Codes mappen deterministisch bidirektional;
5. unbekannte Legacywerte bleiben sichtbar/blockiert und werden nicht gelöscht;
6. jede wirksame Änderung erzeugt Drift; reine Auditmetadaten nicht;
7. API/Classic/React/PDF/Signed/Handoff besitzen Snapshot-/Hashparität;
8. historische Artefakte verwenden den gespeicherten Snapshot und verändern
   sich nicht durch spätere Live-Datenänderungen.

## Bestehende P1-Erweiterung – Availability, Collateral und Illiquiditätslimit

### Beobachtung

`unlocked_other_assets_rappen` summiert jede aktive Position mit
`assignment="Anderes Vermögen"` und
`is_available_for_goal_funding=true` zum vollen FX-konvertierten Betrag. Der
Pfad berücksichtigt für Alternative/Custom weder `asset_liquidity`, Lock-up,
Notice, Gate, Settlement, Verkaufskosten, Steuer, Haircut, Commitment noch
unfunded Capital Calls.

Der Zielportfolio-Cap behandelt registrierte illiquide Suballocations,
insbesondere Private Equity. Er prüft nicht, ob ein tatsächliches Kunstwerk,
eine Beteiligung oder ein Custom-Bestand die mandatsweite Illiquiditätsgrenze
bereits ausschöpft.

### Gemeinsamer Fixvertrag

Der Runde-31-Cross-Asset-Vertrag wird wiederverwendet:

```text
total_value[t]
advised_principal[t]
tradable_now[t]
reserve_available[t]
goal_available[t]
pledgeable_net_proceeds[t]
committed_unfunded[t]
```

Ein `AlternativeTradabilitySchedule` enthält mindestens Lock-up, Notice,
Redemption Frequency, Gate/Side Pocket, erwartetes Settlement, Markt-/Broker-
Status, Verkaufskosten, Steuerannahme, Haircut, Pledge/LTV/Rang und
periodischen Nettoerlös. Verkauf reduziert Asset-Principal genau einmal;
Belehnung erzeugt getrennte Proceeds und Liability. Der finale
`maxIlliquid`-Verdict aggregiert **Ist plus Ziel** nach derselben registrierten
Illiquiditätsdefinition.

### Zusätzliche Pflichttests

1. bis 2099 gebundenes Asset -> heute weder tradable noch goal-available;
2. Gate/Notice/Settlement verschiebt Verfügbarkeit periodengerecht;
3. Verkaufskosten/Haircut reduzieren nur Nettoerlös, nicht Bruttowert;
4. Belehnung erzeugt Liability und lässt Asset-Principal bestehen;
5. voller Boolean-Unlock ohne Schedule ist blockiert;
6. `maxIlliquid` berücksichtigt vorhandene und vorgeschlagene Positionen;
7. Unknown/Stale/Blocked zählt nicht als liquide Reserve;
8. Report und PDF zeigen dieselben Brutto-/Netto-/Zeitreihen.

## Bestehende P1-Erweiterung – Liability, Depot-Verdict und Publikation

### Beobachtung

Die allgemeine Assignment-Domain erlaubt Alternative/Custom als
`Verbindlichkeit`. Enginepfade ziehen den positiven Principal als Liability
ab. Der Advisory-Report addiert dagegen jeden positiven Positionsbetrag zum
Gesamtvermögen und erkennt Kredite nur über Typtext plus negativen Betrag;
das Schema verbietet negative Positionsbeträge. Eine Alternative-Liability
kann deshalb als Asset erscheinen.

Depot-Check und PDF klassifizieren aus unterschiedlichen Heuristiken.
Alternative-Ampeln und Kundenwerte können damit auf target-implied,
generischem oder falsch gemapptem Bestand beruhen. Dies erweitert die
bestehenden Findings; es rechtfertigt keine neuen generischen IDs.

### Gemeinsamer Fixvertrag

1. Geschlossene Asset-/Liability-Matrix und separate Liabilitymodelle.
2. Eine Vermögensreconciliation publiziert `gross_assets`, `liabilities`,
   `net_wealth`, `advisory`, `tradable`, `reserve_available` und
   `goal_available` aus demselben Snapshot.
3. Depot-Verdicts unterscheiden `available`, `unavailable` und `blocked`.
4. Keine Alternative-Ampel ohne vollständige Valuation-/Classification-
   Coverage.
5. Keine PDF-/Signed-Publication ohne denselben Root-Hash wie Run und
   kundenwirksame UI.

## Zielbild: drei Alternative-Komponenten unter einem bestehenden Root-Manifest

### `AlternativeAssetModelSnapshot`

Der Snapshot beschreibt, **was** gehalten wird und **wie** es modelliert wird:

```text
snapshot_id, schema_version, policy_id
tenant_id, client_id, mandate_id, position_id
position_type, registered_subtype, assignment
asset_identity, legal_owner, ownership_or_quantity
currency, model_class, model_version, model_basis
return_source_id, return_as_of, volatility_source_id, correlation_source_id
valuation_snapshot_id, tradability_schedule_id
cashflow_component_ids[], liability_link_ids[]
coverage_status, blocking_reasons[]
business_hash, created_at
```

### `AlternativeValuationSnapshot`

Der Snapshot beschreibt, **welcher Wert zu welchem Zeitpunkt mit welcher
Evidence** gilt. Er trennt Bruttowert, Fair-Value-Status,
Bewertungsunsicherheit, Haircut, Kosten und Nettoverkaufswert.

### `AlternativeTradabilitySchedule`

Der Schedule beschreibt periodisch, **wann und zu welchem Nettoerlös** die
Position verkauft oder beliehen werden kann. Er enthält auch Capital Calls,
Distributions und unfunded Commitments, wenn der Subtyp dies erfordert.

### Einbindung in `AllocationRunInputManifest`

Es wird kein zweiter generischer Root-Snapshot erfunden. Das in Runde 31
definierte `AllocationRunInputManifest` referenziert die drei
Alternative-Komponenten per ID und Business-Hash. Derselbe Root wird gebunden
an:

- TargetAllocation und jeden OptimizerRun,
- deterministische und Monte-Carlo-Projektion,
- Goal-/Reserve-/Illiquiditäts-Evidence,
- Depot-/Advisory-Analytics,
- Advisory-Report und alle PDFs,
- Finalisierung, Signed Artifact und Handoff.

Ein Consumer darf aus Live-Daten nur einen **neuen** Snapshot erzeugen. Er darf
ein historisches Artefakt nicht unter derselben ID neu interpretieren.

## Verbindliche Subtyp-Termmatrix vor Codeänderung

| Modellklasse | Required | Bedingt/optional | Nicht still ableiten |
|---|---|---|---|
| `PRIVATE_EQUITY_FUND` | Fund-/Share-Class-ID, Vintage, Commitment, Paid-in, NAV/as-of/source, unfunded, Currency, Lock-up, Distribution-/Call-Schedule | Secondary quote, Gate, FX hedge | Liquidität, sofortiger Vollverkauf, Gold-CMA |
| `HEDGE_FUND` | Fund-/Share-Class-ID, NAV/as-of/source, Notice, Redemption Frequency, Gate/Side Pocket, Settlement, Fees | High-water mark, FX hedge | täglich liquide oder PE-Modell |
| `PHYSICAL_GOLD` | Menge, Feinheit, Custody/Location, Preisquelle/as-of, Currency, Spread, Verkaufskosten, Settlement | Zertifikat/Evidence, Versicherung | Fonds-NAV oder Sammlerstückwert |
| `CRYPTO_ASSET` | Asset/Network, Menge, Custody, Preisquelle/as-of, Currency, Markt-/Settlementpolicy | Wallet-/Exchange-Evidence, Staking separat | pauschale 800-bps-Rendite oder Cashklassifikation |
| `COLLECTIBLE` | Objektidentität, Eigentum, Zustand, Bewertungsquelle/methode/as-of, Evidence, Currency, Verkaufszeit/-kosten | Versicherung separat, Provenienz/Zertifikat | Versicherungswert = Fair Value, monatliche Liquidität |
| `INFRASTRUCTURE_OR_PRIVATE_DEBT` | registrierter Vertragstyp, Instrument-/Issuer-ID, Cashflow-/Maturity-/Credit-/Valuationterms | Covenants, Collateral | generischer Alternatives-Bucket ohne Terms |
| `EXPLICIT_CUSTOM_COMPOSITION` | Bestandteile, Registry-Key je Bestandteil, Gewichtsumme 10.000, Bewertung/Tradability je Bestandteil | benannter Aggregationszweck | 50/20/10/5/15-Default |
| unbekannt/`OTHER` | ausreichende Daten zur Registry-Zuordnung | kontrollierter Reviewworkflow | automatische PE-/Gold-/Liquidity-Zuordnung |

Diese Matrix ist vor der Implementierung fachlich freizugeben und zu
versionieren. Sie darf nicht als lose UI-Optionsliste leben.

## Claude-Implementierungsplan

### Phase 0 – Falsch-positive Nutzung stoppen

1. Alternative/Custom-Readiness vor Generate/Rebuild/Finalize/PDF/Sign/Handoff
   serverseitig prüfen.
2. Unknown, stale, unvalued, Custom-ohne-Composition,
   liability-misclassified oder ungehasht -> `blocked`, nicht Warning-only.
3. UI und PDF dürfen blockierte Daten anzeigen, aber keine scheinbar valide
   Rendite-, Risiko-, Reserve-, Goal- oder Liquiditätsaussage daraus ableiten.
4. Den aktuellen Governance-Hold sichtbar machen; keine Behauptung, er sei
   bereits vollständig technisch erzwungen.

### Phase 1 – Domain, Registry und Legacy-Inventar

1. Alle produktiven Werte für Typ, Subtyp, Assignment, Liquidität,
   Bewertungsmethode und Legacy-Custom inventarisieren.
2. Registry-Keys und versionierte Termmatrix definieren.
3. Dry-run-Migrationsreport mit Anzahl je Zielklasse, fehlenden Terms,
   Ambiguität und vorgeschlagener Quarantäne erzeugen.
4. Nur eindeutig belegte Werte automatisch migrieren; Rest quarantänisieren.
5. SQLite/PostgreSQL/Pydantic/ORM/UI auf dieselbe Domain bringen.

### Phase 2 – Valuation und Tradability

1. `AlternativeValuationSnapshot` und `AlternativeTradabilitySchedule`
   implementieren.
2. Source-/Evidence-, Date-/Freshness-, Future-Date-, FX-, Ownership-,
   Gross/Net-/Haircut- und Settlementvalidierung zentralisieren.
3. Fundingmethoden in periodische Sell-/Pledge-Proceeds übersetzen.
4. Capital Calls, Distributions und unfunded Commitments genau einmal in den
   Cashflow-/Liabilityvertrag integrieren.

### Phase 3 – Assetmodell, Custom-Migration und Engine

1. `AlternativeAssetModelSnapshot` und registrierte Resolver implementieren.
2. Current-Holding- und Target-SAA-Modell explizit trennen.
3. Das heutige Custom-Defaultportfolio entfernen.
4. `asset_expected_return_bps` fachlich entscheiden und entweder vollständig
   governieren oder aus der Simulationsbehauptung entfernen.
5. Ist-plus-Ziel-Illiquiditätsverdikt implementieren.

### Phase 4 – Roundtrip, Root-Hash und Consumer

1. Symmetrische DTOs und echtes PATCH/no-op-idempotentes Update einführen.
2. Defaultmaterialisierung aus dem Editor entfernen.
3. Drei Komponentensnapshots in `AllocationRunInputManifest` binden.
4. Engine, MC, Goal, Reserve, Depot, Advisory-Report, React, PDF, Signed und
   Handoff auf den persistierten Root umstellen.
5. Coverage, Blocker, as-of, Methode, Liquidität und Hash kanalgleich
   publizieren.

### Phase 5 – Abnahme und Rollout

1. Unit-, Contract-, Property-, Mutation-, Replay-, Tamper- und Browsertests.
2. Echte PostgreSQL-Migration inklusive Constraints und Rollbackprobe.
3. Legacy-Dry-run gegen anonymisierte Produktionswertedomains.
4. Cross-Channel-Golden-Tests aus einem Root-Snapshot.
5. Parallel-run/Reconciliation vor Aktivierung; keine stille In-place-
   Neuinterpretation historischer Runs.

## Invarianten für die Implementierung

1. Eine Position besitzt genau einen registrierten Assetmodelltyp.
2. `Custom` ist entweder vollständig zusammengesetzt oder blockiert.
3. Kein Consumer erfindet aus unbekanntem Typ einen Bucket.
4. Current-Holding-Annahmen stammen nicht still aus Target-SAA.
5. Bruttowert, Fair Value, Nettoverkaufswert und verfügbarer Erlös bleiben
   getrennt.
6. Missing ist nicht null, null ist nicht zero und unknown ist nicht liquid.
7. Valuation-as-of, Quelle, Methode, Evidence und Freshness sind gemeinsam
   gebunden.
8. `advised != tradable != reserve_available != goal_available`, sofern nicht
   derselbe Snapshot ihre Gleichheit ausdrücklich belegt.
9. Verkauf, Distribution, Capital Call und Belehnung wirken genau einmal.
10. Eine Liability erzeugt keinen Assetreturn und erscheint nicht in
    `gross_assets`.
11. Jeder wirksame Fachwert ändert den Business-Hash; reine Auditmetadaten
    nicht.
12. No-op Edit behält Werte, Modell, Ergebnis und Hash.
13. Historische Hashversionen bleiben verifizierbar und werden nicht
    rückwirkend umdefiniert.
14. Alle kundenwirksamen Kanäle lesen denselben eingefrorenen Root-Snapshot.
15. Unvollständige Evidence führt zu `blocked`, nicht zu einem grünen Verdict.

## Nicht ausreichende Scheinfixes

Folgende Änderungen schließen die Findings **nicht**:

- nur `Custom` im PDF von liquidity auf alternatives mappen;
- nur `asset_location` dem Response hinzufügen;
- nur die vier freien Strings in Enums verwandeln;
- nur das Renditefeld in die Projektion addieren, ohne Volatilitäts-,
  Korrelations-, Quellen- und Exactly-once-Vertrag;
- alle Alternative-Subtypen pauschal mit Gold- oder PE-CMA behandeln;
- `Custom` pauschal als 100 Prozent Alternatives behandeln;
- UI-Defaults verstecken, aber serverseitig weiter materialisieren;
- `asset_liquidity` direkt als Goal-Funding-Boolean interpretieren;
- Versicherungswert pauschal mit Fair Value gleichsetzen;
- den bisherigen Hashencoder in-place ändern und historische Anchortests
  neu baselinen;
- nur Warnungen anzeigen und Generate/PDF/Sign/Handoff weiter zulassen;
- getrennte Fixes je Kanal ohne gemeinsamen Snapshot und Root-Hash.

## Acceptance-Checkliste

- [ ] Geschlossene, dialektgleiche Typ-/Subtyp-/Assignment-/Methoden-/Liquiditätsdomain.
- [ ] Versionierte Required-/Forbidden-Termmatrix je Assetmodell.
- [ ] Legacy-Inventar, Dry-run, eindeutige Migration und Quarantänebericht.
- [ ] Kein stilles Custom-Defaultportfolio.
- [ ] Symmetrischer Create/PATCH/Response-Roundtrip einschließlich Standort.
- [ ] Keine Persistenz von UI-Platzhaltern als Fachfakten.
- [ ] Evidence-gebundene Bewertung mit validiertem as-of und Freshness.
- [ ] Brutto-/Fair-/Nettoverkaufswert und Bewertungsunsicherheit getrennt.
- [ ] Periodischer Tradability-/Redemption-/Settlement-/Funding-Schedule.
- [ ] Capital Calls, Distributions, Verkauf und Belehnung genau einmal.
- [ ] Getrennte Current-Holding- und Target-SAA-Modellbasis.
- [ ] Explizite Entscheidung über `asset_expected_return_bps`.
- [ ] Ist-plus-Ziel-Illiquiditätsverdikt.
- [ ] Asset-/Liability-Matrix und korrekte Gross/Liability/Net-Reconciliation.
- [ ] Alle wirksamen Felder im versionierten Business-Hash.
- [ ] Historische Hashes verifizierbar; neue Finalisierung nutzt neuen Manifestvertrag.
- [ ] API/Classic/React/Portal/PDF/Signed/Handoff-Parität.
- [ ] Server-Gates vor Generate/Rebuild/Finalize/PDF/Sign/Handoff.
- [ ] SQLite-/PostgreSQL-/Browser-/Replay-/Tamper-/Concurrency-Abnahme.
- [ ] Kein früherer P0/P1 durch die Änderung regressiert.

## Claude-/GPT-Startcheckliste

Claude soll vor der ersten Codeänderung:

1. diesen Audit vollständig lesen,
2. danach den Runde-31-Liquiditätsaudit und die dortige
   `AllocationRunInputManifest`-Definition lesen,
3. die vorhandenen Property-, Depot-, Preference-, Liability- und
   Handoff-Findings nicht duplizieren,
4. zuerst ein maschinenlesbares Legacy-Inventar und eine Termmatrix vorlegen,
5. die Entscheidung „Custom migrieren oder explizit zusammensetzen“ separat
   zur fachlichen Freigabe stellen,
6. die Entscheidung über `asset_expected_return_bps` explizit dokumentieren,
7. Schema/Migration, Domain, Snapshot, Resolver, Engine, UI und Publikation in
   kleinen, reviewbaren Schritten implementieren,
8. für jeden Schritt Vorher-/Nachher-Reproduktionen und negative Tests liefern,
9. historische Hashanker nicht durch bloßes Neubaselining grün machen,
10. und erst nach echter PostgreSQL-, Browser- und Cross-Channel-Abnahme eine
    Releasefreigabe vorschlagen.

Empfohlene Reihenfolge der Pull Requests:

1. Registry, Termmatrix, DTO-Vertrag und Legacy-Dry-run;
2. ValuationSnapshot und TradabilitySchedule;
3. AssetModelSnapshot und Custom-Migration;
4. Engine-/Availability-/Illiquiditätsintegration;
5. Root-Manifest-/Hashmigration;
6. Classic/React/API/PDF/Signed/Handoff-Parität;
7. PostgreSQL-/Browser-/Replay-/Rolloutabnahme.

Jeder Pull Request nennt betroffene Findings, neue Invarianten, Migration,
Rollback, Tests und verbleibende Blocker. Ein grüner Teiltest schließt keinen
Finding, solange die kanalübergreifende Acceptance-Checkliste offen ist.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

```text
branch: codex/asset-allocation-stochastic-core
HEAD:   5efea8634363982ed3a8372ea8e0591804a663e2
tracked status: keine sichtbaren Änderungen
global clean: nicht behauptet
reason: vorbestehende ACL-unlesbare .pytest*-Verzeichnisse unter 5eyes-backend
```

Die bekannten ACL-Warnungen wurden weder betreten noch verändert noch
gelöscht.

### Isolierte Runtime-Reproduktion

Ein temporärer Python-Harness wurde mit `PYTHONPATH=.` gegen die produktiven
Module ausgeführt und anschließend per Patch entfernt. Die zwölf bestätigten
Prüfpunkte deckten ab:

1. freie Subtyp-Domain,
2. 1.000-Prozent-Return-Domain,
3. freie Liquiditätsdomain,
4. freie Bewertungsmethode,
5. Response ohne Standort,
6. verworfenes Typfeld im Update,
7. Alternative-Defaultgewichte,
8. Custom-Defaultgewichte,
9. Custom-PDF-Fallback,
10. UI-Liquiditätsvokabular vs. Depot-Tier,
11. Hashblindheit für wirksame Terms,
12. Hashänderung ohne Summarywirkung beim Return.

Es wurden keine Produkt- oder Testdateien hinterlassen.

### Fokussierter Bestands-Gate

Der relevante Bestands-Gate lief zweimal mit getrennten DB-, Log- und
Basetemp-Pfaden und deaktiviertem pytest-Cache:

```text
erster Lauf:  535 passed, 1 skipped, 1 warning in 225.56s
zweiter Lauf: 535 passed, 1 skipped, 1 warning in 230.66s
```

Abgedeckt waren 23 Testdateien aus API-/Wealth-Contracts, Inputvalidierung,
Hashankern, Runtime-/Engine-Regressionen, Bucketmetrik, Depot-/Illiquiditäts-
Checks, Wealth-Cashflows, Illiquid-Cap, Classic-Editor, Advisory-Report,
PDF-Renderer, Goal-Liabilities, Gesamtvermögen und Production-Contract.

Der Skip in `test_illiquid_cap_integration.py` ist eine bestehende,
profilabhängige Bedingung: Der PE-Anteil lag ohne Cap nur bei 82 Basispunkten,
sodass der Cap in diesem Szenario nicht greifen würde. Die Warning ist eine
vorbestehende `datetime.utcnow()`-Deprecation in `database.py`.

Der grüne Gate widerlegt die Findings nicht. Es fehlen gezielte Tests für:

- Alternative-Felddomain und `asset_location`-Roundtrip,
- Custom-Parität über Engine/Depot/PDF,
- Valuation-Source/Freshness/Evidence,
- UI-Vokabularübersetzung der Alternative-Liquidität,
- Alternative-Fachfelder im Root-Hash,
- current-holding-spezifische Risk-/Returnmomente,
- Alternative-/Custom-Channelparität.

### Nicht ausgeführte Prüfungen

- kein echter Browser-/DOM-Lauf,
- keine echte PostgreSQL-Migration oder Constraint-Prüfung,
- kein Cross-Worker-/Concurrency-Test,
- keine reale Marktpreis-, Gutachter-, Custody- oder Fund-Admin-Integration,
- keine produktive Datenmigration,
- keine PDF-Pixel-/Signatur-/Handoff-End-to-End-Abnahme.

Diese Grenzen verhindern jede Behauptung, der Release-Hold sei technisch
geschlossen.

## Dokumentationsmanifest und Commitvertrag

Dieser Audit ändert ausschließlich folgende fünf Pfade:

1. `docs/audits/2026-09-21-alternative-custom-asset-valuation-tradability-and-publication-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Vor Commit sind verpflichtend:

1. `git diff --check`,
2. Dokumentationsmanifest exakt fünf Pfade,
3. relative Auditlinks auf allen vier Einstiegspfaden,
4. YAML-, Heading-, Tabellen- und Codefence-Strukturprüfung,
5. UTF-8-/Replacement-Character-Prüfung,
6. Zählerparität: vier neue P1, zwei Erweiterungsgruppen über sechs bestehende
   P1-IDs, ein isolierter Harness mit zwölf Prüfpunkten, 535 Passed/1 Skipped,
7. Commitprüfung mit `git show --stat`, `git show --name-only` und
   `git diff HEAD^ HEAD --check`,
8. tracked Git-Status nach Commit; global clean bleibt wegen ACL-Warnungen
   ausdrücklich unbehauptet.

## Releaseentscheidung

**BLOCKED – vier neue P1 sowie zwei bestätigte Erweiterungsgruppen.**

Alternative-/Custom-Vermögen darf erst als reale Beratungs-, Reserve-, Goal-,
Optimizer-, MC-, Depot-, Report-, PDF-, Signatur- oder Handoff-Basis
freigegeben werden, wenn:

1. die geschlossene Domain und Subtyp-Termmatrix produktiv erzwungen sind,
2. Bewertung und Handelbarkeit evidencegebunden gesnapshottet sind,
3. Custom eindeutig migriert oder vollständig zusammengesetzt ist,
4. Current-Holding und Target-SAA getrennt und reconciliable modelliert sind,
5. Availability, Liability und Illiquiditätslimit die bestehenden
   Cross-Asset-Verträge erfüllen,
6. jeder wirksame Wert im `AllocationRunInputManifest` gebunden ist,
7. alle Kundenkanäle denselben Root-Snapshot publizieren,
8. und die vollständige Acceptance-Checkliste auf SQLite, PostgreSQL,
   Browser, PDF, Replay, Tamper und Handoff bestanden ist.

Bis dahin ist der Hold Governance-seitig verbindlich. Der aktuelle Code
erzwingt ihn noch nicht in allen Berechnungs- und Publikationskanälen
vollständig serverseitig.
