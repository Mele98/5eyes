# Sprint U-35 Modul-Split-Plan fuer 5eyes_v2.html

Stand: 2026-06-02
Scope: Vorarbeit fuer den spaeteren Monolith-Refactor, keine Aufspaltung in
diesem Sprint.

## 1. Ausgangslage

`5eyes-electron/frontend/5eyes_v2.html` ist ein historisch gewachsener
Single-File-Frontend-Monolith. Er enthaelt DOM, Styles, Inline-Handler,
Modale, Admin-Panels, PDF-Download-Mechanik, Backtests und fachliche
Workflow-Logik in einer Datei.

Vor einem Modul-Split braucht es eine deterministische Sicherheitslinie:

- aktuelles DOM-Inventar
- aktuelle Inline-Handler
- aktuelle JS-Funktionsnamen
- aktuelle CSS-Selektoren
- aktuelle Modale
- aktuelle Sub-Sections

Diese Sicherheitslinie liegt jetzt in:

- `docs/audits/2026-06-02-monolith-inventory.json`
- `5eyes-backend/tests/test_monolith_inventory_stable.py`
- `scripts/audit_html_monolith.py`

## 2. Refactor-Prinzip

Der Split darf nur ueber kleine, einzeln gruen testbare PRs laufen.
Jede PR muss eine von zwei Aussagen treffen:

1. "Kein Inventar-Drift": Snapshot bleibt identisch.
2. "Bewusster Inventar-Drift": Snapshot wird aktualisiert und die Aenderung
   wird im PR-Body begruendet.

Der erste echte Split darf keine Fachlogik aendern. Er darf nur Code
verschieben und explizite Imports/Exports schaffen.

## 3. Vorgeschlagene Module

### Modul A: Shell, Navigation und Client-Auswahl

Inhalt:
- Topbar
- Sidebar
- Client-Liste
- Hauptnavigation
- globale Layout-Initialisierung

Begruendung:
Die Shell ist querliegend, aber fachlich relativ flach. Sie eignet sich als
erster Split, weil sie hohe Sichtbarkeit hat, ohne Portfolio- oder FINMA-Logik
zu beruehren.

Risiko: mittel
Haupt-Gates: IDs der Navigation, Client-Auswahl, aktiver Step, App-Notice.

### Modul B: Vermoegen, Cashflow und Ziele

Inhalt:
- Vermoegensrubrik
- Cashflow-Editor
- Ziel-Editor
- Ziel-/Cashflow-Validierung in der UI

Begruendung:
Diese Sektionen sind visuell und fachlich eng gekoppelt. Sie sollten zusammen
ausgelagert werden, damit Ziele, Renditebedarf und Cashflow nicht auseinander
driften.

Risiko: hoch
Haupt-Gates: Zieltypen, Pflichtfelder, Feld-Isolation, Cashflow-Defaults.

### Modul C: Risikoprofil und Kenntnisse/Erfahrungen

Inhalt:
- Risikoprofil-Fragebogen
- Kenntnisse und Erfahrungen
- Override-UI
- Risiko-PDF-/Print-Aktionen

Begruendung:
FINMA/FIDLEG-relevant. Dieser Block braucht eigene Tests und darf nicht
parallel mit Asset-Allocation-Logik umgebaut werden.

Risiko: sehr hoch
Haupt-Gates: alle Fragen, Antworten, Override-Begruendung, Kenntnisse-Daten.

### Modul D: Asset Allocation, Strategie und Backtests

Inhalt:
- Asset-Allocation-Hauptseite
- Strategie berechnen
- Anlagepraeferenzen
- Daily/Annual Backtest
- A/B-Policy-Backtest
- Shadow-/Stochastic-Anzeigen, soweit im Monolith vorhanden

Begruendung:
Groesster fachlicher Block. Erst splitten, wenn A-C stabil sind und Snapshot-
Gates bewaehrt funktionieren.

Risiko: sehr hoch
Haupt-Gates: Risiko-Cap, Zielerreichung, Produktpraeferenzen, PDF-Download,
Backtest-Parameter.

### Modul E: Portfolio-Umsetzung und Produkte

Inhalt:
- Portfolio-Empfehlungen
- Produktlisten
- Umsetzungshinweise
- ISIN-/Produktdatenanzeige
- Portfolio-PDF

Begruendung:
Produkt- und TA-Konsistenz ist kritisch. Dieser Block sollte getrennt von der
Strategie-Generierung ausgelagert werden, damit stale RecommendationRuns nicht
versteckt werden.

