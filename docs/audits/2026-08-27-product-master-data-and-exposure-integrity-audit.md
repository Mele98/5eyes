---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-product-master-data-and-exposure-integrity-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "25526170228fab30184721fbbde2fac111d7629e"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-reference-data-read-authorization-and-model-basis-audit.md"
prior_release_audit_commit: "25526170228fab30184721fbbde2fac111d7629e"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-product-master-data-and-exposure-integrity-audit.md"
audit_mode: "read_only_static_schema_service_and_consumer_review_isolated_http_persistence_reproduction_and_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "product exposure JSON, duration, ESG, liquidity and active-state domains from admin API through depot check, advisory reporting and product-universe selection"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 77
focused_adjacent_tests_failed: 0
required_next_action: "introduce one strict product-domain validator for API, import and raw rows, distinguish absent proxy data from invalid explicit data, and block customer analytics on corrupt product metadata"
---

# Produktstammdaten- und Exposure-Integritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die zwölfte Read-only-Kontrollrunde auf
Repository-Head `25526170`. Er ergänzt, ersetzt aber nicht:

1. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
2. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
3. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
4. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
5. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
6. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
7. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
8. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
9. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
10. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
11. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
12. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die zwölf vorgenannten Dokumente in dieser
Reihenfolge. „Fault tolerant“ bedeutet bei ausdrücklich gepflegten,
entscheidungsrelevanten Stammdaten nicht, ungültige Werte still durch andere
Annahmen zu ersetzen.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Ein weiterer P1-Domainvertrag ist offen:

- `ProductCreate` und `ProductUpdate` behandeln die drei Exposure-Maps als
  freie Strings und Duration, ESG, Liquidität sowie `is_active` als praktisch
  ungegrenzte Werte. Ein echter Admin-Request persistierte mit HTTP 200 unter
  anderem kaputtes JSON, `-5000/+15000` Exposure-bps, Duration und ESG
  `999999`, `liquidity_tier='teleport'` und `is_active=2`.
- Der nachgelagerte Parser unterscheidet „nicht gepflegt“ nicht von „explizit
  kaputt“. Malformed Country-JSON wurde still durch den Aktien-Global-Proxy
  ersetzt; ein explizit leeres Currency-Objekt wurde zu 100 % CHF. Negative
  Sector-Werte blieben dagegen erhalten und wurden als `-5000/15000` bps
  aggregiert. `is_active=2` ließ das Produkt anschließend still aus dem aktiven
  Universum verschwinden.

Damit können Depotcheck, Advisory-Sektorbild, Concentration-HHI, IST-/SOLL-
Drift, Duration, ESG und Liquiditätsprofil auf erfundenen oder unmöglichen
Produktdaten beruhen. `AUTH-TEN-05` und `REC-001` dokumentieren bereits die
separate Tenant-/Produktresolver-Lücke; sie wird hier nicht erneut gezählt.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `PROD-DOMAIN-001` | P1 | offen | Produktstammdaten besitzen einen zentralen strikten Post-State- und Runtimevertrag; fehlende Exposure-Daten dürfen versionierte Proxys verwenden, ausdrücklich vorhandene ungültige Daten müssen vor Persistenz beziehungsweise Kundenanalyse fail-closed scheitern |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| freie Produkt-Create-/Update-Felder | `5eyes-backend/schemas/review.py:329-383` |
| Produktmodell mit unbeschränkten Stammdatenfeldern | `5eyes-backend/models/review.py:203-275` |
| Admin-Update persistiert Payload ohne Domainprüfung | `5eyes-backend/routers/review.py:1459-1486` |
| Router dokumentiert ausdrücklich fehlende JSON-Validierung | `5eyes-backend/routers/review.py:1466-1470` |
| Parser verschluckt ungültige explizite Maps und nimmt Proxy | `5eyes-backend/services/product_exposures.py:171-215` |
| Exposure-Aggregation erhält negative Werte | `5eyes-backend/services/product_exposures.py:218-252` |
| Depotcheck konsumiert Maps und numerische Felder live | `5eyes-backend/services/depot_check.py:403-459`, `:532-591` |
| Advisory-Sektorbild konsumiert dieselbe fail-open Map | `5eyes-backend/services/advisory_report.py:487-541` |
| unbekannte Liquidität fällt auf heuristische Klassifikation | `5eyes-backend/services/depot_check.py:53-103` |
| aktive Produktliste verlangt exakt `is_active == 1` | `5eyes-backend/routers/review.py:238-249` |

