---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-depotcheck-end-to-end-product-identity-and-publication-integrity-audit"
status_as_of: "2026-10-05"
audit_started_on: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "eb5c9d6cc2a53c414af1c948dea01f9f408235b5"
prior_release_audit_path: "docs/audits/2026-10-05-cross-consumer-benchmark-governance-integrity-audit.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-publication-integrity-audit.md"
audit_mode: "read_only_static_service_orm_api_pdf_ui_review_cross_channel_reconciliation_and_focused_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
scope: "depotcheck product identity, holdings and allocation source binding, warning propagation, stress semantics, API UI PDF parity and publication eligibility"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
focused_backend_tests_passed: 134
focused_backend_tests_failed: 0
required_next_action: "separate target portfolio analysis from a true holdings-based depot check, bind every channel to one immutable complete snapshot, preserve all blocking warnings, and fail closed instead of falling back across incompatible data sources"
---

# Depotcheck-End-to-End-, Produktidentitaets- und Publikationsintegritaetsaudit

## Geltung und Abgrenzung

Dieser Audit schliesst `CORE-COVERAGE-002` aus dem
[Core-Readiness-Audit](2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md).
Er ersetzt nicht die bereits tiefen Einzelpruefungen, sondern reconciliert
deren Ergebnisse ueber den tatsaechlichen Nutzerfluss hinweg. Besonders
massgeblich bleiben:

1. der
   [Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Audit](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md),
2. der
   [Stress-Replay-/Policy-A/B-Audit](2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md),
3. der
   [Cross-Consumer-Benchmark-Governance-Audit](2026-10-05-cross-consumer-benchmark-governance-integrity-audit.md),
4. der
   [Ex-ante-Kosten-/Zuwendungs-/Konfliktnachweis-Audit](2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md),
5. sowie die Produkt-, Preis-, FX-, Suitability-, Preference- und
   Portfolio-Handoff-Audits.

Die alten Findings zu falschem IST-Fallback, ungebundenem Stresskatalog,
Kosten, Benchmark und Produktdaten werden hier nicht neu gezaehlt. Neu
untersucht wird, ob API, aktives HTML-Frontend und eigenstaendiges PDF
gemeinsam wirklich dasselbe Produkt "Depot-Check" bilden.

## Kurzurteil

**Der Depotcheck ist nicht release-ready und darf in der aktuellen Form nicht
als vollstaendige Pruefung des aktuellen Kundendepots publiziert werden.**

Der aktive Nutzerfluss verbindet zwei fachlich verschiedene Produkte unter
demselben Namen:

- API und Modal versprechen einen vollstaendigen IST-SOLL-Depotcheck mit
  Drift, aktuellen Exposures, Top-Positionen, Liquiditaet, Warnungen und
  Stress des aktuellen Depots.
- Das vom selben Modal angebotene PDF ist absichtlich eine reine
  SOLL-Analyse des empfohlenen Zielportfolios. Sein Test fordert sogar, dass
  `IST vs.` und Drift nicht enthalten sind.

Diese Differenz ist kein kleiner Darstellungsfehler. Die Kanaele loesen
RecommendationRun, TargetAllocation und Holdings unterschiedlich auf. Der
PDF-Pfad faengt sogar einen HTTP-409/404-Portfolio-Konflikt ab und ersetzt die
fehlende oder stale Empfehlung durch Strategie-Zielprodukte. Danach verwirft
er saemtliche Warnungen des zuvor berechneten Depotchecks und publiziert nur
Kosten-/Performance-Datenqualitaetswarnungen.

Auch der Stressabschnitt bricht die Produktidentitaet: Das Modal behauptet,
zu zeigen, was mit dem "aktuellen Depot" in der Krise passiert waere. Der
Service dokumentiert dagegen selbst, dass er ausschliesslich die aktuelle
TargetAllocation, also den SOLL-Mix, verwendet. Das PDF fuehrt dieselben
Legacy-Szenarien in der Zielportfolioanalyse auf, ohne Allocation-, Szenario-
oder Snapshotidentitaet auszugeben.

Die 134 fokussierten Bestandstests sind gruen. Sie bestaetigen die technische
Stabilitaet der implementierten Semantik, nicht deren fachliche Einheit. Ein
Test verlangt explizit ein target-only PDF; ein anderer verlangt, dass ein
degradierter Payload mit ausstehenden Daten weiterhin vollstaendig rendert.

## Findings-Register

