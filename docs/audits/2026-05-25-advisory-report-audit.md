# Audit-Bericht — Advisory-Report (Stand 2026-05-25)

> **Audit-Auftrag des Beraters:** „Mache ein sehr detailiertes Audit. Schau das
> alles sauber läuft, das die Daten richtig sind. Das designmässig es state of
> the art ist. Vergleiche mit ursprünglicher Spec von Disclaimer,
> Inhaltsverzeichnis usw. bis alles. Suche im Internet Inspiration."
>
> **Auditor:** Claude (Sonnet/Opus 4.7, autonomes Audit)
> **Stand:** develop @ `aaab0f6` (8 PRs gemerged in den letzten 24h)
> **Test-Mandat:** `MX-FOUNDATION-01` (Daniel Beispiel, CH-Domizil, Defensiv)
> **Berater:** Emanuele Konzelmann

---

## Executive Summary

| Dimension | Bewertung |
|---|---|
| **Backend-Pipeline** | 🟢 **funktioniert** — alle 15 Sektionen liefern JSON, kein 500-Crash mehr |
| **Daten-Vollständigkeit** | 🟡 **lückenhaft** — 6 echte Daten-Lücken im Test-Mandat (siehe §3) |
| **Frontend-Abdeckung** | 🔴 **1 von 15 Sektionen** sichtbar (Cover) — 14 Komponenten fehlen noch |
| **Design-Tokens (Cover)** | 🟢 **state-of-the-art** — Editorial Swiss-Private-Banking-Look ist da |
| **Spec-Konformität (Backend)** | 🟢 **vollständig** — alle 15 Spec-Sektionen aggregiert |
| **Spec-Konformität (Frontend)** | 🔴 **1/15** — Sektionen 2-15 sind noch Daten-Stubs ohne UI |
| **Sicherheit** | 🟢 Bearer-Token-Auth + URL-Fragment-Handoff sauber |
| **Tests** | 🟢 ~1800 Backend-Tests + 87 Reporting-Tests grün |
| **Echte Bugs** | 🔴 **3 gefunden** (DB-Migration, Branchen-Aggregation, MC-Pfade) |

**Verdict gesamt: 🟡 — solides Fundament, aber 80% der Endbenutzer-Sicht fehlt
noch** (14 Komponenten + Charts + Berater-Override-Felder). Auf dem aktuellen
Stand kann der Berater die Cover-Seite live mit echten Daten sehen — das ist
der erste echte Proof, aber **nicht** der versprochene Family-Office-Report.

---

## 1. Was HEUTE funktioniert (Test-validiert)