## `PROD-DOMAIN-001` – Explizit kaputte Produktdaten werden ersetzt oder publiziert

### Ist-Zustand

Die drei Felder

- `country_exposure_json`,
- `sector_exposure_json`,
- `currency_exposure_json`

sind in Create und Update lediglich `Optional[str]`. Es gibt keine Prüfung auf
JSON-Objekt, Keydomain, exakte Integer, Bool-Ausschluss, Nichtnegativität,
Einzelgrenzen oder Summe 10.000 bps. Ebenso fehlen belastbare Domains für
`duration_years_x10`, `esg_score_x10`, `liquidity_tier`, `credit_rating`,
`currency` und Update-`is_active`.

Der Parser `_parse_or_proxy()` fängt nahezu jeden Konvertierungsfehler und
behandelt ihn wie fehlende Daten. Das ist für `NULL` als ausdrücklich
ungepflegten Legacyzustand sinnvoll, aber für vorhandenes kaputtes JSON eine
andere Semantik. Ein leeres Dict gilt zunächst als explizit geparst, wird im
Currency-Pfad danach dennoch durch die Produktwährung ersetzt.

Bei syntaktisch gültigen Maps werden Werte nur mit `int(v)` konvertiert.
Negative Werte, Werte über 10.000, Bool, Floats, unbekannte Keys und falsche
Summen bleiben möglich. `aggregate_exposures()` verwendet zwar positive Werte
für seinen Nenner, schreibt beim Beitrag aber den ursprünglichen negativen Wert
fort. Das erzeugt negative und über 100 % liegende Portfolioanteile.

### Ausgeführte HTTP-/Service-Reproduktion

Ein echter FastAPI-Request eines berechtigten Firm-A-Admins setzte:

```json
{
  "country_exposure_json": "{broken",
  "sector_exposure_json": "{\"US Tech\":-5000,\"Health\":15000}",
  "currency_exposure_json": "{}",
  "duration_years_x10": 999999,
  "esg_score_x10": 999999,
  "liquidity_tier": "teleport",
  "is_active": 2
}
```

Der Endpoint `PUT /products/product-a` antwortete HTTP 200 und alle Werte lagen
anschließend unverändert in der Datenbank. Die produktiven Helper ergaben:

```text
country_after_malformed_explicit_input =
  {'US': 6500, 'CH': 300, 'GB': 400, 'JP': 600, ...}

aggregated_sector_bps =
  {'US Tech': -5000, 'Health': 15000}

currency_after_explicit_empty_object =
  {'CHF': 10000}

GET /products after is_active=2 = []
```

Der Country- und Currency-Output sieht plausibel aus, stammt aber nicht aus den
explizit gespeicherten Daten. Der Sector-Output ist mathematisch unmöglich. Das
macht den Fehler schwerer erkennbar als einen sichtbaren Domainkonflikt.

### Risiko

- Kunden- und Beraterberichte können negative beziehungsweise über 100 %
  liegende Länder-/Sektor-/Währungsanteile publizieren.
- Malformed Stammdaten werden als scheinbar valide Proxyannahme ausgegeben;
  Quelle und Datenqualitätsstatus bleiben unsichtbar.
- HHI, Driftwarnungen, Suitability-/Diversifikationsbegründung und
  Liquiditätsprofil können einen anderen Sachverhalt darstellen als gepflegt.
- Unbeschränkte Duration und ESG-Werte verfälschen gewichtete
  Fondscharakteristika.
- `is_active=2` ist weder aktiv noch kanonisch inaktiv: Ein erfolgreicher
  Update-Request lässt ein Produkt still aus Universum und Folgeanalysen
  verschwinden.
- Weil Recommendation-/Reportpfade Produktstammdaten teilweise live lesen,
  kann derselbe Fehler auch bereits finalisierte Entscheidungsstände verändern;
  der separate Publikationssnapshot-Vertrag aus den Vor-Audits bleibt daher
  zusätzlich erforderlich.

## Verbindlicher Fixvertrag

### Eine zentrale Produktdomain

1. Create, merged Update, JSON-/CSV-Import und Runtime-Raw-Row-Prüfung verwenden
   denselben Produktdomainvalidator. Kein Router und kein Report besitzt eine
   schwächere lokale Variante.
