---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-historical-return-schema-and-drift-integrity-followup-audit"
status_as_of: "2026-08-28"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "de65d3cca65a4883f6ab1d74f434adebd33273ea"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-market-price-and-fx-reference-integrity-audit.md"
prior_release_audit_commit: "de65d3cca65a4883f6ab1d74f434adebd33273ea"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-28-historical-return-schema-and-drift-integrity-audit.md"
audit_mode: "read_only_static_schema_router_service_review_real_startup_sqlite_and_isolated_http_determinism_reproduction_and_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "annual and sub-asset historical-return logical keys, SQLite/PostgreSQL schema parity, input chronology, strategy drift and backtest reproducibility"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 107
focused_adjacent_tests_skipped: 1
focused_adjacent_tests_failed: 0
required_next_action: "replace divergent annual-return keys with identical partial unique indexes, validate closed historical years strictly, and make drift/backtest consume complete versioned top-level or explicit sub-asset snapshots"
---

# Historische-Renditen-, Schema- und Driftintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die vierzehnte Read-only-
Kontrollrunde auf Repository-Head `de65d3cc`. Er ergänzt, ersetzt aber nicht:

1. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
2. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
3. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
4. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
5. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
6. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
7. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
8. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
9. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
10. den
    [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
11. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
12. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
13. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
14. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die vierzehn vorgenannten Dokumente in dieser
Reihenfolge. Ein SQLite-Positivtest auf ORM-`create_all()` beweist nicht den
echten Raw-Bootstrap-Vertrag; ein grüner PostgreSQL-DDL-Compile beweist keine
fachliche Eindeutigkeit ohne den logischen Key.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Drei weitere P1-Verträge sind offen:

- SQLite-Raw-Bootstrap, ORM-Metadata und Alembic definieren drei verschiedene
  Eindeutigkeitszustände für `asset_class_annual_returns`. Der echte SQLite-
  Startup verhindert Top-Level plus Sub-Asset desselben Jahres; Alembic und
  ORM erlauben dagegen beliebig viele gleiche Top-Level- und Sub-Asset-Keys.
- Der Strategy-Drift-Endpoint filtert Sub-Asset-Zeilen nicht aus und verlangt
  kein vollständiges Top-Level-Jahr. Fehlende Bucketrenditen werden implizit
  null; eine legitime Sub-Asset-Zeile kann die Top-Level-Aktienrendite abhängig
  von DB-Reihenfolge überschreiben.
- Der Admin-Write koerziert Bool/Floats via `int()` und akzeptiert beliebige
  Zukunftsjahre. Fünf echte HTTP-200-Requests speicherten `True` als `1` bps
  für 2099; die Backtest-Matrix behandelte 2099 als vollständig verfügbare
  Historie.

Damit sind historische Renditen und Drift weder dialektgleich noch
deterministisch, granularitätsrein oder zeitlich historisch belegt.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `RETURN-SCHEMA-001` | P1 | offen | Top-Level- und Sub-Asset-Renditen besitzen in SQLite, ORM und PostgreSQL denselben NULL-sicheren logischen Unique-Key; Duplikate werden vor Migration inventarisiert und von jedem Reader fail-closed erkannt |
| `DRIFT-BASIS-001` | P1 | offen | Strategy-Drift verwendet ausschließlich vollständige Top-Level-Jahre beziehungsweise einen ausdrücklich gebundenen Sub-Asset-Snapshot; fehlende Buckets und Granularitätsmischung werden nie zu Nullrenditen umgedeutet |
| `RETURN-TIME-001` | P1 | offen | Historische Renditewrites akzeptieren nur exakte Integer, kanonische abgeschlossene Jahre, klare Granularität und eine versionierte Quelle; Zukunftsjahre erscheinen niemals als historische Backtestdaten |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| ORM-Modell ohne Unique-/Domain-Constraint | `5eyes-backend/models/snapshots.py:38-51` |
| Raw-SQLite-Unique ignoriert `sub_asset_class` | `5eyes-backend/database.py:912-925` |
| Alembic-Baseline ohne Annual-Return-Unique | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:24-35` |
| Runtime fügt `sub_asset_class` additiv hinzu, repariert Index aber nicht | `5eyes-backend/database.py:363-375` |
| Sub-Asset-Helper erwartet logisch einen Dreierschlüssel | `5eyes-backend/services/market_data/sub_asset_backfill.py:111-153` |
| Top-Level-Loader überschreibt Duplicate-Keys im Dict | `5eyes-backend/services/backtest_strategy.py:72-106` |
| Sub-Asset-Loader überschreibt Duplicate-Keys ebenso | `5eyes-backend/services/backtest_strategy.py:111-148` |
| Admin-GET mischt Granularitäten; Admin-PUT sucht ohne `sub_asset_class` | `5eyes-backend/routers/system.py:343-359`; `:413-467` |
| Drift lädt alle Granularitäten und setzt fehlende Returns implizit null | `5eyes-backend/routers/snapshots.py:185-218`; `:246-262` |
| Backtest-Default verwendet den gesamten verfügbaren Jahresbereich | `5eyes-backend/services/backtest_strategy.py:279-290`; `:1224-1260` |
| Öffentlicher Backtest dokumentiert Default „max verfügbarer Bereich“ | `5eyes-backend/routers/allocation.py:916-986` |
| Backtest-PDF konsumiert denselben Live-Datensatz | `5eyes-backend/routers/pdf_reports.py:1810-1845` |

## `RETURN-SCHEMA-001` – Der logische Key widerspricht sich je Datenbankpfad

### Fachlicher Schlüssel

Top-Level und Sub-Asset teilen dieselbe Tabelle. Fachlich sind zwei getrennte
Keydomänen nötig:

```text
Top-Level: (year, asset_class) WHERE sub_asset_class IS NULL
Sub-Asset: (year, asset_class, sub_asset_class)
           WHERE sub_asset_class IS NOT NULL
```

Der Sub-Asset-Backfill dokumentiert diesen Vertrag selbst und filtert bei
seinem Upsert auf alle drei Werte.

### Drei tatsächlich verschiedene Schemazustände

1. **Echter SQLite-Startup:** Der Raw-Bootstrap erzeugt
   `UNIQUE(year, asset_class)`. `ensure_runtime_columns()` ergänzt später
   `sub_asset_class`, baut den zu breiten Index aber nicht um. Top-Level und
   irgendein Sub-Asset derselben Klasse/Jahr können nicht koexistieren;
   mehrere Sub-Assets ebenfalls nicht.
2. **ORM-Testdatenbank:** `Base.metadata.create_all()` erzeugt überhaupt keinen
   Unique-Key. Diese häufige Testfixture lässt Top-Level und Sub-Assets zwar
   zu, aber auch beliebige Duplikate.
3. **Alembic/PostgreSQL:** Die Baseline hat ebenfalls keinen Unique-Key. Ein
   produktiver PostgreSQL-Stand kann mehrere gleiche fachliche Rows halten.

### Ausgeführte echte SQLite-Startup-Reproduktion

Nach `init_db()` enthielt die Tabelle `sub_asset_class`, aber weiterhin:

```text
CREATE UNIQUE INDEX uq_acr_year_class
ON asset_class_annual_returns(year, asset_class)
```

Danach:

```text
Top-Level: 2026 / Aktien / sub_asset_class=NULL       => committed
_upsert_sub_asset_return(... Aktien_CH_Large ...)    => (True, 'created')
commit                                                 => IntegrityError
UNIQUE constraint failed:
  asset_class_annual_returns.year,
  asset_class_annual_returns.asset_class
```

Der Helper meldet vor dem Commit irreführend „created“, obwohl der reale
Desktop-/SQLite-Vertrag diesen Fachzustand verbietet.

### Ausgeführte Duplicate-/Reihenfolge-Reproduktion

Auf dem ORM-/Alembic-äquivalenten Schema wurden für 2025 zwei zulässige
Top-Level-`Aktien`-Zeilen mit `1000` und `10000` bps gespeichert. Nur ihre
Insert-Reihenfolge wurde vertauscht:

```text
source-a 1000, dann source-b 10000 => matrix equities=10000
source-b 10000, dann source-a 1000 => matrix equities=1000
```

`load_annual_returns_matrix()` erkennt die Ambiguität nicht; die zuletzt
iterierte Row überschreibt die erste. SQL garantiert für gleiche
Sortierschlüssel keine stabile Reihenfolge.

### Risiko

- Die produktiv gedachte Sub-Asset-Funktion scheitert auf einem echten
  SQLite-Startup, obwohl ihre ORM-Tests grün sind.
- PostgreSQL erlaubt inkonsistente Duplicate-Renditen, die Backtest und
  Reporting abhängig von Queryplan, Import oder Restore verändern.
- Der manuelle Top-Level-Upsert filtert nicht auf `sub_asset_class IS NULL`
  und kann bei koexistierenden Rows eine beliebige Sub-Asset-Zeile ändern.
- Der Admin-GET gruppiert nur nach Jahr und `asset_class`; Sub-Assets können
  die sichtbare Top-Level-Zelle überschreiben.

## `DRIFT-BASIS-001` – Drift mischt Granularitäten und erfindet Nullrenditen

### Ist-Zustand

Der Backtest-Top-Level-Loader filtert Sub-Assets aus und akzeptiert nur Jahre,
in denen alle fünf Buckets vorkommen. Der separate Drift-Endpoint tut beides
nicht:

- er lädt alle `AssetClassAnnualReturn`-Rows im Zeitraum;
- er gruppiert nur nach `year` und `asset_class`;
- Sub-Asset-Zeilen überschreiben damit Top-Level-Zeilen;
- für jeden fehlenden Asset-Bucket verwendet die Berechnung
  `year_returns.get(ac, 0)`;
- `has_drift_data` ist bereits bei einer einzigen Row wahr.

Das sind zwei Quellenverträge für dieselbe Tabelle und denselben fachlichen
Begriff „Strategiehistorie“.

### Ausgeführte Granularitäts-Reproduktion

Ausgangsallokation: fünf Buckets mit je 2000 bps. Für 2025 existierten eine
Top-Level-Aktienrendite von 0 sowie eine legitime
`Aktien_CH_Large`-Sub-Asset-Rendite von `10000` bps.

```text
insert Top-Level, dann Sub-Asset:
  drifted Aktien = 3333 bps
  strategy chart end = 120.0

insert Sub-Asset, dann Top-Level:
  drifted Aktien = 2000 bps
  strategy chart end = 100.0
```

Der logische Datensatz ist identisch; nur die DB-Reihenfolge ändert die
publizierte Drift.

### Ausgeführte Partial-Year-Reproduktion

Mit nur einer Aktienrendite von `10000` bps und ohne die übrigen vier Buckets:

```text
has_drift_data = True
drifted = {
  Aktien: 3333,
  Obligationen: 1667,
  Immobilien: 1667,
  Liquiditaet: 1667,
  Alternative: 1667
}
chart end = 120.0
```

Die vier fehlenden Renditen wurden nicht als Datenlücke gemeldet, sondern
mathematisch als exakt 0 % behandelt.

### Risiko

- Driftampel, theoretische Gewichte und Charts können auf einer anderen
  Granularität als die Sollstrategie beruhen.
- Unvollständiger Backfill sieht wie ein vollständiges Nullreturn-Szenario aus.
- Fehler bleiben plausibel: Summe und Chart sind mathematisch konsistent, nur
  die Datenbasis ist falsch.
- Ein späterer Sub-Asset-Import kann bestehende Top-Level-Drift rückwirkend
  verändern.

## `RETURN-TIME-001` – Zukunftsjahre werden als Historie akzeptiert

### Ist-Zustand

Der Admin-Endpoint erhält zwar einen FastAPI-Integer im URL-Pfad, verwendet für
`return_bps` aber ein freies Dict und `int(body['return_bps'])`. Dadurch werden
Bool, numerische Strings und Floats koerziert. Eine Return-Range existiert, aber
keine Year-Domain und kein Vertrag „abgeschlossenes historisches Kalenderjahr“.

`load_annual_returns_matrix()` übernimmt jedes vollständige Jahr. Wenn der
Caller keinen Bereich angibt, verwendet `_years_in_range()` alle Keys. Der
öffentliche Strategie-Backtest beschreibt dieses Verhalten als maximal
verfügbaren Bereich und das PDF nutzt denselben Service.

### Ausgeführte HTTP-Reproduktion

Für alle fünf Top-Level-Buckets wurde ausgeführt:

```text
PUT /admin/system/annual-returns/2099/{asset_class}
{"return_bps": true, "source": "future-audit"}
```

Alle fünf Requests antworteten HTTP 200 und speicherten `return_bps=1`.
Danach enthielt die produktive Matrix:

```text
2099 = {
  equities: 1,
  bonds: 1,
  real_estate: 1,
  alternatives: 1,
  liquidity: 1
}
```

Ohne explizite Querygrenze wird 2099 damit als historisches Backtestjahr
verwendet.

## Verbindlicher Fixvertrag

### Ein identischer logischer Key auf allen Dialekten

1. SQLite-Raw-Schema, ORM-Metadata und Alembic erhalten zwei identische
   Partial-Unique-Indizes:
   `(year, asset_class) WHERE sub_asset_class IS NULL` und
   `(year, asset_class, sub_asset_class) WHERE sub_asset_class IS NOT NULL`.
2. Die additive Migration inventarisiert vor DDL jeden Duplicate-Key und jeden
   Konflikt zwischen Top-Level/Sub-Asset. Sie wählt niemals anhand ID,
   Insert-Reihenfolge oder `first()` eine Gewinnerzeile.
3. Der alte SQLite-Index `uq_acr_year_class` wird definitionsgeprüft und
   idempotent ersetzt. Bestehende konfliktfreie Rows bleiben unverändert.
4. Create-/Upsertpfade verwenden denselben logischen Key. Top-Level-Admin-
   Update filtert explizit `sub_asset_class IS NULL`; Sub-Asset-Update verlangt
   einen kanonischen Sub-Key.
5. Jeder Reader erkennt Defense-in-depth gleichrangige Duplikate und endet mit
   Domainkonflikt statt Dict-Overwrite.

### Strikte Renditedomain und Zeit

6. Write-Schema ist typisiert: `return_bps` exakter Integer, kein Bool/String/
   Float, fachliche Range; `year` exakter Integer im erlaubten historischen
   Bereich; `asset_class`/`sub_asset_class` kanonisch und konsistent; Source
   nichtleer, versioniert und auditierbar.
7. Für „historisch“ sind nur abgeschlossene Kalenderjahre zulässig. Laufendes
   Jahr darf nur in einem expliziten provisional/as-of-Modus existieren und
   niemals still in Final-Backtest oder Kunden-PDF gelangen. Zukunftsjahre
   scheitern mit 422.
8. Der vollständige Batch beziehungsweise Post-State wird vor Mutation
   validiert. Teilfehler archivieren oder überschreiben keine valide Row.
9. Raw-/Legacywerte werden vor Verwendung auf Key, Typ, Range, Jahr,
   Granularität und Source geprüft.

### Drift, Backtest und Snapshot

10. Top-Level-Drift verwendet ausschließlich `sub_asset_class IS NULL` und nur
    Jahre mit exakt allen fünf kanonischen Buckets. Fehlend oder doppelt ist
    ein sichtbarer Datenqualitätskonflikt, niemals 0 %.
11. Sub-Asset-Analysen verwenden einen getrennten, expliziten Pfad und eine
    vollständige Required-Key-Menge. Top-Level und Sub-Asset werden nicht im
    selben untypisierten Dict zusammengeführt.
12. Backtest und Drift binden Dataset-Version, Source-Set, As-of, Granularität,
    vollständige Keyliste und Hash. Finalisierte Kundenpublikation liest den
    gebundenen Snapshot, nicht eine später veränderte Live-Tabelle.
13. Admin-GET liefert getrennte Top-Level-/Sub-Asset-Strukturen oder einen
    typisierten flachen Key; kein Sub-Asset überschreibt eine Top-Level-Zelle.

## Verbindliche Testmatrix

### Schema und Migration

- Frischer echter SQLite-Startup, ORM-`create_all` und Alembic-PostgreSQL-Head
  besitzen dieselben zwei Partial-Unique-Indizes.
- Top-Level plus mehrere verschiedene Sub-Assets desselben Jahres/Buckets sind
  erlaubt; Duplicate Top-Level und Duplicate derselben Sub-Asset-Zeile sind
  verboten.
- Upgrade repariert den alten SQLite-Zweierschlüssel idempotent; konfliktfreie
  Bestandsrows bleiben bytegleich.
- Duplicate-Altbestand lässt Migration und Runtime fail-closed enden; keine
  automatische Gewinnerauswahl.
- Echte PostgreSQL-Parallelwrites liefern genau eine fachliche Row und einen
  stabilen Conflict-/Retry-Vertrag.

### API und Domain

- Bool, Float, Stringzahl, null, overrange, unbekannte Asset-/Sub-Asset-Klasse,
  Blank-Source, laufendes und zukünftiges Jahr scheitern mit 422.
- Gültige abgeschlossene Top-Level- und Sub-Asset-Jahre roundtrippen exakt.
- Top-Level-PUT kann bei vorhandenen Sub-Assets nur die NULL-Row ändern;
  Sub-Asset-PUT nur den exakten Dreierschlüssel.
- Batchfehler hinterlässt Rows und Auditlog unverändert.

### Reader, Drift und Backtest

- Jede Permutation derselben Rows ergibt bitgenau dieselbe Matrix, Drift,
  Backtest und Hash.
- Duplicate-Key, fehlender Bucket und Granularitätsmischung scheitern vor
  Berechnung/Renderer; kein `.get(..., 0)` für fehlende Pflichtdaten.
- Legitimer Sub-Asset-Import verändert Top-Level-Drift nicht.
- Future-/laufende Jahresrow erscheint weder in Available Years noch in
  Kunden-PDF/-Portal; provisional Daten sind explizit markiert und getrennt.
- Änderung einer Live-Rendite nach Finalisierung verändert den gebundenen
  Kundenstand nicht, sondern erzeugt Dataset-Drift beziehungsweise einen neuen
  Snapshot.

## Empfohlene Umsetzungsreihenfolge

1. Fachlichen Top-Level-/Sub-Asset-Key und abgeschlossene-Year-Domain zentral
   definieren.
2. Altbestand auf zu breiten SQLite-Key und fehlende PostgreSQL-Eindeutigkeit
   inventarisieren.
3. Additive Alembic-Revision, ORM-Indizes und SQLite-Legacy-Reparatur gemeinsam
   einführen.
4. Admin-Create/Update/GET und beide Backfillhelper auf den zentralen Vertrag
   umstellen.
5. Drift- und Backtestloader strikt trennen, vervollständigen und mit einem
   Dataset-Snapshot binden.
6. API-, Permutations-, Raw-, Parallel-, SQLite-, echte PostgreSQL- und
   Publikationstests ausführen.

## Definition of Done

Die drei Findings gelten erst als geschlossen, wenn gleichzeitig:

- SQLite-Raw, ORM und Alembic denselben NULL-sicheren logischen Key erzwingen;
- Top-Level und mehrere Sub-Assets konfliktfrei koexistieren;
- gleichrangige Duplikate weder persistiert noch implizit ausgewählt werden;
- API und Runtime exakte Typ-, Range-, Year-, Granularitäts- und Source-Domains
  verwenden;
- Drift keine Sub-Assets oder Phantom-Nullrenditen in Top-Level-Daten mischt;
- Backtest und Kundenpublikation nur abgeschlossene, vollständige,
  gesnapshottete historische Datensätze verwenden;
- API-, Raw-, Permutations-, Parallel-, Migration- und echte PostgreSQL-Tests
  grün sind;
- der vollständige Backend-/Frontend-Gate auf dem Fixcommit erneut grün ist;
  und
- dieser Audit mit Fixcommit, Migration, Testzahlen und Restpunkten
  aktualisiert oder durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an Annual Returns, Sub-Assets, Strategy Drift oder Backtest:

1. Diesen Audit vollständig lesen.
2. `RETURN-SCHEMA-001`, `DRIFT-BASIS-001`, `RETURN-TIME-001` und den
   Marktdaten-Snapshotvertrag gemeinsam behandeln.
3. Niemals nur ORM-`create_all` testen; echten SQLite-Bootstrap und Alembic-
   PostgreSQL-Head vergleichen.
4. `NULL`-Top-Level und non-NULL-Sub-Asset als zwei explizite Keydomänen
   modellieren.
5. Keine fachliche Eindeutigkeit durch `.first()` oder Dict-Overwrite
   vortäuschen.
6. Fehlende Pflicht-Buckets nie zu 0 % umdeuten.
7. Zukunftsjahre nie als historische Available Years ausgeben.
8. Kundenwirksame Historie mit Granularität, Source, As-of und Hash binden.
9. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline- und Audit-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Der fokussierte bestehende Annual-/Sub-Asset-/Backtest-/Snapshotring auf dem
auditierten Head ergab:

```text
107 passed, 1 skipped, 156 warnings in 28.70s
```

Diese grünen Positivtests widerlegen die Findings nicht. Sie verwenden für
Sub-Assets überwiegend ORM-`create_all` statt des realen SQLite-Raw-Bootstraps
und enthalten weder den PostgreSQL-Duplicate-Key, die Drift-
Granularitätspermutation, das Partial-Year noch den HTTP-200-Zukunftsjahr.