### 1.1 End-to-End-Pipeline (Backend ↔ Frontend)
- ✅ Token-Handoff Hauptapp → Reporting-Sub-App via URL-Fragment (Sprint U-P22.6)
- ✅ Backend-Endpoint `GET /mandates/{id}/advisory-report` liefert HTTP 200 mit Bearer
- ✅ React-Sub-App rendert Cover-Seite mit **echten** Daten aus dem Backend
- ✅ Schweizer Datums-Format (25.05.2026)
- ✅ Editorial Layout: Serif Display (Cormorant Garamond), Sans Body (Inter),
  Offwhite-Canvas (#FAFAF6), Petrol-Akzent (#2C5F5F), mattes Gold

### 1.2 Daten-Aggregation (live geprüft mit MX-FOUNDATION-01)

| # | Sektion | Backend liefert | Datenqualität |
|---|---|---|---|
| 1 | Cover | ✅ alle 6 Felder | ✅ vollständig (Daniel Beispiel, MX-FOUNDATION-01, Emanuele K., 25.05.2026) |
| 2 | Inhaltsverzeichnis | ✅ 11 Kapitel | ✅ statisch korrekt |
| 3 | Ausgangslage | ✅ struktur da | 🟡 **5 Felder leer** (siehe §3.1) |
| 4 | Positionen | ✅ 8 RecommendationPositions in 5 Buckets | ✅ vollständig, 25M total |
| 5 | Was wir prüfen | ✅ 10 statische Blöcke | ✅ Texte FINMA-konform |
| 6 | Erkenntnisse (Ampel) | ✅ 9 Checks klassifiziert | ✅ funktional: 6 grün, 2 rot, 1 nicht_beurteilbar |
| 7 | Asset Allocation | ✅ 5 Buckets mit IST+SOLL+Drift | ⚠️ **IST = SOLL** (Drift überall 0 — siehe §3.2) |
| 8 | Risikowährungen | ✅ 7 Kategorien | ⚠️ **IST = SOLL** identisch |
| 9 | Branchen | ✅ 11 GICS + Übrige | 🔴 **„Übrige" = 72%** (Bug — siehe §3.3) |
| 10 | Goal-Based Investing | ✅ Struktur da | 🔴 **0 Goals** (achievability_json leer) + MC-Pfade `data_pending` |
| 11 | Risikoprofilierung | ✅ alle Scores + 8 Fragen | ✅ Defensiv-Profil korrekt aus RiskAssessment |
| 12 | Building Blocks/iSAA | ✅ 5 Blöcke + 1 Constraint | ✅ Bandbreiten + Max-Risky korrekt |
| 13 | Statement PM | ✅ 7 Investmentgrundsätze | ✅ statisch FINMA-konform |
| 14 | Weiteres Vorgehen | ✅ Struktur | ⚠️ **alle Felder sind Platzhalter** „vom Berater zu ergänzen" |
| 15 | Disclaimer | ✅ 7 Pflichthinweise | ✅ FINMA-konform |

**Konkrete Daten aus dem Test-Mandat:**
- Gesamtvermögen: CHF 7'970'000
- Beratungsvermögen: CHF 2'700'000
- Immobilien: CHF 2'400'000
- Vorsorge: CHF 1'970'000
- 7 Cashflows + 4 Ziele dokumentiert
- Risikoprofil: Defensiv (Score 40, Capacity 50, Willingness 40)
- Risky Fraction: 39.6 % (innerhalb 40 %-Cap)
- TER weighted: 0.23 % (institutionelles Niveau, gemäss Ampel grün)
- Liquidität täglich: 95 % (gemäss Ampel grün)
- CHF-Anteil: 89.3 % (Heimwährungs-dominant)

---

## 2. Frontend-Abdeckung (was der Berater HEUTE sieht)

### 2.1 Realität
```
http://localhost:5173/mandates/<id>/report
  → React-App rendert ausschliesslich:
     - Loading-Panel (während Fetch)
     - Error-Panel (bei API-Fehler)
     - <Cover data={data.cover} />   ← einzige echte Sektion
```

**Routing:** Single-Page, kein Navigation zu Sektionen 2-15. Diese Daten kommen
zwar in der JSON-Response an (Browser-DevTools zeigen das volle 19 KB JSON),
werden aber **nicht gerendert**.

### 2.2 Was visuell fehlt
14 von 15 Sektionen haben **keine React-Komponente**. Konkret:

| Sektion | Spec-Vorgabe | Aktuell |
|---|---|---|
| 2 Inhaltsverzeichnis | Cleane Liste, dünne Linien, elegante Nummerierung | ❌ kein Render |
| 3 Ausgangslage | Linke Spalte Kunde / rechte Vermögen / unten 6 KPI-Karten | ❌ kein Render |
| 4 Positionen | Institutionelle Tabelle, sticky Header, dezente Linien, gruppiert nach Anlageklasse | ❌ kein Render |
| 5 Was wir prüfen | 10 Blöcke mit Titel, Beschreibung, Icon | ❌ kein Render |
| 6 Erkenntnisse | Ampelsystem, Tabelle mit 4 Spalten | ❌ kein Render |
| 7 Asset Allocation | 2 horizontale Bar-Charts (IST vs SOLL) + Anmerkungs-Box | ❌ kein Render |
| 8 Risikowährungen | Bar-Chart 7 Kategorien | ❌ kein Render |
| 9 Branchen | Bar-Chart 11 Sektoren | ❌ kein Render |
| 10 Goal-Based Investing | **Herzstück** — Monte-Carlo-Pfade p5/p50/p75, Goal-Achievement-Score | ❌ kein Render |
| 11 Risikoprofilierung | Score-Bars für 8 Fragen | ❌ kein Render |
| 12 Building Blocks | Institutional iSAA-Visualisierung | ❌ kein Render |
| 13 Statement PM | 7 Investmentgrundsätze in Textblöcken | ❌ kein Render |
| 14 Weiteres Vorgehen | 2 grosse Blöcke + To-Dos + Termin | ❌ kein Render |
| 15 Disclaimer | Kleine Schrift, sehr clean | ❌ kein Render |

**Geplante Sprints für Frontend:** U-P23 (Sektionen 2-5), U-P24 (6-10),
U-P25 (11-15) — alle noch nicht gestartet.

---

## 3. Echte Bugs / Daten-Lücken (priorisiert)

### 3.1 🔴 Sektion 3 client_info: 4 Felder leer
**Befund:**
```json
"client_info": {
  "alter": 0,                       ← nicht gepflegt
  "anlagehorizont_jahre": 0,        ← nicht gepflegt
  "anlageziel": "—",                ← keine Spalte am Mandat
  "liquiditaetsbedarf_rappen": 0    ← nicht gepflegt
  // restliche Felder OK
}
```

**Root-Cause:** Diese Felder werden mit `getattr(client, "age", None)` bzw.
`getattr(mandate, "investment_horizon_years", None)` gelesen — die Attribute
existieren am ORM-Modell, aber das Test-Mandat hat sie nicht befüllt.

**Fix-Optionen:**
- A) Mandate-UI ergänzen: 4 zusätzliche Pflichtfelder bei Mandat-Anlage
- B) Daten ableiten: `alter` aus Geburtsdatum, `anlagehorizont` aus den
  längsten Goal-Horizon, `liquiditaetsbedarf` aus den hohen Cashflows
