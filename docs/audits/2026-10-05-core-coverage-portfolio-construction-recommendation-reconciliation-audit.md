---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "core-coverage-portfolio-construction-recommendation-reconciliation-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "5eyes"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/core-coverage-portfolio-construction-reconciliation-audit"
audited_repository_head: "83af2a84fbc16cd2ef602bb3d4baa22c04325bc2"
reference_task: "CORE-COVERAGE-003 (asset-allocation-stochastic-core, 2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md, Abschnitt 3)"
audit_mode: "read_only_static_router_service_model_schema_test_review"
audit_mutated_product_code: false
audit_mutated_tests: false
scope: "RecommendationRun-Erzeugung aus TargetAllocation, Produktselektion, Aggregation, Gewichts-/Betragsreconciliation, RecommendationRun<->TargetAllocation-Bindung und Staleness, Bestandsinteraktion (Holdings), Consumer-Paritaet (API/PDF/Beratungsprotokoll/Handoff), Fail-closed-Verhalten"
release_decision: "blocked_confirmed_p1"
new_confirmed_p1: true
required_next_action: "ein zentrales, versioniertes RecommendationChainSnapshot einfuehren, das Zielgewicht, aggregiertes Produktgewicht, Coverage-Luecke/Cash-Rest, Holdings-Reconciliation und TargetAllocation-Bindung in EINEM Hash bindet; Generierungs-Warnungen persistieren statt sie nach der HTTP-Antwort zu verwerfen; die drei unabhaengig kodierten Staleness-Filter durch einen einzigen Resolver ersetzen"
---

# Portfolio-Construction-/Recommendation-Reconciliation-Audit

## Geltung und Abgrenzung