| ID | Prio | Status | Releasewirkung |
|---|---:|---|---|
| `DEPOT-E2E-IDENTITY-001` | P1 | offen | UI/API und PDF verwenden denselben Produktnamen fuer IST-SOLL-Depotpruefung beziehungsweise reine SOLL-Zielportfolioanalyse; der PDF-Button verspricht Drift, die der Bericht absichtlich ausschliesst. |
| `DEPOT-E2E-SOURCE-001` | P1 | offen | API und PDF loesen Run, Holdings und TA unterschiedlich auf; der PDF-Pfad faengt Portfolio-HTTP-Konflikte ab und faellt auf Strategieprodukte zurueck. |
| `DEPOT-E2E-WARNING-001` | P1 | offen | Der PDF-Builder verwirft `compute_depot_check().warnings`; somit koennen Drift-, Konzentrations-, Liquiditaets-, Coverage- und fehlende-Vermoegen-Warnungen im PDF fehlen. |
| `DEPOT-E2E-STRESS-001` | P1 | offen | UI bezeichnet TargetAllocation-Stress als Replay des aktuellen Depots; keine Holdings-, Bewertungs-, Allocation- oder Szenarioversion bindet die Aussage. |
| `DEPOT-E2E-SNAPSHOT-001` | P1 | offen | Kein gemeinsames immutable DepotCheckAnalysisSnapshot bindet Holdings, Bewertung, TA, Empfehlung, Kosten, Benchmark, Stress, Warnungen und Publikation. |

Geerbte offene P1 bleiben bestehen, insbesondere `DEPOT-CONTEXT-001` bis
`DEPOT-PUBLICATION-001`, `STRESS-CONTEXT-001`, `STRESS-SCENARIO-001`,
`BENCH-*`, Kosten-/Produkt-/Preis-/FX- und Publication-Findings. Die fuenf
neuen IDs beschreiben deren Cross-Channel- und Produktgrenzen; sie ersetzen
keine der zugrunde liegenden Ursachen.

## Tatsächlicher End-to-End-Datenfluss

```text
HTML-Modal "Depot-Check & Diversifikation"
  |
  +-- GET /mandates/{id}/depot-check
  |     \-- latest RecommendationRun, beliebiger Status
  |           +-- RecommendationPosition.current_amount
  |           |     \-- <= 0: target_amount wird als IST verwendet
  |           +-- Product-Live-Daten
  |           \-- separate Current-TargetAllocation fuer SOLL/Baender
  |
  +-- GET /mandates/{id}/backtest/stress-replays
  |     \-- separate Current-TargetAllocation per .first()
  |           \-- unversionierter Hardcode-Szenariokatalog
  |                 (UI nennt das "aktuelles Depot")
  |
  \-- Button "PDF: Depot-Check mit Drift ..."
        \-- _build_depotcheck_data
              +-- berechnet Depotcheck erneut
              +-- berechnet Stress erneut
              +-- baut Strategie aus eigener Aufloesung
              +-- _build_portfolio_data
              |     \-- Current-TA-gebundener Final- oder Draft-Run
              |           \-- RecommendationHolding-Market-Values
              |                 (werden fuer das target-only PDF nicht gezeigt)
              +-- bei HTTP 404/409: strategy.products als Fallback
              +-- Top-Positionen/Exposures/Betrag aus SOLL
              +-- Depotcheck-Warnungen werden verworfen
              \-- PDF sagt korrekt: ausschliesslich Zielportfolio
```

Es gibt weder eine gemeinsame Read-Transaktion noch eine gemeinsame
`snapshot_id`, `as_of`, `holdings_hash`, `allocation_id`, `run_id`,
`benchmark_definition_id`, `stress_catalog_id`, `cost_snapshot_id` oder einen
Publication-Fingerprint.

## Codeanker auf dem auditierten Head