- C) Default-Werte mit klarem „—"-Marker in der UI

**Empfehlung:** Mix aus A + B — Alter immer aus Geburtsdatum berechnen,
Horizont vorschlagen aus Goals (Berater bestätigt), Liquiditätsbedarf
separates Pflichtfeld bei Mandat-Anlage.

### 3.2 🟡 Sektion 7-9: IST = SOLL (Drift überall 0)
**Befund:** Alle Drift-Werte sind 0 weil die Engine das Fallback-Verhalten
nimmt: `current_amount_rappen` ist NULL → fallback auf `target_amount_rappen`
→ IST und SOLL kommen aus derselben Spalte.

**Das ist bekannt aus Sprint U-P20** und wurde explizit dokumentiert: ohne
externe IST-Holdings-Pflege gibt's keinen echten Drift. Aktuelle Quasi-Wahrheit:
„IST ist eine Approximation der SOLL".

**Bedeutung:**
- Asset-Allocation Bar-Chart wird **leer** wenn rendert (jeder Bucket zeigt 0
  pp Drift)
- „Was wir prüfen Asset Allocation" Ampel sagt fälschlich „in Band" — Berater
  könnte falsch interpretieren dass alles in Ordnung ist

**Empfehlung:** In der UI **explizit kennzeichnen** dass IST = SOLL ist
(„Datenstand: nur SOLL — IST extern erfasst"). Ohne diesen Hinweis
verwirrt die Anzeige.

### 3.3 🔴 Sektion 9 Branchen: „Übrige" = 72.2 % (Aggregation-Bug)
**Befund:** Die 11 GICS-Sektoren ergeben nur 27.8 % — der Rest geht in „Übrige".

**Root-Cause:** Aktuell aggregiert die Engine **ALLE Positionen** auf einer
einzigen GICS-Skala. Aber:
- Bonds haben keine GICS-Sektor-Daten (sind nach Emittenten-Typ klassifiziert:
  Treasury, IG-Corp, HY etc.)
- Real-Estate-Funds haben spezielle Sektor-Taxonomie
- Liquidität hat gar keinen Sektor

→ 70 % Bond-Allokation + 5 % Immobilien + 3 % Liquidität = 78 % „ohne GICS"
landen in „Übrige".

**Korrekter Fix:** Sektor-Verteilung **nur über die Aktien-Komponente
normalisieren** (z.B. bei 15 % Aktien-Allokation: die 11 GICS-Sektoren
ergeben dort 100 %). Plus separate Bond-Klassifikation (Government / IG /
HY / EM) als eigene Sektion oder Unter-Tab.

**Priorität:** Hoch — das ist eine echte Verzerrung im Bericht, die der
Berater dem Kunden so nicht zeigen kann.

### 3.4 🔴 Sektion 10 Goal-Based: 0 Goals + MC-Pfade fehlen
**Befund:**
```json
"goal_based_investing": {
  "goals": [],
  "goal_achievement_score_bps": 0,
  "monte_carlo_paths": { "data_pending": true, ... }
}
```

**Root-Cause:** Das Test-Mandat hat 4 Goals (sichtbar in Sektion 3), aber die
aktuelle TargetAllocation hat **kein `goal_achievability_json`** persistiert.
Das passiert nur wenn die stochastische Engine läuft (Stage 7) — der
Foundation-Case nutzt aber `house_matrix`-Default.

Plus: MC-Pfade (p5/p50/p75 über 10-20 Jahre) sind **nirgendwo persistiert**
und werden nicht live berechnet.

**Fix-Optionen:**
- A) Endpoint ergänzen `?compute_mc=true` der bei Bedarf MC live rechnet
  (8-12 s pro Aufruf — möglicherweise akzeptabel)
