---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "core-coverage-002-depotcheck-end-to-end-integrity-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "5eyes"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/core-coverage-depotcheck-e2e-audit"
audited_repository_head: "83af2a84fbc16cd2ef602bb3d4baa22c04325bc2"
reconciled_reference_document: "asset-allocation-stochastic-core/docs/audits/2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md"
reconciled_reference_task: "CORE-COVERAGE-002"
prior_related_audit_path: "docs/audits/2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md"
prior_related_audit_scope: "services/depot_check.py::compute_depot_check consumption via routers/allocation.py (/depot-check) and services/advisory_report.py — NICHT routers/pdf_reports.py"
audit_mode: "read_only_static_service_router_pdf_renderer_and_test_review_no_runtime_mutation"
audit_mutated_product_code: false
audit_mutated_tests: false
scope: "routers/pdf_reports.py depotcheck.pdf endpoint, services/pdf/documents/depotcheck.py and services/pdf/components/depotcheck_soll.py renderer, services/depot_check.py as data source, tests/pdf/test_depotcheck_soll_analysis.py, frontend Depot-Check modal/button labelling"
release_decision: "confirmed_p1_scope_and_naming_gap_on_the_pdf_consumer_only"
new_confirmed_p0: false
new_confirmed_p1: true
---

# Depotcheck End-to-End-Integritätsaudit (`CORE-COVERAGE-002`)

## Geltung und Abgrenzung

Dieser Audit beantwortet gezielt die im Reconciliation-Dokument
`2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md`
unter `CORE-COVERAGE-002` offen gelassene Frage: Prüft der aktive
PDF-Endpunkt `routers/pdf_reports.py::get_depotcheck_pdf` tatsächlich das
**aktuelle IST-Depot** des Kunden, oder analysiert er — trotz des Namens
„Depotcheck" — ausschliesslich das **empfohlene SOLL-Zielportfolio**?

Er ist bewusst additiv zum
[Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Integritätsaudit vom
03.09.2026](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md)
("Kontrollrunde 22"). Jener Audit deckt `services/depot_check.py` und
dessen Konsum über `routers/allocation.py::get_depot_check`
(`GET /mandates/{id}/depot-check`, die **Live-Modal-Ansicht**) sowie über
`services/advisory_report.py` (Advisory-Report-PDF, Sektion "Erkenntnisse")
ab und bestätigt dort sieben P1-Findings (`DEPOT-CONTEXT-001` bis
`DEPOT-PUBLICATION-001`), insbesondere den Fallback „`current_amount<=0` →
`target_amount`".

Diese Runde schliesst eine andere, bisher nicht auditierte Lücke: den
**dritten, separaten Konsumenten** von `compute_depot_check` — den
eigenständigen, exportier-/archivierbaren PDF-Endpunkt
`/mandates/{mandate_id}/reports/depotcheck.pdf`. Der Audit vom 03.09.2026
erwähnt `routers/pdf_reports.py`, `services/pdf/documents/depotcheck.py`
oder `services/pdf/components/depotcheck_soll.py` an keiner Stelle (geprüft
per Volltextsuche gegen den dortigen Dokumenttext). Er ersetzt diesen Audit
nicht und wird durch ihn nicht ersetzt; bei Widersprüchen gilt aktueller
Code zuerst, danach beide Audits nebeneinander.

## Kurzfazit

**Der Verdacht des Reconciliation-Dokuments ist für den PDF-Endpunkt
bestätigt — nicht als Interpretationsfrage, sondern als durchgängig
dokumentiertes, getestetes und UI-beworbenes Verhalten.**

`get_depotcheck_pdf` liefert ein Dokument, das nach eigenem Code-Kommentar,
eigener Docstring-Kette, eigenem Datenklassen-Kommentar, eigenem
In-PDF-Fliesstext und einem eigens dafür geschriebenen Test **ausschliesslich
das empfohlene Zielportfolio** beschreibt. Alle Felder, die tatsächliche
Kundenbestände (IST) tragen könnten, werden zwar aus
`compute_depot_check()` geladen, aber vor dem Rendering verworfen:

- `DepotCheckData.buckets` (IST-vs-SOLL-Drift pro Hauptanlageklasse,
  `ist_bps`/`soll_bps`/`drift_bps`/`in_band`) wird befüllt, aber von keiner
  Renderer-Funktion je gelesen.
- `country_exposure_bps`, `sector_exposure_bps`, `currency_exposure_bps` und
  `concentration_hhi` (die undekorierten, IST-benannten Felder) werden
  ebenso befüllt und ebenso nie gerendert — nur die `soll_*`-Geschwister
  werden angezeigt.