| Bereich | Anker | Beobachtung |
|---|---|---|
| API-Versprechen | `5eyes-backend/routers/allocation.py:592-615` | Nennt den Endpoint vollstaendigen Depot-Check mit IST-SOLL, Exposures, HHI, Top-Positionen, Liquiditaet und Warnungen. |
| API-IST-Quelle | `5eyes-backend/services/depot_check.py:243-308` | Neuester beliebiger Run; Current<=0 wird Target; fehlende Produkte verschwinden; Wealth-Fallback ist clientweit. |
| API-SOLL-Quelle | `5eyes-backend/services/depot_check.py:479-535` | Separat gelesene Current-TA und Zielbetraege desselben ungebundenen Run. |
| Modal-Produkt | `5eyes-electron/frontend/5eyes_v2.html:4097-4165` | Titel, IST-vs-SOLL-Drift und PDF-Tooltip versprechen einen gemeinsamen Depotcheck samt Drift. |
| Modal-Erfolg | `5eyes-electron/frontend/5eyes_v2.html:12993-13008` | Keine Warnung bedeutet visuell "Depot-Check ohne Auffaelligkeiten". |
| Modal-Waehrung | `5eyes-electron/frontend/5eyes_v2.html:12506-12509` | Positionsbetraege werden hart als CHF formatiert. |
| Modal-Stressaussage | `5eyes-electron/frontend/5eyes_v2.html:13129-13150` | Behauptet Replay der aktuellen Bucket-Gewichtung und des aktuellen Depots. |
| Stress-Wahrheit | `5eyes-backend/services/backtest_stress.py:135-170` | Verwendet ausdruecklich Current-TargetAllocation/SOLL, keine reale Position-History; Foundation-Hardcode. |
| PDF-Builder | `5eyes-backend/routers/pdf_reports.py:1513-1608` | Beschreibt target portfolio; mischt Depotcheck, Stress, Strategie, Portfolio, Kosten und Performance aus separaten Reads. |
| PDF-Fail-open | `5eyes-backend/routers/pdf_reports.py:1523-1530` | Jeder Portfolio-HTTP-Fehler fuehrt zu `strategy.products`. |
| PDF-Warnungsverlust | `5eyes-backend/routers/pdf_reports.py:1593-1601` | `warnings` enthaelt nur `_depotcheck_data_quality_warnings(costs, performance)`, nie `dc.warnings`. |
| Portfolio-Aufloesung | `5eyes-backend/routers/pdf_reports.py:1012-1149` | Current-TA-gebundener Final-oder-Draft-Run und RecommendationHolding; andere Wahrheit als Depotcheck-Service. |
| PDF-Datenmodell | `5eyes-backend/services/pdf/base.py:298-332` | Nennt sich reine SOLL-Analyse, traegt aber zugleich unpublizierte IST-Felder. |
| PDF-Produkt | `5eyes-backend/services/pdf/documents/depotcheck.py:1-49` | Target-only, Titel dennoch Depot-Check. |
| PDF-SOLL-Abschnitte | `5eyes-backend/services/pdf/documents/depotcheck.py:52-174` | Rendert Zielallokation, Ziel-Exposures, Zielrisiko und Zielpositionen; maximal sechs gefilterte Warnungen. |
| PDF-Methodik | `5eyes-backend/services/pdf/documents/depotcheck.py:205-233` | Erklaert erst am Ende, dass ausschliesslich das Zielportfolio analysiert wird. |
| Kodifizierte Semantik | `5eyes-backend/tests/pdf/test_depotcheck_soll_analysis.py:183-230` | Fordert target-only ohne IST-vs und erfolgreiches Rendering bei degradierten Daten. |

## `DEPOT-E2E-IDENTITY-001` – Ein Name, zwei inkompatible Produkte

### Beobachtung

Das Modal ist eindeutig als laufende Depotueberwachung positioniert. Es zeigt
"Asset-Klassen-Drift (IST vs SOLL)", aktuelle Exposures, Top-Positionen,
Liquiditaet und Warnungen. Der PDF-Button im selben Modal verspricht
"Depot-Check mit Drift, Diversifikation, Stress-Replays".

Das PDF ist dagegen bewusst eine Zielportfolioanalyse:

- Cover: "Depot-Check – Analyse des empfohlenen Zielportfolios";
- alle Allocation-, Sub-Allocation-, Exposure- und Top-Position-Abschnitte
  verwenden Sollwerte;
- die Methodik stellt erst auf der letzten Seite klar, dass Bank- oder
  Drittdepots ausserhalb des Dokuments abgeglichen werden;
- der Test verbietet `IST vs.` und Drift ausdruecklich.

Ein Nutzer darf deshalb aus dem UI-Kontext erwarten, dass der Download die
gerade betrachtete Pruefung dokumentiert. Tatsaechlich dokumentiert er einen
anderen Gegenstand. Der Disclaimer auf der letzten Seite heilt weder den
Button noch den Dokumenttitel, die fehlende IST-Evidence oder eine moegliche
Archivierung als angeblicher Depotcheck.