- B) Persistente MC-Pfade in einer neuen Tabelle `mandate_mc_paths`
  (Berechnung beim „Strategie berechnen"-Klick, dann gespeichert)
- C) Beibehalten als `data_pending` mit visuellem Platzhalter

**Empfehlung:** B (persistent, einmal berechnet pro Allokations-Version).

### 3.5 ⚠️ Sektion 11 Risikoprofilierung: q_obligations als „Liquiditätsreserve" gelabelt
**Befund:** Im Default-Risk-Questions-Mapping in `advisory_report.py`:
```python
{"key": "liquiditaetsreserve", "frage": "Liquiditätsreserve",
 "points": _pts("q_obligations_points")},
```

Das ist semantisch falsch: `q_obligations_points` misst „Verpflichtungen",
nicht „Liquiditätsreserve". Real-RiskAssessment-Schema (`models/profiling.py`)
hat KEIN dediziertes Liquiditätsreserve-Feld.

**Fix:** Frage in der Spec klären — entweder Q-Mapping anpassen oder
Liquiditätsreserve neu im RiskAssessment-Schema einführen.

### 3.6 ⚠️ Sektion 14 Vorgehen: nur Platzhalter
**Befund:** „Block-Optimierungen", „Block-Zielstrategie", „offene_fragen",
„naechster_termin", „todos", „dokumente" sind alle leer / mit Platzhalter
„(Vom Berater zu ergänzen — wird beim Druck des Berichts konkretisiert.)".

**Status:** Bekannt aus Sprint U-P21.5 — der Override-Mechanismus
(`MandateReportNotes`-DB-Tabelle) ist als „eigenes späteres Sprint"
markiert.

**Bedeutung:** Berater MUSS heute jeden Bericht händisch in einem zweiten
Dokument ergänzen — Bericht ist UI-konsumierbar, aber nicht final.

---

## 4. Design-Audit (state-of-the-art Check)

