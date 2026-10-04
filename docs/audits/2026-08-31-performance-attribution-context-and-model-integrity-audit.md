---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-performance-attribution-context-and-model-integrity-followup-audit"
status_as_of: "2026-08-31"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "d38b553e2afa5ccbca1cfb6c119a46715efda023"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md"
prior_release_audit_commit: "d38b553e2afa5ccbca1cfb6c119a46715efda023"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-31-performance-attribution-context-and-model-integrity-audit.md"
audit_mode: "read_only_static_service_advisory_api_frontend_review_orm_and_math_reproduction_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "performance attribution naming and economic meaning, risk-score mapping, allocation and CMA provenance, Brinson arithmetic, weight-domain validation and advisory publication behavior"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 115
focused_adjacent_tests_skipped: 1
focused_adjacent_tests_failed: 0
focused_adjacent_test_warnings: 1
required_next_action: "replace the current degraded forward-looking pseudo-attribution with either a strictly named expected SAA policy-tilt analysis bound to the verified allocation snapshot or a true ex-post attribution with frozen period, holdings, returns, flows, fees, FX and benchmark data; fix risk-score bucketing and arithmetic/domain validation before any customer publication"
---

# Performance-Attribution-Context- und Modellintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die achtzehnte Read-only-
Kontrollrunde. Er wurde gegen Repository-Head `d38b553e` durchgeführt und
ergänzt, ersetzt aber nicht:

1. den
   [Stress-Replay-/Policy-A/B-Modellintegritätsaudit](2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md),
2. den
   [Strategy-Backtest-Context-/Gebühren-/Publikationsintegritätsaudit](2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md),
3. den
   [Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit](2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md),
4. den
   [Historische-Renditen-/Schema-/Driftintegritätsaudit](2026-08-28-historical-return-schema-and-drift-integrity-audit.md),
5. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
6. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
7. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
8. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
9. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
10. den
    [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
11. den
    [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
12. den
    [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
13. den
    [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
14. den
    [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
15. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
16. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
17. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
18. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst,
danach dieser Audit und anschließend die vorgenannten Dokumente in dieser
Reihenfolge. Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Drei P1-Verträge und ein P2-Vertrag sind
zusätzlich offen:

- Die als `Performance-Attribution (Brinson)` bezeichnete Sektion ist keine
  Ex-post-Performanceattribution. Sie besitzt weder Berichtsperiode noch
  realisierte Holdings, Renditen, Cashflows, Gebühren, FX-Umrechnung oder einen
  eingefrorenen Marktbenchmark. Portfolio und House-Matrix-Benchmark erhalten
  dieselben aktuellen CMA-Erwartungsrenditen; Selection und Interaction sind
  daher konstruktiv null. Fachlich ist dies höchstens eine erwartete
  SAA-Policy-Tilt-Analyse.
- Die Builder-Query vergleicht `final_score_x10` direkt mit House-Matrix-
  Bereichen `1..10`. Ein fachlich gültiger Score `80` sucht deshalb Bucket 80
  und liefert den degradierten Leerzustand statt einer Analyse.
- Allocation, Risk Assessment, House Matrix und CMA werden über unabhängige
  Current-/`.first()`-Queries zusammengebaut. Der moderne Allocation-Context,
  Snapshot-CMA, Tenant/Jurisdiktion, Approval, Input-/Context-Hash und die
  persistierten Sub-Allokationen werden nicht geprüft. Fehlende CMA-Werte
  werden zu null Rendite umgedeutet.
- Die Rechenfunktion akzeptiert negative und gehebelte Gewichte. Ihr Total-
  Interaction-Wert ist nicht der Brinson-Interaction-Term, sondern ein
  Residuum, das die Summenidentität künstlich erzwingt. Im ausgeführten
  Beispiel war der ausgewiesene Total-Interaction-Effekt `1 bp`, während die
  eigentliche Interaction-Formel `0 bp` ergab.

Der bestehende fokussierte Gate bleibt grün, weil er diese Verträge nicht
prüft: Der Integrationstest akzeptiert ausdrücklich `degraded`; der
Property-Sweep prüft nur die per Residuum erzwungene Identität.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `ATTR-SEMANTICS-001` | P1 | offen | Kundenbezeichnungen und Methodik unterscheiden strikt zwischen erwarteter SAA-Tilt-Analyse und echter, periodenbezogener Ex-post-Performanceattribution |
| `ATTR-CONTEXT-001` | P1 | offen | Jede publizierte Analyse verwendet genau den verifizierten Allocation-/Publication-Context einschließlich exakter RA, Policy, Snapshot-CMA, Jurisdiktion, Tenant, Sub-Allokationen und Hashes |
| `ATTR-SCORE-001` | P1 | offen | Validierter `score_x10` wird ausschließlich über den kanonischen Bucket-Helper auf `1..10` abgebildet; fehlende oder mehrdeutige House-Matrix-Basis blockiert fail-closed |
| `ATTR-MATH-001` | P2 | offen | Gewicht-, Return- und Reconciliation-Domänen sind strikt; jede ausgewiesene Brinson-Komponente entspricht ihrer Formel und Totals/Buckets besitzen eine dokumentierte Rundungsregel |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Forward-looking-Default und gleiche Portfolio-/Benchmarkreturns | `5eyes-backend/services/performance_attribution.py:112-143` |
| Keine Gewichts-/Return-Domänenvalidierung | `5eyes-backend/services/performance_attribution.py:145-180` |
| Bucket-Effekte werden einzeln per Floor-Division gerundet | `5eyes-backend/services/performance_attribution.py:160-178` |
| Total-Interaction wird als Residuum erzwungen | `5eyes-backend/services/performance_attribution.py:183-206` |
| Builder lädt Current-TA per `.first()` | `5eyes-backend/services/advisory_report.py:3647-3656` |
| Builder lädt RA per `.first()` ohne Deleted-Filter | `5eyes-backend/services/advisory_report.py:3666-3677` |
| `final_score_x10` wird direkt gegen House-Matrix `1..10` verglichen | `5eyes-backend/services/advisory_report.py:3676-3688`; `5eyes-backend/services/portfolio_engine_house_matrix.py:1289` |
| Kanonische Score-Validierung/-Abbildung existiert bereits | `5eyes-backend/services/portfolio_engine.py:579-589` |
| Builder lädt globale Current-CMA per `.first()` | `5eyes-backend/services/advisory_report.py:3708-3717` |
| Nur fünf CH-/Gold-CMA-Felder, Missing wird über `_safe_int` null | `5eyes-backend/services/advisory_report.py:2925-2929`; `:3713-3719` |
| Builder deklariert Brinson-/FIDLEG-Basis und fängt jede Exception | `5eyes-backend/services/advisory_report.py:3721-3749` |
| Verifizierter persistierter Allocation-Context existiert | `5eyes-backend/services/portfolio_engine.py:4160-4365` |
| Kanonischer Allocation-Rebuild existiert | `5eyes-backend/services/portfolio_engine.py:5386-6164` |
| Jurisdiktions-/Tenant-CMA-Resolver existiert | `5eyes-backend/services/jurisdiction/resolve.py:74-145` |
| Runtime-CMA-Vollständigkeitsgate existiert | `5eyes-backend/services/cma_validation.py:44-111` |
| Advisory JSON wird gecacht und unverändert ausgeliefert | `5eyes-backend/routers/allocation.py:618-631`; `5eyes-backend/services/advisory_report_cache.py:154-176` |
| Kundenportal liefert denselben Aggregator direkt | `5eyes-backend/routers/client_portal.py:92-116` |
| Frontend-API verlangt die Sektion, rendert sie derzeit aber nicht | `5eyes-electron/frontend/reporting/src/api/client.ts:135-170`; `5eyes-electron/frontend/reporting/src/api/types.ts:828-854`; `5eyes-electron/frontend/reporting/src/App.tsx:477` |
| Tests akzeptieren degradierten Builder und prüfen nur Restidentität | `5eyes-backend/tests/test_performance_attribution.py:189-208`; `:272-330` |

## `ATTR-SEMANTICS-001` – Erwartete Policy-Tilts sind keine Performanceattribution

### Tatsächlich gerechnete Information

Die Builder-Dokumentation nennt als Portfolio die aktuellen TA-Bucketgewichte,
als Benchmark die House-Matrix-Defaultgewichte und als Returns die aktuelle
CMA. `benchmark_returns_bps` wird nicht übergeben; die Rechenfunktion kopiert
deshalb `portfolio_returns_bps` als Benchmarkreturns.

Damit gilt pro Bucket konstruktiv:

```text
selection   = benchmark_weight * (portfolio_return - benchmark_return) = 0
interaction = weight_delta     * (portfolio_return - benchmark_return) = 0
```

Übrig bleibt ausschließlich die erwartete Renditedifferenz aus abweichenden
Top-Level-Gewichten. Das kann als prospektive SAA-Tilt- oder Policy-
Abweichungsanalyse nützlich sein. Es ist jedoch keine Messung tatsächlich
erzielter Performance und keine Zerlegung einer historischen Über-/
Unterrendite.

Es fehlen mindestens:

- eindeutiger Periodenbeginn, Periodenende und As-of;
- tatsächliche Start-/Durchschnittsgewichte und Portfolio-TWR;
- realisierte oder marktbasierte Bucket-/Security-Returns;
- externer Benchmark einschließlich Index, Currency und Total-/Price-Return;
- Cashflows und Flow-Timing;
- Gebühren, Steuern und andere Kosten;
- FX-Kurse, Hedging und Bewertungswährung;
- Datenquellen, Abrufzeit, Version und Hash;
- Rebalancing-/Corporate-Action-Konventionen.

Trotzdem lauten Methode und Quellenlabel `brinson_fachler_hood_1986`,
`performance_attribution` und `FIDLEG`-Methodentransparenz. Diese Bezeichnung
kann einen prospektiven Konfigurationsvergleich als historische
Leistungsanalyse erscheinen lassen.

### Verbindlicher Zielvertrag

Es gibt nur zwei saubere Varianten:

1. **Prospektive Analyse:** in API, UI und Dokumenten eindeutig als
   `expected_saa_policy_tilt_analysis` beziehungsweise „Erwartete SAA-
   Abweichungsanalyse“ benennen. Selection/Interaction nicht als scheinbar
   gemessene Nullen publizieren. Allocation, House-Matrix und CMA müssen aus
   einem eingefrorenen, verifizierten Entscheidungscontext stammen.
2. **Ex-post-Attribution:** echte periodenbezogene Positions-, Return-, Flow-,
   Fee-, FX- und Benchmark-Snapshots persistieren und daraus eine versionierte
   Attribution erzeugen. Fehlt eine Pflichtquelle, bleibt die Sektion
   unavailable oder der finale Publikationspfad blockiert; sie wird nie aus
   aktuellen CMA-Erwartungen rekonstruiert.

## `ATTR-SCORE-001` – Gültiger Score 80 sucht einen nicht existierenden Bucket 80

### Ursache

Der Strategy-Score ist in Zehntelpunkten gespeichert (`0..100`). Die House-
Matrix deckt nach ihrer eigenen Runtime-Validierung exakt die Buckets `1..10`
ab. Der produktive Optimizer ruft dafür
`risk_score_bucket_from_validated_score()` über `_risk_score_bucket()` auf.

Der Attribution-Builder überspringt beide Validatoren und verwendet
`final_score_x10` direkt in:

```text
HouseMatrix.score_from <= risk_score <= HouseMatrix.score_to
```

### Ausgeführte ORM-Reproduktion

Mit dem kanonischen Testmandat, einer aktuellen TA und einem fachlich
hergeleiteten Current-RA-Score `80` ergab der direkte Builder-Aufruf:

```text
final_score_x10 = 80
error = "Keine House-Matrix-Default fuer das Risikoprofil gefunden."
buckets = 0
```

Das ist kein seltener Randfall, sondern der Normalfall für gültige Scores über
10. Der Bericht liefert dadurch einen formal vollständigen Null-/Error-Block,
obwohl eine House-Matrix für Bucket 8 vorhanden ist.

### Fixvertrag

- Zuerst `validate_risk_assessment_model_input()` auf der exakt zur Allocation
  gehörenden RA ausführen.
- Danach ausschließlich den kanonischen Score-Bucket-Helper verwenden.
- House-Matrix über die exakte `TA.policy_id` laden und exactly-one für den
  Bucket verlangen; Overlap und Missing sind Domainkonflikte.
- Current-RA und `TA.based_on_assessment_id` müssen übereinstimmen. Soft-
  gelöschte, historische oder fremde RAs sind kein Fallback.
- Keine Clamp-, Default- oder `.first()`-Semantik.

## `ATTR-CONTEXT-001` – Live-Hybrid statt Allocation-Snapshot

### Unabhängige Queries

Die Sektion baut ihren Kontext aus vier voneinander unabhängigen Reads:

1. erste Current-TA des Mandats;
2. jüngste Current-RA des Mandats;
3. erste aktive House-Matrix-Row der TA-Policy und des fehlerhaft verwendeten
   Scores;
4. jüngste globale Current-CMA.

Sie prüft nicht:

- `context_artifacts_required == 1`;
- `based_on_assessment_id` und `capital_market_assumptions_id`;
- `input_snapshot_hash` und Live-Inputdrift;
- `allocation_context_hash`;
- `sub_allocations_json` und `effective_constraints_json`;
- Policy-/RA-/CMA-Currentness und Soft-Delete vollständig;
- CMA-Tenant, Jurisdiktion und Freigabestatus;
- Runtime-CMA-Vollständigkeit;
- Engine-Version, Methodik und Publication-Fingerprint.

Für die Returns verwendet sie ausschließlich fünf Live-Felder der gewählten
CMA: CH-Aktien, CHF-IG-Bonds, CH-Immobilien, Gold und Liquidität. Dadurch werden
unter anderem DE-Home-Annahmen, internationale Mischungen, persistierte
Sub-Allokationen und optimizerwirksame Modellanpassungen ignoriert. `_safe_int`
macht `NULL`, leere Werte und viele Fehler zu `0`.

### Publikationsfolge

Jede Exception wird broad gefangen und als Null-Payload mit `error` ausgeliefert.
Der Advisor-Endpoint kann diesen Block zusätzlich vor einem künftigen Context-
Preflight cachen; das Kundenportal verwendet denselben Aggregator direkt. Das
React-Schema verlangt die Sektion, während die aktuelle App sie noch nicht
als eigene Ansicht rendert. Die Zahl ist damit bereits API-/Kundenportal-
Bestandteil, auch wenn die React-Darstellung noch „In Vorbereitung“ zeigt.

### Verbindlicher Zielvertrag

- Der zentrale Advisory-Publication-Preflight aus dem Post-Commit-Audit läuft
  **vor** Cache, Aggregator und Renderer.
- Die Attribution erhält den bereits aufgelösten, unveränderlichen
  `AdvisoryPublicationContext`; innerhalb des Builders sind keine Current-
  Queries erlaubt.
- Für eine prospektive SAA-Tilt-Analyse stammen Allocation, Bucket-/Sub-
  Allocation, Policy-House-Matrix und CMA aus exakt demselben verifizierten
  Decision Snapshot. Snapshot-CMA ist nie durch eine aktuelle CMA ersetzbar.
- CH/DE, Tenant und Approval werden über die bestehenden Resolver-/Validation-
  Gates geprüft. Keine Rohfeld-Defaults.
- Final-/Kundenmodus behandelt fehlenden oder korrupten Pflichtcontext als
  stabilen HTTP-409-Konflikt; Renderer und Cache werden nicht aufgerufen.
- Preview darf den Fehler sichtbar und strukturiert ausweisen, aber niemals
  Nullwerte als berechnete Attribution darstellen.

## `ATTR-MATH-001` – Restterm statt Interaction und fehlende Domäne

### Ausgeführte Reproduktionen

Die reine Funktion akzeptierte ohne Fehler:

```text
portfolio weights: equities 15000, bonds -5000
benchmark weights: equities 5000, bonds 5000
result portfolio return: 950 bps
result excess return: 500 bps
```

Ein negatives Bucketgewicht und ein 150-Prozent-Exposure werden somit als
normale Attribution gerechnet.

Der Sweep über kleine Gewichts- und Returndifferenzen fand außerdem:

```text
equity weight delta = -20 bps
equity return delta = -13 bps
reported total interaction = 1 bp
formula total interaction  = 0 bp
sum displayed bucket interactions = 0 bp
```

Der Grund ist dokumentierter Code: Allocation und Selection werden aus ihren
akkumulierten Numeratoren gefloort; Interaction wird nicht aus ihrem
akkumulierten Numerator berechnet, sondern als
`total_excess - allocation - selection` erzwungen. Dadurch stimmt die
Gesamtidentität immer, aber der ausgewiesene Wert ist nicht mehr die
Interaction-Formel und reconciliert nicht zwingend zu den Bucketzeilen.
Python-Floor-Division rundet negative Terme zusätzlich asymmetrisch nach unten.

### Fixvertrag

- Exakte erlaubte Bucketmenge; keine unbekannten oder fehlenden Pflichtkeys.
- Alle Gewichte echte Integer, keine Bools; `0..10000`; Portfolio und
  Benchmark jeweils exakt 10.000 bps oder explizit dokumentierte Cash-
  Restkomponente.
- Returns echte finite Integer-Bps innerhalb eines fachlich definierten
  Bereichs; Missing ist Fehler, nicht null.
- Alle drei Komponenten aus ihren tatsächlichen Numeratoren berechnen.
- Eine einzige dokumentierte Rundungsregel, idealerweise Decimal-/Rational-
  Reconciliation mit explizitem Rundungsrest als eigener technischer Wert,
  nicht als fachliche Interaction.
- Summe der publizierten Bucketkomponenten und Totals muss bis zur expliziten
  Rundungstoleranz reconciliieren. Keine Komponente darf nur zur Erfüllung der
  Identität umgeschrieben werden.

## Verbindliche Testmatrix

### Semantik und Context

Neue Datei `tests/test_performance_attribution_publication_contract.py`:

- gültiger moderner CH-Context liefert exakt seine RA-, Policy-, CMA-, TA- und
  Hash-IDs in `model_basis`;
- dasselbe für DE mit DE-Home-/Tenant-CMA; CH-Current-CMA darf nicht gelesen
  werden;
- `context_artifacts_required=1` mit missing/partial/corrupt Contextartefakten
  blockiert vor Berechnung;
- RA-/Policy-/CMA-ID-Mismatch, soft-deleted oder noncurrent Anker, falscher
  Tenant/Jurisdiktion und unapproved CMA blockieren;
- Wealth-/Cashflow-/Goal-/Preference-Drift blockiert;
- Snapshot-CMA fehlt oder ist soft-deleted: aktuelle Ersatz-CMA darf nicht
  impersonieren;
- Builder erzeugt keine DB-Writes und ruft keine Seeder auf;
- Cache-Hit wird erst nach erneutem Publication-Preflight bedient.

### Score und House Matrix

- gültige Scores an allen kanonischen Bucketgrenzen, insbesondere `0`, `25`,
  `45`, `65`, `80`, `95`, werden über denselben Helper wie Generate gemappt;
- `80` verwendet House-Matrix-Bucket 8;
- invalid score/profile, raw Bool/String, Missing und Override-Inkonsistenz
  blockieren vor House-Matrix-Query;
- 0 oder mehr als 1 aktive House-Matrix-Row für den wirksamen Bucket blockiert;
- fremde Policy oder `.first()`-Reihenfolge kann das Resultat nicht ändern.

### Mathematik

Neue Property-/Boundary-Verträge:

- negative, über 10.000 liegende, Bool-/String- und nicht auf 10.000
  summierende Gewichte werden abgelehnt;
- fehlende, nichtfinite oder außerhalb der Fachdomäne liegende Returns werden
  abgelehnt;
- jede Bucketkomponente entspricht exakt ihrer Formel;
- Total jeder Komponente entspricht der definierten Aggregation ihrer Buckets;
- Rundungsrest ist separat und bounded; Interaction ist nie Residuum;
- Permutation der Inputdict-Reihenfolge verändert nichts;
- zufällige gültige Portfolios erfüllen Reconciliation und Bounds.

### Publikation

- Advisor JSON, Kundenportal und Advisory-PDF liefern bei jedem Pflichtfehler
  409; Cache/Renderer werden nicht aufgerufen;
- prospektive Analyse ist in Schlüssel, Titel, Beschreibung und Methodik
  eindeutig als erwartet gekennzeichnet;
- Ex-post-Attribution verlangt Periode, As-of, Benchmark, Holdings, Returns,
  Flows, Fees, FX, Quellen und Hash;
- `error` plus numerische Nullen darf nicht als berechnetes Ergebnis gelten;
- React-Types und Renderer besitzen discriminated status
  `available|unavailable|blocked` statt scheinbarer Pflichtnullen;
- Preview/Final, JSON/PDF/Kundenportal verwenden dieselbe Context-ID und
  denselben Publication-Fingerprint.

## Empfohlene Umsetzungsreihenfolge

1. Produktentscheidung treffen: prospektive SAA-Tilt-Analyse kurzfristig
   korrekt benennen; echte Ex-post-Attribution separat spezifizieren.
2. Builder aus dem freien Aggregator lösen und an den zentralen
   Advisory-Publication-Context binden.
3. Score-Bucket über die bestehende validierte Helperfunktion korrigieren und
   exactly-one House-Matrix-Vertrag nutzen.
4. Snapshot-CMA-/Jurisdiktions-/Tenant-/Completeness-Gates und persistierte
   Sub-Allokationen verwenden.
5. Rechenfunktion mit strikten Domains und ehrlicher Rundungsreconciliation
   härten.
6. API-/Frontendstatus migrieren; finalen Publikationspfad bei
   Integritätsfehlern blockieren.
7. Erst danach eine echte Ex-post-Pipeline mit eingefrorenen Markt-/Portfolio-
   Snapshots ergänzen.

## Definition of Done

Dieser Blocker ist erst geschlossen, wenn gleichzeitig gilt:

- kein Kundenfeld nennt prospektive CMA-Tilts „Performance-Attribution“;
- gültiger Score `80` verwendet deterministisch Bucket 8;
- exakt dieselben RA-/Policy-/CMA-/TA-/Suballocation-/Hash-Anker wie der
  freigegebene Allocation-Snapshot werden verwendet;
- CH/DE und Tenant sind vollständig getrennt und testbelegt;
- Missing-/Corrupt-/Drift-Inputs führen im Finalpfad zu 409 vor Cache und
  Renderer;
- Gewichte und Returns sind strikt validiert;
- Allocation, Selection und Interaction entsprechen jeweils ihrer Formel;
- Bucketzeilen und Totals reconciliieren nach dokumentierter Rundung;
- eine echte Ex-post-Sektion besitzt vollständig eingefrorene Periode,
  Holdings, Benchmark, Returns, Flows, Fees, FX, Quellen und Hash;
- API, Kundenportal, React und PDF zeigen dieselbe Semantik und Context-ID;
- neue Negativ-, Property-, CH/DE-, Cache-, Endpoint- und Publikationstests
  laufen grün;
- bestehende Tests wurden nicht durch breite Golden-/Null-Orakelupdates
  beruhigt.

## Claude-/GPT-Startcheckliste

Vor jeder Änderung in dieser Fläche:

1. Diesen Audit und die drei unmittelbar vorherigen Audits vollständig lesen.
2. Nicht die bestehende Null-/`error`-Form als fachlich berechnetes Ergebnis
   konservieren.
3. Keine neue Current-/`.first()`-Query im Attribution-Builder ergänzen.
4. Den zentralen Publication-Context injizieren; keine Seeder oder Writes im
   Readpfad.
5. Den vorhandenen Risk-Score-, CMA-, Jurisdiktions- und Allocation-Context-
   Validator wiederverwenden.
6. Prospektive und Ex-post-Analyse als getrennte Datenverträge behandeln.
7. Tests zuerst rot auf Score 80, DE-vs-CH, kaputten Context, negative Gewichte
   und Interaction-Reconciliation schreiben.
8. Finalpfade auf 409 plus „Renderer/Cache nicht aufgerufen“ prüfen.
9. Keine historischen Snapshot-/Stress-/Backtest-Fixes durch Live-CMA-
   Fallbacks umgehen.
10. Nach Umsetzung Audit, Stable Entry, Claude-Handoff, Deploy- und
    Provisioning-Blocker synchron aktualisieren.

## Unveränderte Baseline- und Audit-Evidenz

Ausgeführter fokussierter Gate:

```text
python -m pytest -q -p no:cacheprovider --basetemp <TEMP> \
  tests/test_performance_attribution.py \
  tests/test_risk_metrics_kpi.py \
  tests/property/test_risk_metrics_kpi_properties.py \
  tests/test_advisory_report.py \
  tests/test_ar2_persist_mc_risk_kpis.py
```

Ergebnis:

```text
115 passed, 1 skipped, 1 warning in 60.80s
```

Der Skip ist die optionale, lokal nicht installierte Hypothesis-Abhängigkeit.
Die Warnung ist die bekannte Python-3.14-Deprecation zu `datetime.utcnow()`.
Der Gate ist Regressionsevidenz, aber keine Widerlegung der Findings:

- der Builder-Test akzeptiert einen degradierten Payload;
- es gibt keinen gültigen Score-80-/House-Matrix-Happy-Path;
- es gibt keinen Allocation-/Snapshot-/CH-DE-Contextvertrag;
- der Sweep prüft nur, dass der als Residuum erzeugte Interaction-Wert die
  Totalidentität erzwingt;
- invalid/negative/gehebelte Gewichte werden nicht getestet.

Der letzte vollständige Backend-Gate bleibt unverändert:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
```

Auch dieser grüne SQLite-Gate hebt die bestätigten Semantik-, Context-, Score-
und Mathematikblocker nicht auf.