### Fixvertrag

Es muessen zwei explizit unterschiedliche Dokumenttypen existieren:

1. **Zielportfolioanalyse** – analysiert nur die freigegebene Empfehlung und
   nennt sich ueberall so; kein aktuelles Depot, keine Drift und keine
   Rebalancingaussage.
2. **Depotcheck** – setzt einen vollstaendigen, bewerteten Holdings-Snapshot
   voraus und zeigt nachvollziehbar IST, SOLL, Drift, Coverage und Massnahmen.

Ein Button darf nur den Snapshot exportieren, der im sichtbaren Modal liegt.
Endpoint, Dateiname, Dokumenttyp, Titel, UI-Text und Auditlog muessen dieselbe
Produktidentitaet tragen.

## `DEPOT-E2E-SOURCE-001` – Unterschiedliche Wahrheiten und PDF-Fail-open

### Beobachtung

Der JSON-Depotcheck verwendet den neuesten RecommendationRun unabhaengig von
Status und aktiver TargetAllocation. Er liest den alten Current-Skalar und
ersetzt nicht-positive Werte durch Target.

Der PDF-Portfoliohelper verwendet dagegen einen zur Current-TA passenden
Final- oder ersatzweise Draft-Run und aggregiert RecommendationHoldings. Das
waere zumindest eine andere, reichere Datenquelle. Der target-only Renderer
zeigt diese Current-Felder aber nicht.

Noch schwerer wiegt der Fehlerpfad: Wenn `_build_portfolio_data()` wegen
fehlender/staler Empfehlung oder fehlender TA HTTP 404/409 wirft, faengt der
Depotcheck-PDF-Builder die Domainentscheidung ab und verwendet
`strategy.products`. Aus einem Konflikt, der im Portfolio-PDF blockiert, wird
so im "Depot-Check" ein normaler Zielproduktbericht.

### Releasefolge

Ein stale, fehlendes oder nur als Draft vorhandenes Portfolio kann je nach
Kanal blockieren, als angebliches IST analysiert oder als reine Sollstruktur
publiziert werden. Keine der drei Varianten weist eine gemeinsame Run- oder
Allocation-ID aus. Ein spaeteres Replay ist nicht beweisbar.

### Fixvertrag

- Ein zentraler Resolver liefert genau einen typisierten Analysecontext oder
  einen blockierenden Domainfehler.
- `Final`-Publikation akzeptiert keine Draft- oder Strategy-Product-
  Ersatzquelle.
- Ein Conflict darf nur sichtbar als Conflict weitergegeben werden, nicht in
  ein semantisch anderes Produkt fallen.
- Alle Channels geben `holdings_snapshot_id`, `target_allocation_id`,
  `recommendation_run_id`, Status, As-of und Hash aus.

## `DEPOT-E2E-WARNING-001` – Warnungen verschwinden vor dem PDF

### Beobachtung

`compute_depot_check()` erzeugt Warnungen unter anderem fuer fehlendes
Beratungsvermoegen, Bandverletzungen, Laender-/Sektor-/Waehrungsdrift,
Konzentration und illiquide Anteile. `_build_depotcheck_data()` ruft diesen
Service auf, uebernimmt viele seiner Werte, setzt das PDF-Feld `warnings` aber
ausschliesslich aus Kosten- und Performance-Datenqualitaet zusammen.

Selbst diese gefilterte Liste rendert das PDF nur bis zum sechsten Eintrag.
Es existieren keine strukturierte Severity, kein Finding-Code, kein
blockierend/nicht-blockierend-Status und kein Nachweis, dass alle
publikationsrelevanten Warnungen sichtbar sind.

### Fixvertrag

- Ein Finding ist ein strukturiertes Objekt mit stabiler ID, Severity,
  betroffener Dimension, Evidence-State, Message und Publication-Impact.
- Der Snapshot besitzt eine vollstaendige, deterministisch sortierte
  Finding-Liste und einen Hash.
- API, UI und PDF duerfen textlich anders darstellen, aber keine Findings
  verlieren oder herabstufen.
- Blockierende Findings verhindern Final-PDF/Signatur/Handoff.
- Layoutbegrenzung darf hoechstens eine sichtbare Zusammenfassung plus
  vollstaendigen Anhang erzeugen, nie stilles Abschneiden.

## `DEPOT-E2E-STRESS-001` – SOLL-Stress wird als aktuelles Depot verkauft