2. Exposure-Felder werden intern als typisierte Maps behandelt. Jeder Key ist
   nichtleer und dimensionsgerecht; jeder Wert ist ein exakter Integer, kein
   Bool, im Bereich `0..10000`; mindestens ein Wert ist positiv und die Summe
   ist exakt 10.000 bps beziehungsweise folgt einer explizit versionierten,
   dokumentierten Rundungstoleranz.
3. Länder- und Währungscodes verwenden eine gepflegte Domain einschließlich
   ausdrücklich erlaubter Sammelkeys wie `RoW` oder `Global`. Sektoren verwenden
   eine kanonische Taxonomie. Unbekannte Keys sind kein stiller Freitext.
4. `NULL` bedeutet „nicht gepflegt, versionierter Proxy zulässig“. Jeder
   nicht-NULL-Wert – auch `""`, `{}`, malformed JSON oder ein falscher Typ –
   bedeutet „explizit angegeben“ und muss bei Ungültigkeit 422 beziehungsweise
   einen Runtime-Domainkonflikt auslösen. Explizit kaputt wird nie als fehlend
   umgedeutet.
5. Proxyresultate tragen `source='proxy'`, Proxy-Version und Stichtag. Explizite
   Daten tragen `source='product_master'`. Kunden- und Auditpayloads machen die
   Quelle sichtbar.

### Weitere Stammdatenfelder

6. `is_active` ist strikt 0/1 beziehungsweise API-seitig strikt bool; Werte wie
   `2`, `-1`, Strings und Bool-als-Integer-Mehrdeutigkeit scheitern.
7. `duration_years_x10` und `esg_score_x10` besitzen fachliche Einheiten und
   plausible Bounds; `liquidity_tier` und `credit_rating` sind Enums;
   `currency` ist ein kanonischer zulässiger Code. Feldisolation je Produkttyp
   verhindert sinnlose Kombinationen.
8. Update validiert den vollständigen gemergten Post-State vor Mutation und
   Commit. Ein 422 lässt die bestehende Produktzeile bytegleich unverändert.
9. Additive DB-CHECKs sichern boolesche/rangefähige Spalten. JSON-Maps werden
   entweder normalisiert relational/versioniert persistiert oder über
   PostgreSQL-JSONB plus Constraints und denselben Servicevalidator geschützt.

### Consumer und Altbestand

10. Depotcheck, Advisory, Kosten-/Produktconsumer und Final-Publikation prüfen
    jede tatsächlich verwendete Raw-Produktzeile vor Berechnung. Ungültige
    explizite Daten führen bei Pflichtsektionen zu 409 und verhindern Renderer,
    Handoff und partiellen 200-Erfolg.
11. Altbestände werden vor Migration inventarisiert. Eine Bereinigung darf
    malformed Werte nicht automatisch durch Proxyannahmen überschreiben;
    fachliche Freigabe, Quelle und Audit-Evidence sind nötig.
12. Der bereits offene zentrale tenant-/jurisdiktionsfähige Produktresolver
    (`AUTH-TEN-05`, `REC-001`) bleibt Pflicht. Ein strikter Wertvalidator ersetzt
    keine Object-Scope-Prüfung.
13. Finalisierte Recommendation-/Publikationsstände binden einen versionierten
    Produkt-/Kosten-/Exposure-Snapshot. Spätere Stammdatenänderungen erzeugen
    Drift oder einen neuen Entscheidungsstand, keinen stillen Rewrite.

## Verbindliche Testmatrix

### API und Import

- Parametrisch je Exposure-Dimension: malformed JSON, Liste/Scalar/NULL-Key,
  leerer Dict, Blank-Key, Bool, Float, Stringzahl, negativer Wert, `10001`,
  falsche Summe und unbekannter Key führen zu 422.
- Gültige 10.000-bps-Maps für Länder, Sektoren und Währungen roundtrippen exakt.
- `duration_years_x10`, `esg_score_x10`, `liquidity_tier`, `credit_rating`,
  `currency` und `is_active` prüfen untere/obere Grenze sowie Bool/String.
- Partial Update wird gegen den vollständigen Post-State validiert; nach jedem
  Negativfall bleiben Datenbankzeile, Auditlog und Cache unverändert.
- JSON-Bulk- und CSV-Import haben dieselbe Domain. Partial Success darf nur
  fachlich unabhängige valide Zeilen committen und berichtet jede ungültige
  Zeile deterministisch.

