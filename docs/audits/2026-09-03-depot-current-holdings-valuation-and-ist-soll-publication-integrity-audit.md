---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-depot-current-holdings-valuation-ist-soll-publication-integrity-followup-audit"
status_as_of: "2026-09-03"
audit_started_on: "2026-09-03"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend/reporting"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "08993953e4f8abd34f28d8ae3adf9fb2e87ec9be"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md"
prior_release_audit_commit: "08993953e4f8abd34f28d8ae3adf9fb2e87ec9be"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md"
audit_mode: "read_only_static_service_orm_api_pdf_react_review_targeted_runtime_reproduction_existing_backend_and_frontend_test_gates"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "depot-check recommendation and target-allocation context, actual holdings and valuation provenance, current-versus-target fallback semantics, product and currency coverage, traffic-light findings, API React and PDF publication parity"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_backend_tests_passed: 222
focused_backend_tests_failed: 0
focused_frontend_tests_passed: 69
focused_frontend_tests_failed: 0
required_next_action: "define one immutable mandate-bound holdings valuation snapshot with exact run allocation prices FX and coverage; forbid target values as silent current holdings; derive every allocation exposure verdict React view and PDF from that same complete snapshot and fail closed for missing stale mixed or unvalued positions"
---

# Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die zweiundzwanzigste Read-only-
Kontrollrunde. Er wurde gegen den unveränderten Repository-Head `08993953`
durchgeführt und am 3. September 2026 konsolidiert. Produktcode und Tests
blieben unverändert.

Er ergänzt, ersetzt und schließt insbesondere nicht:

1. den unmittelbar vorherigen
   [Ex-ante-Kosten-/Retrozessions-/Konfliktnachweis-Integritätsaudit](2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md),
2. den
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
3. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
4. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
5. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
6. den
   [Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit](2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md),