- Die angezeigte Positionstabelle (`top_positions`) und die
  Subanlageklassen-Tabelle (`sub_allocations`) werden NICHT aus
  `compute_depot_check()`s IST-Daten gebaut, sondern aus einer zweiten,
  unabhängig geladenen Positionsliste (`_build_portfolio_data`), aus der
  explizit nur `target_amount_rappen`/`target_weight_bps` ausgelesen werden
  — obwohl dieselben Positions-Dicts dort auch `current_amount_rappen`,
  `current_weight_bps` und `drift_bps` (aus `RecommendationHolding`)
  enthalten. Auch diese real vorhandene IST-Information wird verworfen,
  bevor sie das PDF erreicht.

Gleichzeitig bewirbt die Elektron-UI genau dieses PDF im selben Modal, das
die Live-IST-vs-SOLL-Ansicht zeigt, mit einem Tooltip, der ausdrücklich
„**mit Drift**" verspricht — ein Versprechen, das der Code selbst in
derselben PDF als nicht eingehalten dokumentiert
(„Der Depot-Check analysiert ausschliesslich das empfohlene
Zielportfolio.").

Der zugrunde liegende Service `compute_depot_check()` selbst ist **nicht**
rein fiktiv — er berechnet reale (wenn auch gemäss Kontrollrunde 22
fehlerhafte) IST-Werte für den Live-Modal-Konsumenten. Der PDF-Pfad
nutzt davon aber nur die SOLL-Hälfte. Das Problem dieser Runde ist daher
präzise: **ein Datenname ("Depotcheck"), drei Konsumenten, zwei
unterschiedliche fachliche Inhalte, keine sichtbare Trennung für den
Endnutzer.**

| Kernfrage | Befund |
|---|---|
| Analysiert der PDF-Endpunkt das aktuelle IST-Depot? | **Nein**, nachweislich nicht — weder in den gerenderten Daten noch in Text/Tests. |
| Analysiert er das empfohlene SOLL-Zielportfolio? | **Ja**, ausschliesslich. |
| Werden IST und SOLL im PDF nebeneinander reconciliiert? | **Nein**, keine Drift-/Band-/Massnahmen-Darstellung im PDF. |
| Fliessen Suitability/Präferenzen/Steuern in die PDF-Aussagen ein? | **Nein**, nur CMA-Risikokennzahlen und ein generischer Kostenausweis. |
| Schliessen bestehende Tests die semantische Lücke? | **Nein** — ein Test verlangt explizit die Abwesenheit von IST/Drift-Text. |
| Ist der Name „Depotcheck" im Kontext dieses PDFs irreführend? | **Ja**, insbesondere durch den Download-Button-Tooltip „mit Drift". |

## Findings-Register

| ID | Prio | Status | Releasewirkung |
|---|---:|---|---|
| `DEPOTCHECK-SCOPE-001` | P1 | bestätigt | PDF-Endpunkt rendert ausschliesslich SOLL-Felder; alle IST-benannten Felder in `DepotCheckData` werden berechnet, aber nie gerendert. |
| `DEPOTCHECK-SCOPE-002` | P1 | bestätigt | Die im PDF sichtbare Positions-/Suballokationstabelle verwirft real vorhandene `current_amount_rappen`/`current_weight_bps`/`drift_bps`-Werte aus `RecommendationHolding`, bevor sie `DepotCheckData` erreichen. |
| `DEPOTCHECK-NAMING-001` | P1 | bestätigt | UI-Button-Tooltip verspricht „Depot-Check mit Drift", das ausgelieferte PDF dokumentiert selbst das Gegenteil; derselbe Modaltitel „Depot-Check & Diversifikation" deckt zwei fachlich verschiedene Dokumente. |
| `DEPOTCHECK-TEST-001` | P2 | bestätigt | Bestehender PDF-Test kodifiziert die Abwesenheit von IST-/Drift-Inhalt als Erfolgskriterium; keine der drei Testfunktionen prüft reale Bestände, Suitability oder Reconciliation. |
| `DEPOTCHECK-OVERLAY-001` | P2 | bestätigt | Die PDF-„Qualitative Einschätzung" sowie alle Erkenntnis-Texte sind generische Strukturanalysen des Zielportfolios; keine kunden-/depotspezifische Suitability-, Präferenz- oder Steuerwirkung fliesst ein, weil es keine IST-Befunde gibt, auf die eine solche Wirkung angewendet werden könnte. |

Keines dieser Findings schliesst die sieben P1-Findings der Kontrollrunde 22
vom 03.09.2026 (`DEPOT-CONTEXT-001` bis `DEPOT-PUBLICATION-001`). Diese
bleiben für den Live-Modal- und Advisory-Report-Konsumenten unverändert in
Kraft.

## Tatsächlicher Datenfluss (PDF-Pfad)

```text
GET /mandates/{id}/reports/depotcheck.pdf
  (routers/pdf_reports.py:1829 get_depotcheck_pdf)
  |
  +-- _build_depotcheck_data(mandate, db)              [pdf_reports.py:1566]
  |     |
  |     +-- dc = compute_depot_check(db, mandate)      [services/depot_check.py:465]
  |     |      -> buckets{ist_bps,soll_bps,drift_bps,in_band}      (berechnet, NIE gerendert)
  |     |      -> country/sector/currency_exposure_bps  (IST,       berechnet, NIE gerendert)
  |     |      -> concentration_hhi                     (IST,       berechnet, NIE gerendert)
  |     |      -> soll_country/sector/currency_exposure_bps          (gerendert)
  |     |
  |     +-- portfolio = _build_portfolio_data(mandate, db)   [pdf_reports.py:1044]
  |     |      -> positions[i] = {target_weight_bps, target_amount_rappen,
  |     |                          current_weight_bps, current_amount_rappen,  <- IST, real
  |     |                          drift_bps}                                   <- real, aus RecommendationHolding
  |     |
  |     +-- top_positions = [ {amount_rappen: target_amount_rappen,
  |     |                      weight_bps:   target_weight_bps, ...}             <- current_* verworfen
  |     |                     for item in positions ]                [pdf_reports.py:1633-1645]
  |     +-- sub_allocations = aggregate(positions, nur target_*)     [pdf_reports.py:1664-1692]
  |     \-- qualitative_assessment: Text ueber "das empfohlene Zielportfolio" [pdf_reports.py:1795-1821]
  |
  +-- ReportLabRenderer().render_depotcheck(ctx, data)    [reportlab_renderer.py:104]
        -> build_depotcheck_flowables(ctx, data)          [documents/depotcheck.py:28]
             liest ausschliesslich: data.target_allocation_bps, data.bucket_bands_bps,
             data.sub_allocations, data.soll_country/sector/currency_exposure_bps,
             data.soll_concentration_hhi, data.top_positions, data.risk_metrics,
             data.cost_disclosure, data.performance, data.qualitative_assessment
             -> data.buckets, data.country_exposure_bps, data.sector_exposure_bps,
                data.currency_exposure_bps, data.concentration_hhi: NIE referenziert

Parallel, vom selben compute_depot_check() aber über einen ANDEREN Endpunkt:
GET /mandates/{id}/depot-check  (routers/allocation.py:701)
  -> dieselbe IST/SOLL-Struktur, in der Live-Modal-Ansicht ("m-dc") gerendert
  -> siehe Kontrollrunde 22 fuer dort bestaetigte P1-Bugs in genau diesen Feldern
```

## `DEPOTCHECK-SCOPE-001` — PDF-Endpunkt rendert ausschliesslich das SOLL-Zielportfolio

### Beobachtung

Die Funktionskette ist an vier unabhängigen Stellen im selben Feature
wortgleich dokumentiert als SOLL-exklusiv:

```python
# 5eyes-backend/services/pdf/base.py:296-298
@dataclass(frozen=True)
class DepotCheckData:
    """Depotcheck-PDF Daten-Bundle fuer die reine SOLL-Analyse."""
```

```python
# 5eyes-backend/routers/pdf_reports.py:1566-1567
def _build_depotcheck_data(mandate: Mandate, db: Session) -> DepotCheckData:
    """Build the client-facing analysis of the recommended target portfolio."""
```

```python
# 5eyes-backend/routers/pdf_reports.py:1834
    """Depotcheck-PDF: reine Analyse des empfohlenen Zielportfolios."""
```

```python
# 5eyes-backend/services/pdf/documents/depotcheck.py:1,29
"""Target-only depot analysis for the client consultation."""
...
def build_depotcheck_flowables(ctx: PDFContext, data: DepotCheckData) -> list:
    """Compose a professional SOLL analysis without current-vs-target drift."""
```

Das PDF selbst sagt es dem Leser explizit, auf Seite „Methodik und
rechtlicher Hinweis":

```python
# 5eyes-backend/services/pdf/documents/depotcheck.py:218-223
'Der Depot-Check analysiert ausschliesslich das empfohlene Zielportfolio. '
'Der Abgleich mit Bank- oder Drittdepotunterlagen erfolgt ausserhalb '
'dieses Dokuments durch den Berater. ...'
```

Trotzdem lädt `_build_depotcheck_data` die vollständige IST/SOLL-Struktur
aus `compute_depot_check()` (inkl. `buckets` mit `ist_bps`/`soll_bps`/
`drift_bps`/`in_band`, inkl. der undekorierten — also IST-gemeinten —
`country_exposure_bps`/`sector_exposure_bps`/`currency_exposure_bps`/
`concentration_hhi`) und reicht sie 1:1 in `DepotCheckData` weiter:

```python
# 5eyes-backend/routers/pdf_reports.py:1612-1632
return DepotCheckData(
    ...
    buckets=dc.get("buckets") or {},
    country_exposure_bps=dc.get("country_exposure_bps") or {},
    sector_exposure_bps=dc.get("sector_exposure_bps") or {},
    currency_exposure_bps=dc.get("currency_exposure_bps") or {},
    soll_country_exposure_bps=soll_country,
    soll_sector_exposure_bps=soll_sector,
    soll_currency_exposure_bps=soll_currency,
    concentration_hhi=dc.get("concentration_hhi") or {},
    soll_concentration_hhi=soll_hhi,
    ...
)
```

`build_depotcheck_flowables` (`services/pdf/documents/depotcheck.py:28-234`)
liest aus diesem Objekt ausschliesslich `data.target_allocation_bps`,
`data.bucket_bands_bps`, `data.sub_allocations`,
`data.soll_country_exposure_bps`, `data.soll_sector_exposure_bps`,
`data.soll_currency_exposure_bps`, `data.soll_concentration_hhi`,
`data.top_positions`, `data.risk_metrics`, `data.cost_disclosure`,
`data.performance`, `data.stress_scenarios`, `data.warnings` und
`data.qualitative_assessment`. Eine repositoryweite Suche bestätigt: `
data.buckets`, `data.country_exposure_bps`, `data.sector_exposure_bps`,
`data.currency_exposure_bps` und `data.concentration_hhi` (ohne
`soll_`-Präfix) werden **in keiner** Datei unter
`services/pdf/documents/` oder `services/pdf/components/` gelesen.

### Reproduktion (Codepfad-Nachweis statt Laufzeitprobe)

Dieser Nachweis erfolgte statisch, da ausdrücklich keine Produktcode-
Mutation erlaubt ist: `grep -n "data\.buckets\|data\.country_exposure_bps\|
data\.sector_exposure_bps\|data\.currency_exposure_bps\|data\.concentration_hhi\b"
services/pdf/**/*.py` liefert für `documents/depotcheck.py` keinen Treffer;
die einzigen Treffer für `data.sub_allocations`/`data.top_positions` liegen
in `documents/depotcheck.py` sowie — als separates, hier nicht betroffenes
Dokument — `documents/contract_signoff.py:90`.

### Erforderliche Lösung / Auditvertrag

1. Der PDF-Endpunkt muss entweder (a) umbenannt und klar als
   „Zielportfolio-Analyse"/„SOLL-Depot-Check" deklariert werden, solange er
   keine IST-Daten zeigt, oder (b) tatsächlich die bereits berechneten
   `buckets`/`country_exposure_bps`/`sector_exposure_bps`/
   `currency_exposure_bps`/`concentration_hhi`-Felder (IST) neben den
   `soll_*`-Feldern rendern, inklusive Drift- und Bandverletzungs-Anzeige.
2. Wird Variante (b) gewählt, muss zuerst Kontrollrunde 22
   (`DEPOT-IST-001`, `DEPOT-HOLDING-001`, `DEPOT-COVERAGE-001`,
   `DEPOT-FX-SCOPE-001`, `DEPOT-VERDICT-001`) geschlossen sein — sonst würde
   der PDF-Pfad exakt dieselben, bereits dokumentierten Fehler lediglich in
   einen weiteren Kanal spiegeln.
3. Totgelegte Felder dürfen nicht weiter in `DepotCheckData` befüllt werden,
   ohne dass ein Renderer sie konsumiert — das verschleiert sowohl für
   Reviewer als auch für künftige Audits den tatsächlichen Funktionsumfang.

## `DEPOTCHECK-SCOPE-002` — Reale Holding-Daten werden ein zweites Mal verworfen

### Beobachtung

`_build_portfolio_data` (`routers/pdf_reports.py:1044-1181`) lädt für die
jüngste zur aktuellen `TargetAllocation` passende `RecommendationRun` die
`RecommendationHolding`-Zeilen und aggregiert deren `market_value_rappen`
pro Position zu `current_amount_by_position`:

```python
# routers/pdf_reports.py:1121-1152
holding_rows = (
    db.query(RecommendationHolding)
    .filter(
        RecommendationHolding.run_id == last_run.id,
        RecommendationHolding.deleted_at.is_(None),
    )
    .all()
)
current_amount_by_position: dict[str, int] = {}
for holding in holding_rows:
    ...
    current_amount_by_position[pos_id] = (
        current_amount_by_position.get(pos_id, 0)
        + int(getattr(holding, "market_value_rappen", 0) or 0)
    )
...
for pos in pos_list:
    ...
    current_amount = current_amount_by_position.get(str(getattr(pos, "id", "") or ""), 0)
    current_bps = (
        int(round(current_amount / current_total * 10000))
        if current_total > 0 and current_amount > 0
        else 0
    )
    drift_bps = current_bps - target_bps if current_total > 0 else 0
    positions.append({
        ...
        "target_weight_bps": target_bps,
        "current_weight_bps": current_bps,
        "drift_bps": drift_bps,
        "target_amount_rappen": int(getattr(pos, "target_amount_rappen", 0) or 0),
        "current_amount_rappen": current_amount,
        ...
    })
```

Diese Positions-Dicts enthalten also real vorhandene IST-Werte aus der
Holding-Pipeline — der gleichen Pipeline, die Kontrollrunde 22 als die
*fachlich reichere* Quelle identifiziert (dort referenziert über
`services/portfolio_engine_live_rebalancing.py`). Doch `_build_depotcheck_data`
verwirft genau diese Felder beim Bau der sichtbaren Tabellen:

```python
# routers/pdf_reports.py:1633-1645
top_positions=[
    {
        ...
        "amount_rappen": int(item.get("target_amount_rappen", 0) or 0),
        "weight_bps": int(item.get("target_weight_bps", 0) or 0),
        "ter_bps": int(item.get("ter_bps", 0) or 0),
    }
    for item in positions
],
```

```python
# routers/pdf_reports.py:1682-1687 (_aggregate_depotcheck_sub_allocations)
row["weight_bps"] = int(row["weight_bps"]) + int(
    item.get("target_weight_bps", 0) or 0
)
row["amount_rappen"] = int(row["amount_rappen"]) + int(
    item.get("target_amount_rappen", 0) or 0
)
```

`item.get("current_weight_bps")`, `item.get("current_amount_rappen")` und
`item.get("drift_bps")` werden an keiner dieser Stellen gelesen. Die
`DepotCheckData.top_positions`-Docstring bestätigt dies als beabsichtigten,
nicht nur übersehenen Vertrag:

```python
# services/pdf/base.py:320-323
top_positions: list = field(default_factory=list)
"""Liste mit product_name, isin, asset_class, sub_asset_class, currency,
amount_rappen, weight_bps, ter_bps."""
```

— kein `current_amount_rappen`, kein `drift_bps` im dokumentierten Vertrag.

### Erforderliche Lösung / Auditvertrag

1. Entweder wird `current_weight_bps`/`current_amount_rappen`/`drift_bps`
   explizit in `DepotCheckData.top_positions`/`sub_allocations` aufgenommen
   und im Renderer dargestellt, oder das Laden der `RecommendationHolding`-
   Daten in diesem Pfad wird als bewusst ungenutzt dokumentiert, damit kein
   Reviewer annimmt, IST-Daten seien hier bereits abgedeckt.
2. Bevor Variante 1 umgesetzt wird, ist zu klären, ob
   `RecommendationHolding.market_value_rappen` (dieser Pfad) oder
   `RecommendationPosition.current_amount_rappen` (der von
   `compute_depot_check` genutzte Skalar, siehe `DEPOT-HOLDING-001` vom
   03.09.2026) die kanonische IST-Quelle werden soll — beide dürfen nicht
   unabhängig nebeneinander weiterbestehen.

## `DEPOTCHECK-NAMING-001` — Button-Versprechen „mit Drift" widerspricht dem eigenen PDF-Text

### Beobachtung

Im Electron-Frontend öffnet ein einziges Modal unter dem Titel „Depot-Check
& Diversifikation" sowohl die Live-JSON-Ansicht (`GET /mandates/{id}/depot-check`,
mit echten — wenn auch laut Kontrollrunde 22 fehlerhaften — IST-Werten) als
auch den Download-Button für das hier auditierte PDF:

```html
<!-- 5eyes-electron/frontend/5eyes_v2.html:4225 -->
<div class="mhd"><div class="mtitle">Depot-Check &amp; Diversifikation</div>...

<!-- 5eyes-electron/frontend/5eyes_v2.html:4290 -->
<button class="btn-p" onclick="downloadServerPdf('depotcheck')"
  title="Server-PDF: Depot-Check mit Drift, Diversifikation, Stress-Replays">
  PDF herunterladen
</button>
```

```javascript
// 5eyes-electron/frontend/5eyes_v2.html:13264
var data = await API.get('/mandates/' + encodeURIComponent(mid) + '/depot-check');
```

Der Tooltip verspricht wörtlich „**mit Drift**". Das heruntergeladene PDF
dokumentiert in seinem eigenen Fliesstext das Gegenteil
(`services/pdf/documents/depotcheck.py:219`: „Der Depot-Check analysiert
ausschliesslich das empfohlene Zielportfolio.") und enthält laut
`DEPOTCHECK-SCOPE-001`/`-002` keine Drift-Darstellung. Ein Berater, der den
Tooltip liest und das PDF ungeprüft an einen Kunden weiterleitet, verspricht
damit etwas, das das Dokument nachweislich nicht liefert.

Die Modal-interne Unterscheidung ist für die Person am Bildschirm nicht
offensichtlich: derselbe Button-Block, dieselbe Überschrift, zwei fachlich
verschiedene Wahrheiten (Live-IST/SOLL vs. PDF-nur-SOLL) hinter einem Klick.

### Erforderliche Lösung / Auditvertrag

1. Der Tooltip-Text ist entweder zu korrigieren (keine Erwähnung von
   „Drift", solange das PDF keine Drift zeigt) oder das PDF ist um die in
   `DEPOTCHECK-SCOPE-001` beschriebenen, bereits berechneten IST/Drift-Felder
   zu erweitern.
2. Das PDF-Dokument und die Live-Modal-Ansicht sollten im UI klar als zwei
   unterschiedliche Artefakte mit unterschiedlichem Geltungsbereich
   benannt werden (z.B. „Live-Depot-Check (IST vs. SOLL)" versus
   „Zielportfolio-Analyse (PDF)"), nicht unter demselben Modaltitel.
3. Diese sprachliche Richtigstellung ist exakt die im Reconciliation-
   Dokument unter `CORE-COVERAGE-002` geforderte Bedingung: „Zielportfolio-
   analyse darf nicht als umfassender aktueller Depotcheck verkauft werden."

## `DEPOTCHECK-TEST-001` — Tests kodifizieren die Lücke statt sie zu schliessen

### Beobachtung

`tests/pdf/test_depotcheck_soll_analysis.py` enthält vier Tests. Der
Dateiname selbst benennt den Geltungsbereich explizit als „SOLL-Analyse".
Der erste Test macht die Abwesenheit von IST-/Drift-Inhalt zu einem
bestandenen Prüfkriterium:

```python
# tests/pdf/test_depotcheck_soll_analysis.py:183-201
def test_depotcheck_is_target_only_and_structurally_complete():
    reader, text = _text(ReportLabRenderer().render_depotcheck(_context(), _data()))

    assert len(reader.pages) >= 10
    for anchor in (
        "Hauptanlageklassen", "Subanlageklassen", "Laenderallokation",
        "Sektorallokation", "Waehrungsallokation", "Risikoanalyse",
        "Diversifikation und Klumpenrisiken", "Kosten und Gebuehren",
        "Performancevergleich", "Qualitative Einschaetzung",
    ):
        assert anchor in text
    assert "IST vs." not in text
    assert "Drift-Tabelle" not in text
```

Die übrigen drei Tests prüfen ausschliesslich Struktur und Robustheit:

- `test_depotcheck_contains_target_details_and_benchmark` (Zeile 204-214):
  prüft nur, dass Zielpositions-/Benchmark-Strings im Text vorkommen —
  alle Eingabedaten sind bereits `soll_*`-Felder.
- `test_depotcheck_degraded_payload_still_renders` (Zeile 217-230): prüft
  nur, dass ein fast leeres `DepotCheckData`-Objekt kein PDF zum Absturz
  bringt und „Daten ausstehend" erscheint — keine inhaltliche Aussage.
- `test_depotcheck_dense_realistic_payload_stays_on_eleven_pages` (Zeile
  233-260): prüft Seitenzahl-Stabilität bei vielen Zeilen — ebenfalls rein
  strukturell.

Keiner der vier Tests instanziiert `compute_depot_check()`, lädt eine
`WealthPosition`/`RecommendationHolding` aus der DB oder prüft, ob ein
tatsächlicher Kundenbestand jemals in das PDF einfliesst. Die Tests
widerlegen damit exakt nicht das, was das Reconciliation-Dokument vermutet
hatte, sondern bestätigen es aktiv: „Tests, die nur Struktur, Seitenzahl
oder degradiertes Rendering prüfen, schliessen diese semantische Lücke
nicht."

Separat davon testen `tests/test_depot_check.py` (33 Tests) und
`tests/test_depot_check_helpers.py` echte IST/SOLL-Aggregation — aber nur
für den von Kontrollrunde 22 auditierten Live-Endpunkt
(`compute_depot_check()` direkt), nicht für den PDF-Pfad. Keiner dieser
Tests instanziiert `_build_depotcheck_data` oder
`get_depotcheck_pdf`.

### Fokussierter Testlauf dieser Runde

```text
python -m pytest -q -p no:cacheprovider \
  --basetemp C:\tmp\5eyes-depotcheck-pdf-audit-20261005 \
  tests/pdf/test_depotcheck_soll_analysis.py \
  tests/test_depot_check.py \
  tests/test_depot_check_helpers.py
```

Ergebnis: `44 passed`. Ein grüner Testlauf bestätigt hier ausdrücklich NICHT
die Abwesenheit des Scope-Findings — er bestätigt lediglich, dass der
Scope absichtlich eng und die Tests konsistent dazu geschrieben sind.

### Erforderliche Lösung / Auditvertrag

1. Ein neuer Test muss `_build_depotcheck_data`/`get_depotcheck_pdf` mit
   einem Mandat aufrufen, das sowohl `RecommendationHolding`- als auch
   `RecommendationPosition.current_amount_rappen`-Werte besitzt, die vom
   Zielwert abweichen, und beweisen, ob/dass diese Abweichung im PDF
   sichtbar wird (aktuell: nicht sichtbar).
2. Sobald `DEPOTCHECK-SCOPE-001`/`-002` behoben sind, muss
   `test_depotcheck_is_target_only_and_structurally_complete` umbenannt und
   inhaltlich umgedreht werden (IST-vs-SOLL-Inhalt muss dann PFLICHT sein,
   nicht verboten).
3. Mindestens ein Cross-Channel-Test muss Live-Endpunkt (`/depot-check`)
   und PDF-Endpunkt (`/reports/depotcheck.pdf`) für dasselbe Mandat
   gegenüberstellen und explizit prüfen, ob beide denselben Depotbestand
   beschreiben oder ob das Dokument seinen engeren Geltungsbereich
   mindestens klar kennzeichnet.

## `DEPOTCHECK-OVERLAY-001` — Keine Suitability-/Präferenz-/Steuerwirkung auf PDF-Aussagen

### Beobachtung

Eine Volltextsuche nach `suitability`, `preference` und `tax` in
`services/depot_check.py`, `services/pdf/documents/depotcheck.py` und
`services/pdf/components/depotcheck_soll.py` ergibt ausser einem
Code-Kommentar (`services/depot_check.py:600`, Verweis auf die
Staleness-Prüfung der `TargetAllocation`) keinen Treffer. Die einzige
kundenspezifische Textaussage im PDF ist
`_build_depotcheck_qualitative_assessment`:

```python
# routers/pdf_reports.py:1815-1821
return (
    f"Das empfohlene Zielportfolio ist auf das Risikoprofil {profile} "
    f"ausgerichtet und verteilt das Anlagevermoegen auf {active_buckets} "
    f"Hauptanlageklassen sowie {active_products} konkrete Zielpositionen. "
    f"{concentration} Die Analyse ist eine Beratungsgrundlage; der Abgleich "
    "mit Bank- oder Drittdepotunterlagen erfolgt durch den Berater."
)
```

Diese Aussage bezieht sich ausschliesslich auf das Risikoprofil-Label und
eine HHI-Konzentrationsschwelle des Zielportfolios — beides bereits durch
die vorgelagerte Asset-Allocation-/Suitability-Prüfung bestimmt, nicht neu
gegen einen tatsächlichen Bestand abgeglichen. Es gibt keine
„Kaufen/Verkaufen/Halten"-Handlungsempfehlung, keine depot-spezifische
Steuerfolge und keine Präferenz-/ESG-Abweichungsaussage zum tatsächlichen
Bestand, weil es — konsistent mit `DEPOTCHECK-SCOPE-001` — keine
tatsächlichen Bestandsbefunde gibt, auf die eine solche Wirkung angewendet
werden könnte.

### Erforderliche Lösung / Auditvertrag

1. Sollte der PDF-Umfang auf echte IST-Daten erweitert werden
   (`DEPOTCHECK-SCOPE-001`), muss jede daraus resultierende
   Handlungsempfehlung gegen die aktuelle Suitability-/Präferenz-/Exclusion-
   Prüfung (siehe `2026-09-04-product-suitability-appropriateness-and-
   recommendation-eligibility-integrity-audit.md`) sowie gegen eine
   Steuerkontext-Prüfung laufen, bevor sie publiziert wird.
2. Solange der PDF-Umfang SOLL-only bleibt, ist dies explizit zu
   dokumentieren, damit kein Konsument annimmt, die „Qualitative
   Einschätzung" sei eine geprüfte Handlungsempfehlung zum bestehenden
   Depot.

## Zusammenhang mit dem House-Matrix-Benchmark (Querverweis `CORE-COVERAGE-001`)

Der Depotcheck-PDF-Pfad baut für den Performance-Vergleich eine eigene
House-Matrix-Benchmark:

```python
# routers/pdf_reports.py:1742-1782 (_depotcheck_house_matrix_benchmark)
```

Dies bestätigt unabhängig den im Reconciliation-Dokument unter
`CORE-COVERAGE-001` benannten Befund „der Depotcheck baut eine eigene
House-Matrix-Benchmark". Eine vertiefte Benchmark-Governance-Prüfung bleibt
ausserhalb des Geltungsbereichs dieses Audits (`CORE-COVERAGE-002`) und ist
dem separaten `CORE-COVERAGE-001`-Auftrag vorbehalten.

## Verifikation dieser Runde

- Vollständige Lektüre von `routers/pdf_reports.py` (2057 Zeilen),
  insbesondere der Depotcheck-Sektion (Zeilen 1560-1848).
- Vollständige Lektüre von `services/depot_check.py` (718 Zeilen).
- Vollständige Lektüre von `services/pdf/documents/depotcheck.py` (299
  Zeilen) und der `DepotCheckData`-Definition in `services/pdf/base.py`
  (Zeilen 296-341).
- Gezielte Lektüre von `_build_portfolio_data`
  (`routers/pdf_reports.py:1044-1181`).
- Repositoryweite Grep-Verifikation, dass `data.buckets`/
  `data.country_exposure_bps`/`data.sector_exposure_bps`/
  `data.currency_exposure_bps`/`data.concentration_hhi` in keiner
  Renderer-Datei unter `services/pdf/` gelesen werden.
- Vollständige Lektüre von `tests/pdf/test_depotcheck_soll_analysis.py`
  (261 Zeilen) sowie Kopfkommentar/Stichproben aus `tests/test_depot_check.py`.
- Gezielte Lektüre der Frontend-Stellen `5eyes-electron/frontend/
  5eyes_v2.html:4223-4292` (Modal/Button) und `:13251-13281`
  (`openDepotCheck`, Live-API-Aufruf).
- Fokussierter Testlauf (siehe oben): `44 passed`, keine Mutation.
- Bestätigt per Volltextsuche: `2026-09-03-depot-current-holdings-
  valuation-and-ist-soll-publication-integrity-audit.md` erwähnt
  `pdf_reports.py`, `documents/depotcheck.py` oder `depotcheck_soll` an
  keiner Stelle — dieser Audit deckt somit tatsächlich eine zuvor nicht
  dokumentierte Fläche ab und dupliziert Kontrollrunde 22 nicht.

### Repositoryzustand

- Branch: `codex/core-coverage-depotcheck-e2e-audit`
- auditierter Head: `83af2a84fbc16cd2ef602bb3d4baa22c04325bc2`
- Produktcode verändert: **nein**
- Tests verändert: **nein**
- Konfiguration verändert: **nein**
- Einziger neuer, committeter Pfad dieser Runde:
  `docs/audits/2026-10-05-core-coverage-depotcheck-end-to-end-integrity-audit.md`

## Selbst-Audit und Nachweisgrenzen

- Dieser Audit ist rein statisch (Code-/Test-/Dokumentlektüre plus ein
  unveränderter, bestehender Testlauf). Es wurde keine Live-API, kein
  Electron-Build und kein echtes PDF-Rendering gegen eine reale
  Mandats-Datenbank ausgeführt; alle Codepfad-Schlussfolgerungen (insb.
  „wird nie gerendert") stützen sich auf vollständige Lektüre der
  betroffenen Dateien plus gezielte Grep-Verifikation, nicht auf
  Instrumentierung zur Laufzeit.
- Die Bewertung von `DEPOTCHECK-SCOPE-002` beruht auf der Annahme, dass
  `_build_portfolio_data` für das geprüfte Mandat tatsächlich
  `RecommendationHolding`-Zeilen vorfindet; existieren keine solchen
  Zeilen, bleibt `current_amount_rappen` ohnehin `0` und der Befund
  bezieht sich dann primär auf die fehlende Datenstruktur/Dokumentation,
  nicht auf konkret verlorene Zahlen in jedem Einzelfall.
- Dieser Audit bewertet nicht erneut die Korrektheit von
  `compute_depot_check()`s IST-Berechnung selbst (Fallback-Bug, FX-Scope,
  Coverage) — dafür gilt unverändert Kontrollrunde 22 vom 03.09.2026.
- Dieser Audit bewertet nicht die Benchmark-Governance-Frage
  (`CORE-COVERAGE-001`) und nicht die Portfolio-Construction-/Recommendation-
  Reconciliation-Frage (`CORE-COVERAGE-003`); beide bleiben eigene
  Aufträge.
- Wie im Reconciliation-Dokument gefordert: ein bestehender grüner
  Testlauf (`44 passed`) ist hier ausdrücklich **kein** Gegenbeweis zum
  Scope-Finding — die Tests sind, wie unter `DEPOTCHECK-TEST-001` gezeigt,
  bewusst so geschrieben, dass sie den engen Scope bestätigen, nicht
  widerlegen.