Dieser Audit beantwortet `CORE-COVERAGE-003` aus dem Reconciliation-Dokument
`2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md`
(Repository `asset-allocation-stochastic-core`, Abschnitt 3,
„Portfoliozusammensetzung und Produktempfehlung"). Jenes Dokument stellt fest,
dass Produktstammdaten, Suitability/Appropriateness, Anlagepräferenzen/ESG,
IST-Bestände, Kosten, Liquiditätsinstrumente, Alternative Anlagen und
Trade-/Execution-Handoff jeweils einzeln tief auditiert sind, aber ein
einziger beweisbarer Weg von der freigegebenen Target Allocation bis zur
finalen Empfehlung und Ausführungsanweisung fehlt.

Dieser Audit ist additiv und ersetzt insbesondere nicht:

1. den
   [Produkt-Suitability-/Angemessenheits-/Recommendation-Eligibility-Integritätsaudit](2026-09-04-product-suitability-appropriateness-and-recommendation-eligibility-integrity-audit.md)
   (`ELIG-*`, deckt Produktzulassung am Anfang der Kette ab),
2. den
   [Portfolio-Handoff-/Handelsinstruktions-/Ausführungsnachweis-Integritätsaudit](2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md)
   (`HANDOFF-*`, deckt das Ende der Kette ab),
3. den
   [Depot-/IST-Bestand-/Bewertungs-/SOLL-Publikations-Integritätsaudit](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md),
4. den
   [Ex-ante-Kosten-/Retrozessions-/Konfliktnachweis-Integritätsaudit](2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md),
5. den
   [Investment-Präferenz-/ESG-/Exclusion-Integritätsaudit](2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md).

Geprüft wurde ausschließlich der Code-Pfad **zwischen** diesen beiden Enden:
von einer geladenen `TargetAllocation` über Produktuniversum-Filterung,
Aggregation, Gewichts-/Betragsreconciliation und Holdings-Anbindung bis zum
persistierten `RecommendationRun`/`RecommendationPosition`, sowie die
Frage, ob alle Konsumenten (API, PDF, Beratungsprotokoll, Handoff) denselben
Datensatz lesen. Bei Widersprüchen gelten aktueller Code zuerst, danach dieser
Audit, danach die oben genannten Dokumente.

## Kurzfazit

**Nein, es existiert kein einziger beweisbarer, reconciliierender Weg von der
freigegebenen Target Allocation zur finalen Empfehlung.** Die Kette ist
technisch lückenlos ausführbar (jeder Schritt läuft ohne Exception durch),
aber an drei konkreten, im Code nachweisbaren Stellen entsteht ein stiller
Rest oder eine Divergenz, die kein nachgelagerter Konsument mehr sehen kann:

1. Bis zu 50 Basispunkte Zielgewicht können bei der Produktselektion ohne
   Produkt- oder Cash-Gegenbuchung verschwinden, und die Finalisierung
   toleriert zusätzlich eine Gewichtssumme zwischen 9900 und 10100 bps ohne
   eigene Warnung für die Lücke selbst. Die einzige Stelle, die diese Lücke
   überhaupt benennt (`warnings` aus `generate_recommendation_run`), ist ein
   Rückgabewert der HTTP-Antwort — kein Feld auf `RecommendationRun`. Nach dem
   ersten Response ist die Information nicht mehr rekonstruierbar.
2. `RecommendationPosition.current_amount_rappen` — die einzige Spalte, über
   die `depot_check.py` reale IST-Bestände lesen würde — wird von keinem
   produktiven Schreibpfad je gesetzt. Jede produktive Zeile hat dort `NULL`,
   wodurch der Depotcheck-Fallback unbedingt auf `target_amount_rappen`
   zurückfällt: IST wird tautologisch gleich SOLL. Parallel erzeugt dieselbe
   Generierung sehr wohl echte Holdings-Daten in einer separaten Tabelle
   (`RecommendationHolding`), die aber ausschließlich vom
   Live-Rebalancing/Handoff-Pfad gelesen wird — nicht vom Depotcheck.
3. Mindestens drei Code-Stellen implementieren unabhängig voneinander die
   Frage „passt dieser Run noch zur aktuellen TargetAllocation?" mit
   unterschiedlicher Semantik. Der client-facing-Pfad des Beratungsprotokolls
   (`advisory_report.py`) ist dabei **permissiver** als der operative
   PDF-Pfad (`pdf_reports.py`): Er akzeptiert einen Legacy-Run ohne
   `target_allocation_id`-Bindung als Treffer für JEDE aktuelle Allokation,
   während der PDF-Pfad densselben Run korrekt als nicht passend ablehnt. Ein
   zu `_strategy_drift_warnings()` (Allocation-vs-RiskAssessment/CMA-Drift)
   äquivalenter zentraler Resolver für „Recommendation vs. aktuelle
   TargetAllocation" existiert nicht; jeder Konsument hat seine eigene
   Teilwahrheit.

Keiner dieser drei Befunde erfordert eine Race Condition oder einen
Edge-Case-Exploit. Sie treten im dokumentierten, vom Code selbst
kommentierten Normalbetrieb auf.

## Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `RECOMM-RECON-001` | P1 | bestätigt | Zielgewichtssumme kann bis zu 150 bps (Generierung + Finalisierung kombiniert) ohne Produkt- oder Cash-Gegenbuchung und ohne persistierte Begründung von 10000 bps abweichen. |
| `RECOMM-WARN-001` | P1 | bestätigt | Generierungs-Warnungen (Coverage-Lücke, Suitability-Fallback, TER-Lücke) sind ein reiner HTTP-Response-Wert; `RecommendationRun` besitzt kein Feld dafür und keine spätere Abfrage kann sie rekonstruieren. |
| `RECOMM-HOLDINGS-001` | P1 | bestätigt | `RecommendationPosition.current_amount_rappen` wird von keinem produktiven Pfad geschrieben; der Depotcheck-Fallback macht IST faktisch identisch mit SOLL. Echte Holdings existieren parallel in `RecommendationHolding`, werden vom Depotcheck aber nie gelesen. |
| `RECOMM-STALE-001` | P1 | bestätigt | Drei unabhängig kodierte TargetAllocation-Staleness-Filter (review.py, advisory_report.py, pdf_reports.py) mit unterschiedlicher Semantik; kein zentraler Resolver äquivalent zu `_strategy_drift_warnings()`. |
| `RECOMM-BIND-001` | P2 | bestätigt | `RecommendationRun.target_allocation_id` ist eine reine `String`-Spalte ohne Foreign Key und ohne Content-Hash — anders als `policy_id` (FK) im selben Modell. Die Bindung lebt ausschließlich in Anwendungslogik, nicht im Schema. |

## Tatsächlicher Codepfad (TargetAllocation → persistierte Empfehlung)

```text
TargetAllocation (is_current=1, mandate-gebunden)
  |
  v
generate_recommendation_run()                       services/portfolio_engine.py:6760
  +-- TA-Anker-Validierung (is_current, Policy, CMA,  :6788-6846
  |   Assessment) -- fail-closed bei Mismatch
  +-- RecommendationRun INSERT                        :6890-6911
  |     target_allocation_id = allocation.id          :6895  (Column ohne FK, Modell :412)
  +-- previous_holdings_by_product                     :6868
  |     (echte Holdings je Produkt, fuer spaeteren
  |      RecommendationHolding-INSERT)
  +-- pro Sub-Allocation: Produktmatching              :6930-6973
  |     exact -> Fallback (asset_class) -> relaxed
  |     (ignore_suitability=True, siehe ELIG-FALLBACK-001)
  +-- fehlende Sub-Klasse <= 50 bps: STILL geskippt     :7014-7032
  |     (keine Produkt-/Cash-Zeile fuer die Luecke)
  +-- Aggregation gleicher Produkt-IDs                  :6997-7012
  +-- Konzentrationslimit-Validator                      :7034
  +-- RecommendationPosition INSERT je Produkt           :7046-7061
  |     current_amount_rappen WIRD NICHT GESETZT
  +-- RecommendationHolding INSERT (echte Units/MV)      :7063-7082
  |     NUR wenn previous_holdings_by_product Treffer hat
  +-- Live-Rebalancing-Payload (separater Pass)           :7153-7190
  |     enrichert positions_payload in-memory (current_*,
  |     rebalance_*) -- schreibt NICHT auf
  |     RecommendationPosition.current_amount_rappen zurueck
  v
return { run, positions, warnings, ... }                :7199-7215
  warnings = ephemere HTTP-Response, kein DB-Feld
```

```text
finalize_recommendation()                            routers/review.py:2669-2706
  +-- _validate_recommendation_for_finalization()        :165-263
  |     total_weight in [9900, 10100] bps -- Luecke selbst
  |     erzeugt KEINE Warnung, nur harter Fehlerfall ausserhalb
  |     der Bandbreite
  +-- warnings (NUR TER/Marktdaten, NICHT die
  |   Generierungs-Warnungen aus generate_recommendation_run)
  |   werden als Freitext in AuditLog.new_value gespeichert :2702
  +-- run.result_status = "Final"                          :2697
  +-- aeltere Final-Runs -> "Superseded"                    :2692-2696
```

## `RECOMM-RECON-001` — Zielgewicht kann ohne Gegenbuchung verschwinden

### Beobachtung

In `generate_recommendation_run()` wird pro Sub-Allocation ein Produkt
gesucht. Findet sich auch nach dem relaxed-Fallback (`ignore_suitability=True`)
kein Kandidat, wird die Sub-Klasse in `missing_sub_classes` gesammelt und die
Schleife läuft mit `continue` weiter — ohne dass irgendeine Position oder
Cash-/Reserve-Zeile das fehlende Gewicht übernimmt
(`services/portfolio_engine.py:6966-6973`):

```python
if not candidates:
    warnings.append(f"Kein passendes Produkt fuer {sub['sub_asset_class']} gefunden.")
    missing_sub_classes.append({...})
    continue
```

Erst danach wird geprüft, ob die **Summe** der fehlenden Gewichte 50 bps
überschreitet (`portfolio_engine.py:7014-7032`):

```python
if total_missing_bps > 50:
    ...
    raise ValueError(...)
```

Bleibt die Lücke bei oder unter 50 bps, läuft die Funktion ohne Fehler durch.
Es gibt an dieser Stelle keine Gegenbuchung: Weder wird das fehlende Gewicht
der Liquiditätsposition zugeschlagen, noch entsteht eine explizite
„ungedeckt"-Zeile. Die Summe der tatsächlich gespeicherten
`RecommendationPosition.target_weight_bps` kann daher bis zu 50 bps unter
10000 liegen, ohne dass ein Byte in der Datenbank diesen Zustand von einer
exakt reconciliierten Allokation unterscheidet — nur die ephemere
`warnings`-Liste (siehe `RECOMM-WARN-001`) nennt den Grund.

Die Finalisierung verschärft die Lücke nicht, sondern definiert ihre eigene,
unabhängige Tolerenz: `_validate_recommendation_for_finalization()` akzeptiert
jede Summe zwischen 9900 und 10100 bps (`routers/review.py:243-245`):

```python
total_weight = sum(int(position.target_weight_bps or 0) for position in positions)
if total_weight < 9900 or total_weight > 10100:
    errors.append(f"Positionsgewichte summieren auf {total_weight} bps statt ca. 10000 bps.")
```

Diese ±100-bps-Bandbreite ist **nicht** deckungsgleich mit der 50-bps-Grenze
aus der Generierung (sie ist doppelt so groß) und erzeugt — anders als der
Generierungs-Check — nicht einmal eine Warnung für den Fall, dass die Summe
z. B. bei 9950 liegt; sie wird einfach akzeptiert. Ein Final-Run kann also
0,5 % seines Zielvermögens ohne jede Produkt- oder Cash-Zuordnung und ohne
jede gespeicherte Erklärung tragen.

### Reproduzierbarer Kontrollfluss

1. Sub-Allocation „Private Equity" hat `target_weight_bps=40` und keinen
   zulässigen oder relaxed-Kandidaten im Produktuniversum des Mandats.
2. `missing_sub_classes` enthält genau diesen Eintrag;
   `total_missing_bps = 40 <= 50` → kein `ValueError`.
3. `aggregated_positions` enthält keine Zeile für diese 40 bps.
4. `_validate_recommendation_for_finalization()` sieht
   `total_weight = 9960` (wenn alle übrigen Sub-Allocations vollständig
   produktgedeckt sind) → `9960 >= 9900` → kein Fehler, keine Warnung.
5. `finalize_recommendation()` setzt `result_status="Final"`.
6. Kein PDF-, API- oder Handoff-Konsument kann aus den gespeicherten Daten
   rekonstruieren, dass 0,4 % des Zielvermögens nie einem Produkt zugeordnet
   wurden.

### Erforderliche Lösung / Auditvertrag

1. Jede fehlende Sub-Klasse erzeugt entweder eine explizite,
   gekennzeichnete Cash-/Reserve-Gegenbuchung oder blockiert die
   Finalisierung — niemals ein stiller Rest.
2. Generierungs- und Finalisierungs-Toleranz verwenden denselben, einmal
   definierten Grenzwert statt zwei unabhängiger Zahlen (50 bps vs. 100 bps).
3. Jede akzeptierte Lücke wird als strukturiertes, persistiertes Feld
   (`unallocated_weight_bps`, `unallocated_reason`) auf dem Run gespeichert,
   nicht nur als Text in einer HTTP-Antwort oder einem Audit-Freitext.
4. Ein Reconciliation-Test prüft explizit:
   `sum(position.target_weight_bps) + unallocated_weight_bps == 10000` für
   jeden Final-Run.

## `RECOMM-WARN-001` — Generierungs-Warnungen sind nicht persistiert

### Beobachtung

`generate_recommendation_run()` sammelt während der Produktselektion
Warnungen für: Coverage-Lücken, Fallback-Nutzung, Suitability-Override
(relaxed matching) und fehlende TER-Daten. Diese Liste wird ausschließlich im
Rückgabedikt der Funktion zurückgegeben (`portfolio_engine.py:7199-7215`):

```python
return {
    "run": run,
    "positions": positions_payload,
    "warnings": warnings,
    ...
}
```

Das `RecommendationRun`-Modell (`models/review.py:405-431`) besitzt keine
Spalte für diese Warnungen — weder `warnings_json` noch ein vergleichbares
Feld. `RecommendationRunResponse` (`schemas/review.py:1134-1148`) exponiert
ebenfalls kein solches Feld. Sobald der aufrufende Endpoint
(`routers/review.py:2563-2594`, `generate_recommendation_run_endpoint`) seine
HTTP-Antwort gesendet hat, existiert diese Information nirgendwo mehr in der
Datenbank.

Die Finalisierung berechnet eine **andere**, engere Warnmenge
(`_validate_recommendation_for_finalization`, nur TER/Marktdaten-Qualität,
`routers/review.py:253-262`) und schreibt diese als unstrukturierten Text in
`AuditLog.new_value` (`routers/review.py:2702`):

```python
new_value=("Final; Warnungen: " + " | ".join(warnings)) if warnings else "Final",
```

Das bedeutet konkret: Ein Run, der beim Generieren über den
Suitability-Relaxation-Fallback lief (bereits als `ELIG-FALLBACK-001`
dokumentiert) oder eine Coverage-Lücke nahe der 50-bps-Grenze hatte, trägt
diese Information **nicht** in sich. Weder Finalisierung noch PDF noch
Beratungsprotokoll noch Handoff können je wieder feststellen, dass diese
konkrete Empfehlung mit einer degradierten Produktabdeckung erzeugt wurde.

### Risiko

Ein Berater, der die ursprüngliche JSON-Antwort des Generate-Calls nicht
aufbewahrt (z. B. weil die UI sie nur kurz anzeigt), hat keinen Weg, später
zu rekonstruieren, warum eine bestimmte Position als „Fallback" oder
„Suitability-Override" gekennzeichnet war. Der Finalisierungs-Audit-Log-Text
suggeriert Vollständigkeit („Final; Warnungen: ..."), deckt aber nachweislich
nicht dieselbe Warnmenge ab.

### Erforderliche Lösung / Auditvertrag

1. `RecommendationRun` erhält ein strukturiertes, append-only
   `generation_warnings_json`-Feld, das exakt die beim Erzeugen berechneten
   Warnungen bindet (nicht die separat berechneten Finalisierungs-Warnungen).
2. PDF, Beratungsprotokoll, API und Handoff lesen und zeigen dieselbe
   persistierte Warnmenge, nicht eine Teilmenge oder einen Freitext-Rest im
   Audit-Log.
3. Ein Run mit nicht-leeren Fallback-/Override-Warnungen erhält ein
   sichtbares, maschinenlesbares Flag, das Finalisierung, Signatur und
   Handoff nach Policy blockieren oder zumindest kennzeichnen können.

## `RECOMM-HOLDINGS-001` — IST-Bestand ist für den Depotcheck tautologisch SOLL

### Beobachtung

`RecommendationPosition.current_amount_rappen` ist im Modell dokumentiert als
echter IST-Bestand des Kunden (`models/review.py:445-449`):

```python
# Sprint U-P20 (2026-05-24): Echte IST-Holdings des Kunden. NULL =
# noch nicht gepflegt (Berater hat Empfehlung erstellt, Kunde hat noch
# nichts gekauft). depot_check.py liest dieses Feld als IST-Amount
# statt auf target_amount zurueckzufallen (= echter IST/SOLL-Drift).
current_amount_rappen = Column(Integer)
```

Eine repositoryweite Suche nach schreibenden Zuweisungen
(`current_amount_rappen\s*=`) findet außerhalb von Tests ausschließlich die
Spaltendefinition selbst (`models/review.py:449`) und DDL/Migrationen
(`alembic/versions/c91f2c722881_baseline_schema.py`,
`migrations/2026-05-24-u-p20-current-amount-rappen.sql`). Es gibt **keinen**
produktiven Service- oder Router-Pfad, der diese Spalte setzt:

- `generate_recommendation_run()` setzt beim `RecommendationPosition`-Insert
  (`portfolio_engine.py:7046-7060`) nur `target_weight_bps`,
  `target_amount_rappen` und Referenzpreisfelder — `current_amount_rappen`
  fehlt im Konstruktoraufruf vollständig.
- `RecommendationPositionCreate` und `RecommendationPositionResponse`
  (`schemas/review.py:1151-1169` ff.) enthalten das Feld nicht; es ist über
  die API nicht einmal lesbar oder schreibbar.
- Der Direct-Create-Endpoint (`routers/review.py:2723-2779`) übernimmt
  denselben Schema-Typ und kann die Spalte somit ebenfalls nicht befüllen.

`depot_check.py::_load_positions()` liest die Spalte und fällt bei
`<= 0` (also immer, weil NULL) auf den SOLL-Betrag zurück
(`services/depot_check.py:344-347`):

```python
current_amount = _safe_int(getattr(rec_pos, "current_amount_rappen", 0))
if current_amount <= 0:
    # Fallback auf target_amount wenn current_amount nicht gepflegt
    current_amount = _safe_int(getattr(rec_pos, "target_amount_rappen", 0))
```

Für jeden produktiv erzeugten `RecommendationRun` ist dieser Fallback nicht
der Ausnahme-, sondern der Normalfall. Der gesamte IST-SOLL-Vergleich, den
`compute_depot_check()` für Band-/Drift-/Ampel-Logik auf Basis von
`RecommendationPosition` berechnet, vergleicht in Wahrheit **SOLL mit SOLL**
— jede Drift ist auf diesem Pfad per Konstruktion null.

Gleichzeitig erzeugt dieselbe Generierung sehr wohl echte Bestandsdaten: für
jede Position, zu der `_latest_holdings_by_product_for_mandate()`
(`portfolio_engine.py:6868`) einen Treffer liefert, wird eine
`RecommendationHolding`-Zeile mit echten `units_milli`/`market_value_rappen`
angelegt (`portfolio_engine.py:7063-7082`). Eine repositoryweite Suche zeigt,
dass `services/depot_check.py` die Tabelle `RecommendationHolding` an keiner
Stelle abfragt — nur `services/portfolio_engine_live_rebalancing.py` und die
bereits separat auditierten Handoff-/PDF-Pfade lesen sie.

### Konsequenz: drei verschiedene „IST"-Werte für denselben Run

| Konsument | Quelle fuer „IST" | Tatsaechlicher Wert |
|---|---|---|
| `depot_check.py` (RecommendationPosition-Zweig) | `current_amount_rappen` | == `target_amount_rappen` (immer, da NULL) |
| Live-Rebalancing / Handoff | `RecommendationHolding` + Live-Preis | echter oder `implied_from_target` Wert (siehe `HANDOFF-VALUATION-001`) |
| `depot_check.py` (WealthPosition-Fallback, wenn keine RecommendationPosition existiert) | `WealthPosition` | unabhaengig von RecommendationRun gepflegt |

Diese drei Werte sind nicht dieselbe Zahl und werden nicht gegeneinander
reconciliiert. Welcher Wert ein Berater oder Kunde als „IST" sieht, hängt
allein davon ab, welcher Endpoint zufällig aufgerufen wird.

### Risiko

Ein Depotcheck, der über den `RecommendationPosition`-Zweig läuft, kann
niemals eine Abweichung zwischen Kundendepot und Zielallokation anzeigen,
unabhängig davon, was der Kunde tatsächlich hält — die Berechnung ist
strukturell tautologisch. Gleichzeitig kann derselbe Mandant über den
Handoff-Pfad eine völlig andere, teils fiktive (`implied_from_target`)
IST-Basis sehen. Der Name „Depotcheck" suggeriert eine Prüfung des
tatsächlichen Bestands; der Code liefert sie auf diesem Pfad nicht.

### Erforderliche Lösung / Auditvertrag

1. `current_amount_rappen` entweder aus `RecommendationHolding` (oder einer
   gemeinsamen Holdings-Valuation-Quelle) befüllen, bevor es gelesen wird,
   oder die Spalte und den Fallback-Pfad als das kennzeichnen, was sie sind:
   nicht-funktional.
2. `depot_check.py` und das Live-Rebalancing/Handoff lesen dieselbe
   Holdings-Quelle und denselben Bewertungszeitpunkt.
3. Ein Depotcheck ohne verifizierte reale Holdings-Daten zeigt explizit
   „keine IST-Daten verfügbar" statt eine SOLL-SOLL-Nullabweichung zu
   suggerieren.
4. Ein Regressionstest instanziert einen produktiven `generate_recommendation_run`-Lauf
   (nicht nur Testfixtures mit direkt gesetztem `current_amount_rappen`) und
   prüft, dass der resultierende Depotcheck eine von SOLL verschiedene
   IST-Zahl zeigt, sobald eine reale, abweichende Holding existiert.

## `RECOMM-STALE-001` — Drei unabhängige, inkonsistente TargetAllocation-Staleness-Filter

### Beobachtung

Für die Frage „referenziert dieser `RecommendationRun` noch die aktuelle
`TargetAllocation` des Mandats?" existiert kein zentraler Resolver,
vergleichbar mit `_strategy_drift_warnings()`
(`services/portfolio_engine.py:3096`), das Allocation-vs-RiskAssessment/CMA-Drift
zentral behandelt. Stattdessen implementieren mindestens drei Stellen die
Frage unabhängig:

**1. `routers/review.py::get_current_recommendation_payload`**
(`routers/review.py:2611-2620`):

```python
runs_for_current_allocation = [
    item for item in runs
    if str(item.target_allocation_id or "") == str(current_allocation.id or "")
    and item.result_status != "Superseded"
]
```

Exakter String-Vergleich; ein Run mit `target_allocation_id=NULL` matcht
NIEMALS, weil `str(None or "") == ""` nie gleich einer echten Allocation-ID
ist. `Superseded` ist explizit ausgeschlossen.

**2. `services/advisory_report.py::_cached_latest_recommendation_run`**
(`services/advisory_report.py:62-92`), nur im `client_facing`-Modus (also
genau für das signierte, kundenseitige Beratungsprotokoll):

```python
query = query.filter(RecommendationRun.result_status == "Final")
current_ta = _cached_current_ta(db, mandate)
if current_ta is not None:
    query = query.filter(
        or_(
            RecommendationRun.target_allocation_id.is_(None),
            RecommendationRun.target_allocation_id == current_ta.id,
        )
    )
```

Dieser Pfad behandelt `target_allocation_id IS NULL` explizit als Treffer für
JEDE aktuelle Allokation — bewusst kommentiert als Rückwärtskompatibilität
für Legacy-Runs vor Einführung der Bindung (Zeilen 65-72). Das ist
**permissiver** als Filter 1 und 3: ein alter, nie an eine TargetAllocation
gebundener Final-Run erscheint hier als gültig für die aktuelle Allokation,
während derselbe Run in Filter 1 nie auftauchen würde.

**3. `routers/pdf_reports.py`** (Zeilen 1075-1107):

```python
matching_runs = (
    db.query(RecommendationRun)
    .filter(
        RecommendationRun.mandate_id == mandate.id,
        RecommendationRun.target_allocation_id == current_allocation_id,
    )
    .order_by(RecommendationRun.created_at.desc())
    .all()
)
last_run = (
    next((run for run in matching_runs if run.result_status == "Final"), None)
    or next((run for run in matching_runs if run.result_status == "Draft"), None)
)
```

Exakter Vergleich ohne NULL-Ausnahme, mit einer dritten, eigenen
Final-vor-Draft-Auswahllogik. Dieser Pfad würde den in Filter 2 akzeptierten
Legacy-Run korrekt mit 409/404 ablehnen.

Alle drei Implementierungen sind in ihrem jeweiligen lokalen Kontext
plausibel begründet und einzeln kommentiert — aber sie sind keine eine
Wahrheit. Der bereits separat dokumentierte `HANDOFF-CONTEXT-001` zeigt den
vierten, noch schwächeren Punkt dieses Spektrums: der Handoff-Endpoint prüft
überhaupt keinen Run-Status oder TargetAllocation-Bezug.

### Risiko

Dieselbe Mandatssituation (ein Final-Run ohne `target_allocation_id`,
erzeugt vor einer späteren TargetAllocation-Neuberechnung) kann je nach
aufgerufenem Endpoint als „gültig und aktuell" (Beratungsprotokoll,
client-facing) oder als „veraltet, blockiert" (operative PDF-Erzeugung)
erscheinen. Gerade der kundenseitig sichtbare, potenziell zu signierende
Beratungsprotokoll-Pfad ist dabei die **permissivste**, nicht die
konservativste Implementierung — das ist die falsche Richtung für ein
Dokument, das rechtlich als Kundeninformation gilt.

### Erforderliche Lösung / Auditvertrag

1. Ein einziger `resolve_recommendation_staleness(run, mandate)`-Service
   ersetzt alle lokalen Filter in `review.py`, `advisory_report.py` und
   `pdf_reports.py`.
2. Die Behandlung von Legacy-Runs ohne `target_allocation_id` ist eine
   bewusste, einmal getroffene und überall gleich angewandte Policy-
   Entscheidung — nicht eine Nebenwirkung eines lokalen `or_()`-Filters in
   genau einem Consumer.
3. Der client-facing/signierende Pfad ist niemals permissiver als der
   interne Beratungs-/PDF-Pfad; im Zweifel gilt die strengere Regel für
   Kundendokumente.
4. Ein gemeinsamer Test instanziert denselben Mandatszustand (Final-Run ohne
   TA-Bindung + neue aktuelle TargetAllocation) und erwartet von allen vier
   Konsumenten (review.py-Payload, Beratungsprotokoll, PDF, Handoff)
   dasselbe Verdict.

## `RECOMM-BIND-001` — Die Bindung an die TargetAllocation existiert nur in Anwendungslogik

### Beobachtung

Im selben Modell ist `policy_id` als echter Foreign Key deklariert, während
`target_allocation_id` eine reine `String`-Spalte ohne Fremdschlüssel und
ohne `nullable=False` ist (`models/review.py:409-414`):

```python
policy_id = Column(String, ForeignKey("optimizer_policies.id"), nullable=False)
capital_market_assumptions_id = Column(String)
...
target_allocation_id = Column(String)
```

Die Integrität der Bindung wird ausschließlich zur Erzeugungszeit
(`portfolio_engine.py:6788-6846`) und zur Finalisierungszeit
(`routers/review.py:179-222`) durch Anwendungscode hergestellt. Es gibt
weder einen Content-Hash der referenzierten Allocation (`input_snapshot_hash`
existiert auf `TargetAllocation`, wird aber nicht auf `RecommendationRun`
mitgeführt oder verglichen) noch eine DB-Invariante, die eine nachträgliche,
außerhalb der Anwendung erfolgte Änderung verhindert oder sichtbar macht.

### Risiko

Ein direkter SQL-Schreibzugriff, eine fehlerhafte Migration oder ein
zukünftiger Code-Pfad, der `target_allocation_id` ohne die in
`generate_recommendation_run`/`_validate_recommendation_for_finalization`
implementierten Prüfungen setzt, wird von der Datenbank nicht
zurückgewiesen. Dies ist dasselbe Strukturmuster, das die bereits bestätigten
Audits `ELIG-GOVERNANCE-001` und `HANDOFF-INTEGRITY-001` für Produktregeln
bzw. Handoff-Snapshots unabhängig dokumentiert haben — hier wiederholt es
sich für die zentrale Kettenbindung selbst.

### Erforderliche Lösung / Auditvertrag

1. `target_allocation_id` als Foreign Key auf `target_allocations.id`
   deklarieren (dialektgleich für SQLite und PostgreSQL).
2. Einen `target_allocation_content_hash` auf `RecommendationRun`
   mitführen und bei jedem Lesen gegen den aktuellen Hash der Allocation
   prüfen, nicht nur gegen `is_current`.
3. Negative Migrationstests (SQLite mit `foreign_keys=ON` und echtes
   PostgreSQL) gegen orphane oder manipulierte `target_allocation_id`.

## Verifikation dieser Runde

Dieser Audit ist ausschließlich statische Codeanalyse (Lesen und
repositoryweite Suche). Es wurde keine Laufzeitreproduktion mit einer
temporären Datenbank durchgeführt und kein bestehender Test ausgeführt. Die
Befunde stützen sich auf:

- direkte Lektüre der zitierten Funktionen mit Zeilennummern auf dem
  auditierten Head `83af2a84fbc16cd2ef602bb3d4baa22c04325bc2`;
- repositoryweite Negativsuche (`current_amount_rappen\s*=`,
  `RecommendationHolding`, `target_allocation_id=`) zur Bestätigung
  fehlender Schreib-/Lesepfade;
- Vergleich der drei genannten Staleness-Filter im Volltext.

| Suchziel | Ergebnis |
|---|---|
| `current_amount_rappen\s*=` außerhalb Tests/DDL | keine Treffer in Services/Routern |
| `RecommendationHolding` in `services/depot_check.py` | keine Treffer |
| `current_amount_rappen` in `schemas/review.py` | keine Treffer (Feld nicht in API-Schema) |
| `target_allocation_id` als Spaltendefinition | `Column(String)`, kein `ForeignKey` (Modell :412) |
| `warnings_json`/vergleichbares Feld auf `RecommendationRun` | keine Treffer |

### Selbst-Audit und Nachweisgrenzen

- Es wurde **kein** Test ausgeführt (`pytest` wurde in dieser Runde nicht
  aufgerufen); die Befunde sind reine Kontrollfluss-/Schemabelege, keine
  beobachteten Laufzeitwerte aus einer echten Datenbank.
- Kosten-/Steuer-/FX-Integration in die Gewichts-/Betragsreconciliation
  wurde bewusst nur als fehlende Verzahnung festgestellt (`fee_assumptions_json`
  wird auf dem Run gespeichert, aber nicht in `target_amount_rappen`
  verrechnet); die fachliche Korrektheit der separat auditierten
  Kostenberechnung selbst (`2026-09-02-ex-ante-cost-inducement-...`) wurde
  nicht erneut geprüft.
- Eine Mindeststückelungs-/Lot-Size-Rundung existiert im gesamten Backend an
  keiner Stelle (repositoryweite Suche nach `lot_size`, `min_lot`,
  `fractional_share`, `round_lot` ergab keinen Treffer); dies ist keine neue
  ID, sondern bestätigt, dass die unter `HANDOFF-INSTRUCTION-001` bereits
  dokumentierte Lücke (keine handelsfeste Stückzahl) bereits auf Ebene der
  Empfehlung beginnt, nicht erst beim Handoff.
- Die React-UI und die Classic-UI (`5eyes_v2.html`) wurden nicht auf eigene,
  möglicherweise zusätzlich divergierende Refetch-Pfade untersucht; dies
  bleibt eine offene Frage für einen gezielten Frontend-Parity-Audit.
- Ob ein Produkt zum Selektionszeitpunkt tatsächlich „eligible, verfügbar und
  bewertet" war (im Sinne von `CORE-COVERAGE-003`), ist bereits durch
  `ELIG-RULE-001`/`ELIG-DEFAULT-001`/`ELIG-FALLBACK-001` beantwortet und wurde
  hier nicht erneut geprüft; dieser Audit beschränkt sich auf das, was
  zwischen Selektion und persistierter Empfehlung mit dem Ergebnis dieser
  Selektion geschieht.
- Dieser Audit ist eine Bestandsaufnahme, keine fachliche, rechtliche oder
  produktive Freigabe. Produktcode, Tests und Konfiguration wurden nicht
  verändert.

## Schlussentscheidung

`CORE-COVERAGE-003` ist nicht erfüllt. Die Kette von TargetAllocation bis
Empfehlung ist lauffähig, aber nicht reconciliierend: Gewicht kann ohne
Gegenbuchung verschwinden, die einzige Stelle, die das bemerkt, verwirft ihre
Erkenntnis nach der HTTP-Antwort, die einzige Spalte für echten IST-Bestand
ist strukturell tot, und vier Konsumenten (API-Payload, Beratungsprotokoll,
PDF, Handoff) beantworten „ist dieser Run noch aktuell?" mit vier
unterschiedlich strengen, unabhängig gewarteten Regeln. Vor realer Beratung
oder Ausführung ist ein zentrales `RecommendationChainSnapshot` mit
persistierten Reconciliation-, Holdings- und Staleness-Verdicts erforderlich,
das von allen genannten Konsumenten gelesen statt lokal rekonstruiert wird.