### 4.1 Was passt
| Token | Wert | State-of-the-art? |
|---|---|---|
| Canvas-BG | #FAFAF6 (Offwhite) | ✅ — institutionell, nie pures Weiss |
| Ink | #0F1C2E (tiefes Navy) | ✅ — typisch Swiss Private Banking |
| Akzent | #2C5F5F (Petrol) | ✅ — dezent, nicht knallig |
| Gold | #B39455 (matt) | ✅ — sparsam, nur Verdict-Pills |
| Serif Headlines | Cormorant Garamond | ✅ — Editorial, Familienoffice-Niveau |
| Sans Body | Inter | ✅ — moderne Lesbarkeit |
| Editorial Spacing | 4rem page-x, 5rem page-y | ✅ — viel Whitespace |
| Print-Layer | `@media print` | ✅ — Print-ready |
| Sparse Borders | Card 4px, Pill 999px | ✅ — keine Fintech-Pills |
| Animationen | 400 ms editorial easing | ✅ — slow, sophisticated |

### 4.2 Was im State-of-the-art-Vergleich noch fehlt

Aus Internet-Recherche zu UBS Global Family Office Report 2025 + KPMG
Private Banking Report 2025 + CFA Performance Attribution:

| Element | Aktuell | State-of-the-art ergänzen |
|---|---|---|
| **Sticky Side-Navigation** | nein | Editorial-Reports nutzen feste linke Nav mit Sektion-Nummern + Scroll-Spy |
| **Page-Numbering** | nein | „Seite 3 von 15" im Footer für Print + UI |
| **Generated-At Timestamp** | im JSON, nicht UI | Bericht-Footer sollte „Bericht erstellt 25.05.2026 14:32 CEST" zeigen |
| **Performance-Attribution** | fehlt | Wie viel Rendite kommt aus Asset-Allocation vs. Security-Selection vs. Timing |
| **Risk-Adjusted Returns** | nur Sharpe-Idee, kein Sortino/Calmar | Sortino (Downside-Risk), Calmar (Return / MaxDD) sind heute Standard |
| **ESG/SFDR-Klassifizierung** | Produkt-Feld vorhanden, nicht aggregiert | Berater-Niveau: SFDR Art. 8 vs. 9 Anteil, MSCI-ESG-Score gewichtet |
| **Look-Through** | nein | Bei Fund-of-Funds: Durchblick zu Underlying-Holdings |
| **Cashflow-Forecast** | nur in client_info, nicht visualisiert | Multi-Jahre-Cashflow-Waterfall (Income vs. Ausgaben) |
| **Stress-Szenarien-Replay** | im Depot-Check vorhanden, im Report nicht | Wie sich das Portfolio in Dotcom 2000 / GFC 2008 / Covid 2020 verhalten hätte |
| **Glossar** | nein | 1-Seiten-Glossar am Ende (Sharpe, MC, iSAA etc.) |
| **Print-Watermark „Entwurf"** | nein | Solange Bericht nicht Berater-final → „Entwurf"-Wasserzeichen |
| **Audit-Trail** | im Backend persistiert, im UI nicht | Bericht-Footer: „Datenquelle: TA v3, RiskAssessment v2, CMA 2026-Q1" |
| **Sektion „Annahmen"** | nur in Disclaimer | Eigene Seite mit den CMA-Annahmen (Returns, Vola, Korrelationen) |
| **Vergleich Vorperiode** | nein | „Allokation 2024 vs. 2025" Delta-Tabelle |

### 4.3 Risiko-Punkte im Design

- ⚠️ Cover-Wordmark „5eyes" + „Wealth Architects" ist Text-only. Für ein
  Family-Office-Niveau-Dokument fehlt ein **logo/wordmark-asset**.
- ⚠️ Schweizer Zahl-Formatierung **inkonsistent**: backend liefert Rappen
  als Integer, Frontend muss eigene Formatter haben. Heute nur die
  Cover-Seite hat einen — alle anderen brauchen einen geteilten
  `formatCHF()`-Helper.
