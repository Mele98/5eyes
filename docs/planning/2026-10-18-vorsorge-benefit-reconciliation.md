# Vorsorge: Fortschreibung, Bezug und Benefit-Reconciliation (Konzept)

Stand 2026-10-18 · Bezug: PR `fix/vorsorge-exposure-mapping` (VORSORGE-PROJECTION-001),
PENSION-AVAILABILITY-001 („Phase 1 Benefit-Reconciliation fehlt").

Dieses Dokument beschreibt, was der PR umsetzt (Phase 0.5), und wie ein vollständiger
automatischer Bezug (Kapital / Rente / Gemischt) modelliert würde. Für Phase 1 ist es
nur ein Konzept: Ab Abschnitt 3 ist nichts davon implementiert.

## 1. Fachentscheid (User, 2026-10-18)

Vorsorgegelder werden **nicht verwaltet**, sondern wie in der klassischen Finanzplanung
deterministisch fortgeschrieben. Die Software rät weder eine Anlageklassen-Aufteilung
(früher pauschal 45 % Aktien / 45 % Obligationen / 10 % Liquidität), noch schätzt sie eine
Aktienexposure.

| Vorsorgeart | Fortschreibung (nominal p.a.) | Bezug in Phase 0.5 |
|---|---|---|
| 3a-Konto, Freizügigkeitskonto | erfasster Zins, Default **0 %** | automatisch als Kapital, nach pauschaler Kapitalbezugssteuer |
| 3a-/FZ-Wertschriften (Depot) | erfasste Rendite, Default **3 %** | automatisch als Kapital, nach pauschaler Kapitalbezugssteuer |
| Police (3a/3b, Lebensversicherung) | Rückkaufswert heute → **garantierter Ablaufwert** bei Fälligkeit (geometrisch interpoliert); ohne Ablaufwert: Satz, Default 0 % | automatisch bei Fälligkeit (3b/LV ohne Kapitalbezugssteuer) |
| BVG / Pensionskasse | erfasster Zins, Default **0 %** | **kein** automatischer Bezug: Kapitalbezug als verknüpften Vermögenszufluss erfassen; Rente siehe Abschnitt 3 |

Die Defaults 0 % / 3 % sind ein User-Entscheid und liegen als benannte, versionierte
Konstanten in `services/portfolio_engine_pension_positions.py`
(`PENSION_PROJECTION_ASSUMPTIONS_VERSION = "vorsorge-projektion-2026-10-18"`). Ein Satz pro
Position überschreibt den Default (`pension_interest_rate_bps`).

## 2. Was Phase 0.5 umsetzt

### 2.1 Eigene Kategorie statt geratener Anlageklassen

- Externe Vorsorge (`position_type='Vorsorge'`, `assignment='Anderes Vermögen'`, aktiv) steht in
  `PortfolioSummary.pension_bound_rappen`. Sie ist in `total_rappen` enthalten, wird aber **nicht**
  auf `amounts_rappen` verteilt.
- Exposure-Tilts (`_apply_external_exposure_tilts`) rechnen Zähler und Nenner ohne gebundene
  Vorsorge. Ausnahme: Hat der Berater bewusst eine vollständige Aufteilung erfasst
  (`alloc_*_bps` = 10000), zählt diese im Tilt mit. Fortgeschrieben wird die Position trotzdem
  deterministisch.
- Die Gesamtvermögens-Darstellung (`total_allocation`) zeigt eine Zeile
  „Vorsorge (gebunden)" als fixen Block, der in IST und SOLL identisch ist und nie umgeschichtet
  wird. Die Summen bleiben exakt (Beträge = `total_base_rappen`, Gewichte = 10'000 bps). Gibt es
  keine Vorsorge, bleibt die Ausgabe byte-identisch.
- Vorsorge im **Beratungsvermögen** (vom Berater bewusst als verwaltet erfasst) bleibt im
  Bucket-Modell (erfasste Aufteilung bzw. bisheriger gemischter Default). Siehe Abschnitt 5.

### 2.2 Deterministische Serie und Bezug

`_build_external_foundation_projection` liefert zusätzlich, nur wenn externe Vorsorge existiert:

- `pension_series_rappen` (Länge H+1): Wert aller externen Vorsorge-Positionen bis zum Bezug, danach 0.
- `pension_payout_series_rappen` (Länge H): Netto-Bezüge, die der Loader in den Cashflow-Pfad
  addiert (wie ein Vermögenszufluss).

Index-Konvention (wie `_simulate_bucket_path`): `Serie[t]` ist der Wert nach t Jahren. `cashflow[k]`
(Kalenderjahr `start_year + k`) wirkt auf `Serie[k+1]`. Ein Bezug im Offset k entnimmt
`Wert[k+1]`, und die Position ist ab Index k+1 null. Damit ist der Bezug im Gesamtvermögen
neutral bis auf die Steuer und wird genau einmal freies Vermögen.

Konsumenten: MC-Total-Pfade (deterministisch addiert wie Direktimmobilie bzw. verpfändetes
3a-Guthaben), `_build_external_goal_funding_series` (Gesamtvermögens-Ziele im Optimizer; die
Vorsorge läuft dort nicht mehr in der CPI-Basis) und der Reserve-Pfad (über
`inflow_projection_series_rappen`).

Das Bezugsjahr wird in dieser Reihenfolge bestimmt: Police-Fälligkeit, dann „Verfügbar ab"
(`liquidity_available_from`, im Monolith bisher nur als Notiz gespeichert, jetzt echtes Feld),
dann `mandate.client_birth_year + pension_retirement_age`, dann `mandate.retirement_year`. Fehlt
alles, bleibt die Position gebunden, und das Reasoning weist darauf hin. Liegt das Bezugsjahr in
der Vergangenheit, erfolgt der Bezug im ersten Projektionsjahr.

### 2.3 Doppelzählung (Befund mit Zahlen)

develop (d3c9a67), CMA 0 %, Beratungsvermögen 100'000, BVG 300'000, vom Berater erfasster
Kapitalbezug 300'000 im Offset 2:

| Pfad | develop | korrekt |
|---|---|---|
| Total-Pfad | 400k, 400k, 400k, **700k**, 700k, 700k | 400k × 6 |
| `external_goal_funding_series` | 300k × 6 (neben dem Zufluss im Beratungspfad) | 300k, 300k, 300k, 0, 0, 0 |

Fix: `WealthInflow.linked_position_id`. Ein verknüpfter Zufluss **ist** der Bezug. Der
automatische Bezug entfällt, und die Position wird ab dem Jahr des Zuflusses ausgebucht. Die API
validiert, dass nur auf eine aktive externe Vorsorge-Position desselben Kunden verknüpft wird.
Ein nicht verknüpfter Zufluss im selben Jahr wie ein automatischer Bezug, der nach einem
Vorsorgebezug aussieht (`source_type='Saeule3b'` oder Stichworte wie 3a/PK/BVG/Police), wird als
„Möglicher Doppelbezug" gemeldet und nicht still entfernt.

### 2.4 Kapitalbezugssteuer (User-Entscheid 2026-10-18)

Das pauschale Steuermodul (`TaxRegime.pension_lumpsum_tax`, CH-Light 6 %) wird für den
Vorsorgebezug **nicht** verwendet, und es gibt keine Abhängigkeit vom Steuerdomizil des Mandats.
Pro Vorsorge-Position gilt:

1. Erfasster Betrag `pension_lumpsum_tax_rappen` aus dem Steuerrechner des Kantons. Er hat Vorrang
   und wird höchstens bis zum Bruttobezug abgezogen.
2. Sonst ein erfasster Satz `pension_lumpsum_tax_bps`.
3. Sonst der defensive Default `PENSION_LUMPSUM_TAX_DEFAULT_BPS = 1000` (10 %) für 3a,
   Freizügigkeit und BVG-Kapital. Policen der Säule 3b bzw. Lebensversicherungen bleiben bei 0 %.

Das Reasoning weist aus, ob der Wert erfasst ist oder ob der Default gilt
(„Kapitalbezugssteuer CHF X (erfasst)" bzw. „(Default 10 %, defensiv)").

## 3. Phase 1: automatischer BVG-Bezug (nur Konzept)

### 3.1 Altersguthaben bis zur Pensionierung

```
AG(t+1) = AG(t) · (1 + z_t) + AGS(t)
AGS(t)  = koordinierter Lohn(t) · s(Alter_t)          (obligatorisch)
```

- `z_t`: BVG-Mindestzins (obligatorisch) bzw. der von der Pensionskasse gutgeschriebene Zins
  (umhüllende Kassen). Heute pflegt der Berater ihn als einen Satz pro Position.
- `s(Alter)`: Altersgutschriften-Sätze nach BVG (Altersstufen). Überobligatorische Beiträge sind
  reglementarisch.
- Die Beiträge sind bereits im Netto-Lohn-Cashflow abgezogen. Sie dürfen nicht nochmals als
  Ausgabe erscheinen, sondern nur als Zuwachs des Altersguthabens. Sonst entsteht eine neue
  Doppelzählung bzw. ein Verlust.
- Alternative ohne Lohn-Modell: die projizierte Altersleistung aus dem PK-Ausweis
  („voraussichtliches Altersguthaben mit Zins") als Zielwert übernehmen und, wie bei der Police,
  geometrisch interpolieren. Das ist robuster und verlangt keine Lohnannahmen.

### 3.2 Bezugsform ab Bezugsalter

- **Kapital:** wie Phase 0.5, also `Wert[k+1]` abzüglich der erfassten bzw. Default-Kapitalbezugssteuer als Zufluss.
- **Rente:** `R = AG(Pensionierung) · UWS`, als wiederkehrender Einkommens-Cashflow ab dem
  Bezugsjahr. Das Altersguthaben verlässt das Gesamtvermögen im Bezugsjahr ohne Zufluss (es wird
  in die Rente umgewandelt). Die Rente ist **voll einkommenssteuerpflichtig**, die
  Teuerungsanpassung ist reglementarisch (meist keine). Hier lässt sich
  `PlanningAssumption.pension_indexation_bps` verwenden.
- **Gemischt:** Kapitalquote q. Dann gilt Kapital = q · AG (mit Steuer) und Rente =
  (1 − q) · AG · UWS.
- Hinterlassenen- und Invalidenleistungen werden nicht modelliert und brauchen einen eigenen
  Szenario-Ansatz.
- Damit eine vom Berater zusätzlich erfasste Rente nicht doppelt zählt, braucht ein
  Einkommens-Cashflow „BVG-Rente" dieselbe Verknüpfung wie der Zufluss (`linked_position_id` auf
  Cashflow). Ist er verknüpft, ersetzt er die automatische Rente.

### 3.3 Verfügbarkeit (PENSION-AVAILABILITY-001 Phase 1)

Der Schloss-Pool (`unlocked_other_assets_rappen`) bleibt unverändert fail-safe. Mit aufgelöstem
Bezugsjahr könnte er künftig pro Jahr statt nur „heute" bewertet werden. Dafür bräuchte die
Reserve-Logik eine zeitabhängige Verfügbarkeit.

### 3.4 Weitere Lücken

- Positionen haben keinen Eigentümer (Kunde/Partner). Für das Rentenalter wird das Geburtsjahr
  der Hauptperson verwendet. Für Paare braucht es ein Eigentümer-Feld an der Position.
- WEF-Vorbezug (`pension_wef_possible`) wird nicht modelliert.
- Gestaffelter 3a-Bezug (Steueroptimierung über mehrere Jahre) wird nicht modelliert. Heute ist
  pro Position genau ein Bezugsjahr möglich. Mehrere Konten sind mehrere Positionen.
- Die Cashflow-Projektion des Endpoints `/clients/{id}/cashflow-projection` und die
  Frontend-Vorschau zeigen die automatischen Bezüge noch nicht. Die Vorschau schreibt externe
  Vorsorge mit demselben Satz fort, verteilt sie aber nicht auf Anlageklassen.

## 4. Data-Owner-Werte (nötig für Phase 1, nicht erfinden)

| Wert | Quelle / Owner | Heute |
|---|---|---|
| BVG-Mindestzins pro Jahr | Bundesrat, jährlich | nicht hinterlegt; Satz pro Position, Default 0 % |
| Umwandlungssatz obligatorisch / umhüllend | BVG bzw. Reglement der Pensionskasse | nicht hinterlegt; pro Position erfassen (neues Feld) |
| Altersgutschriften-Sätze, Koordinationsabzug, Eintrittsschwelle | BVG | nicht hinterlegt |
| Referenzalter AHV/BVG | AHVG/BVG | nur `mandate.retirement_year` / `pension_retirement_age` |
| 3a-Bezugsfenster | BVV 3 | nicht modelliert |
| Kapitalleistungssteuer-Tarif je Kanton/Gemeinde, Zivilstand | Steuer-Owner | pro Position erfasst (Steuerrechner); Default defensiv 10 % (User-Entscheid) |
| Einkommenssteuer auf Renten | Steuer-Owner | `dividend/interest_tax_bps` als Näherung, nicht verdrahtet |
| Indexierung BVG-Renten | Reglement | `pension_indexation_bps` (PlanningAssumption) |
| Default-Sätze 0 % (Konto/BVG/Police), 3 % (Wertschriften), 10 % Kapitalbezugssteuer | **User-Entscheid 2026-10-18** | Konstanten, versioniert |

## 5. Idee: Vorsorge als verwaltetes Mandat (Anlagestiftung)

Wenn eine Anlage- oder Vorsorgestiftung die Software nutzt, ist Vorsorgevermögen nicht
„gebunden und fortgeschrieben", sondern **das verwaltete Vermögen selbst**. Skizze:

- Eigener Mandatstyp (z. B. `mandate_type='Vorsorge'`) wird von Anfang an als verwaltetes Mandat
  erfasst (Beratungsvermögen = Vorsorgekapital).
- Die Anlagegrenzen nach BVV 2 (Art. 53 ff.: Kategorienlimiten für Aktien, Immobilien,
  alternative Anlagen, Fremdwährungen ohne Absicherung, Einzelschuldner) werden als harte
  Bandbreiten anstelle bzw. zusätzlich zur Hausmatrix geführt. Die Erweiterungsbegründung nach
  Art. 50 Abs. 4 BVV 2 ist als dokumentierter Override nötig.
- Kein Exposure-Tilt gegen ein „Gesamtvermögen" der versicherten Person, denn die Stiftung
  verwaltet ein Kollektiv bzw. eine Freizügigkeitslösung, keinen Haushalt.
- Ziele: Leistungsversprechen bzw. Zielrendite gegenüber BVG-Mindestzins und Umwandlungssatz
  statt Konsumziele. Das passt zur bestehenden Zielfamilie „Rendite".
- Datenmodell: die Vorsorge-Position eines Haushalts könnte auf ein solches Mandat verweisen.
  Dann ist sie nicht „gebunden", sondern Teil eines anderen, verwalteten Mandats, und die
  Gesamtvermögens-Sicht des Haushalts zeigt dessen SOLL.

## 6. Transfer-Ledger und Guards (PENSION-TRANSFER-LEDGER-001, 2026-10-19)

Folgefix zum Codex-Review von PR #642
(`docs/audits/2026-10-18-vorsorge-transfer-ledger-pr642-current-review.md` auf dem Codex-Branch).

**Ledger.** `services/pension_transfer_ledger.py::PensionTransferLedgerV1` hält pro Quelle mit Bezug
eine Zeile: Quelle, Herkunft (`linked_inflow` | `auto`), Bezugsjahr, Eröffnungs-Bestand, Brutto
(fortgeschriebener Wert im Bezugsjahr), Kapitalbezugssteuer und deren Quelle (erfasst CHF / erfasst %
/ Default), Netto ins freie Vermögen, Restbestand (0), Zielwährung und FX-Basis, Bewertungsjahr,
Policy-Version und SHA-256-Hash. Invariante: Brutto = Steuer + Netto (auf den Rappen), Restbestand 0.
Die Netto-Serie des Ledgers ist die einzige Basis für die Vorsorge-Zuflüsse im Engine-Pfad. Den frei
erfassten Betrag eines verknüpften Zuflusses ersetzt sie; der Zufluss bestimmt nur das Jahr. Die
Reasoning-Sätze werden aus den Zeilen formuliert. Weicht der erfasste Betrag ab, gibt es einen Hinweis.

**Horizont.** Ein aktiver Link hat immer Vorrang vor der Auto-Regel. Liegt er hinter dem Horizont,
bleibt die Quelle bis Horizontende gebunden, und es gibt keinen früheren Auto-Bezug. Ledger-Zeilen und
Hash hängen nicht vom Horizont ab, nur `within_horizon` ändert sich.

**Fail-closed.** Die API antwortet so:
- Deaktivieren, Löschen oder Umklassifizieren der Quelle bei aktivem Link: 409 `PENSION_SOURCE_LINKED`.
- Verknüpfter Zufluss, der wiederkehrend oder real ist: 422.
- Zweiter aktiver Link auf dieselbe Quelle: 422 `PENSION_SOURCE_ALREADY_LINKED`. Abgesichert ist das
  zusätzlich durch den partiellen Unique-Index `ux_wealth_inflow_one_active_pension_link`, und zwar im
  Model (Bootstrap), im SQLite-Runtime-Patch und in Alembic `a6d2e8f4c1b9`.

Die Engine meldet für Bestandsdaten `PensionTransferLedgerError` bei Orphan-Link, Mehrfach-Link,
Raten- oder Real-Link und bei einem Link vor dem Bewertungsjahr.

**Bewusst nicht umgesetzt:**
- **Teil- und Ratenbezug.** Das bräuchte einen persistierten Restbestand je Rate, also
  `transfer_mode='partial'`, mit Summe der Bruttoentnahmen plus Schlussbestand ≤ fortgeschriebener
  Kapitalstock. Bis dahin lehnen API und Engine solche Links ab, statt die Checks zu lockern.
- **Echter FK mit RESTRICT auf `linked_position_id`.** Das scheitert an Soft-Delete. Ersatz sind die
  symmetrischen Router-Guards und der Engine-Orphan-Check.
- **Ledger im API-Payload und PDF.** Die Dateien sind durch parallele PRs belegt. Gebunden ist der
  Ledger trotzdem, und zwar über die Foundation-Serien im Projection-Context-Hash.
- **Cashflow-Tab (`routers/clients.py`) und Reserve-Neuberechnung im Advisory-Report.** Beide nutzen
  noch die Roh-Zuflüsse und kennen auch den Auto-Bezug nicht. Das ist ein Folgepunkt.