### Runtime und Publikation

- Raw/Legacy malformed, negative, over-100 %, falsche Summe und `is_active=2`
  scheitern im Depotcheck und Advisory vor Berechnung/Renderer.
- Nur `NULL` aktiviert Proxy; `{}`, `""` und malformed JSON niemals.
- Proxy-Payload enthält Quelle/Version, expliziter Payload die
  Produktstammdatenquelle.
- Kein Exposure-Output enthält negative Werte, Werte über 10.000 oder eine
  Summe ungleich 10.000.
- Duration, ESG, Liquidität, HHI und IST-/SOLL-Drift verwenden nur validierte
  Inputs.
- Produktänderung nach Finalisierung verändert den gebundenen
  Publikationssnapshot nicht und erzeugt sichtbare Drift.

### Tenant und Datenbank

- Die bestehenden `AUTH-TEN-05`-/`REC-001`-Negativtests bleiben Teil des Rings:
  Firma A kann Firm-B-Produkte weder lesen, ändern, mappen noch referenzieren.
- SQLite- und PostgreSQL-Domain-/CHECK-Verhalten ist identisch.
- Migration inventarisiert und blockiert ungültige Altzeilen, statt sie
  willkürlich zu normalisieren.

## Empfohlene Umsetzungsreihenfolge

1. Typisierte Product-Domain und Proxy-vs-explicit-Semantik festlegen.
2. Validator in Create, merged Update und beide Importpfade integrieren.
3. Runtime-Gate vor Depotcheck, Advisory und finaler Publikation ergänzen.
4. Produkt-/Exposure-Snapshot und Quellmetadaten versionieren; Altbestand
   inventarisieren und kontrolliert migrieren.
5. DB-Constraints/JSONB beziehungsweise normalisierte Exposuretabellen additiv
   einführen.
6. API-, Import-, Raw-Daten-, Consumer-, Snapshot-, Tenant- und echte
   PostgreSQL-Migrationstests ausführen.

## Definition of Done

`PROD-DOMAIN-001` gilt erst als geschlossen, wenn gleichzeitig:

- alle Schreib- und Importpfade denselben vollständigen Post-State validieren;
- Exposure-Maps nur kanonische, nichtnegative 10.000-bps-Verteilungen enthalten;
- fehlend und explizit ungültig technisch und fachlich unterscheidbar sind;
- Proxys versioniert und als solche offengelegt werden;
- Duration, ESG, Liquidität, Rating, Currency und Active-State strikte Domains
  besitzen;
- Raw-/Legacyfehler jeden kundenwirksamen Consumer vor Berechnung blockieren;
- Final-/Publikationsstände einen unveränderlichen Produkt-/Exposure-Snapshot
  binden;
- API-, Import-, Runtime-, Report-, Snapshot-, Tenant- und echte PostgreSQL-
  Tests grün sind;
- der vollständige Backend- und Frontend-Gate auf dem Fixcommit erneut grün
  ist; und
- dieser Audit mit Fixcommit, Migration, Testzahlen und Restpunkten aktualisiert
  oder durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an Produkten, Exposures, Depotcheck, Advisory oder Produktimport:

1. Diesen Audit vollständig lesen.
2. `PROD-DOMAIN-001`, `AUTH-TEN-05`, `REC-001` und den
   Publikationssnapshot-Vertrag gemeinsam behandeln.
3. `NULL` nicht mit malformed, leerem String oder leerem Objekt gleichsetzen.
4. Keine explizit kaputten Produktdaten durch Proxywerte plausibilisieren.
5. Keine neue Exposure-Normalisierung im Router oder Report duplizieren.
6. Raw-/Legacyzeilen ebenso strikt wie API-Payloads prüfen.
7. Customer-facing Pflichtsektionen bei Domainfehlern fail-closed blockieren.
8. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline- und Audit-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Der fokussierte bestehende Produkt-/Depot-/Kostenring auf dem auditierten Head
ergab:

```text
77 passed, 1 warning in 51.06s
```

Diese grünen Positivtests widerlegen `PROD-DOMAIN-001` nicht. Sie enthalten
weder den ausgeführten malformed-/negative-/overrange-Post-State noch die
strikte Unterscheidung zwischen fehlendem und ungültigem Exposure oder den
Runtime-Block vor kundenwirksamer Berechnung.