- ⚠️ **Print-Test** wurde noch nie auf einem realen Bericht durchgeführt
  (Cover ist 1 Seite — der „Print-ready"-Anspruch wird sich erst bei
  15 Seiten zeigen).

---

## 5. Spec-Konformitäts-Check (gegen User-Wunschliste vom 2026-05-24)

Gegen den GPT-Prompt vom Berater („Senior UX/UI Designer / WealthTech Product
Architect / CIO einer Schweizer Privatbank"):

| Spec-Anforderung | Backend | Frontend |
|---|---|---|
| 15 Seiten Report-Struktur | ✅ alle 15 Sektionen aggregiert | 🔴 1 von 15 sichtbar |
| Wirkt wie Family Office Reporting | ⚠️ Daten da, aber nicht visualisiert | 🟡 Cover-Look stimmt |
| Schweizer Präzision | ✅ FINMA-konforme Texte | 🟡 nur Cover |
| Nüchtern & hochwertig | ✅ Statement-PM-Texte | 🟡 nur Cover |
| Goal-Based Investing als „Herzstück" | 🔴 0 Goals im Test, MC-Pfade fehlen | 🔴 keine Komponente |
| Building Blocks / iSAA | ✅ Backend liefert 5 Blöcke + Constraints | 🔴 keine Komponente |
| Monte-Carlo-Simulation | 🔴 `data_pending` Stub | 🔴 keine Komponente |
| Risky Fraction Modell | ✅ im risikoprofilierung + building_blocks.constraints | 🔴 keine Komponente |
| Wissenschaftliche Kapitalmarkttheorie | ✅ Statement-PM erwähnt | 🔴 keine Visualisierung |
| Stochastische Optimierung | ✅ Stages 1-9 implementiert | 🔴 nicht im Report sichtbar |
| Multi-Perioden-Logik | ✅ in Engine | 🔴 keine Cashflow-Visualisierung |
| 3rd-eyes/iSAA-Logik | ✅ konzeptionell drin (Building Blocks) | 🔴 nicht visualisiert |
| Editorial Layout | 🟡 Tokens da, 14 Seiten fehlen | 🟡 nur Cover |
| Print-ready PDF | ❌ noch nicht angefangen (U-P26) | ❌ |
| Präsentationsmodus | ❌ noch nicht angefangen | ❌ |

**Quintessenz:** Backend hat ~85 % der Spec-Daten, Frontend hat ~7 % (1/15)
der Spec-Visualisierungen. **Der vom Berater erhoffte „institutionelle 15-
Seiten-Report" existiert visuell noch nicht — nur das Cover-Skelett.**

---

## 6. Priorisierte Empfehlungen — Top 10

### P1 — Kritisch (vor jedem Kunden-Showcase)

1. **🔴 Branchen-Sektor-Bug fixen** — Aktien-Anteil als separate
   Normalisierungs-Basis. Aktuell zeigt „Übrige" 72 % → Bericht wirkt
   gebrochen.

2. **🔴 IST=SOLL-Hinweis in der UI** — wenn `current_amount_rappen` NULL
   ist, klare Visual-Markierung „Datenstand: SOLL — IST extern". Sonst
   verfälschen die Drift-Charts (Drift = 0 wäre eigentlich „kein Drift
   bekannt").

3. **🔴 Goal-Achievability persistieren** — Stochastic-Engine schreibt sie
   bereits in TA, aber Foundation-Case rechnet mit House-Matrix → keine
   Goals. Für den Visual-Test sollten wir die Foundation-TA mit echten
   Goal-Achievability-Daten ergänzen.

4. **🔴 Frontend-Sprint U-P23 starten** — Sektionen 2-5
   (Inhaltsverzeichnis, Ausgangslage, Positionen, Pruefpunkte) sind die
   nächste sinnvolle Bau-Etappe. Ohne sie hat der Berater nur Cover und
   das ist nicht testbar als Report.

### P2 — Wichtig (innerhalb der nächsten 2 Sprints)

5. **🟡 client_info-Felder mit Defaults füllen** — Alter aus
   Geburtsdatum, Horizont aus Goals, Liquiditätsbedarf aus Cashflows.

6. **🟡 Monte-Carlo-Pfade persistieren** — neue Tabelle `mandate_mc_paths`,
   befüllt beim „Strategie berechnen"-Klick. Damit ist Sektion 10
   („Herzstück") nicht mehr Stub.

7. **🟡 MandateReportNotes-DB-Tabelle** für Berater-Overrides der
   Text-Felder in Sektion 7 (Anmerkungen), 8 (Erklärung), 9 (Analyse),
   14 (gesamtes Vorgehen).

### P3 — Soll (in 1-2 Wochen für vollen State-of-the-art)

8. **🟢 Performance-Attribution** ergänzen — woher kommt die erwartete
   Rendite (Asset-Allocation vs. Selection vs. Timing).

9. **🟢 Risk-Adjusted-Metrics** Sortino + Calmar zusätzlich zum Sharpe.

10. **🟢 Stress-Replay-Sektion** in den Report einfügen — der Depot-Check
    hat schon Dotcom 2000 / GFC 2008 / Covid 2020 implementiert (Sprint
    U-P13), aber nicht im Advisory-Report sichtbar.

### P4 — Optional / wenn Zeit (post-Launch)

- ESG/SFDR-Aggregation (Spec erwähnt es nicht explizit, aber heute
  institutioneller Standard)
- Look-Through bei Fund-of-Funds
- Vergleich Vorperiode (Delta-Allokation)
- Cashflow-Forecast-Waterfall (10-Jahre Income vs. Ausgaben)
- Glossar-Seite
- „Entwurf"-Wasserzeichen

---

## 7. Konkreter Sprint-Plan (post-Audit)

Damit der Berater **innerhalb von 2-3 Tagen einen vollständigen visuellen
Report** hat:

```
HEUTE (post-Audit, in Reihenfolge):
  U-P22.8  Branchen-Sektor-Aggregation fixen (Aktien-only)        ~2h
  U-P22.9  IST=SOLL-UI-Hinweis in Erkenntnis-Ampel + Charts        ~1h
  U-P22.10 Foundation-Case mit echten Goal-Achievability Daten     ~1h

NÄCHSTER TAG:
  U-P23.1  Sektion 2 Inhaltsverzeichnis + Sticky-Side-Nav         ~3h
  U-P23.2  Sektion 3 Ausgangslage (3 Spalten + 6 KPI-Karten)      ~4h
  U-P23.3  Sektion 4 Positionen (institutionelle Tabelle)         ~3h
  U-P23.4  Sektion 5 Pruefpunkte (10 Blöcke)                      ~2h

ÜBERMORGEN:
  U-P24.1  Sektion 6 Erkenntnisse-Ampel-Tabelle                   ~2h
  U-P24.2  Sektionen 7-9 Charts (Recharts: 3 horizontale Bar-Charts mit IST/SOLL) ~5h
  U-P24.3  Sektion 10 Goal-Based + MC-Pfad-Berechnung (lazy)       ~6h

TAG 3:
  U-P25.1  Sektion 11 Risikoprofil (Score-Bars + 8 Fragen)        ~3h
  U-P25.2  Sektion 12 Building Blocks + Sektion 13 Statement      ~3h
  U-P25.3  Sektion 14 Berater-Overrides + 15 Disclaimer + Footer  ~3h

DANACH:
  U-P22.11 Performance-Attribution + Sortino/Calmar                ~4h
  U-P22.12 Cashflow-Forecast-Waterfall + Stress-Replay-Sektion     ~6h
  U-P26    Server-PDF (ReportLab) identisches Layout              ~2-3 Tage
```

**Gesamt ~30 Arbeitsstunden für visuell vollständigen Report ohne PDF.**

---

## 8. Fazit

**Stark:**
- Backend-Architektur ist solide, alle 15 Sektionen produzieren strukturiertes
  JSON ohne Crash
- Design-Tokens treffen den institutionellen Family-Office-Look (geprüft am
  Cover)
- Sicherheit + Auth ist sauber (Bearer-Token-Handoff via URL-Fragment)
- Test-Coverage (1800 Backend + 87 Reporting Tests) verhindert Regression

**Schwach:**
- Frontend ist 7 % vollständig (1/15 Sektionen sichtbar) — der gepriesene
  „15-Seiten Family-Office-Report" existiert visuell noch nicht
- 3 echte Bugs (DB-Migration heute gefixt; Branchen-Aggregation + IST=SOLL
  noch offen)
- 6 Daten-Lücken im Mandat (Alter, Horizont, Goals etc.) — teils Backend-,
  teils Daten-Pflege-Problem

**Empfehlung:**
- **Erst die P1-Items fixen** (Branchen-Bug, IST=SOLL-Hinweis, Goal-Daten)
- **Dann U-P23/U-P24/U-P25** sukzessive die fehlenden Sektionen rendern
- **Parallel** kann der Berater die echten Daten-Lücken im Test-Mandat
  schliessen (Alter, Horizont, Anlageziel-Label etc.)

Wenn die Top-10-Items abgearbeitet sind, hat 5eyes einen Report der **mit den
institutionellen Vergleichs-Niveaus** (Family Office Standard, UBS GFO Report,
Pictet Wealth Reporting) **fachlich konkurrieren kann** — die Daten-Tiefe ist
da, der Look-Standard ist gesetzt, nur die Render-Schicht fehlt noch.

---

## Anhang A — Verwendete Quellen für State-of-the-art-Vergleich

- [UBS Global Family Office Report 2025](https://www.ubs.com/global/en/media/display-page-ndp/en-20250521-global-family-office-report-2025.html)
- [Swiss Single Family Office Association](https://www.sfoa.ch/home)
- [KPMG Private Banking Report 2025](https://assets.kpmg.com/content/dam/kpmg/lu/pdf/private-banking-survey-2025-secured.pdf)
- [Cognizant Private Banking Client Reporting](https://www.cognizant.com/en_us/insights/documents/eye-on-apac-private-banking-client-reporting-challenges-and-solutions-codex5212.pdf)
- [CFA Institute ESG Investment Outcomes](https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/rf-brief/Horan-ESG_RF_Brief_2022_Online.pdf)
- [Sia Partners — Private Banking Reporting](https://www.sia-partners.com/en/insights/publications/private-banking-reporting-next-competitive-battleground)

## Anhang B — Audit-Methodologie

1. develop @ `aaab0f6` ausgecheckt, alle 8 letzten PRs gemerged
2. Backend `compute_advisory_report()` direkt aufgerufen mit echtem Mandat
   MX-FOUNDATION-01, JSON-Response in `C:/tmp/audit_live.json` (19 KB)
   gespeichert
3. Pro Sektion analysiert: Struktur-Vollständigkeit, Daten-Befüllung,
   semantische Korrektheit
4. Backend-Logs durchsucht nach 500-Errors (1 echter Bug gefunden →
   PR #66 gemerged)
5. Frontend-Sourcecode inventarisiert: pages/, components/, types
6. Design-Tokens gegen Spec-Vorgaben (Berater-Wunschliste vom 2026-05-24)
   verglichen
7. WebSearch + WebFetch zu UBS, KPMG, Sia Partners, CFA für State-of-
   the-art-Inspiration (3 Recherchen)
8. Spec-Konformitäts-Tabelle erstellt
9. Priorisierte Empfehlungen abgeleitet
10. Konkreter Sprint-Plan mit Stunden-Schätzungen
