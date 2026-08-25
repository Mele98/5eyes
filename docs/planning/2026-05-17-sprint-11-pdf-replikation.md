# Sprint 11 — PDF-Replikation: Server-PDF an Frontend-Vorlage anpassen

**Datum:** 2026-05-17 (Nacht)
**Status:** Spec / aktiv
**User-Direktive:** "Das Portfolio das gezogen wird wenn es gedruckt wird,
ist vollkommen nicht gleich wie das das ich als beispiel gegeben habe.
Bitte halte dich an das, von Aufbau wording usw. Einfach an unser system
anpassen!"

## 0. Problem

Server-PDF (Sprint 5 ReportLab) hat strukturell **andere Layout/Wording**
als Frontend-Browser-Print (`buildAnlagestrategieDocHtml`). Berater sieht
verschiedene Dokumente abhaengig vom Pfad — verwirrend, unprofessionell.

## 1. Soll-Layout (exakt wie Frontend)

**Format:** A4 LANDSCAPE, margin 0
**Branding:** "WealthArchitekten" (dunkler Header #0f172a)

**8 Sektionen in dieser Reihenfolge:**

1. **Header** (dark): Logo + "Anlagestrategie" + "Vertraulich · Erstellt am
   <DATUM>" links; "Kundendossier" + "Mandat <NR>" + "Beratungsvermoegen
   CHF <X>" rechts
2. **Kenntnisse & Erfahrungen (Eignungspruefung)**: 2-Spalten-Tabelle
   "Finanzdienstleistungen" / "Finanzinstrumente" mit Bool-Markers
3. **Risikoprofil**: Box mit "Risikoprofil X/10" + Profil-Label +
   "Anlagehorizont X Jahre" + "Mandat: <Typ>"
4. **Soll-Allokation & Toleranzbaender**: 5-Spalten-Tabelle (Anlageklasse
   mit Farb-Dot | Soll % | Bar-Visualisierung | Band Min-Max | Betrag CHF)
5. **Umsetzung in Produkte (ISIN)**: 4 Metric-Boxen oben (Produkte-Count
   + Zielvolumen + Gewichtete TER + Anzahl Waehrungen) + 6-Spalten-
   Tabelle (Produkt+ISIN | Subklasse | Soll % | Zielwert | CCY | TER)
6. **Risikoindiktatoren & Prognose (Monte Carlo)**: 5 Metric-Boxen
   (Erwartete Rendite | Median CAGR | Volatilitaet | Max DD | VaR 95%)
   mit Color-Border (orange/rot fuer DD/VaR)
7. **Anlageziele & Zielerreichung**: 4-Spalten-Tabelle (Rang | Ziel |
   Score-Bar | Zielgroesse) mit Color-Code (>=70 gruen, 45-69 orange,
   <45 rot)
8. **Bestaetigung & Unterschrift**: 2 Spalten mit Unterschriftslinien +
   Labels "Ort, Datum / Klient(in)" und "Ort, Datum / Anlageberater"

**Footer (jede Seite):** 8px grau, FIDLEG-Disclaimer woertlich

## 2. Wording (woertlich aus Frontend uebernehmen)

- "WealthArchitekten" (Brand)
- "Anlagestrategie" (Titel)
- "Vertraulich · Erstellt am <DATUM>"
- "Kundendossier", "Mandat", "Beratungsvermoegen"
- "Kenntnisse & Erfahrungen (Eignungspruefung)"
- "Kenntnisse vorhanden", "Aufklaerung erhalten"
- "Risikoprofil", "VON 10"
- "Soll-Allokation & Toleranzbaender"
- "Anlageklasse", "Soll", "Visualisierung", "Band Min-Max", "Betrag"
- "Total Beratungsvermoegen"
- "Umsetzung in Produkte (ISIN)"
- "Produkte", "Zielvolumen", "Gewichtete TER", "Waehrungen"
- "Das Portfolio ist die konkrete Umsetzung der Soll-Allokation in
  Produktbausteine. Detailbestaende und spaetere Live-Drift werden im
  Review nachgefuehrt."
- "Risikoindiktatoren & Prognose (Monte Carlo)"
- "Erwartete Rendite", "Median CAGR", "Volatilitaet", "Max. Drawdown",
  "VaR 95%"
- "p.a. langfristig", "geometrisch", "p.a. annualisiert", "historisch",
  "1-Jahres-Risiko"
- "Anlageziele & Zielerreichung"
- "Rang", "Ziel", "Zielerreichung", "Score", "Zielgroesse"
- "RANG <X>"
- "Bestaetigung & Unterschrift"
- "Ich bestaetige, die vorliegende Anlagestrategie besprochen und
  verstanden zu haben."
- "Der Anlageberater bestaetigt, die Strategie besprochen und
  dokumentiert zu haben."
- "Ort, Datum", "Klient/in", "Anlageberater"
- FIDLEG-Disclaimer woertlich: "Dieses Dokument wurde in Uebereinstimmung
  mit dem Bundesgesetz ueber die Finanzdienstleistungen (FIDLEG) erstellt.
  Es dient der Dokumentation der Anlageberatung und stellt keine Garantie
  fuer Anlageergebnisse dar. Vergangenheitswerte sind kein verlaesslicher
  Indikator fuer zukuenftige Ergebnisse. Erstellt am <DATUM>."

## 3. Farben (aus Frontend)

| Asset-Class | Farbe |
|---|---|
| Aktien | #1e4b8f (dunkelblau) |
| Obligationen | #78601a (braun) |
| Immobilien | #2c5080 (blaugrau) |
| Alternative | #4a6080 (dunkelgrau) |
| Liquiditaet | #166534 (gruen) |

| Goal-Score | Farbe |
|---|---|
| >=70 | #166534 (gruen) |
| 45-69 | #92400e (orange) |
| <45 | #991b1b (rot) |

Header-BG: #0f172a (dark slate)
Metric-Boxes: #f8fafc bg, #e2e8f0 border (default)
"Max DD": #fde68a border (orange Akzent)
"VaR 95%": #fecaca border (rot Akzent)

## 4. Implementation-Plan

**Phase 1 (jetzt):** Styles + Layout + Header/Footer
- styles.py: Landscape A4, WealthArchitekten-Farben, neue Konstanten
- components/header.py: dunkler Banner, 2-spaltiger Header
- components/footer.py: FIDLEG-Disclaimer

**Phase 2:** 7 neue Component-Module
- saa_table_bars.py (5-Spalten mit Bar-Visualisierung)
- eignungspruefung.py
- risikoprofil_box.py
- produkte_table.py + metric_boxes
- risiko_metriken.py
- ziele_table.py
- unterschrift.py

**Phase 3:** Data-Loader erweitern
- AnlagestrategieData um neue Felder
- routers/pdf_reports.py: aus DB laden

**Phase 4:** Document-Composer
- documents/anlagestrategie.py neu komponieren

**Phase 5:** Tests anpassen
