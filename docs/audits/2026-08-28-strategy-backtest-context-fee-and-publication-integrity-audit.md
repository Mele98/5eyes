---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-strategy-backtest-context-fee-and-publication-integrity-followup-audit"
status_as_of: "2026-08-28"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "ab6615eea2d2119b1c34516b14434ee537e1c6a1"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md"
prior_release_audit_commit: "ab6615eea2d2119b1c34516b14434ee537e1c6a1"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md"
audit_mode: "read_only_static_router_service_pdf_frontend_review_isolated_http_reproduction_direct_pdf_mapping_and_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "strategy backtest decision context, annual/daily fee parity, request-domain integrity, benchmark parity and customer PDF disclosure"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 80
focused_adjacent_tests_skipped: 1
focused_adjacent_tests_failed: 0
required_next_action: "bind every published backtest to one verified modern allocation context, apply and disclose one strict fee/input contract in annual and daily modes, and make JSON, UI and PDF consume the same typed result and benchmark fingerprint"
---

# Strategy-Backtest-Context-, Gebühren- und Publikationsintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die sechzehnte Read-only-
Kontrollrunde auf Repository-Head `ab6615ee`. Er ergänzt, ersetzt aber nicht:

1. den
   [Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit](2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md),
2. den
   [Historische-Renditen-/Schema-/Driftintegritätsaudit](2026-08-28-historical-return-schema-and-drift-integrity-audit.md),
3. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
4. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
5. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
6. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
7. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
8. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
9. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
10. den
    [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
11. den
    [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
12. den
    [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
13. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
14. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
15. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
16. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die sechzehn vorgenannten Dokumente in dieser
Reihenfolge. Die bereits dokumentierten Fehler in Preis-/FX-Quellenauswahl,
historischen Renditeschlüsseln und Strategy-Snapshot-Provenienz bleiben
eigenständige Blocker. Dieser Audit untersucht zusätzlich, ob der eigentliche
Strategy-Backtest denselben verifizierten Entscheidungsstand, dieselben Kosten
und denselben Benchmark in JSON, Browser und PDF verwendet.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Vier weitere P1-Verträge sind offen:

- Der Backtest nimmt die erste aktuelle Target Allocation, ohne ihren modernen
  Allocation-Context, Input-Hash oder ihre RA-/Policy-/CMA-Anker zu prüfen. Ein
  vollständig von diesen Artefakten entkernter moderner Datensatz wird als
  erfolgreicher Backtest publiziert. Sharpe verwendet zugleich eine beliebige
  globale aktuelle CMA oder einen erfundenen Default von 80 bps.
- Im Daily-Modus werden `strategy_fee_bps` und `benchmark_fee_bps` vollständig
  ignoriert. JSON und PDF zeigen identische Nettoergebnisse mit und ohne
  Kosten; das PDF setzt die übermittelten Kosten zusätzlich auf null.
- Requestwerte besitzen keinen geschlossenen Fachvertrag. Tippfehler bei
  `resolution` werden still zu Annual, negative Benchmarkgewichte zu null,
  beliebige Summen normalisiert, malformed Sub-Asset-Einträge übersprungen und
  extreme Gebühren intern anders gekappt als extern ausgewiesen.
- Interaktives JSON und Kunden-PDF unterstützen verschiedene
  Benchmarkverträge. Die UI sendet den ausgewählten Sub-Asset-Benchmark an die
  PDF-Route, die ihn nicht annimmt; FastAPI ignoriert den unbekannten Parameter.
  Im Daily-Modus ignoriert bereits der Service den Sub-Asset-Benchmark. Ein
  Daily-PDF beschreibt anschließend trotzdem Annual Returns und jährliche
  Year-End-Methodik.

Damit ist ein Backtest weder ein reproduzierbarer Replay der freigegebenen
Strategie noch ein verlässlicher Kosten-/Benchmarkvergleich. Eine formal
erfolgreiche PDF kann einen anderen fachlichen Inhalt zeigen als das unmittelbar
zuvor sichtbare Modal.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `BACKTEST-CONTEXT-001` | P1 | offen | Jeder veröffentlichte Backtest verwendet exakt eine verifizierte moderne TA samt RA, Policy, Snapshot-CMA, Input-/Context-Hash, Jurisdiktion und unverändertem Modellcontext; Live-/Defaultwerte ersetzen keinen Snapshotanker |
| `BACKTEST-FEE-001` | P1 | offen | Annual und Daily wenden exakt dieselben strikt validierten Strategie-/Benchmarkkosten an; ausgewiesener, gerechneter und in Brutto/Netto-Pfaden gebundener Wert ist identisch |
| `BACKTEST-INPUT-001` | P1 | offen | Auflösung, Zeitraum, Gebühren, Top-Level- und Sub-Asset-Gewichte besitzen eine bool-sichere geschlossene Domain; unbekannte oder unmögliche Werte scheitern statt still gekappt, normalisiert oder übersprungen zu werden |
| `BACKTEST-PDF-PARITY-001` | P1 | offen | JSON, Browser und PDF konsumieren denselben typisierten Backtest-Context mit identischem Modus, Benchmark, Kosten, Dataset, Provenienz und Fingerprint; Renderer erfinden oder verlieren keine Methode |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| JSON-Route und freie Queryparameter | `5eyes-backend/routers/allocation.py:889-984` |
| Malformed Sub-Asset-Einträge werden übersprungen | `5eyes-backend/routers/allocation.py:889-913` |
| Backtest wählt Current-TA per `.first()` | `5eyes-backend/services/backtest_strategy.py:1121-1173` |
| Live-Wealth- und CHF-100.000-Fallback | `5eyes-backend/services/backtest_strategy.py:937-961`; `:1175-1185` |
| Beliebige Current-CMA beziehungsweise 80-bps-Default | `5eyes-backend/services/backtest_strategy.py:963-979`; `:1187` |
| Tippfehler bei Resolution werden Annual | `5eyes-backend/services/backtest_strategy.py:1144` |
| Negative/unsummierte Benchmarkgewichte werden normalisiert | `5eyes-backend/services/backtest_strategy.py:982-1005` |
| Daily-Builder besitzt keinen Fee-Parameter | `5eyes-backend/services/backtest_strategy.py:898-926` |
| Daily-Early-Return reicht Gebühren nicht durch | `5eyes-backend/services/backtest_strategy.py:1190-1228` |
| Annual-Pfad übernimmt rohe Fees, Math-Helper kappen separat | `5eyes-backend/services/backtest_strategy.py:233`; `:357`; `:1261-1323` |
| PDF-Builder/Route kennen keinen Sub-Asset-Benchmark | `5eyes-backend/routers/pdf_reports.py:1803-1865`; `:1874-1926` |
| PDF-Datenmodell verliert Resolution, Provenienz und Sub-Benchmark | `5eyes-backend/services/pdf/base.py:367-418` |
| PDF-Methodentext behauptet immer Annual Returns/Year-End | `5eyes-backend/services/pdf/documents/backtest.py:141-160` |
| UI erlaubt je Kostenfeld bis 500 Prozent | `5eyes-electron/frontend/5eyes_v2.html:4268-4328` |
| UI multipliziert Prozent in bps und sendet an JSON/PDF | `5eyes-electron/frontend/5eyes_v2.html:13641-13717`; `:13914-13947` |
| UI sendet Sub-Asset-Query auch an inkompatible PDF-Route | `5eyes-electron/frontend/5eyes_v2.html:13920-13931` |
| Korrekte moderne Allocation-Context-Prüfung existiert bereits | `5eyes-backend/services/portfolio_engine.py:4160-4365`; `:5386-6164` |

## `BACKTEST-CONTEXT-001` – Performance ohne Entscheidungscontext

### Aktueller Pfad

`run_strategy_backtest()` sucht eine nicht gelöschte Current-TA per
ungeordnetem `.first()`. Danach werden nur die fünf Top-Level-Gewichte gelesen.
Der Pfad prüft nicht:

- genau eine aktuelle Target Allocation;
- `context_artifacts_required == 1`;
- `sub_allocations_json`, `effective_constraints_json` und
  `allocation_context_hash`;
- `input_snapshot_hash` und Drift der Mandatsinputs;
- `based_on_assessment_id`, Policy- und Snapshot-CMA-ID;
- Tenant, Client, Jurisdiktion, Universum oder Engine-Version;
- dass die publizierten Gewichte dem verifizierten Context entsprechen.

Fehlt `advisory_wealth_at_generation_rappen`, wird aktuelles Live-Vermögen
verwendet. Fehlt auch dieses, rechnet der Backtest mit CHF 100.000. Der
Risk-free-Wert für Sharpe stammt nicht aus der Allocation-CMA, sondern aus der
ersten global aktuellen CMA; fehlt sie oder ihr Wert, werden 80 bps erfunden.

### Ausgeführte HTTP-Reproduktion

In einer gültigen Route-Fixture wurde eine Current-TA auf einen ausdrücklich
modernen Zustand gesetzt und anschließend vollständig entankert:

```text
context_artifacts_required            = 1
based_on_assessment_id                = NULL
capital_market_assumptions_id         = NULL
input_snapshot_hash                   = NULL
sub_allocations_json                  = NULL
effective_constraints_json            = NULL
allocation_context_hash               = NULL
RiskAssessment-Rows des Mandats       = 0
CapitalMarketAssumption-Rows          = 0
```

Ergebnis:

```text
GET /mandates/{id}/backtest/strategy  => HTTP 200
soll                                  => vorhanden
risk_free_bps                         => 80
```

Der kanonische Allocation-Rebuild würde denselben modernen Datensatz wegen
fehlender Artefakte und Anker fail-closed ablehnen. Der Backtest umgeht diesen
Vertrag vollständig.

### Risiko

- Eine stale oder beschädigte Allocation wird weiterhin als historische
  Strategieperformance ausgegeben.
- Sharpe, Startvermögen und Methode können aus drei verschiedenen Zeitständen
  stammen: Allocationgewicht, Live-Vermögen und Live-/Default-CMA.
- Das PDF wirkt final und trägt Mandatsdaten, obwohl seine Modellbasis nicht
  beweisbar ist.
- Duplicate-Current-Altbestände werden abhängig von DB-Reihenfolge ausgewählt.

## `BACKTEST-FEE-001` – Daily verliert sämtliche Kosten

### Ursache

Der Annual-Pfad berechnet Gebühren erst nach dem Daily-Early-Return. Der
Daily-Builder besitzt keinen Fee-Parameter und baut weder `fee_bps_per_year`
noch einen `gross`-Block. Deshalb werden beide vom Request akzeptierten
Gebührenwerte im Daily-Modus nie angewendet und nicht in das Resultat
aufgenommen.

Der PDF-Mapper liest die fehlenden Top-Level-Felder anschließend mit `or 0`.
Damit verschwindet im Kunden-PDF sogar die Tatsache, dass Kosten angefordert
worden waren.

### Ausgeführte HTTP- und PDF-Reproduktion

Auf vollständigen täglichen Preisdaten wurden zwei identische Backtests
ausgeführt:

```text
A: resolution=daily, strategy_fee_bps=0,    benchmark_fee_bps=0
B: resolution=daily, strategy_fee_bps=1000, benchmark_fee_bps=500
benchmark_equities_bps=10000
```

Beide Responses waren HTTP 200 mit `resolution_used=daily`. Die vollständigen
`soll`- und `benchmark`-Pfade waren jeweils identisch; die Top-Level-Fee-Felder
fehlten in beiden Responses.

Der direkte PDF-Builder für Fall B ergab:

```text
BacktestData.strategy_fee_bps            = 0
BacktestData.benchmark_fee_bps           = 0
soll_gross_wealth_path_rappen            = leer
benchmark_gross_wealth_path_rappen       = leer
SOLL-Endwert mit/ohne angeforderte Fees  = identisch
Benchmark-Endwert mit/ohne Fees          = identisch
```

### Zusätzlich inkonsistente Annual-Kappung

Annual verarbeitet `strategy_fee_bps=999999` mit HTTP 200. Response und PDF-
Daten melden 999.999 bps beziehungsweise 9.999,99 Prozent. Der eigentliche
Compounding-Helper kappt intern jedoch auf 10.000 bps. Negative Fees werden
still zu null. Ausgewiesener und angewandter Kostensatz sind damit verschieden.

Die UI verschärft den Fehler: Jedes der drei Strategie-Kostenfelder und das
Benchmarkfeld erlaubt `max="500"` Prozent. Der Browser multipliziert jedes
Feld mit 100; eine formell zulässige Eingabe kann so 50.000 bps je Komponente
und 150.000 bps Gesamt-Strategiekosten senden.

### Risiko

- Daily kann eine kostenintensive Strategie als identisch zu einem
  gebührenfreien Index darstellen.
- Das PDF bestätigt Kosten von null, obwohl der Berater Kosten eingetragen
  hat.
- Annual kann einen anderen Wert anzeigen als mathematisch anwenden.
- Brutto/Netto-Aussagen und Suitability-/Kostenkommunikation sind nicht
  auditierbar.

## `BACKTEST-INPUT-001` – Requestwerte werden still umgedeutet

### Resolution und Zeitraum

Jeder Resolution-String außer exakt `daily` wird zu `annual`. Ein Request mit
`resolution=daliy` liefert daher HTTP 200 Annual statt 422. `start_year` und
`end_year` sind freie Integer ohne geschlossenen Bereich und ohne
`start_year <= end_year`-Vertrag. Ein leerer Zeitraum wird als erfolgreicher
Response mit Warnung statt als Requestfehler behandelt.

### Top-Level-Benchmark

Die fünf Gewichte sind freie optionale Integer. `_normalize_benchmark_weights`
setzt negative Werte auf null und skaliert jede positive Restsumme auf 10.000.
Ausgeführt wurde:

```text
benchmark_equities_bps=-5000
benchmark_bonds_bps=10000
```

Das Ergebnis war HTTP 200 und ein Benchmark von 0/10.000 bps. Weder Response
noch Warnung bewahrt, dass der übermittelte Vertrag fachlich unmöglich war.

### Sub-Asset-Benchmark

Der Router parst ein freies CSV-ähnliches Stringformat. Einträge ohne
Doppelpunkt, leere Keys und nichtnumerische Werte werden übersprungen. Der
Service kappt auch hier negative Gewichte und normalisiert den Rest. Damit kann
ein Tippfehler einen anderen zulässigen Benchmark erzeugen, ohne dass der
Benutzer davon erfährt.

### Fachliche Folge

Das ist keine harmlose Eingabehilfe. Gewicht, Gebühr, Modus und Zeitraum
bestimmen direkt die relative Performanceaussage. Still umgeschriebene
Vergleichsparameter dürfen nicht in einem Kunden-PDF als angeforderter
Benchmark erscheinen.

## `BACKTEST-PDF-PARITY-001` – Modal und PDF sind verschiedene Produkte

### Sub-Asset-Benchmark verschwindet

Die JSON-Route nimmt `benchmark_sub_assets` an und reicht es als
`benchmark_sub_weights_bps` an den Service. PDF-Route und `_build_backtest_data`
besitzen diesen Parameter nicht. Die aktive UI baut ihn trotzdem in den PDF-
Querystring ein. FastAPI ignoriert den unbekannten Queryparameter; der
ausgewählte Sub-Asset-Benchmark erscheint nicht im PDF.

Auch die JSON-Parität endet am Moduswechsel: Der Daily-Early-Return verarbeitet
nur `benchmark_weights_bps`. `benchmark_sub_weights_bps` wird erst im späteren
Annual-Block gelesen. Die UI erlaubt Daily plus Sub-Asset, der Service liefert
dann jedoch keinen Sub-Asset-Benchmark und keine Warnung.

Damit kann ein Berater im Modal beispielsweise einen SMI-/US-Submix sehen und
unmittelbar danach ein PDF ohne diesen Benchmark herunterladen, ohne sichtbare
Fehlermeldung.

### Daily-PDF beschreibt Annual

`BacktestData` trägt weder `resolution_used` noch Dataset-/Source-/As-of-/Hash-
Metadaten, Allocation-/CMA-Anker oder einen Benchmarkfingerprint. Der Renderer
behauptet fest:

- Quelle `asset_class_annual_returns`;
- historische Jahresrenditen;
- jährliches Rebalancing als Year-End-Snapshot.

Diese Beschreibung wird auch bei einem echten Daily-Resultat gerendert. Das
PDF kann deshalb tägliche Preis-/FX-Daten visualisieren und gleichzeitig eine
andere Datenquelle und Methodik attestieren.

### Weitere Paritätsverluste

- Daily-zu-Annual-Fallback ist im JSON über `resolution_used`/Warnung sichtbar,
  aber das PDF-Datenmodell trägt den verwendeten Modus nicht als
  revisionsfesten Methodikanker.
- Der Service kann einen `benchmark_sub_asset`-Block liefern; `BacktestData`
  besitzt dafür keine Felder.
- Risk-free-Basis, verwendete CMA, TA, Datenstand und Quellenauswahl fehlen im
  PDF-Auditblock.
- Die Route rendert nach jeder fachlich leeren/indicativen 200-Antwort weiter;
  ein verbindlicher finaler versus ausdrücklich indikativer Previewmodus ist
  nicht definiert.

## Verbindlicher Fixvertrag

### Ein Backtest-Context als einzige Wahrheit

1. JSON, PDF und Browser verwenden einen gemeinsamen typisierten
   `StrategyBacktestRequest`, `StrategyBacktestContext` und
   `StrategyBacktestResult`; keine zweite PDF-Parameter-/Mappinglogik.
2. Vor jeder kundenseitigen Berechnung exakt eine aktuelle, nicht gelöschte TA
   über den bestehenden exactly-one Resolver laden.
3. Moderne TA verlangt alle Contextartefakte, RA-, Policy- und Snapshot-CMA-
   Anker. Der kanonische `build_target_payload_from_allocation()`-Rebuild oder
   ein daraus extrahierter reiner Preflight prüft Input-/Context-Hash,
   Jurisdiktion, Tenant, Client und Modellbasis.
4. Die fünf Backtestgewichte stammen aus dem verifizierten Target-Payload.
   Persistierte Sub-Allokationen werden bei einem Sub-Asset-SOLL aus demselben
   Context verwendet; sie werden nicht aus Live-Produkten rekonstruiert.
5. Risk-free stammt aus der exakt verankerten Snapshot-CMA. Fehlt der fachlich
   benötigte Wert, endet der finale Backtest fail-closed; kein globaler Current-
   oder 80-bps-Ersatz.
6. Initialkapital und As-of werden aus dem Generation-Snapshot gebunden. Live-
   Vermögen oder CHF 100.000 sind nur in einem expliziten, sichtbar
   gewässerten Previewmodus zulässig und nie in einem finalen Kundendokument.
7. Backtest-Context enthält mindestens TA-/RA-/Policy-/CMA-ID,
   `allocation_context_hash`, `input_snapshot_hash`, Engine-/Schema-Version,
   Jurisdiktion, Dataset-ID/Hash/As-of, Auflösung, Periodengrenzen,
   Rebalancingregel, Fee-Vertrag, Benchmark und einen kanonischen
   `backtest_fingerprint`.

### Strikte Requestdomain

8. FastAPI verwendet ein typisiertes Pydantic-Querymodell mit
   `extra='forbid'`; unbekannte Parameter und Bool-zu-Integer scheitern.
9. `resolution` ist `Literal['annual', 'daily']`. Ein fachlich erlaubter
   Daily-zu-Annual-Fallback bleibt explizit als `requested_resolution` und
   `resolution_used` erhalten und ist im finalen PDF sichtbar; alternativ
   verlangt finaler Modus exakt die angeforderte Auflösung.
10. Jahresgrenzen sind exakte Integer in einem dokumentierten historischen
    Bereich; `start <= end`; keine Future-/Partial-Years nach dem Vertrag des
    Annual-Return-Audits.
11. Gebühren sind exakte, nichtnegative Integer-bps innerhalb eines
    fachlich festgelegten Produktmaximums. Negative, Float-, Bool-, String- und
    Overrange-Werte ergeben 422, keine Kappung. Das UI verwendet dieselbe
    Obergrenze in Prozent.
12. Top-Level-Benchmarkgewichte sind je 0..10.000 und summieren sich im
    finalen Request exakt auf 10.000. Falls ein interaktiver Normalisierungs-
    Komfort gewollt ist, geschieht er sichtbar vor dem Submit; der Server
    speichert angefordert und effektiv getrennt und finalisiert erst nach
    Bestätigung. Negative Werte werden nie zu null umgedeutet.
13. Sub-Asset-Benchmark ist eine strukturierte Liste/Map mit kanonischen,
    eindeutigen Keys, bool-sicheren BPS und exakter Summe. Unbekannte,
    doppelte, malformed oder für Dataset/Jurisdiktion nicht verfügbare Keys
    scheitern statt übersprungen zu werden.

### Einheitliche Fee- und Pfadberechnung

14. Ein gemeinsamer Fee-Helper wird in Annual, Daily, Top-Level, Sub-Asset,
    Rebalanced und No-Rebalance verwendet. Er liefert für jeden Pfad Netto und
    bei Fee > 0 den korrespondierenden Brutto-Pfad.
15. Daily wendet den dokumentierten Periodisierungsvertrag an, beispielsweise
    taggenau auf Basis kalendarischer Tage oder als klar definierter täglicher
    Faktor. Der angewandte Annual-bps-Wert und die Formel stehen im Resultat.
16. `reported_fee_bps == applied_fee_bps` ist eine harte Invariante. Kein
    Helper darf einen Wert kappen, während ein übergeordneter Payload den
    ungekürzten Wert publiziert.
17. Strategy und Benchmark verwenden dieselbe Periodisierung und denselben
    Perioden-/Rebalancingcutoff. Gebühren werden nicht doppelt oder nur auf
    einen der beiden Pfade angewandt.

### Publikations- und PDF-Parität

18. `_build_backtest_data` erhält ausschließlich den bereits verifizierten
    `StrategyBacktestResult`; es fragt keine eigene Live-Basis nach und
    verwirft keine fachlichen Felder.
19. JSON und PDF akzeptieren dieselben Top-Level-/Sub-Asset-Benchmarkparameter.
    Ein unbekannter PDF-Queryparameter ergibt 422 statt stiller Ignorierung.
20. `BacktestData` trägt `requested_resolution`, `resolution_used`, Fee-
    Vertrag, Benchmarktyp/-gewichte, Risk-free, TA-/CMA-IDs, Dataset-Hash/As-of,
    Fingerprint und Brutto-/Netto-Pfade.
21. Der PDF-Methodentext wird ausschließlich aus dem Resultat gebaut: Annual
    nennt Annual Returns; Daily nennt Preis-/FX-Serie, tatsächlichen
    Rebalancingcutoff und Daily-Fee-Formel. Fallbacks und indikative
    Annahmen stehen prominent auf jeder betroffenen Ergebnis-/Methodikseite.
22. Preflight-, Input-, Dataset- oder Contextfehler führen zu 409/422, bevor
    der Renderer aufgerufen wird. Unbekannte Server-/Renderfehler bleiben 500;
    kein partielles Erfolgs-PDF.
23. Preview und finaler Kundenmodus sind explizit getrennt. Nur Preview darf
    einen zulässigen indikativen Ersatz verwenden und ist auf jeder Seite als
    `ENTWURF/INDIKATIV` markiert.

## Verbindliche Testmatrix

### Context, Anker und Drift

- Kein/duplicate Current-TA, Legacy-TA, `context_artifacts_required=1` mit
  einem fehlenden Artefakt, Hashfehler, fehlende/noncurrent RA/Policy,
  fehlende/gelöschte/fremde CMA sowie Client-/Tenant-/Jurisdiktionsmismatch
  ergeben 409; Renderer und Pfadhelper werden nicht aufgerufen.
- Wealth-, Cashflow-, Goal- oder Preferences-Drift seit dem Input-Snapshot
  ergibt 409; weder aktuelle Livewerte noch aktuelle CMA ersetzen den
  Snapshot.
- Verankerte CMA mit `liquidity_return_bps=0` bleibt exakt null; fehlender Wert
  führt final fail-closed und niemals zu 80.
- Zwei Current-Altrows werden defense-in-depth als Konflikt erkannt; DB-
  Unique-Vertrag und Reader sind beide testabgedeckt.

### Gebühren und Mathematik

- Annual und Daily jeweils mit 0, 1, 100 und erlaubtem Maximalwert: Netto-
  Endwert, Returnserie und Metriken entsprechen der dokumentierten Formel.
- Daily mit 1000/500 bps unterscheidet sich beweisbar vom gebührenfreien
  Pfad; beide `gross`-Blöcke sind vorhanden und unverändert.
- Negativ, Bool, Float, Stringzahl und Max+1 ergeben 422. Kein Math-Helper-
  Clamp wird als gültiger Requestvertrag getestet.
- Top-Level und Sub-Asset sowie Rebalanced/No-Rebalance wenden denselben
  Fee-Wert genau einmal an.
- Response, PDF-Datenmodell und Methodikblock weisen exakt den angewandten
  Wert aus.

### Request- und Benchmarkdomain

- `resolution=daliy`, leerer/unknown Modus, start>end, Future- und
  Out-of-range-Year ergeben 422.
- Negative, >10.000, unsummierte, Bool- und unbekannte Top-Level-Gewichte
  ergeben 422; exakt 10.000 roundtrippt unverändert.
- Sub-Asset malformed CSV/JSON, Duplicate-Key, unbekannter Key, negative oder
  unsummierte BPS und fehlende Periodendaten ergeben einen expliziten
  Domainfehler. Nichts wird still übersprungen.
- Daily-zu-Annual-Fallback ist nur im definierten Modus zulässig und in JSON
  sowie PDF identisch sichtbar.

### JSON/PDF/UI-Parität

- Parametrisiert über Annual/Daily, Top-Level/Sub-Asset, Fee 0/>0 und
  Rebalancingvarianten: JSON und PDF-Daten besitzen denselben Fingerprint,
  Zeitraum, Modus, Benchmark, Fee, Endwert und Modellbasis.
- Daily plus Sub-Asset wird entweder fachlich vollständig unterstützt oder
  bereits im Request explizit abgelehnt; niemals still zu „kein Benchmark“.
- Ein im Modal ausgewählter Sub-Asset-Benchmark erscheint exakt im PDF; keine
  unbekannten Queryparameter werden ignoriert.
- Daily-PDF nennt ausschließlich die Daily-Quelle/-Methode; Annual-PDF
  ausschließlich die Annual-Quelle/-Methode.
- Preflightfehler aller Contextanker ergeben an JSON- und PDF-Route 409 und
  der Renderer-Spy bleibt ungerufen.
- Browser-E2E prüft UI-Maxima, bps-Konvertierung, angezeigte effektive
  Parameter, Fallbackhinweis und PDF-Query gegen den Serververtrag.
- PDF-Text-/Metadatenprüfung beweist TA-/CMA-/Dataset-IDs, Fingerprint,
  Resolution und Kosten; nicht nur erfolgreiche Byteerzeugung.

### Datenbank und Reproduzierbarkeit

- Derselbe Kontext, Dataset-Snapshot und Request erzeugen unabhängig von
  Insert-Reihenfolge, Worker und SQLite/PostgreSQL exakt denselben Fingerprint
  und Pfad.
- Parallel laufender Datenrefresh kann einen bereits gestarteten finalen
  Backtest nicht hybridisieren; entweder konsistenter Snapshot oder 409.
- Annual-/Daily-Dataset- und Source-Constraints aus den beiden vorigen
  Rendite-/FX-Audits sind Bestandteil des Backtest-Gates.

## Empfohlene Umsetzungsreihenfolge

1. Produktentscheidung treffen: Backtest nur als klar indikativer Preview oder
   zusätzlich als final publizierbares, entscheidungsgebundenes Dokument.
2. Gemeinsame Request-/Context-/Result-Modelle einführen und JSON/PDF auf einen
   Servicecall reduzieren.
3. Exactly-one-TA und kanonischen Allocation-Rebuild vor alle Pfadberechnungen
   setzen; Risk-free und Wealth ausschließlich aus verankertem Snapshot.
4. Strikte Query-/Benchmark-/Fee-Domain implementieren; stille Clamp-, Skip-
   und Typo-Fallbacks entfernen.
5. Daily-Fee-Mathematik samt Brutto/Netto implementieren und gegen Annual-
   Vertrag abgleichen.
6. Sub-Asset-Parameter und vollständige Provenienz in `BacktestData` und
   Renderer übernehmen; dynamischen Methodiktext bauen.
7. API-, PDF-, UI-, Context-, Raw-, Determinismus-, Parallel- und echte
   PostgreSQL-Tests ausführen.

## Definition of Done

Die vier Findings gelten erst als geschlossen, wenn gleichzeitig:

- jeder finale Backtest exakt eine moderne, vollständig verifizierte
  Allocation-/Risk-/Policy-/CMA-/Input-/Contextbasis besitzt;
- kein Live-/globaler/default Wert einen fehlenden Snapshotanker ersetzt;
- Annual und Daily dieselben Gebühren korrekt anwenden und vollständig als
  Brutto/Netto ausweisen;
- ausgewiesene und mathematisch angewandte Fees bitgenau identisch sind;
- Resolution, Zeitraum, Fees sowie Top-Level-/Sub-Asset-Benchmark eine strikte
  bool-sichere Domain besitzen und keine stillen Clamps/Skips stattfinden;
- JSON, Browser und PDF denselben Fingerprint, Benchmark, Modus, Datensatz,
  Kosten- und Methodikvertrag zeigen;
- Daily-PDF keine Annual-Methode behauptet und Sub-Asset-Auswahl nicht verliert;
- jeder Domain-/Context-/Datasetfehler vor Rendering 409/422 ergibt;
- API-, PDF-, UI-, Raw-, Race-, Determinismus-, Migrations- und echte
  PostgreSQL-Tests grün sind;
- der vollständige Backend-/Frontend-Gate auf dem Fixcommit erneut grün ist;
  und
- dieser Audit mit Fixcommit, Testzahlen und Restpunkten aktualisiert oder
  durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen am Strategy Backtest:

1. Diesen Audit und die direkt vorgelagerten Snapshot-, Annual-Return- und
   Marktpreis-/FX-Audits vollständig lesen.
2. Nicht nur den Fee-Parameter in den Daily-Helper einbauen: zuerst den
   gemeinsamen Context-/Request-/Result-Vertrag herstellen.
3. Bestehenden modern-allocation Rebuild und exactly-one Resolver
   wiederverwenden; keinen parallelen „leichteren“ Backtest-Preflight erfinden.
4. Risk-free nie aus global Current oder Hardcode ersetzen, wenn eine moderne
   Allocation explizit einen CMA-Snapshot verlangt.
5. Requestfehler nie durch Clamp, Normalisierung, Skip oder Modusfallback
   unsichtbar machen.
6. JSON und PDF nicht separat erweitern; beide müssen dasselbe unveränderliche
   Resultat konsumieren.
7. Sub-Asset-Benchmark, Resolution und Fees bis zum Renderer und Methodiktext
   durchreichen.
8. Previewannahmen sichtbar markieren; finale PDFs ohne vollständige
   Provenienz fail-closed blockieren.
9. Tests müssen negative Verträge und Renderer-nicht-aufgerufen prüfen, nicht
   nur Signaturen und erfolgreiche Bytes.
10. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline- und Audit-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Der fokussierte bestehende Backtest-/Fee-/PDF-/Sub-Asset-Ring auf dem
auditierten Head ergab:

```text
80 passed, 1 skipped, 34 warnings in 13.84s
```

Ausgeführt wurden:

```text
tests/test_backtest_strategy.py
tests/test_bug8a_backtest_fees.py
tests/test_bug8b_backtest_pdf_fees.py
tests/test_backtest_pdf.py
tests/test_sub_asset_backtest_engine.py
```

Der Skip ist ein bewusst manueller Network-Test. Die grünen Tests widerlegen
die Findings nicht. Sie prüfen Annual-Fee-Mathematik inklusive bewusstem
Clamp, PDF-Fee-Felder/-Signaturen, grundlegendes PDF-Rendering sowie den
Annual-Sub-Asset-Service. Sie enthalten weder Daily Fees, beschädigten modernen
Allocation-Context, strikte negative Queryverträge, JSON/PDF-Sub-Asset-Parität
noch einen auflösungsabhängigen PDF-Methodiktext.