7. sowie den grundlegenden
   [Post-Commit-Integritätsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Laufzeitbelege
zuerst, danach dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zum Advisory-Report-Audit vom Mai

Der [Advisory-Report-Audit vom 25. Mai](2026-05-25-advisory-report-audit.md)
hatte bereits erkannt, dass fehlende `current_amount_rappen` auf
`target_amount_rappen` fallen und dadurch IST=SOLL sowie eine falsche grüne
Ampel entstehen können. Damals wurde als P1 insbesondere ein sichtbarer
„IST basiert auf SOLL“-Hinweis gefordert.

Dieser Hinweis wurde in React und PDF für den Spezialfall implementiert, dass
**alle** Current-Werte `None` sind. Der zugrunde liegende Datenvertrag wurde
aber nicht geschlossen. Explizite Nullwerte und teilweise fehlende Werte
erhalten keinen Banner. Seitdem existiert außerdem eine eigene
`RecommendationHolding`-/Live-Rebalancing-Wahrheit, die der Depotcheck nicht
verwendet. Kontrollrunde 22 prüft deshalb den heutigen vollständigen
Service-/Holding-/Verdict-/Kanalvertrag und ersetzt den Altbefund nicht durch
eine bloße Wiederholung.

## Kurzurteil

**Release bleibt hart blockiert.** Der Depotcheck analysiert nicht
zuverlässig das aktuelle IST-Depot. Er wählt den jüngsten RecommendationRun
nach `created_at`, unabhängig von Finalität, Supersession und wirksamer
Soll-Allokation. Seine RecommendationPositions werden zugleich als Empfehlung
und als aktueller Bestand verwendet.

Ist `current_amount_rappen` fehlend (`None`), negativ oder exakt `0`, ersetzt der Service
den Wert durch `target_amount_rappen`. Das Flag `ist_basiert_auf_soll` prüft
dagegen nur, ob alle Rohwerte exakt `None` sind. Dadurch bleiben besonders
gefährliche Fälle unsichtbar:

- Ein expliziter Nullbestand wird als voller Zielbestand behandelt und nicht
  markiert.
- Bei teilweise gepflegten Beständen werden echte Current-Werte mit
  erfundenen Target-Werten addiert; der Banner bleibt aus.
- Ein einziger vorhandener Current-Wert macht den ganzen Bericht angeblich
  IST-basiert.

Die Reproduktion zeigte einen gespeicherten Bestand von `0`, der als
`100000000` Rappen, 100 Prozent Aktien und grüne Asset-Allocation-Ampel mit
„Keine Massnahme erforderlich“ publiziert wurde. Ein zweiter Fall addierte
80 Mio. echte Current-Rappen und 50 Mio. Target-Rappen zu einem angeblichen
IST-Depot von 130 Mio., ebenfalls ohne Banner.

Parallel existiert eine fachlich reichere Holding-/Live-Valuation-Pipeline.
Sie liest Units, Market Value, Holding-Stichtag, Preise, Preisqualität und FX.
Der Depotcheck ignoriert diese Daten. Im Beleg meldete die Live-Pipeline 20
Mio. Rappen aus einer vorhandenen Holding, während der Depotcheck 90 Mio. aus
dem alten RecommendationPosition-Feld ausgab.

Der WealthPosition-Fallback ist ebenfalls keine belastbare Alternative. Er
liest clientweite statt mandatgebundene Positionen, addiert Rappenbeträge
verschiedener Währungen nominal ohne FX und erzeugt daraus keine Currency-
Exposure. 10 Mio. CHF plus 10 Mio. USD ergaben exakt 20 Mio. angebliche
Beratungsvermögens-Rappen, aber eine leere Währungsverteilung.

Grüne Gates sind kein Gegenbeweis. 222 fokussierte Backend- und 69 Frontend-
Tests bestanden. Ein bestehender Depotcheck-Test bezeichnet den Nullwert-
Fallback ausdrücklich als „bestehenden depot_check-Bug“ und umgeht ihn mit
positiven IST-Werten. Die Banner-Tests decken nur all-`None` und einen einzigen
vollständig positiven Current-Wert ab; Partial-, Zero-, Holding-, Draft-
Override-, FX- und Cross-Channel-Negativfälle fehlen.

## Stabiles Findings-Register

| ID | Prio | Status | Releasewirkung |
|---|---:|---|---|
| `DEPOT-CONTEXT-001` | P1 | bestätigt | Jüngster beliebiger Run wird gegen unabhängige heutige Current-TA und Live-Produkte ausgewertet; Run-ID und Bewertungsstichtag fehlen im Output. |
| `DEPOT-IST-001` | P1 | bestätigt | `None`, `0` und negative Werte werden durch SOLL ersetzt; Partial-/Zero-Fälle bleiben unmarkiert und verfälschen Total, Gewichte und Drift. |
| `DEPOT-HOLDING-001` | P1 | bestätigt | Depotcheck ignoriert RecommendationHolding, Units, Preise, Preisqualität, FX und Live-Valuation und publiziert eine zweite IST-Wahrheit. |
| `DEPOT-COVERAGE-001` | P1 | bestätigt | Nicht auflösbare Produktpositionen werden still entfernt; Produktauswahl prüft Active-/Deleted-State nicht; kein Vollständigkeitsvertrag schützt Totale und Exposures. |
| `DEPOT-FX-SCOPE-001` | P1 | bestätigt | Wealth-Fallback ist clientweit, summiert mehrere Währungen nominal ohne FX und lässt Currency-/Country-/Sector-Exposure leer. |
| `DEPOT-VERDICT-001` | P1 | bestätigt | Ampeln und Handlungsanweisungen laufen auf Surrogat-/Mischdaten; fehlende oder unbekannte IST-Evidence kann grün und „keine Massnahme“ werden. |
| `DEPOT-PUBLICATION-001` | P1 | bestätigt | API, React und PDF besitzen keinen gemeinsamen Holdings-Snapshot; React formatiert Positionen hart als CHF und Banner transportieren nur ein unzureichendes Boolean. |

Keines dieser Findings schließt ältere Produkt-, Preis-, FX-, Snapshot- oder
Publikationsfindings. Ein P1 in Kundenbestand, Bewertung, Drift,
Konzentration, Liquidität, Währungsrisiko oder Handlungsempfehlung blockiert
Final-/Kundenpublikation.

## Tatsächlicher Datenfluss

```text
compute_advisory_report
  |
  +-- compute_depot_check
  |     |
  |     +-- newest RecommendationRun by created_at (beliebiger Status)
  |     |      |
  |     |      +-- RecommendationPosition.current_amount_rappen
  |     |      |       \-- <= 0 / None: target_amount_rappen als IST
  |     |      |
  |     |      \-- Product live, fehlende Product-ID wird übersprungen
  |     |
  |     +-- falls keine auflösbare RecommendationPosition:
  |     |      clientweite WealthPositions, raw nominal ohne FX
  |     |
  |     \-- separate heutige Current-TargetAllocation
  |            -> Buckets, Exposures, HHI, Liquidität, Warnungen
  |
  +-- eigener newest-Run-Cache für Positionen/Banner/Sektorkontext
  |      \-- Banner true nur wenn ALLE current_amount exakt None
  |
  +-- Erkenntnisse/Ampeln aus Depotcheck ohne Evidence-State
  +-- React: Boolean-Banner und CHF-Hardcode
  \-- PDF: Boolean-Banner und mandate_currency

parallel, nicht konsumiert:
RecommendationHolding + Units + Holding-as-of + PriceHistory + FX
  -> build_live_rebalancing_payload
  -> eigene Current-Market-Value-/Drift-Wahrheit
```

Es gibt keinen gemeinsamen `holdings_snapshot_id`, `valuation_as_of`,
`source_run_id`, `allocation_id`, Coverage-Status oder Hash.

## Codeanker auf dem auditierten Head

| Bereich | Anker | Beobachtung |
|---|---|---|
| Advisory-Run | `5eyes-backend/services/advisory_report.py:61-92` | Newest nach `created_at`, kein Final-/Superseded-/Allocation-Vertrag. |
| Doppelter Read | `5eyes-backend/services/advisory_report.py:280-323` | Depotcheck und Advisory-Cache lösen Context getrennt auf. |
| Bannerlogik | `5eyes-backend/services/advisory_report.py:464-477` | Fallback bei `current > 0`, Flag nur `all(... is None)`. |
| Positionen | `5eyes-backend/services/advisory_report.py:941-1044` | SOLL aus latest Run, aber ohne Run-ID, Status, as-of oder Currency-Kontext. |
| Depot-Run | `5eyes-backend/services/depot_check.py:243-308` | Newest Run; Current<=0 fällt auf Target; erst bei null auflösbaren Rows Wealth-Fallback. |
| Produktcoverage | `5eyes-backend/services/depot_check.py:263-284` | Nicht gefundene Products werden übersprungen; Product-Read ohne Active-/Deleted-Filter. |
| IST-Berechnung | `5eyes-backend/services/depot_check.py:389-465` | Ersatzwerte fließen in Total, Buckets, Exposures, HHI, TER und Liquidität. |
| Unabhängige TA | `5eyes-backend/services/depot_check.py:479-510` | Current-TA wird unabhängig vom gewählten Run geladen. |
| Wealth-FX | `5eyes-backend/services/depot_check.py:287-307`, `461-515` | Raw Amounts werden addiert; Exposure-Maps entstehen nur für RecommendationPositions. |
| Ampel | `5eyes-backend/services/advisory_report.py:1151-1187`, `1253-1286` | Erkenntnisse kennen keinen Holdings-/Coverage-State; keine Bandverletzung ergibt grün. |
| Holding-Modell | `5eyes-backend/models/review.py:387-433` | RecommendationPosition besitzt Current-Skalar; RecommendationHolding besitzt Units, Market Value und as-of. |
| Live-Valuation | `5eyes-backend/services/portfolio_engine_live_rebalancing.py:288-430`, `560-675` | Verwendet Holdings, Preise, Freshness, FX, Valuation-Basis und as-of. |
| Preisrefresh | `5eyes-backend/services/market_data_daily_refresh.py:55-94` | Aktualisiert Referenzpreisfelder, nicht RecommendationPosition.current_amount. |
| Wealth-Scope | `5eyes-backend/models/wealth.py:6-17` | WealthPosition ist clientgebunden und currencytragend, aber nicht mandatgebunden. |
| React-Banner | `5eyes-electron/frontend/reporting/src/pages/AssetAllocation.tsx:32-63`; `Risikowaehrungen.tsx:42-60`; `Branchen.tsx:38-47` | Zeigt ausschließlich das unzureichende Boolean. |
| React-Ampel | `5eyes-electron/frontend/reporting/src/pages/Erkenntnisse.tsx:15-78` | Rendert Verdict ohne Datenbasis-/Coverage-Warnung. |
| React-Currency | `5eyes-electron/frontend/reporting/src/lib/format.ts:9-21`; `pages/Positionen.tsx:70,138,201` | Formatter und Positionenseite setzen CHF fest. |
| TypeScript | `5eyes-electron/frontend/reporting/src/api/types.ts:673-721` | Top-Level `mandate_currency` fehlt im Vertrag. |
| PDF | `5eyes-backend/services/pdf/documents/advisory_report.py:258`, `1110-1237` | PDF nutzt Currency, aber denselben Boolean-/Verdict-Payload. |
| Kodifizierter Bug | `5eyes-backend/tests/test_depot_check.py:321-356` | Test kommentiert Zero-Fallback als bestehenden Bug und vermeidet Zero. |

## `DEPOT-CONTEXT-001` – Run und Soll-Allokation gehören nicht zwingend zusammen

### Beobachtung

Sowohl Advisory-Cache als auch Depotcheck wählen separat den zeitlich jüngsten
Run. Kein Filter verlangt `Final`, eine nicht supersedierte Empfehlung oder
die TA, auf die sich der Run bezieht. Der Depotcheck lädt danach unabhängig
die heutige Current-TA. Live-Produktattribute und Exposure-Maps ergänzen die
Mischsicht.

Unter PostgreSQL READ COMMITTED können die separaten Statements bei einer
gleichzeitigen Run-/TA-Transition sogar innerhalb eines Reportaufrufs
verschiedene committed Zustände sehen. Schon ohne Race reicht ein neuer Draft,
um einen Final-Run zu verdrängen.

### Reproduktion

Ein älterer Final-Run enthielt 100 Prozent Aktien. Ein neuerer Draft enthielt
100 Prozent Obligationen. Die unabhängige Current-TA blieb bei 100 Prozent
Aktien.

```json
{
  "available_runs": [
    {"status": "Final", "product": "FINAL-*"},
    {"status": "Draft", "product": "DRAFT-*"}
  ],
  "published_products": ["DRAFT-*"],
  "published_ist_bps": {"Aktien": 0, "Obligationen": 10000},
  "independent_current_ta_soll_bps": {"Aktien": 10000, "Obligationen": 0},
  "asset_allocation_verdict": {
    "bewertung": "gelb",
    "beurteilung": "2 Anlageklasse(n) ausserhalb des Bandes: Aktien, Obligationen."
  },
  "report_exposes_source_run_id": false,
  "report_exposes_valuation_as_of": false
}
```

Der Bericht verwandelte damit einen nicht finalen Entwurf in die angebliche
IST-Basis und leitete daraus eine Kundenhandlung gegen eine andere TA ab.

### Fixvertrag

1. Reportanforderung referenziert einen expliziten mandateigenen Final-Run.
2. Der Run referenziert die exakt dazugehörige TA; kein unabhängiger Current-
   Fallback ist in historischer/finaler Publikation erlaubt.
3. Alle Product-/Exposure-Versionen sind im Holdings-Snapshot eingefroren.
4. API liefert Run-ID, Run-Status, Allocation-ID, Snapshot-ID, Hash und
   Bewertungsstichtag.
5. Race-/Supersession-/Tie-Break-Regeln werden zentral und atomar erzwungen.

## `DEPOT-IST-001` – Fehlendes oder nulles IST wird als SOLL erfunden

### Beobachtung

Der Service verwendet:

```python
current_amount = safe(current_amount_rappen)
if current_amount <= 0:
    current_amount = safe(target_amount_rappen)
```

Das vermischt drei fachlich verschiedene Zustände:

- `None`: Bestand unbekannt;
- `0`: Position nachweislich nicht gehalten;
- negativ/invalid: Domain- oder Modellfehler.

Alle drei werden zu „der Kunde hält genau den Zielbetrag“. Die Bannerlogik
prüft jedoch nur `all(raw is None)`. Zero und Partial bleiben daher
unmarkiert.

### Reproduktion A – expliziter Nullbestand

```json
{
  "stored_current_rappen": 0,
  "stored_target_rappen": 100000000,
  "reported_total_rappen": 100000000,
  "reported_equity_ist_bps": 10000,
  "ist_basiert_auf_soll": false,
  "asset_allocation_verdict": {
    "bewertung": "gruen",
    "beurteilung": "Alle Anlageklassen liegen innerhalb des Toleranzbandes.",
    "handlungsempfehlung": "Keine Massnahme erforderlich."
  }
}
```

### Reproduktion B – teilweise fehlendes IST

```json
{
  "known_current_rappen": 80000000,
  "missing_current": null,
  "reported_total_rappen": 130000000,
  "reported_ist_bps": {"Aktien": 6154, "Obligationen": 3846},
  "ist_basiert_auf_soll": false
}
```

Die 50 Mio. Obligationen sind ausschließlich SOLL, werden aber zum Current-
Total und zu allen IST-Analysen addiert.

### Fixvertrag

- `known_zero`, `known_positive`, `missing`, `invalid` und `stale` bleiben
  getrennte Zustände.
- Target-Werte dürfen nie in ein Feld oder eine Kennzahl mit IST-Semantik
  eingehen.
- Partial Coverage führt zu `unknown/partial`, nicht zu einem falschen Total.
- Ein optionaler What-if-View „IST als SOLL angenommen“ ist klar getrennt,
  nie Default und erzeugt keine Compliance-/Handlungsampel.
- Coverage wird nach Position, Marktwert und Exposure-Dimension publiziert.

## `DEPOT-HOLDING-001` – Zwei konkurrierende Wahrheiten über den aktuellen Bestand

### Beobachtung

`RecommendationHolding` enthält Units, Market Value, Quelle und `as_of_date`.
Die Live-Rebalancing-Pipeline kombiniert diese Daten mit aktuellen Preisen,
Preisqualität, Referenzpreis und FX und kennzeichnet die Valuation-Basis.

Der Depotcheck liest ausschließlich
`RecommendationPosition.current_amount_rappen`. Der tägliche Marktdatenjob
aktualisiert nur Referenzpreisfelder, nicht diesen Betrag. Ohne separaten
Schreibpfad bleibt der angebliche Current-Betrag deshalb historisch, obwohl im
System bereits frischere Holding-/Preis-Evidence liegt.

### Reproduktion

```json
{
  "recommendation_position_current_rappen": 90000000,
  "holding_market_value_rappen": 20000000,
  "depot_check_total_rappen": 90000000,
  "live_rebalancing_total_rappen": 20000000,
  "live_valuation_basis": "implied_from_holding_market_value"
}
```

Beide Werte werden vom selben Repository als heutiges IST verwendet. Der
Kundenbericht nennt weder Quelle noch Stichtag und kann den Unterschied nicht
erklären.

### Fixvertrag

1. Eine kanonische Holdings-Valuation-Pipeline entscheidet je Position über
   Evidence, Units, Preis, FX, Freshness und Valuation-Basis.
2. Depotcheck, Live-Rebalancing, Advisory, API, React und PDF lesen denselben
   immutable Snapshot.
3. Implied-from-target darf nicht als tatsächlicher Bestand gelten.
4. Stale/missing price, FX oder holding as-of ist sichtbar und blockiert
   finalen IST-Verdict nach definierter Policy.
5. Der alte Current-Skalar wird migriert, eindeutig semantisiert oder entfernt.

## `DEPOT-COVERAGE-001` – Unvollständige Positionen verschwinden aus Nenner und Analyse

Die Product-Abfrage filtert nur IDs. Ist ein Product nicht auflösbar, wird die
RecommendationPosition übersprungen. Sind noch andere auflösbare Positionen
vorhanden, greift der Wealth-Fallback nicht. Active- und Deleted-State werden
beim Product-Read ebenfalls nicht geprüft.

Damit können Positionen aus Total und Nenner verschwinden oder deaktivierte
Produkte weiterwirken. Alle verbleibenden Gewichte werden anschließend wieder
auf 100 Prozent normiert. Es gibt keinen `positions_expected`,
`positions_valued`, `market_value_coverage_bps` oder Blocker.

### Fixvertrag

- Jede erwartete Position muss genau einmal aufgelöst und bewertet werden.
- Orphan, deleted, inactive, duplicate und fremde Product-ID sind explizite
  Fail-closed-Fehler.
- Total und Exposure-Nenner bleiben an das vollständige Positionsuniversum
  gebunden; fehlende Werte werden nicht weg-normalisiert.
- Coverage pro Betrag, Position, Preis, FX, TER, Country, Sector, Currency und
  Liquidity wird getrennt ausgewiesen.

## `DEPOT-FX-SCOPE-001` – Wealth-Fallback verliert Mandat und Währung

### Beobachtung

WealthPosition besitzt `client_id` und `currency`, aber keine `mandate_id`.
Der Fallback lädt alle aktiven clientweiten Positionen mit Assignment
„Beratungsvermögen“. Bei mehreren Mandaten desselben Kunden kann dadurch
derselbe Bestand in verschiedene Mandatsreports geraten.

`current_value_rappen` wird ungeachtet der Currency roh addiert. Für
WealthPosition-Fallbacks werden keine Country-/Sector-/Currency-Exposure-Maps
gefüllt. Die Bucket- und Top-Positionsanalyse läuft trotzdem weiter.

### Reproduktion

```json
{
  "raw_chf_rappen": 10000000,
  "raw_usd_rappen": 10000000,
  "reported_total_rappen": 20000000,
  "currency_exposure_bps": {},
  "warnings": ["Top-3-Positionen = 100.0% des Depots (Konzentrations-Risiko)"]
}
```

Eine 1:1-Nominaladdition ersetzt eine Wechselkursumrechnung; gleichzeitig
verschwindet gerade die Information, dass überhaupt USD vorhanden ist.

### Fixvertrag

- Holdings sind explizit einem Mandat/Depot/Account zugeordnet oder besitzen
  einen dokumentierten Allocation-Key.
- Jede Position wird mit zeitgleichem FX-Snapshot in Mandatswährung bewertet.
- Originalcurrency, Originalbetrag, FX-Rate, Quelle, as-of und Zielbetrag
  bleiben nachvollziehbar.
- Ohne FX gibt es kein Total und kein daraus abgeleitetes Verdict.
- Multi-Mandate-/Shared-Account-Regeln werden explizit modelliert und getestet.

## `DEPOT-VERDICT-001` – Ampeln behandeln Surrogate wie bewiesene Kundendaten

`_build_erkenntnisse` erhält nur das berechnete Depotcheck-Dict. Es kennt
weder Run-/Snapshot-ID noch Holding-Coverage, Valuation-Freshness oder die
Fallbackart je Position. Sobald Buckets vorhanden und keine Bandverletzung
berechnet ist, lautet die Asset-Allocation-Ampel grün.

Dieselbe Surrogatbasis treibt Währungsstruktur, Hedge-Vorschlag,
Diversifikation, Branchenkonzentration, Liquidität, Alternative Anlagen und
Gebühren. Der Banner in den drei Diagrammsektionen verändert diese Verdicts
nicht und erscheint in der Erkenntnisse-Tabelle selbst nicht.

### Fixvertrag

- Jeder Verdict erhält `evidence_state`, Snapshot-ID, Coverage, as-of und
  Reason-Codes.
- Fehlend, partial, stale, mixed oder target-implied ergibt
  `nicht_beurteilbar/unknown`, niemals grün.
- Handlungsempfehlungen mit Kundenauswirkung entstehen nur aus
  publikationsfähiger Evidence.
- Banner und Ampel dürfen sich semantisch nicht widersprechen.
- Berater-Textoverride kann fehlende Messdaten nicht in einen bewiesenen
  Status verwandeln.

## `DEPOT-PUBLICATION-001` – Kundenkanäle transportieren keinen vollständigen Datenbasisvertrag

React und PDF zeigen den „IST basiert auf SOLL“-Banner nur anhand des einen
Booleans. Partial-, Zero-, stale-, Holding- und FX-Zustände sind damit nicht
darstellbar. Die Erkenntnisse-Seite zeigt gar keinen Datenbasisstatus.

Der Backend-Payload enthält `mandate_currency`, der TypeScript-Top-Level-
Vertrag nicht. Die React-Positionenseite verwendet `formatChfRappen` an drei
Stellen; dieser Formatter schreibt `CHF` fest. Der PDF-Pfad liest dagegen
`mandate_currency`. EUR-/USD-Mandate können somit unterschiedliche Labels
zeigen.

Die Positionenseite heißt „Übersicht Ihrer Positionen“, während ihr Backend
ausdrücklich SOLL-Empfehlungspositionen liefert. Ein kleiner Hinweis erklärt
dies, aber Run-ID, Status und Stichtag fehlen. Die parallelen IST-
Diagrammsektionen verwenden teilweise dieselben Rows in anderer Semantik.

### Fixvertrag

1. Ein versioniertes `HoldingsValuationSnapshot`-Schema gilt kanalgleich.
2. Evidence-State ist ein discriminated union, kein Boolean.
3. Run, TA, valuation as-of, Currency, Coverage und Hash sind sichtbar und
   maschinenlesbar.
4. React erhält Currency als Feld und verwendet einen generischen
   Money-Formatter.
5. SOLL-Positionen und IST-Holdings sind getrennte Views und Datenmodelle.
6. Cross-Channel-Golden-Tests vergleichen Werte, Labels, Status und Blocker.

## Zielbild: kanonischer `HoldingsValuationSnapshot`

Mindestens folgende Felder sind erforderlich:

### Identität und Context

- `snapshot_id`, `schema_version`, `context_hash`
- `tenant_id`, `client_id`, `mandate_id`, Depot-/Account-ID
- `recommendation_run_id`, Run-Status und Run-Hash
- `target_allocation_id` und Allocation-Hash
- `valuation_as_of`, `generated_at`, Actor/System-Quelle

### Positionsevidence

- Position-/Holding-/Product-ID
- Evidence-State: known-zero, known-positive, missing, invalid, stale
- Originalamount und Originalcurrency
- Units und Holding-as-of
- Preis, Preisdatum, Quelle und Freshness
- FX-Rate, Quelle, Datum und Conversion-Pfad
- Market Value in Mandatswährung
- Valuation-Basis ohne implied-target als Ist-Nachweis

### Coverage und Ergebnis

- erwartete, geladene, bewertete und fehlende Positionen
- Market-Value-Coverage als Zähler/Nenner
- Coverage je Exposure-/Liquidity-/Fee-Dimension
- reconciliertes Total in Mandatswährung
- IST-Buckets und getrennte SOLL-Buckets
- Drift nur bei vollständigem kompatiblem Context
- Verdict-Evidence-State und Reason-Codes
- `publication_ready`

Der Snapshot ist immutable. Preis-, FX-, Holding- oder Run-Änderung erzeugt
eine neue Version; historische Kundenberichte referenzieren weiterhin ihren
exakten Hash.

## Verbindliche Testmatrix

### Current-State-Domain

Für einzelne und gemischte Portfolios:

1. Current positiv;
2. Current exakt null;
3. Current `None`;
4. Current negativ/malformed aus Legacydaten;
5. alle missing;
6. teilweise missing;
7. teilweise zero;
8. Current vorhanden, aber stale;
9. Target null/positiv;
10. Current und Target widersprechen.

Kein Fall darf Target still als Current übernehmen.

### Run-/TA-Context

1. älterer Final plus neuerer Draft;
2. Superseded plus Final;
3. Run ohne TA;
4. Run mit fremder/gelöschter TA;
5. Current-TA wechselt nach Run;
6. gleiche `created_at` mit Tie-Break;
7. Concurrent Run-/TA-Finalisierung;
8. Replay desselben Snapshot-Hashs.

### Holdings und Valuation

1. Units plus frischer Preis;
2. Market Value ohne Units;
3. RecommendationPosition-Skalar widerspricht Holding;
4. mehrere Holding-Versionen/as-of;
5. fehlender Preis;
6. stale/future Preis;
7. fehlendes oder ungültiges FX;
8. Originalcurrency entspricht Mandatswährung;
9. Cross-Currency;
10. Preisrefresh ändert neuen Snapshot, nicht historischen.

### Scope und Coverage

1. zwei Mandate desselben Clients;
2. zwei Depots/Accounts;
3. orphan Product;
4. deleted/inactive Product;
5. teilweise Product-Auflösung;
6. Position ohne Exposure;
7. Wealth-Fallback in mehreren Währungen;
8. Coverage darf nie durch Weglassen auf 100 Prozent steigen.

### Verdict und Kanäle

Für API, React, Advisory-PDF und Depotcheck-PDF jeweils:

- complete/partial/missing/stale/invalid/mixed;
- known-zero;
- Run-/TA-Mismatch;
- CHF/EUR/USD;
- identische Total-, Bucket-, Exposure-, Drift- und Verdictwerte;
- identische Reason-Codes und sichtbare Blocker;
- kein Grün bei nicht publikationsfähiger Evidence;
- kein CHF-Hardcode außerhalb eines CHF-Snapshots.

### Zielumgebung

- SQLite bleibt schneller Logikgate.
- PostgreSQL ist Pflicht für Isolation, FK, Tenant/RLS, Concurrency und
  immutable Snapshot-Constraints.
- Native Electron-/PDF-Artefakte sind Pflicht für sichtbare Currency-, Banner-
  und Verdict-Parität.
- Custodian-/Holding-/Price-/FX-Replay ist mit realitätsnahen Stichtagen zu
  testen.

## Empfohlene Umsetzungsreihenfolge

### Phase A – Sofortige Publikationssperre

1. Target-as-Current-Fallback aus finaler Publikation entfernen.
2. Zero/Partial/Missing/Stale als unknown blockieren.
3. Draft-/Superseded-Run als Reportbasis ablehnen.
4. Verdicts ohne vollständige Evidence auf nicht beurteilbar setzen.

### Phase B – Eine Holdings-Wahrheit

1. `HoldingsValuationSnapshot` modellieren.
2. RecommendationHolding, Prices und FX zentral auflösen.
3. RecommendationPosition-Current-Skalar migrieren.
4. Run/TA/Product/Holding/Account/Tenant relational binden.
5. Coverage und Reconciliation implementieren.

### Phase C – Consumer migrieren

1. Depotcheck auf Snapshot umstellen.
2. Advisory-Sektionen und Erkenntnisse aus demselben Snapshot ableiten.
3. Live-Rebalancing auf denselben Snapshotvertrag bringen.
4. API/OpenAPI/TypeScript angleichen.
5. React und PDFs kanalgleich rendern.

### Phase D – Beweis

1. gesamte Testmatrix umsetzen;
2. PostgreSQL-/RLS-/Race-Gates;
3. native Electron-/PDF-Golden-Gates;
4. Holding-/Price-/FX-Replay und Restore;
5. Fach-, Compliance-, Security- und UX-Abnahme.

## Definition of Done

- [ ] Kein Target-Wert wird still als Current-Bestand verwendet.
- [ ] Zero, Missing, Invalid und Stale sind getrennte Zustände.
- [ ] Partial Coverage blockiert Total-/Drift-/Verdict-Publikation nach klarer
      Policy.
- [ ] Nur expliziter Final-Run und seine gebundene TA bilden den Context.
- [ ] RecommendationHolding, Units, Preise, FX und as-of bilden die einzige
      IST-Wahrheit.
- [ ] Depotcheck und Live-Rebalancing liefern denselben Snapshot-Hash und
      Current-Market-Value.
- [ ] Wealth-/Holding-Scope ist mandat-/account-/tenantgebunden.
- [ ] Multi-Currency wird evidenzgebunden umgerechnet, nie nominal addiert.
- [ ] Orphan/deleted/inactive Products sind sichtbare Blocker.
- [ ] Coverage-Nenner bleibt vollständig und wird nicht weg-normalisiert.
- [ ] Kein Verdict ist grün bei missing, partial, stale, mixed oder invalid.
- [ ] API, React und beide PDFs zeigen identischen Context, Betrag, Currency,
      Status und Reason-Code.
- [ ] React besitzt keinen CHF-Hardcode für mandatvariable Beträge.
- [ ] Historischer Replay bleibt hashidentisch.
- [ ] PostgreSQL-, RLS-, Concurrency-, Electron- und PDF-Gates sind auf der
      Zielumgebung grün.
- [ ] Der Altbefund vom 25. Mai ist mit Zero-/Partial-/Holding-Regressionen
      tatsächlich geschlossen, nicht nur mit einem Banner.

## Claude-/GPT-Startcheckliste

Vor Änderungen an Depotcheck, RecommendationPositions, Holdings, Prices, FX,
Advisory-Sektionen, Erkenntnissen, React oder PDFs:

1. Diesen Audit vollständig lesen.
2. Den Mai-Altbefund und die oben referenzierten Produkt-/Preis-/Snapshot-
   Audits mitlesen.
3. Zuerst Run, TA, Holding-Snapshot und Valuation-as-of benennen.
4. Niemals Target als Current defaulten.
5. Zero nicht als Missing und Missing nicht als Zero behandeln.
6. Keine Position aus Nenner oder Coverage still entfernen.
7. Keine Currency-Beträge ohne FX-/Originalcurrency-Nachweis addieren.
8. Kein Grün und keine Kundenhandlung aus Partial-/Unknown-Evidence ableiten.
9. API, React, Advisory-PDF und Depotcheck-PDF gemeinsam testen.
10. ACL-unlesbare `.pytest_tmp*`-Verzeichnisse weder betreten noch bereinigen.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

- Branch: `codex/asset-allocation-stochastic-core`
- auditierter Head: `08993953e4f8abd34f28d8ae3adf9fb2e87ec9be`
- sichtbare tracked/untracked Änderungen: `0`
- bekannte ACL-unlesbare pytest-Tempverzeichnisse: `53`
- globale Clean-Aussage: ausdrücklich **nein**
- Produktcode verändert: **nein**
- Tests verändert: **nein**

Temporäre Reproduktionsskripte lagen ausschließlich unter `C:\tmp`, wurden
nach Ausführung entfernt und gehörten nie zum Repository. Die ACL-unlesbaren
Verzeichnisse wurden nicht betreten, verändert oder bereinigt.

### Fokussierter Backend-Gate

Ausgeführt aus `5eyes-backend` mit externem Basetemp:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp C:\tmp\5eyes-depot-ist-audit-20260903 `
  tests/test_depot_check.py `
  tests/test_advisory_report.py `
  tests/test_advisory_report_pdf.py `
  tests/test_reporting_api_and_cover.py `
  tests/test_daily_market_data_refresh.py `
  tests/test_live_rebalancing_fx_conversion.py `
  tests/test_depot_illiquid_classification.py
```

Ergebnis:

```text
222 passed, 61 warnings in 76.14s
```

Die 61 Warnungen sind DeprecationWarnings für `datetime.utcnow()` im
Asset-Class-Price-Backfill. Sie erklären oder schließen keines der Findings.

### Fokussierter Frontend-Gate

```powershell
npm.cmd test -- --run `
  src/pages/sections.test.tsx `
  src/api/client.test.ts `
  src/App.a11y.test.tsx `
  src/components/Sidebar.a11y.test.tsx
```

Ergebnis:

```text
Test Files  4 passed (4)
Tests       69 passed (69)
Duration    21.25s
```

Es erschienen nur die bekannten Vite-Hinweise zur esbuild-/oxc-
Konfiguration.

### Letzter vollständiger Backend-Gate

Der letzte dokumentierte vollständige Backend-Gate gehört weiterhin zum
Implementierungscommit `661fe73c`:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed
```

Kontrollrunde 22 hat den Vollgate nicht erneut ausgeführt.

### Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen zum Dokumentationscommit gehören:

1. `docs/audits/2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit wird reproduzierbar aufgelöst mit:

```powershell
git log -1 --format=%H -- docs/audits/2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md
```