### Beobachtung

Das Frontend erklaert: "Modell zeigt was passieren waere wenn das aktuelle
Depot zu Beginn der Krise gehalten wurde." Der Servicecode erklaert das
Gegenteil: Er verwendet die aktuelle TargetAllocation als Soll-Mix und keine
reale Positionshistorie.

Der [Stress-Replay-Audit](2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md)
hat die fehlende Contextbindung, die unversionierten Szenarien, die
Jahresendpunkt-Drawdowns und die statischen Recovery-Monate bereits
reproduziert. Der neue End-to-End-Befund ist die konkrete falsche
Produktbehauptung im Depotcheck und die erneute Liveberechnung fuer UI und
PDF.

### Fixvertrag

Jedes Resultat muss einen diskriminierten Scope besitzen:

- `current_holdings_snapshot`: produkt- und wertbasierter IST-Snapshot;
- `approved_target_allocation`: freigegebener SOLL-Snapshot;
- optional `recommended_post_trade_portfolio`: finaler Empfehlungs-Run.

UI/PDF nennen den Scope sichtbar. `StressEvaluation` bindet Scope-ID/hash,
Szenariokatalog-ID/hash, Bewertungsstichtag, Modellversion, Waehrung,
Cashflowannahmen und Resultathash. Kein Consumer darf aus einem SOLL-Resultat
einen IST-Satz erzeugen.

## `DEPOT-E2E-SNAPSHOT-001` – Kein publizierbares Gesamtartefakt

### Beobachtung

Der PDF-Builder fuehrt mehrere live gelesene Services nacheinander zusammen.
Jeder kann eine andere Current-TA, einen anderen Run, veraenderte Produktdaten
oder einen anderen Benchmark-/Kosten-/Preisstand sehen. Der resultierende
PDF-Audit-Hash beweist deshalb nicht, welche fachlichen Inputs gemeinsam
galten.

Das Problem ist auch ohne Concurrent Update vorhanden, weil die Resolver
bereits verschiedene Auswahlregeln besitzen. Unter READ COMMITTED kommt eine
zeitliche Mischsicht hinzu.

### Zielmodell

```text
DepotCheckAnalysisSnapshot
  identity
    snapshot_id, mandate_id, tenant_id, created_at, valuation_as_of
    status: draft | blocked | approved | published | superseded
    schema_version, engine_version, content_hash
  sources
    holdings_valuation_snapshot_id + hash
    target_allocation_id + context_hash
    recommendation_run_id + run_hash (optional je Produkttyp)
    product_reference_snapshot_id + hash
    cost_snapshot_id + hash
    benchmark_definition/evaluation ids + hashes
    stress_catalog/evaluation ids + hashes
  coverage
    position_count_expected/resolved/valued
    value_coverage_bps, exposure_coverage_bps
    price/fx freshness and missingness
  analysis
    totals, allocations, exposures, concentration, liquidity, risk
    current-vs-target drift and proposed actions
  findings
    complete typed list + aggregate release_eligibility
  publication
    document_type, locale, renderer_version, payload_hash
```

Der Snapshot wird in einer konsistenten Transaktion gebaut und danach
immutable konsumiert. Recompute erzeugt eine neue Version; ein bereits
publiziertes Dokument liest nie still aktuelle Livewerte nach.

## Verbindliche Umsetzungsreihenfolge fuer Claude

### Phase 0 – Rote Contract-Tests vor Refactor

1. Modal-PDF-Contract: Ein als Depotcheck exportierter Bericht enthaelt exakt
   den sichtbaren IST-/SOLL-Snapshot und seine Finding-IDs.
2. Product-identity-Test: Zielportfolioanalyse und Depotcheck besitzen
   unterschiedliche Typen, Endpoints, Titel und Dateinamen.
3. Stale-run-Test: Portfolio-HTTP-409 bleibt im Depotcheck blockierend;
   `strategy.products` wird nicht ersatzweise publiziert.
4. Warning-parity-Test: Jede strukturierte Depotcheck-Warnung erscheint in
   API, UI-Payload und PDF; kein Abschneiden blockierender Findings.
5. Stress-scope-Test: TargetAllocation-Resultat darf nirgends als aktuelles
   Depot bezeichnet werden.
6. Missing/zero/partial/negative holdings: niemals Target als IST; Coverage
   wird rot und Final-Publikation blockiert.
