---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-investment-preference-esg-exclusion-recommendation-constraint-integrity-followup-audit"
status_as_of: "2026-09-04"
audit_started_on: "2026-09-04"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "b5de5c9fb5cad1daf04f7e861a3f94ae81177db0"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-04-product-suitability-appropriateness-and-recommendation-eligibility-integrity-audit.md"
prior_release_audit_commit: "b5de5c9fb5cad1daf04f7e861a3f94ae81177db0"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md"
audit_mode: "read_only_static_ui_router_service_orm_schema_alembic_pdf_test_review_existing_focused_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "Investment-preference provenance and binding across TargetAllocation, RecommendationRun, automatic and manual product selection, ESG modes, thematic exclusions and underweights, geographic and FX preferences, concentration limits, finalization, API reload, customer PDF, signed publication and portfolio handoff"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
static_findings_confirmed: 10
focused_existing_tests_passed: 274
focused_existing_tests_failed: 0
isolated_runtime_harness_executed: false
isolated_runtime_harness_block_reason: "prior tool safety approval unavailable; no bypass attempted"
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "make the verified TargetAllocation preference snapshot the only recommendation constraint source; persist and hash one versioned PreferenceDecision and RecommendationConstraintSnapshot; reject request drift; implement or remove non-operative ESG, thematic, home-bias and FX modes; route automatic and manual positions, finalization, signed publication and handoff through the same fail-closed verdict"
---

# Anlagepräferenz-/ESG-/Ausschluss-/Recommendation-Constraint-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die sechsundzwanzigste Read-only-
Kontrollrunde. Er wurde gegen den unveränderten Repository-Head `b5de5c9`
durchgeführt und verändert weder Produktcode noch Tests.

Geprüft wurde nicht, welche ESG-, Themen-, Währungs- oder Heimmarktpräferenz
wirtschaftlich sinnvoll ist. Geprüft wurde ausschließlich, ob 5eyes die vom
eigenen Schema akzeptierten und im Kundenkanal dargestellten Präferenzen mit
genau demselben, unveränderlichen Kontext in Soll-Allokation, Produktauswahl,
manuellen Positionen, Finalisierung, PDF, Signatur und Handoff durchsetzt.

Dieser Audit ergänzt und ersetzt insbesondere nicht:

1. den unmittelbar vorherigen
   [Produkt-Suitability-/Angemessenheits-/Recommendation-Eligibility-Integritätsaudit](2026-09-04-product-suitability-appropriateness-and-recommendation-eligibility-integrity-audit.md),
2. den
   [Vertragsdokument-/E-Signatur-/signierte-Publikations-Integritätsaudit](2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md),
3. den
   [Portfolio-Handoff-/Handelsinstruktions-/Ausführungsnachweis-Integritätsaudit](2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md),
4. den
   [Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Integritätsaudit](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md),
5. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
6. den
   [Asset-Allocation-Post-Commit-Integritätsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
7. sowie die weiterhin gültige
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code, Tests und Migrationen zuerst, danach
dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu früheren Findings

Die Runde vergibt keine neuen IDs für bereits belegte Tenant-, Positions-,
Signatur- oder Hybridkontextfehler:

- `REC-001`, `REC-002` und `REC-004` bleiben für Tenant-Scoping, ungültige
  Positionsdaten und Mutierbarkeit historischer Runs maßgeblich;
- `REP-004` bleibt für PDF-/Service-Consumer maßgeblich, die einen aktuellen
  TargetAllocation-Kontext mit einem unabhängig gewählten RecommendationRun
  kombinieren;
- `REC-006`, `REP-005`, `REC-003` und Kontrollrunde 23 bleiben für Signatur,
  Final-Run-Bindung und Handoff maßgeblich;
- die Findings der Runde 25 bleiben für ProductSuitability,
  Angemessenheits-/Override-Evidence und `ignore_suitability=True` maßgeblich.

Neu ist hier der vollständige Präferenz- und Restriktionsvertrag: Selbst wenn
alle vorgenannten Findings isoliert geschlossen würden, kann ein
RecommendationRun weiterhin unter einem anderen Präferenzsatz als seine
TargetAllocation entstehen, mehrere als aktiv publizierte Präferenzmodi haben
keine behauptete operative Semantik, und Finalisierung sowie Publikation
besitzen keinen beweisbaren Constraint-Verdict.

## Kurzurteil

Der aktuelle Stand darf **nicht** als technisch durchgesetzte, durchgängig
präferenzkonforme Produktempfehlung freigegeben werden.

Bestätigt sind insbesondere:

1. `TargetAllocation.preferences_json` ist sinnvoll persistiert und Bestandteil
   des `allocation_context_hash`. `generate_recommendation_run()` erzeugt aber
   zusätzlich aus dem optionalen Request einen zweiten Präferenzsatz und nutzt
   genau diesen für Produktfilter, Produkt-Score und Konzentrationslimits.
2. Bei `preferences=None` rekonstruiert der Target-Payload die Soll-Allokation
   aus dem gespeicherten Snapshot, während die Produktauswahl mit leeren
   Default-Sektionen arbeitet. Gespeicherte Produkt-, Währungs-, ESG- und
   Konzentrationsrestriktionen können damit aus der Empfehlung verschwinden.
3. Ein abweichender Request wird nicht gegen den TargetAllocation-Snapshot
   abgelehnt. Die intern erzeugte Driftwarnung wird vom Recommendation-Response
   nicht übernommen. Der RecommendationRun speichert weder Präferenzen noch
   deren Hash oder einen Constraint-Verdict.
4. Zwei Frontend-Recoverypfade verwenden für dieselbe aktuelle
   TargetAllocation unterschiedliche Quellen: einer den gespeicherten
   Allocation-Snapshot, einer den aktuellen lokalen UI-/LocalStorage-Stand.
5. Themenmodi `exclude` und `underweight` werden nicht als harte Ausschlüsse
   beziehungsweise messbare Untergewichte umgesetzt. Nur `overweight` erzeugt
   eine Themen-Suballokation; der spätere Score betrachtet den Ziel-Sleeve,
   nicht die tatsächliche Produkt-Exposure, und ein Score von `-10000`
   entfernt keinen Kandidaten.
6. `best_in_class`, `impact` und `net_zero` kollabieren auf denselben
   SFDR-8/9-Filter. Die UI verspricht für `impact` ausdrücklich SFDR 9.
   `negative_screening` und `esg_integration` werden gespeichert und im PDF
   gezeigt, aber nicht fachlich ausgewertet; Produktdaten für Impact- oder
   Net-Zero-Evidence fehlen.
7. `geo.chFocus` ist ein akzeptierter und publizierter Schema-Key ohne
   Backend-Reader. `policy.hedging=risk_budget` wird wie eine allgemeine
   Hedgingpräferenz lediglich mit `+20` gescored; eine FX-Risikobudgetlogik
   existiert in diesem Produktentscheid nicht.
8. `singlePosition` und `singleIssuer` werden nur im automatischen Generator
   und nur gegen den zweiten Request-Präferenzsatz geprüft. `None`, ein
   gelockerter Request oder manuelle Positionen umgehen den gespeicherten
   Limitstand.
9. Direct Create und `add_position()` prüfen weder Allocation-Präferenzen noch
   Universe, ESG, Themenausschlüsse, Währung oder allgemeine Limits. Der
   Finalizer prüft danach TargetAllocation-Hash, aktives Produkt und
   Gewichtssumme, aber nicht die Positionen gegen den Präferenzsnapshot.
10. API-Reload, Kunden-PDF, Contract-Signoff und Handoff besitzen keinen
    gemeinsamen `RecommendationConstraintSnapshot`. Dadurch kann der
    gespeicherte Präferenztext neben Positionen erscheinen, deren Erzeugungs-
    und Freigabekontext nicht beweisbar derselbe war.

Der fokussierte Bestands-Gate mit 274 bestandenen Tests hebt diese Befunde nicht
auf. Er bestätigt die vorhandenen Positivverträge, enthält aber keinen
Negativfall für den zentralen Split zwischen TargetAllocation- und
Recommendation-Präferenzquelle.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `PREF-CONTEXT-001` | P1 | bestätigt | TargetAllocation und Recommendation-Produktauswahl können zwei verschiedene Präferenzsätze verwenden; der Run speichert keinen davon. |
| `PREF-REFRESH-001` | P1 | bestätigt | Zwei UI-Hydrate-/Recoverypfade generieren für dieselbe Allocation aus gespeicherten beziehungsweise lokalen Live-Präferenzen. |
| `PREF-TILT-001` | P1 | bestätigt | Themen-`exclude` und `underweight` besitzen keine belastbare Produkt-/Exposure-Wirkung; ein negativer Score ist kein Ausschluss. |
| `PREF-ESG-001` | P1 | bestätigt | Drei unterschiedliche ESG-Modi kollabieren auf SFDR 8/9; Impact-, Net-Zero- und Negative-Screening-Claims sind nicht evidenzgebunden. |
| `PREF-GEO-FX-001` | P2 | bestätigt | `geo.chFocus` ist serverseitig wirkungslos; FX-`risk_budget` ist nur ein Hedging-Scorebonus ohne Budgetberechnung. |
| `PREF-LIMIT-001` | P1 | bestätigt | Gespeicherte Einzelpositions-/Emittentenlimits können über `None`, abweichende Requests oder manuelle Positionen umgangen werden. |
| `PREF-MANUAL-001` | P1 | bestätigt | Direct Create und manuelles Add prüfen keine Präferenz-/Restriction-Eligibility. |
| `PREF-FINAL-001` | P1 | bestätigt | Finalisierung verifiziert den TA-Context, nicht aber Präferenzkonformität und Hash der tatsächlichen Positionen. |
| `PREF-PUBLISH-001` | P1 | bestätigt | API/PDF/Signoff/Handoff binden Präferenzsnapshot und Recommendation-Positionen nicht an denselben unveränderlichen Verdict. |
| `PREF-GOVERNANCE-001` | P1 | bestätigt | Es fehlt eine versionierte PreferenceDecision mit Quelle, Akzeptanz, Semantik-/Engine-Version und Run-/Positionsbindung. |

## Positivkontrollen, die erhalten bleiben müssen

Die neuen Findings dürfen nicht zu einem Rückbau bereits guter Kontrollen
führen:

1. `AllocationPreferencesPayload` verbietet unbekannte Top-Level- und
   Sektionskeys und validiert Typen, Wertebereiche und bekannte Vokabulare.
2. `TargetAllocation.preferences_json` wird normalisiert persistiert.
3. Der `allocation_context_hash` bindet `preferences_json`, Bucket-Ziele,
   Suballokationen, effektive Constraints, Policy, CMA, Assessment,
   Input-Snapshot und Optimizer-Seed.
4. Moderne TargetAllocations ohne vollständige Context-Artefakte blockieren.
5. Persistierte Suballokationen werden beim Reload gegen Bucket-Ziele und
   typisierte Bounds reconciliert.
6. `geo.noEm` wirkt in Aktien- und Obligationen-Splits; widersprüchliche
   EM-Vorgaben blockieren.
7. `noStructured`, `noDerivatives`, `noLeverage`, `chfOnly`, `noUsd` und
   `hedgingRequired` wirken als harte Produktfilter, **wenn** der richtige
   Präferenzsatz den Matcher erreicht.
8. `maxIlliquid` und `minReserve` besitzen einen SAA-/Reserve-Reader.
9. Automatisch aggregierte Positionen werden grundsätzlich gegen die
   übergebenen allgemeinen Einzelpositions-/Emittentenlimits geprüft.
10. Recommendation und TargetAllocation werden bereits auf Mandat, aktuelle
    RA, Policy und CMA verankert.

Die Reparatur muss diese Kontrollen zu einem einzigen End-to-End-Vertrag
verbinden, nicht durch ein neues paralleles Regelwerk ersetzen.

## Tatsächlicher Präferenz- und Recommendation-Fluss

```text
Browser vor Strategieerzeugung
  collectAllocationPreferencesFromUI()
       |
       +-- Cache/currentPersona
       +-- localStorage: 5eyes.allocprefs.<mandate>
       +-- keine serverseitige PreferenceDecision-Version
       |
       v
POST /target-allocation/generate { preferences: P_TA }
       |
       v
_normalize_preferences(P_TA)
_merge_mandate_defaults_into_prefs(...)
       |
       +-- SAA / Reserve / Sub-Allocations / Simulation
       +-- TargetAllocation.preferences_json = canonical P_TA
       +-- allocation_context_hash binds P_TA
       |
       v
POST /recommendations/generate
  { target_allocation_id, preferences: P_REQ | null }
       |
       +-----------------------------------------------+
       |                                               |
       v                                               v
build_target_payload_from_allocation(...)      prefs = normalize(P_REQ)
  P_REQ != null -> uses P_REQ                     P_REQ == null -> empty sections
  P_REQ == null -> uses stored P_TA                    |
  verified TA suballocations stay stored               +-- product matcher
       |                                                +-- product score
       +-- may create preference-drift warning          +-- concentration limits
       |                                                     |
       +-------------------- warning not propagated ----------+
                                                             |
                                                             v
                                                  RecommendationPosition[]
                                                  RecommendationRun
                                                    - TA id
                                                    - RA/Policy/CMA ids
                                                    - no preference snapshot
                                                    - no preference hash
                                                    - no position hash
                                                    - no constraint verdict
```

Der `allocation_context_hash` beweist damit nur, dass die gespeicherte
TargetAllocation intern zu ihrem eigenen Präferenzsnapshot passt. Er beweist
nicht, dass die Recommendation-Positionen unter genau diesem Snapshot erzeugt
oder später erneut geprüft wurden.

## Feldweise Consumer-Matrix

| Präferenz | Schema/UI | SAA-/Reserve-Reader | Produkt-Reader | publizierte Semantik | Ist-Vertrag |
|---|---|---|---|---|---|
| `policy.esg=best_in_class` | akzeptiert | keiner | SFDR 8/9 Hardfilter | Best-in-Class | keine Ranking-/Peer-Group-Semantik |
| `policy.esg=impact` | UI: SFDR 9 aktiv | keiner | SFDR 8 **oder** 9 | Impact Investing | widerspricht UI; keine Impact-Evidence |
| `policy.esg=net_zero` | akzeptiert | keiner | SFDR 8 **oder** 9 | Paris-aligned / Net Zero | keine Paris-/Net-Zero-Daten |
| `esg_integration` | UI: Dokumentation | keiner | keiner | ESG-Integration | kein maschinenlesbarer Evidenzstatus |
| `negative_screening` | UI: Dokumentation | keiner | keiner | Negativ-Screening | keine Screening-Regel/-Evidence |
| `policy.universe=funds_only/listed_only` | akzeptiert | keiner | harter Typfilter | aktiver Filter | vorhanden, wenn richtiger Snapshot |
| `policy.universe=standard/extended` | akzeptiert | keiner | identisch: kein Zusatzfilter | Standard/erweitert | kein unterscheidbarer Produktvertrag |
| `policy.homeBias=ch_focus` | akzeptiert | getrennt von `equitiesGeo` | `+35` Score | bevorzugt | Soft-Präferenz |
| `homeBias=europe_focus/global/none` | akzeptiert | getrennt von `equitiesGeo` | kein Boost | eigene Modi | Produktentscheidung nicht unterscheidbar |
| `policy.hedging=chf_only` | akzeptiert | keiner | harter Currencyfilter | nur CHF | vorhanden, wenn richtiger Snapshot |
| `policy.hedging=hedged` | akzeptiert | keiner | `+20` Score | bevorzugt | Soft-Präferenz |
| `policy.hedging=risk_budget` | akzeptiert | kein FX-Budget | `+20` wie `hedged` | FX außerhalb Risiko-Budget | keine Budgetlogik |
| Themen-`overweight` | akzeptiert | erzeugt Themen-Sleeve | Score auf Ziel-Sleeve | übergewichten | SAA-Sleeve vorhanden; Produktexposure nicht bewiesen |
| Themen-`underweight` | akzeptiert | keine Gewichtsänderung | nur erreichbar, wenn Ziel-Sleeve Thema ist | untergewichten | im Normalpfad wirkungslos |
| Themen-`exclude` | akzeptiert | kein Ausschluss | Rückgabe `-10000`, Kandidat bleibt | ausschließen | kein Hardfilter |
| `geo.noEm` | akzeptiert | entfernt EM-Sleeves | kein Exposurefilter | kein EM-Exposure | SAA-Sleeve, aber keine Produkt-Exposure-Evidence |
| `geo.chFocus` | akzeptiert | keiner | keiner | CH-Fokus | serverseitig wirkungslos |
| `geo.hedgingRequired/chfOnly/noUsd` | akzeptiert | keiner | harte Filter | Restriktion | vorhanden, wenn richtiger Snapshot |
| `limits.singlePosition/singleIssuer` | akzeptiert | keiner | post-aggregation im Auto-Generator | Limit | nicht snapshotgebunden; manuell umgehbar |
| `limits.minReserve/maxIlliquid` | akzeptiert | SAA/Reserve | kein Finalpositions-Verdict | Limit | SAA-seitig vorhanden |
| `assetClasses` | akzeptiert | Suballokationsplan | indirekt über exakte/fallback Auswahl | Fokus/Sleeves | TA-gehasht, aber Run-Bindung fehlt |
| `bands` | akzeptiert | SAA-Constraints | keine Positionsprüfung | individuelle Bandbreiten | TA-gehasht |
| `simulation` | akzeptiert | Simulation/MC | keine Produktauswahl | Modellparameter | bei Run-Rebuild ebenfalls zweiter Request möglich |

Die Tabelle unterscheidet bewusst „kein Produktreader“ von „fehlerhaft“: Nicht
jede Präferenz muss ein Produktfilter sein. Fehlerhaft wird der Vertrag dort,
wo UI/PDF eine aktive Restriktion oder spezifische Methodik behaupten, der
Server aber keine entsprechende Wirkung oder Evidence besitzt, oder wo ein
wirksamer Reader mit einem anderen Snapshot arbeitet.

## Codeanker auf dem auditierten Head

| Bereich | Beleg |
|---|---|
| Striktes Präferenzschema | `5eyes-backend/schemas/allocation.py:818-900` |
| TargetAllocation-Präferenz-/Hashfelder | `5eyes-backend/models/allocation.py:78-111` |
| Normalisierung und Snapshot-Parser | `5eyes-backend/services/portfolio_engine.py:457-491` |
| TA-Snapshot-Persistenz | `5eyes-backend/services/portfolio_engine.py:3757`, `3975-3981`, `4022` |
| Context-Hash-Verifikation | `5eyes-backend/services/portfolio_engine.py:4160-4365` |
| Rebuild-Präferenzwahl | `5eyes-backend/services/portfolio_engine.py:5444-5448` |
| Persistierte Suballokation gewinnt | `5eyes-backend/services/portfolio_engine.py:5645-5700` |
| Driftwarnung | `5eyes-backend/services/portfolio_engine.py:2794-2853`, `6016-6023` |
| Recommendation-Doppelsource | `5eyes-backend/services/portfolio_engine.py:6439-6452`, `6519-6529`, `6598-6642` |
| Warning-Verlust | `5eyes-backend/services/portfolio_engine.py:6591`, `6858-6874` |
| Produktfilter | `5eyes-backend/services/portfolio_engine_payload.py:712-768` |
| Produkt-Score und Themenlogik | `5eyes-backend/services/portfolio_engine_payload.py:832-876` |
| Themen-Sleeve-Erzeugung | `5eyes-backend/services/portfolio_engine_house_matrix.py:680-709` |
| Konzentrationslimits | `5eyes-backend/services/portfolio_engine_payload.py:923-958` |
| RecommendationRun ohne Präferenzfelder | `5eyes-backend/models/review.py:355-384` |
| API-Schema ohne Run-Constraint-Snapshot | `5eyes-backend/schemas/review.py:684-717`, `778-856` |
| Direct Create | `5eyes-backend/routers/review.py:2027-2161` |
| Manuelles Add | `5eyes-backend/routers/review.py:2343-2367` |
| Finalisierungsvalidator | `5eyes-backend/routers/review.py:137-235` |
| Finalisierung | `5eyes-backend/routers/review.py:2290-2327` |
| UI gespeicherter Recoverypfad | `5eyes-electron/frontend/5eyes_v2.html:20343-20395` |
| UI Live-Hydratepfad | `5eyes-electron/frontend/5eyes_v2.html:21521-21532` |
| Browser-LocalStorage | `5eyes-electron/frontend/5eyes_v2.html:17620-17678`, `18344-18360` |
| UI ESG-/Home-/FX-Claims | `5eyes-electron/frontend/5eyes_v2.html:3492-3495` |
| UI Restriktionschips | `5eyes-electron/frontend/5eyes_v2.html:17984-18013` |
| PDF liest TA-Präferenzen | `5eyes-backend/routers/pdf_reports.py:394-434` |
| PDF publiziert Präferenzen/Restriktionen | `5eyes-backend/services/pdf/documents/anlagestrategie.py:642-736` |
| PDF wählt Produkte unabhängig | `5eyes-backend/routers/pdf_reports.py:489-535` |
| Alembic RecommendationRun ohne Snapshot | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:883-903` |

## `PREF-CONTEXT-001` – Recommendation und TargetAllocation verwenden verschiedene Präferenzquellen

### Beobachtung

`generate_recommendation_run()` normalisiert am Funktionsanfang unmittelbar den
Request:

```python
prefs = _normalize_preferences(preferences)
```

Wird anschließend eine vorhandene TargetAllocation verwendet, geht derselbe
optionale Request zusätzlich an `build_target_payload_from_allocation()`. Dort
gilt eine andere Fallbackregel:

```python
prefs = _normalize_preferences(
    preferences
    if preferences is not None
    else _allocation_snapshot_preferences(allocation)
)
```

Danach nutzt der Produktloop aber wieder die äußere Variable `prefs`:

```python
_product_matches_constraints(product, prefs, ...)
_product_score(product, sub["sub_asset_class"], prefs, ...)
_validate_recommendation_concentration_limits(aggregated_positions, prefs)
```

Damit entstehen zwei konkrete Fälle:

1. `preferences=None`: Target/SAA/Simulation verwenden den gespeicherten
   TargetAllocation-Snapshot; Produktauswahl und Konzentrationslimits verwenden
   das Schema-Default mit leeren Sektionen.
2. `preferences=P_REQ`: Target-Rebuild, Simulation und Produktauswahl dürfen mit
   `P_REQ` laufen, obwohl der RecommendationRun weiterhin auf die unter `P_TA`
   erzeugte und gehashte TargetAllocation zeigt.

Die Hashprüfung verhindert das nicht. Sie rekonstruiert den Hash korrekt aus
`allocation.preferences_json`; sie vergleicht den Request aber nicht mit diesem
Snapshot.

Die Driftlogik erkennt einen abweichenden Präferenzstring und fügt dem
Target-Payload eine Warnung hinzu. `generate_recommendation_run()` initialisiert
anschließend jedoch eine eigene leere `warnings`-Liste und gibt die
Target-Payload-Warnung nicht zurück. Der Konflikt ist im Recommendation-Response
damit still.

### Risiko

Eine Recommendation kann dieselbe TargetAllocation-ID, RA, Policy und CMA
ausweisen, obwohl ihre Produktauswahl andere oder gar keine Mandatsrestriktionen
verwendet hat. Aus dem gespeicherten Run lässt sich nachträglich nicht
rekonstruieren, welcher Präferenzsatz tatsächlich für Produktfilter, Ranking
und Limits galt.

### Verbindlicher Fixvertrag

1. Bei vorhandener `target_allocation_id` ist ausschließlich der nach
   Hashprüfung normalisierte TA-Snapshot autoritativ.
2. Ein zusätzlicher Request-Präferenzsatz wird entweder verboten oder nur
   akzeptiert, wenn sein kanonischer Hash exakt dem TA-Snapshot entspricht.
3. Ein einziges `effective_preferences`-Objekt muss Target-Rebuild,
   Produktmatcher, Score, Aggregation und Limits speisen.
4. Der Run persistiert `preference_decision_id`, `preferences_hash`,
   `allocation_context_hash`, `constraint_engine_version` und
   `positions_hash`.
5. Abweichung endet fail-closed mit stabilem 409/Reason-Code, nicht mit einer
   verlorenen Warnung.

## `PREF-REFRESH-001` – Frontend-Recovery ist nicht deterministisch

### Beobachtung

`refreshPortfolioFromStoredState()` ermittelt bei fehlender Recommendation die
Präferenzen korrekt aus der geladenen TargetAllocation:

```javascript
var recommendationPrefs =
  allocationPreferencesFromStoredAllocation(allocation);
```

Der andere Hydratepfad in `loadStrategyEngineData()` nimmt für denselben Fall
hingegen den aktuellen UI-/LocalStorage-Stand:

```javascript
var currentPrefs = collectAllocationPreferencesFromUI();
```

Beide senden anschließend die bestehende `target_allocation_id` und ihren
jeweiligen Präferenzsatz an `/recommendations/generate`.

Die normale vollständige Neuberechnung sendet zwar dasselbe lokale `prefs`
nacheinander an Target- und Recommendation-Generate. Dieser Happy Path
neutralisiert die abweichenden Recoverypfade nicht.

### Risiko

Ob eine fehlende Recommendation präferenzkonform regeneriert wird, hängt vom
aufrufenden UI-Zweig und vom lokalen Browserzustand ab. Zwei Browser, zwei
Geräte oder ein zwischenzeitlich editiertes, noch nicht neu berechnetes Formular
können für dieselbe TargetAllocation unterschiedliche Produkte erzeugen.

### Verbindlicher Fixvertrag

1. Recommendation-Regeneration sendet bei bestehender TA nur deren ID.
2. Der Server löst und verifiziert den Präferenzsnapshot selbst.
3. Lokale Änderungen markieren die Strategie ausschließlich als dirty und
   erzwingen eine neue TargetAllocation; sie dürfen keine alte TA umdeuten.
4. Beide Recoverypfade werden in einen einzigen Helper konsolidiert.
5. Browservertragstest: zwei lokale UI-Zustände plus gleiche TA-ID ergeben
   entweder denselben Run oder einen klaren 409 wegen notwendiger
   SAA-Neuberechnung.

## `PREF-TILT-001` – Themenausschlüsse und Untergewichte sind keine Constraints

### Beobachtung

Der Suballokationsbuilder liest ausschließlich `overweight`:

```python
overweight_tilts = [
    key for key, value in tilts.items() if value == "overweight"
]
```

Nur daraus entstehen Themen-Sleeves. `exclude` und `underweight` verändern
weder die Standard-Splits noch ein messbares Exposure-Limit.

Die spätere `_product_score()`-Logik untersucht nicht das Produkt, sondern den
angeforderten `sub_asset_class`-String. Bei `exclude` liefert sie `-10000`,
aber der Kandidat verbleibt in der Liste und `ranked[0]` wird immer ausgewählt,
solange überhaupt ein Kandidat existiert. `_product_matches_constraints()`
kennt Themen überhaupt nicht.

Zusätzlich kann ein Asset-Class-Fallback ein thematisches Produkt für einen
nichtthematischen Ziel-Sleeve wählen. Weil der Score den Ziel-Sleeve statt
`product.sub_asset_class` auswertet, erkennt er die ausgeschlossene
Produktkategorie in diesem Fall nicht einmal als Thema.

### Risiko

UI und PDF können „Fossile Energie ausschließen“ oder „Verteidigung
untergewichten“ dokumentieren, ohne dass die Produktauswahl oder eine
Exposureprüfung diese Aussage garantiert. Ein Kunde kann dadurch genau die
ausgeschlossene Kategorie in der Recommendation erhalten.

### Verbindlicher Fixvertrag

1. `exclude` wird ein harter, vor Ranking angewendeter Produkt-/Exposurefilter.
2. `underweight` erhält eine definierte, messbare Obergrenze und eine
   post-aggregation Exposureprüfung.
3. Die Entscheidung basiert auf versionierten Produkt-/Issuer-/Look-through-
   Exposures, nicht auf dem Namen des Ziel-Sleeves.
4. Fehlende Classification-Evidence blockiert bei aktivem Ausschluss
   fail-closed oder wird als explizit nicht unterstützbar abgelehnt.
5. Bis dahin müssen nicht implementierte Modi aus Schema, UI, PDF und
   gespeicherten Kundenclaims entfernt werden.

## `PREF-ESG-001` – ESG-Modi und publizierte Claims besitzen keine getrennte Semantik

### Beobachtung

Der Matcher behandelt `best_in_class`, `impact` und `net_zero` identisch:

```python
if policy_prefs.get("esg") in (
    "best_in_class", "impact", "net_zero"
):
    if str(product.sfdr_class or "") not in ("8", "9"):
        return False
```

Die UI bezeichnet `impact` dagegen als „SFDR 9 Filter aktiv“. Ein Produkt mit
`sfdr_class="8"` passiert den produktiven Matcher trotzdem.

Auch die übrigen Bedeutungen sind nicht belegt:

- Best-in-Class nutzt weder Peer Group noch `esg_rating` oder
  `esg_score_x10` als Schwelle;
- Net Zero/Paris-aligned besitzt kein Produktfeld für Benchmark,
  Dekarbonisierungspfad oder entsprechende Evidence;
- Impact besitzt außer der groben SFDR-Klasse keine eigene Evidence;
- `negative_screening` und `esg_integration` werden vom Matcher nicht gelesen.

Die UI kennzeichnet die letzten beiden Modi zwar ehrlich als „Dokumentation,
kein Filter“. In Restriktionschips erscheinen sie dennoch mit Häkchen, und das
Kunden-PDF publiziert nur die Bezeichnung, nicht den Status „rein
dokumentarisch / nicht technisch geprüft“.

### Risiko

Verschiedene Kundenentscheidungen erzeugen denselben technischen Filter, und
ein spezifischer Kundenclaim kann stärker sein als die tatsächlich verfügbare
Produktklassifikation. Der spätere PDF-Leser kann nicht erkennen, ob eine
Bezeichnung eine harte Restriktion, einen Scorebonus, eine reine Dokumentation
oder nur einen UI-Text darstellt.

### Verbindlicher Fixvertrag

1. Für jeden ESG-Modus wird schriftlich eine eigene, versionierte Semantik mit
   erforderlichen Produktdaten und Missing-Data-Verhalten definiert.
2. `impact` muss den UI-Vertrag erfüllen oder der UI-Vertrag wird vor
   Produktivnutzung korrigiert.
3. Best-in-Class, Impact und Net Zero dürfen nicht implizit auf denselben
   SFDR-String reduziert werden.
4. Rein dokumentarische Modi erhalten `enforcement_mode="informational"` und
   werden in UI/PDF nicht als erfüllte Restriktion markiert.
5. Recommendation und PDF zeigen Rule-Version, Coverage und Verdict.

## `PREF-GEO-FX-001` – Akzeptierte Geo-/FX-Modi sind nicht kanonisch

### Beobachtung

Das Schema akzeptiert `geo.chFocus`, und PDF sowie Restriktionschips zeigen den
Key als aktive Restriktion. Repositoryweit existiert dafür kein Backend-Reader.
Das Frontend kommentiert selbst, dass `geo.chFocus` nur noch aus
`policy.homeBias` abgeleitet und für die Restriktionsanzeige verwendet wird.

Ein direkter API-Client kann deshalb beispielsweise
`policy.homeBias="global"` und `geo.chFocus=true` gemeinsam speichern. Das
Schema akzeptiert beide Werte; der Server nutzt nur den ersten teilweise,
während das PDF zusätzlich „CH-Fokus“ publiziert.

`policy.hedging="risk_budget"` besitzt ebenfalls keinen eigenen
Produktentscheid. `_product_score()` behandelt den Modus exakt wie `hedged`
und vergibt `+20`, wenn ein Produkt in Heimwährung oder textuell als gehedgt
erkannt wird. Weder Währungsexposures noch ein FX-Risikobudget werden dort
berechnet.

### Risiko

Der gespeicherte Präferenzsnapshot kann intern widersprüchlich sein und eine
präzisere Restriktion behaupten, als der technische Reader umsetzt.

### Verbindlicher Fixvertrag

1. Redundante Keys werden entfernt oder serverseitig kanonisch abgeleitet und
   dürfen nicht widersprüchlich gespeichert werden.
2. Jeder Modus deklariert `hard`, `soft`, `informational` oder `unsupported`.
3. `risk_budget` benötigt eine definierte Exposurebasis, Maßeinheit, Grenze,
   Aggregation und post-selection Prüfung; andernfalls wird der Modus entfernt.
4. API, UI und PDF zeigen denselben Enforcement-Status.

## `PREF-LIMIT-001` – Recommendation-Limits sind nicht an den TA-Snapshot gebunden

### Beobachtung

`_validate_recommendation_concentration_limits()` ist als post-aggregation
Kontrolle grundsätzlich an der richtigen Stelle. Sie liest jedoch nur
`prefs["limits"]` aus dem äußeren Recommendation-Request.

Damit gilt:

- gespeicherte TA-Limits plus `preferences=None` → keine Recommendation-Limits;
- gespeicherte TA-Limits plus gelockerter Request → gelockerte Limits;
- manuell hinzugefügte Positionen → keine Limitprüfung;
- Finalisierung → nur Gesamtgewicht ungefähr 100 Prozent, keine erneute
  Einzelpositions-/Emittentenprüfung.

`maxIlliquid` und `minReserve` besitzen zwar SAA-seitige Reader. Auch diese
Kontrolle ersetzt keinen Verdict darüber, ob die tatsächlich finalisierten
Produkte beziehungsweise manuellen Positionen den publizierten Limitstand
einhalten.

### Risiko

Ein Limit kann im TargetAllocation-Snapshot und Kunden-PDF stehen, während der
finale Run es überschreitet. Da der Run keinen Limit-Snapshot und keinen
Positionshash besitzt, ist die Ursache nachträglich nicht sicher
rekonstruierbar.

### Verbindlicher Fixvertrag

1. Alle Recommendation-Limits stammen ausschließlich aus dem verifizierten
   Präferenzsnapshot.
2. Die Kontrolle läuft nach vollständiger Aggregation und erneut bei
   Finalisierung.
3. Manuelle Änderungen invalidieren den bisherigen Verdict und erzeugen einen
   neuen Positionshash.
4. Emittentenauflösung und Missing-Issuer-Verhalten werden versioniert und
   fail-closed definiert.
5. Der strengste allgemeine, produktspezifische und regulatorische Deckel
   gewinnt; Runde 25 bleibt hierfür zusätzlich maßgeblich.

## `PREF-MANUAL-001` – Manuelle Recommendation-Positionen umgehen Präferenzen vollständig

### Beobachtung

Der direkte Draft-Create prüft aktuelle RA, Policy, CMA und optional die
TargetAllocation-Anker. `RecommendationRunCreate` besitzt aber kein
Präferenzfeld und der erzeugte Run keinen Präferenzhash.

`add_position()` löst anschließend nur ein nicht gelöschtes Produkt auf:

```python
product = _get_product_or_404(body.product_id, db)
```

Die Variable wird nicht gegen Mandatsuniversum, ProductSuitability,
Produkt-/Geo-/ESG-/Themenrestriktionen oder Limits geprüft. Selbst
`Product.is_active` ist in `_get_product_or_404()` nicht Teil des Filters; für
Finalisierung greift später immerhin eine Active-Prüfung.

Die bekannten Tenant-, Gewichts-, Duplikat- und Mutability-Probleme bleiben
unter `REC-001`, `REC-002` und `REC-004` geführt. Das neue Finding betrifft
ausschließlich die fehlende Präferenz-/Constraint-Eligibility.

### Risiko

Ein Advisor kann einen auf aktuelle Anker zeigenden Draft mit beliebigen
aktiven Produkten befüllen und finalisieren, obwohl diese Produkte den
gespeicherten Kundenrestriktionen widersprechen.

### Verbindlicher Fixvertrag

1. Direct Create und manuelles Add verwenden denselben zentralen Resolver wie
   automatische Selektion.
2. Ohne verifizierte TA-Präferenzentscheidung ist keine Position erzeugbar.
3. Jeder Write berechnet einen neuen kanonischen Positionshash und neuen
   Constraint-Verdict.
4. Nicht konforme Positionen blockieren mit stabilen Reason-Codes; ein freier
   Begründungstext ist kein Override.
5. Falls der manuelle Pfad fachlich nicht benötigt wird, wird er für produktive
   Rollen entfernt statt separat halb abgesichert.

## `PREF-FINAL-001` – Finalisierung prüft Hashintegrität, aber nicht Constraint-Eligibility

### Beobachtung

Der Finalizer lädt RA, TargetAllocation, Policy und CMA, prüft Current-Anker und
ruft `build_target_payload_from_allocation(..., preferences=None)` auf. Dadurch
wird der TA-Context samt gespeichertem Präferenzsnapshot korrekt verifiziert.

Danach prüft er jedoch nur:

- mindestens eine Position;
- Summe zwischen 9900 und 10100 bps;
- Produkt vorhanden, nicht gelöscht und aktiv;
- TER- und Marktpreisprobleme als Warnungen.

Er ruft weder `_product_matches_constraints()` noch die Konzentrationslimit-
Kontrolle auf und besitzt keinen Recommendation-Präferenz-/Positionshash zum
Vergleich. Eine integer verifizierte TargetAllocation und nicht konforme
Recommendation-Positionen können deshalb gemeinsam `Final` werden.

### Risiko

Die vorhandene Hashprüfung kann als stärkere Garantie missverstanden werden,
als sie tatsächlich ist. `Final` beweist nur die Integrität des SAA-Snapshots,
nicht die Präferenzkonformität der finalen Produktliste.

### Verbindlicher Fixvertrag

1. Finalisierung verlangt einen grünen, frischen
   `RecommendationConstraintSnapshot` für exakt diesen Run und Positionshash.
2. TA-`allocation_context_hash`, PreferenceDecision-ID und Positionshash werden
   in derselben Transaktion verifiziert.
3. Jede Positionsänderung macht den Verdict ungültig.
4. Finalisierung läuft unter Lock/CAS und schreibt die geprüften Hashes in den
   Finalzustand.
5. Fehlende, veraltete oder nicht vollständig klassifizierte Evidence
   blockiert fail-closed.

## `PREF-PUBLISH-001` – Publikationskanäle können Präferenztext und andere Positionen kombinieren

### Beobachtung

Der Recommendation-Reload rekonstruiert Analytics mit
`preferences=None`, also aus dem gespeicherten TA-Snapshot, lädt die Positionen
aber unverändert aus dem RecommendationRun. Er prüft diese Positionen nicht
erneut gegen den Snapshot und gibt weder Präferenzhash noch Verdict zurück.

Die Anlagestrategie-PDF liest ebenfalls
`TargetAllocation.preferences_json` und publiziert daraus Nachhaltigkeit,
Universum, Heimmarkt, Währung, Produkt-/Geo-Restriktionen und Themen-Tilts. Die
Produktliste wird separat aus einem RecommendationRun geladen. Dass dieser
PDF-Pfad sogar den neuesten beliebigen Run wählen kann, ist bereits als
`REP-004` dokumentiert; Runde 26 ergänzt, dass selbst ein korrekt
TA-zugeordneter Run keine Präferenzbindung besitzt.

Der Contract-Signoff baut auf denselben Strategiedaten auf. SignedPublication
und Portfolio-Handoff besitzen gemäß Runde 23 bis 25 keinen gemeinsamen
Präferenz-/Eligibility-Fingerprint.

### Risiko

Ein Kundenartefakt kann eine aktive Restriktion sichtbar bestätigen und
gleichzeitig Produkte enthalten, deren Konformität zu genau dieser Restriktion
nicht bewiesen ist. Signatur oder Handoff konservieren dann nur den
ungebundenen Zustand.

### Verbindlicher Fixvertrag

1. Publikation erhält explizit einen Final-Run, dessen TA-, Präferenz- und
   Positionshash gemeinsam geprüft sind.
2. Kein Consumer darf TA, Run und Produktliste unabhängig auswählen.
3. PDF/API/UI zeigen Snapshot-ID, as-of, Rule-/Engine-Version, Coverage und
   Verdict mit identischen Reason-Codes.
4. Signatur bindet die exakten PDF-Bytes und den Constraint-Snapshot.
5. Handoff akzeptiert ausschließlich denselben finalen, signierten oder nach
   Produktentscheidung explizit freigegebenen Snapshot.

## `PREF-GOVERNANCE-001` – Präferenzentscheidung ist kein versioniertes Fachobjekt

### Beobachtung

Vor dem Strategie-Generate lebt der UI-Stand in Cache, `currentPersona` und
LocalStorage. Die UI meldet ausdrücklich „Mandatspräferenzen lokal
aktualisiert“. Erst die TargetAllocation-Erzeugung persistiert den JSON-Stand.

TargetAllocation besitzt gute technische Felder wie `set_by`, `set_at`,
`approved_by`, `approved_at` und den Context-Hash. Es fehlt aber ein eigenes,
versioniertes Präferenz-Fachobjekt mit:

- Quelle und Erfassungsmodus;
- Kunde/Advisor als erklärende beziehungsweise erfassende Identität;
- explizitem Akzeptanz-/Bestätigungsereignis;
- Gültigkeitsbeginn und Supersession;
- Semantik-/Taxonomie-/Engine-Version;
- Enforcement-Modus je Feld;
- Evidence-/Coverage-Status;
- Bindung an Recommendation und deren Positionen.

`RecommendationRun`, API-Response und Alembic-Baseline enthalten entsprechend
keine PreferenceDecision-ID, keinen Präferenzhash und keinen Constraint-
Verdict. Die bestehenden allgemeinen Audit-/Signaturfelder ersetzen diese
fachliche Bindung nicht.

### Risiko

Später lässt sich zwar beweisen, welchen JSON-String die TargetAllocation
enthielt, nicht aber, wer welche konkrete Präferenz in welcher Bedeutung
bestätigt hat und ob die finale Recommendation unter genau dieser
Entscheidung geprüft wurde.

### Verbindlicher Fixvertrag

1. Einführung einer append-only `PreferenceDecision` mit Version,
   `supersedes_id`, Actor-/Customer-Acceptance-Evidence und kanonischem Hash.
2. Pro Feld versionierte Semantik und `enforcement_mode`.
3. TargetAllocation referenziert genau eine gültige PreferenceDecision.
4. RecommendationConstraintSnapshot bindet diese ID und ihren Hash an TA,
   Produktuniversum, Regeln, Positionen und Verdict.
5. Änderungs-, Finalisierungs-, Signatur- und Handoffereignisse werden
   append-only mit denselben Hashankern protokolliert.

## Zielbild: `PreferenceDecision` plus `RecommendationConstraintSnapshot`

### 1. Kanonische Präferenzentscheidung

```text
PreferenceDecision
  id
  mandate_id
  version
  supersedes_id
  canonical_preferences_json
  preferences_hash
  semantics_version
  constraint_engine_version
  captured_by
  captured_at
  source_channel
  client_accepted_by / client_accepted_at / evidence_id
  status = draft | accepted | superseded | revoked
```

Jeder Präferenzwert besitzt zusätzlich einen maschinenlesbaren Status:

```text
hard_constraint
soft_preference
informational_only
unsupported
```

`unsupported` darf in einer freigabefähigen Decision nicht als aktive
Präferenz erscheinen.

### 2. Recommendation-Constraint-Snapshot

```text
RecommendationConstraintSnapshot
  id
  recommendation_run_id
  mandate_id
  target_allocation_id
  allocation_context_hash
  preference_decision_id
  preferences_hash
  product_universe_snapshot_hash
  product_rule_set_hash
  constraint_engine_version
  positions_hash
  per_constraint_verdicts_json
  overall_verdict
  evaluated_at
```

Ein per-Constraint-Verdict enthält mindestens:

```text
constraint_id
preference_path
mode
rule_version
status = pass | fail | unknown | not_applicable
coverage
affected_product_ids
reason_codes
evidence_refs
```

Nur vollständige `pass`-Verdicts der verpflichtenden Constraints erlauben
`Final`.

### 3. Einziger Resolver

```text
verified TargetAllocation
  + accepted PreferenceDecision
  + exact ProductUniverse snapshot
  + exact Product/Exposure/Eligibility rules
  + candidate or manual positions
                    |
                    v
resolve_recommendation_constraints(...)
                    |
          +---------+---------+
          |                   |
          v                   v
        PASS                 FAIL/UNKNOWN
          |                   |
          v                   v
persist snapshot          stable 409
          |
          v
Final -> PDF -> Signatur -> Handoff
all require exact same snapshot/hash
```

## Verbindliche Testmatrix

### Snapshot- und Request-Bindung

- TA mit `noUsd=true`, Recommendation `preferences=None`: kein USD-Produkt.
- TA mit `fundsOnly=true`, Recommendation `preferences=None`: kein
  Einzeltitel.
- TA mit `singlePosition=10`, Recommendation `preferences=None`: Überschreitung
  blockiert.
- TA-Snapshot A plus Request B: stabiler 409 und kein Run/keine Position.
- Semantisch identischer, anders sortierter JSON-Request: kanonischer Hash
  identisch.
- beschädigter oder fehlender TA-Präferenzhash: fail-closed.
- Run speichert PreferenceDecision-, Allocation- und Positionshash.

### UI-Hydration

- gespeicherte TA A plus LocalStorage B nutzt niemals B für Regeneration.
- beide Recoverypfade rufen denselben Helper auf.
- UI-Dirty-State erzwingt neue TA statt alter TA plus neuer Präferenz.
- Browserwechsel verändert Recommendation nicht.
- API-Client ohne `preferences` bleibt snapshotkonform.

### Themen und ESG

- einzig verfügbares fossiles Produkt plus `fossil=exclude`: blockiert.
- fossiles Asset-Class-Fallback plus Ausschluss: blockiert.
- `underweight` überschreitet definierte Exposuregrenze: blockiert.
- `impact` plus SFDR 8 folgt exakt dem festgelegten UI-/Fachvertrag.
- `net_zero` ohne erforderliche Evidence: fail-closed.
- `negative_screening` ohne Rule-/Coverage-Evidence: nicht als bestanden
  publizierbar.
- Missing Classification wird nicht still als neutral behandelt.
- PDF zeigt Hard/Soft/Informational und Coverage korrekt.

### Geo, FX und Limits

- widersprüchliche `homeBias=global` plus `geo.chFocus=true`: 422 oder
  kanonische Ableitung.
- `risk_budget` besitzt echte Boundary- und Aggregationstests.
- `singlePosition` und `singleIssuer` gelten nach Aggregation.
- fehlender Issuer bei aktivem Emittentenlimit: fail-closed.
- manuelle Position über Limit: Add oder Finalisierung blockiert.
- manuelles Produkt außerhalb Universe/Geo/Product-Constraints: blockiert.

### Finalisierung und Tamper

- Positionsänderung nach Verdict invalidiert Snapshot.
- Produkt-/Exposure-/Ruleänderung invalidiert oder versioniert deterministisch.
- direkte DB-Manipulation von Gewicht oder Produkt-ID wird über Positionshash
  erkannt.
- Final ohne ConstraintSnapshot: blockiert.
- Final mit `unknown`-Coverage: blockiert.
- parallele Finalisierung verwendet Lock/CAS und exakt einen Gewinner.

### API, PDF, Signatur und Handoff

- API-Response enthält dieselbe PreferenceDecision-/ConstraintSnapshot-ID wie
  PDF und Handoff.
- PDF-Produkte, TA und Präferenztext stammen aus demselben Final-Run-Kontext.
- rein informative Modi werden nicht mit Erfüllungshäkchen dargestellt.
- signierte Bytes binden die Snapshot- und Positionshashes.
- Handoff lehnt Draft, Superseded, stale oder nicht konforme Snapshots ab.
- Portfolio-/Anlagestrategie-/Contract-Signoff-PDF besitzen kanalgleiche
  Verdicts.

### Schema und Migration

- Alembic, ORM und Bootstrap-Schema enthalten identische Felder/Constraints.
- PreferenceDecision-Versionen sind pro Mandat eindeutig.
- Final-Run referenziert zwingend einen grünen ConstraintSnapshot.
- Positionshash ist 64-stelliges SHA-256-Hex und nicht leer.
- Legacy-Zeilen erhalten keine erfundene Kundenakzeptanz oder grünen Verdict.
- echte PostgreSQL-FK-, Unique-, Check-, Lock- und Race-Tests.

## Empfohlene Umsetzungsreihenfolge

### Phase A – Unmittelbare Fehlfreigabe schließen

1. Bei bestehender TA Request-Präferenzen verbieten oder exakt hashvergleichen.
2. Produktmatcher, Score und Limits ausschließlich aus TA-Snapshot speisen.
3. Direct Create/manuelles Add bis zum zentralen Resolver blockieren.
4. `Final` ohne erneute Constraintprüfung blockieren.
5. Nicht implementierte Themen-/ESG-/FX-Modi als nicht freigabefähig markieren.

### Phase B – Fachsemantik festlegen

1. Hard/Soft/Informational pro Präferenzwert definieren.
2. Themen- und ESG-Taxonomie samt Missing-Data-Regel definieren.
3. FX-Risikobudget und Exposurebasis definieren oder Modus entfernen.
4. Limitpräzedenz und Issuer-Auflösung definieren.
5. Kundenakzeptanz- und Änderungsworkflow definieren.

### Phase C – Datenmodell und zentraler Resolver

1. PreferenceDecision und RecommendationConstraintSnapshot per Alembic
   einführen.
2. Kanonische Hashes und Engine-/Semantikversionen implementieren.
3. Produkt-/Exposure-/Universe-Snapshots anbinden.
4. Automatische und manuelle Positionen durch denselben Resolver führen.
5. Append-only Audit- und Supersessionmodell ergänzen.

### Phase D – Consumer anbinden

1. UI-Hydratepfade konsolidieren.
2. Recommendation API um Snapshot/Verdict erweitern.
3. Finalisierung an exakten Positionshash binden.
4. PDF und Contract-Signoff aus einem expliziten Final-Context rendern.
5. Signatur und Handoff an denselben Snapshot binden.

### Phase E – Abnahme

1. Rote Negativtests vor dem Fix schreiben.
2. Fokussierten und vollständigen Backend-Gate ausführen.
3. Browser-/DOM- und visuelle PDF-Parität abnehmen.
4. Echte PostgreSQL-Migration und Concurrency prüfen.
5. Legacy-, Backup-/Restore-, Export-, Retention- und Tamperfälle abnehmen.

## Definition of Done

Kontrollrunde 26 ist erst geschlossen, wenn **alle** Punkte erfüllt sind:

- [ ] Es existiert genau eine kanonische Präferenzquelle je TargetAllocation.
- [ ] Recommendation-Requests können eine TA nicht mit anderen Präferenzen
      umdeuten.
- [ ] `preferences=None` nutzt für SAA, Produkte, Scores und Limits denselben
      gespeicherten Snapshot.
- [ ] RecommendationRun bindet PreferenceDecision-, Allocation- und
      Positionshash.
- [ ] Präferenzdrift blockiert mit stabilem Reason-Code.
- [ ] UI-Hydrate-/Recoverypfade sind deterministisch und serverautoritativ.
- [ ] Jeder Präferenzmodus ist als hard, soft, informational oder unsupported
      klassifiziert.
- [ ] Themenausschlüsse sind echte Exposure-Hardconstraints.
- [ ] Themenuntergewichte besitzen messbare, getestete Grenzen.
- [ ] Best-in-Class, Impact und Net Zero besitzen getrennte, evidenzbasierte
      Semantik.
- [ ] UI-/PDF-Claims entsprechen exakt der implementierten ESG-Regel.
- [ ] Informational-only wird nie als technisch erfüllte Restriktion gezeigt.
- [ ] Redundante `chFocus`-/HomeBias-Felder können nicht widersprechen.
- [ ] FX-`risk_budget` ist implementiert oder entfernt.
- [ ] Einzelpositions-/Emittentenlimits gelten auch bei `None` und manuell.
- [ ] Direct Create und Add Position verwenden denselben Constraint-Resolver.
- [ ] Finalisierung prüft TA-, PreferenceDecision- und Positionshash atomar.
- [ ] Jede Positionsänderung invalidiert den alten Verdict.
- [ ] API, UI, PDF, Signatur und Handoff verwenden dieselbe Snapshot-ID.
- [ ] Kein Consumer wählt TA, Run oder Produkte unabhängig.
- [ ] Kundenakzeptanz und Advisor-Erfassung sind getrennt nachvollziehbar.
- [ ] Semantik-/Taxonomie-/Engine-Versionen sind unveränderlich gespeichert.
- [ ] Legacy-Bestand wird nicht still als akzeptiert oder compliant markiert.
- [ ] Alembic, ORM, SQLite und PostgreSQL besitzen denselben Vertrag.
- [ ] Negative API-/Tamper-/Race-/Browser-/PDF-Tests sind grün.
- [ ] Echte PostgreSQL- und visuelle Browser-/PDF-Abnahme ist dokumentiert.
- [ ] Frühere `REC-*`, `REP-*`, Eligibility-, Signatur- und Handoff-Findings
      bleiben separat geschlossen nachweisbar.

## Claude-/GPT-Startcheckliste

Vor jeder Implementierung:

1. Diesen Audit vollständig lesen.
2. Danach Kontrollrunde 25, `REC-001/002/004`, `REP-004`, Runde 23 und Runde
   24 lesen.
3. Keine weitere lokale Präferenzkopie als neue Wahrheit einführen.
4. Zuerst Hard/Soft/Informational/Unsupported-Semantik schriftlich festlegen.
5. Rote Tests für TA-A/Request-B, `None`, manuelles Add, Themenausschluss und
   Impact-SFDR-8 schreiben.
6. Bei bestehender TA ausschließlich den verifizierten Snapshot verwenden.
7. Den verlorenen Warntext nicht nur sichtbar machen; der Kontextkonflikt muss
   blockieren.
8. Einen zentralen Constraint-Resolver bauen, keinen zweiten Matcher.
9. Finalisierung, PDF, Signatur und Handoff in derselben Änderung anbinden oder
   bis dahin blockieren.
10. Altbestand inventarisieren; keine Preference-Akzeptanz erfinden.
11. Keine ACL-unlesbaren `.pytest_tmp*`-Verzeichnisse betreten oder bereinigen.
12. Kein `git add -A`; nur explizite Manifestpfade stagen.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

- auditierter Head: `b5de5c9fb5cad1daf04f7e861a3f94ae81177db0`
- sichtbare tracked/untracked Änderungen: `0`
- beim Statusaufruf ausgegebene ACL-Warnzeilen zu unlesbaren pytest-
  Tempverzeichnissen: `53`
- globale Clean-Aussage: ausdrücklich **nein**
- Produktcode verändert: **nein**
- Tests verändert: **nein**

Die ACL-unlesbaren Verzeichnisse wurden nicht betreten, verändert oder
bereinigt.

### Statische Negativ- und Kontrollflussbelege

Repositoryweite Suchläufe und direkte Kontrollflussprüfung ergaben:

| Suchziel | Ergebnis |
|---|---|
| RecommendationRun-Präferenzsnapshot/-hash | kein ORM-, API- oder Alembic-Feld |
| `generate_recommendation_run()` bei `None` | TA-Rebuild nimmt Snapshot; Produktloop nimmt leere normalisierte Request-Prefs |
| abweichende Recommendation-Prefs | keine Equality-/Hash-Precondition gegen TA-Snapshot |
| Präferenzdriftwarnung | im Target-Payload erzeugt, nicht in Recommendation-Warnings übernommen |
| `tilts=exclude/underweight` im Suballokationsbuilder | kein Reader; nur `overweight_tilts` |
| Themen in Produktmatcher | keine Prüfung |
| Themen im Produktscore | Ziel-Sleeve-String statt Produktexposure; `-10000` bleibt auswählbar |
| ESG `best_in_class/impact/net_zero` | identischer SFDR-8/9-Block |
| Impact-/Net-Zero-Evidencefelder | keine entsprechenden Produktfelder |
| `geo.chFocus` im Backend | kein fachlicher Reader |
| `hedging=risk_budget` | ausschließlich gleicher `+20`-Score wie `hedged` |
| Direct Create/Add Position | keine Präferenz-/Constraintprüfung |
| Finalisierungsvalidator | kein Produktmatcher, keine allgemeinen Präferenzlimits, kein Positionshash |
| PDF-Präferenzen | TargetAllocation-Snapshot |
| PDF-Produkte | separat gewählter RecommendationRun; `REP-004` bleibt offen |

Direkte Kontrollflüsse schließen ohne Interpretation:

1. Ein vorhandener TA-Snapshot wird bei `preferences=None` nicht in die äußere
   Recommendation-Variable `prefs` übernommen.
2. `_product_matches_constraints()` und die Limitprüfung lesen ausschließlich
   diese äußere Variable.
3. Ein abweichender Request wird trotz erkanntem Drift nicht abgelehnt.
4. `ranked[0]` wählt auch Kandidaten mit Score `-10000`.
5. Der Finalizer verifiziert TA-Artefakte, aber nicht die Positionen gegen
   deren Präferenzen.
6. Der Run enthält keinen Wert, mit dem ein späterer Consumer den tatsächlich
   verwendeten Produktconstraint-Kontext beweisen könnte.

### Kein neuer isolierter Negativharness

In Runde 25 erhielt ein ausschließlich für `C:\tmp` geplanter isolierter
Reproduktionsharness keine Tool-Sicherheitsfreigabe. Diese Entscheidung wurde
in Runde 26 nicht umgangen. Es wurde kein neuer Custom-Harness erzeugt oder
ausgeführt.

Die Einstufung stützt sich auf direkte Produktionskontrollflüsse,
repositoryweite Negativsuche, ORM-/Schema-/Alembic-Vergleich, UI-/PDF-
Quellenvergleich und den fokussierten bestehenden Test-Gate.

### Fokussierter Bestands-Gate

Ausgeführt aus `5eyes-backend` ohne Cacheprovider:

```powershell
python -m pytest -p no:cacheprovider `
  tests/test_allocation_preferences_fail_closed_contracts.py `
  tests/test_portfolio_engine_regressions.py `
  tests/test_portfolio_generate_after_saa_recalc.py `
  tests/test_asset_allocation_reference_integrity_edges.py `
  tests/test_restriktionen_tilts_audit_fixes.py `
  tests/test_products_esg_filter.py `
  tests/test_frontend_navigation_contracts.py `
  tests/test_finalize_mandate_lock.py `
  tests/pdf/test_renderer.py `
  tests/test_runtime_contracts.py::test_current_payload_rebuild_uses_stored_allocation_preferences `
  -q
```

Ergebnis:

```text
274 passed in 167.87s (0:02:47)
```

Der Gate bestätigt insbesondere strikte Präferenz-Inputvalidierung,
TargetAllocation-Context-Verifikation, vorhandene Produktfilter,
Suballokations-Positivpfade, PDF-Rendering und Finalisierungsanker.

Er enthält keinen Negativtest für:

- gespeicherte TA-Restriktionen plus Recommendation `preferences=None`;
- TA-Präferenzsatz A plus Recommendation-Request B;
- Run-Präferenz-/Positionshash;
- Themenausschluss als harter Produkt-/Exposurefilter;
- Impact-SFDR-9-Parität;
- `geo.chFocus`-/FX-Risikobudgetsemantik;
- manuelle Positionen gegen TA-Präferenzen;
- Final-/PDF-/Signatur-/Handoff-ConstraintSnapshot-Parität.

### Letzter vollständiger Backend-Gate

Der letzte vollständig dokumentierte Backend-Gate gehört weiterhin zum
Implementierungscommit `661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4`:

```text
6074 bestanden
0 fehlgeschlagen
10 übersprungen
1 erwartetes XFail
```

Er wurde in dieser Read-only-Runde nicht erneut ausgeführt und ist kein Ersatz
für die fehlende neue Negativtestmatrix, Browser-/PDF-Abnahme oder echte
PostgreSQL-Concurrency-Prüfung.

### Dokumentationsmanifest dieser Runde

Es dürfen ausschließlich diese fünf Dateien geändert werden:

```text
docs/audits/2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md
docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md
docs/CLAUDE_HANDOFF.md
docs/deploy/README.md
docs/deploy/provisioning-runbook.md
```

Produktcode, Tests, Migrationen und generierte Artefakte gehören ausdrücklich
nicht zum Manifest.

## Schlussentscheidung

Kontrollrunde 26 bestätigt neue release-blockierende P1. Der
TargetAllocation-Präferenzsnapshot und sein Hash sind ein guter, aber lokal
begrenzter Kontrollpunkt. Die Recommendation verwendet daneben einen zweiten,
nicht persistierten Request-Kontext; mehrere publizierte Präferenzmodi besitzen
keine behauptete Wirkung; manuelle Positionen und Finalisierung schließen die
Lücke nicht.

Die sichere nächste Einheit ist deshalb ein kanonischer
`PreferenceDecision`- und `RecommendationConstraintSnapshot`-Vertrag. Erst
wenn automatische und manuelle Selektion, Limits, Finalisierung, PDF,
Signatur und Handoff exakt dieselben verifizierten Hashanker und Verdicts
verwenden, ist die publizierte Präferenzkonformität technisch beweisbar.