Risiko: hoch
Haupt-Gates: TargetAllocation-ID, RecommendationRun-ID, Produktgruppen,
ISIN/TER/Waehrung.

### Modul F: Admin, Datenpipeline und Systempanels

Inhalt:
- Admin-Modal
- Market-Data-Panels
- Annual/Daily Backfill
- Shadow-Aggregat
- Optimizer-Mode-/System-Endpunkte

Begruendung:
Admin ist technisch breit, aber customer-facing weniger sensibel. Der Split
soll vorhandene Admin-Klassen erhalten und keine neuen Inline-Styles einfuehren.

Risiko: mittel
Haupt-Gates: Panel-IDs, Reload-Buttons, Endpoint-URLs, keine verbotenen Phrasen.

### Modul G: PDF, Print und Download-Helfer

Inhalt:
- PDF-Download-Helfer
- Print-Buttons
- Loading-/Timeout-Zustaende
- Report-/Einzel-PDF-Routing

Begruendung:
PDF-Mechanik ist querliegend und wird in vielen Sektionen aufgerufen. Als
separates Modul reduziert es Wiederholung, darf aber keine Dokumentinhalte
veraendern.

Risiko: mittel-hoch
Haupt-Gates: Timeout, Base-URL, Fehlermeldungen, rubrikreine Einzel-PDFs.

## 4. Reihenfolge der Auslagerung

1. Modul A: Shell/Navigation
2. Modul F: Admin/Systempanels
3. Modul G: PDF/Print/Download-Helfer
4. Modul B: Vermoegen/Cashflow/Ziele
5. Modul C: Risikoprofil/Kenntnisse/Erfahrungen
6. Modul E: Portfolio/Produkte
7. Modul D: Asset Allocation/Strategie/Backtests

Warum diese Reihenfolge:
- Erst technisch sichtbare, aber fachlich weniger tiefe Flaechen.
- Danach PDF/Print als Querfunktion stabilisieren.
- FINMA- und Asset-Allocation-Bloecke erst splitten, wenn die Snapshot-
  Mechanik in mehreren PRs bewiesen ist.

## 5. Akzeptanz-Gates pro Split-PR

Jede Split-PR muss mindestens:

- `python scripts/audit_html_monolith.py` ausfuehren, wenn der Monolith noch
  existiert oder bewusst veraendert wird.
- `python -m pytest -p no:cacheprovider tests/test_monolith_inventory_stable.py -q`
  gruen haben oder den Snapshot bewusst aktualisieren.
- Keine neuen Inline-Styles in Admin-/Kundenflaechen einfuehren.
- Keine sichtbaren Kundentexte mit Garantien oder Renditeversprechen erzeugen.
- Keine Asset-Allocation-Fachlogik veraendern, ausser der PR ist genau dafuer
  spezifiziert.

## 6. Risiken

| Risiko | Auswirkung | Gegenmassnahme |
|---|---|---|
| Inline-Handler verlieren Binding | Buttons wirken tot | Event-Handler-Inventar + gezielte Smoke-Tests |
| ID-Drift bricht bestehende JS-Selektoren | UI-Bereiche laden nicht | ID-Snapshot bleibt Gate |
| CSS-Selektor-Drift veraendert Layout | visuelle Regression | CSS-Snapshot + Playwright-Screenshots je Modul |
| Modal-Struktur driftet | Dialoge oeffnen/schliessen falsch | Modal-Inventar + manuelle Smoke-Liste |
| Asset-Allocation-Vertrag bricht | falsche Strategie/Produkte | Modul D erst spaet, separate Fachtests |
| FINMA-Text/Print bricht | Compliance-Risiko | Modul C/G separat und mit PDF-Tests |

## 7. Nicht in U-35

- keine echte Aufspaltung
- keine Bundle-Optimierung
- keine TypeScript-Migration
- keine neue UI
- keine fachliche Aenderung an Portfolio, Risiko, Ziele oder Admin

## 8. Naechster Sprint nach U-35

Empfohlen: Modul A als kleinster echter Split.

Ziel fuer den ersten Split:
- Shell-/Navigation-Code aus `5eyes_v2.html` auslagern
- Monolith laedt das Modul weiter deterministisch
- Inventar-Snapshot bleibt unveraendert oder nur bewusst begruendet veraendert
- Ein Browser-Smoke prueft: App startet, Navigation klickbar, aktive Sektion
  bleibt korrekt