7. Cross-channel-fingerprint: API, UI-Export und PDF tragen denselben
   Snapshot- und Payloadhash.

### Phase 1 – Produktentscheidung explizit machen

- Bestehendes target-only PDF zu `Zielportfolioanalyse` umbenennen und aus
  dem IST-Modal entfernen oder den echten Depotcheck implementieren.
- Kein kosmetischer Disclaimer-Fix. Identitaet und Datenvertrag muessen vor
  Text-/Layoutarbeiten feststehen.

### Phase 2 – Eine Holdings- und Context-Wahrheit

- Den im Holdings-Audit geforderten mandatsgebundenen
  `HoldingsValuationSnapshot` umsetzen.
- Zentraler exactly-one Resolver fuer approved TA und finalen passenden Run.
- Produkt-, Preis-, FX-, Kosten- und Exposure-Referenzen einfrieren.
- Coverage explizit berechnen; Unknown bleibt Unknown und wird nie Null/SOLL.

### Phase 3 – Analyse-Snapshot und Finding-Registry

- `DepotCheckAnalysisSnapshot` aus den gebundenen Artefakten erzeugen.
- Drift, Exposures, Konzentration, Liquiditaet, Kosten, Benchmark und Stress
  ausschliesslich daraus ableiten.
- Strukturierte Finding-Registry mit zentralem Publication-Gate.

### Phase 4 – Consumer migrieren

- API, Modal, Advisory, Standalone-PDF, Signatur und Handoff lesen denselben
  Snapshot.
- Alte Current-Query-, Strategy-Product- und Target-as-Current-Fallbacks
  entfernen, nicht parallel bestehen lassen.
- Klare Scope-/As-of-/Coverage-/Version-/Hash-Ausgabe in UI und PDF.

### Phase 5 – Zertifizierung

- Golden Cases fuer komplettes IST, leeres Depot, echte Nullposition,
  Teilcoverage, stale Preis/FX, Multi-Currency, Corporate Action, Draft/Final,
  TA-Wechsel und gleichzeitige Updates.
- Metamorphic Tests fuer Position-Splitting, Waehrungsumrechnung,
  Reihenfolgeinvarianz und identische Snapshots.
- PostgreSQL-Transaktions-/Tenanttests sowie Render-/Text-/Hash-Paritaet.
- Unabhaengiger Re-Audit ohne offene P1 vor Freigabe.

## Akzeptanzkriterien

Der Depotcheck ist erst freigabefaehig, wenn alle Punkte gleichzeitig gelten:

- Der Produktname bezeichnet in jedem Kanal denselben fachlichen Scope.
- Kein Zielwert wird als aktueller Bestand verwendet.
- Holdings, Preise, FX und Exposures sind vollstaendig, as-of- und
  mandatsgebunden oder der Check ist sichtbar/blockierend unvollstaendig.
- TA und RecommendationRun sind exakt gebunden und publikationsberechtigt.
- Kosten, Benchmark und Stress tragen typisierte Definitionen und Hashes.
- Alle Findings sind vollstaendig und kanalgleich; P1 blockiert Final.
- API, sichtbares UI, PDF, Signatur und Handoff referenzieren denselben
  immutable Snapshot.
- Reproduzierbare Golden-/Negative-/Race-/Tenant-Tests sind gruen.
- Kein `except HTTPException` oder broad fallback wechselt still den
  fachlichen Gegenstand.

Bis dahin lautet die korrekte Produktbeschreibung:

> Es existieren eine nicht belastbar IST-basierte Depotcheck-Ansicht und eine
> separate Zielportfolioanalyse unter demselben Namen. Beide sind fuer
> kundenwirksame Depotpruefung nicht freigegeben.

## Ausgefuehrte Verifikation

```text
python -m pytest -q -p no:cacheprovider \
  --basetemp C:\\tmp\\ares_depot_e2e_20261005 \
  tests/test_depot_check.py \
  tests/test_depot_check_helpers.py \
  tests/test_depot_illiquid_classification.py \
  tests/pdf/test_depotcheck_soll_analysis.py \
  tests/test_asset_allocation_reference_integrity_edges.py \
  tests/test_advisory_report.py

134 passed in 125.48s
```

Die gruene Suite ist die Baseline fuer Claudes Refactor. Sie ist keine
Freigabe, weil die heute getestete target-only- und degraded-rendering-
Semantik selbst Teil des Produktidentitaetsproblems ist.
