# Owner-Handover — was DU (Berater) die nächsten Tage tun musst

> **Datum:** 2026-05-25 Abend
> **Adressat:** Emanuele Konzelmann (Owner / Berater)
> **Zweck:** Klare Liste was nur DU tun kannst (Codex und Claude können
> es nicht). Damit nichts verloren geht während Codex parallel weiterbaut.

---

## TL;DR — die 5 nächsten Owner-Aktionen

| # | Was | Wann | Aufwand |
|---|---|---|---|
| 1 | **Codex' nächste PRs reviewen** (U-P23 PR B-E) | wenn sie aufkommen | je 5 min |
| 2 | **Visual-Check** der neuen Sektionen sobald sichtbar | nach Codex' PR C | 10 min |
| 3 | **Stage 8 Owner-Verifikation** für Default-Stochastic-Switch | wenn 4 reale Mandate Shadow-Daten haben | 30-45 min |
| 4 | **Daten-Pflege im Test-Mandat** (optional, U-P30 löst's sonst) | jederzeit | 5 min |
| 5 | **NPM install + Vite-Restart** sobald U-P23 PR E (Recharts) gemerged | nach Codex' PR E | 2 min |

---

## 1. Codex' nächste PRs reviewen

Codex arbeitet aktuell an **U-P23 PR B-E**. Erwartete Reihenfolge:

| PR | Inhalt | Erwarteter Diff |
|---|---|---|
| ⏳ **PR B** | Branchen-Bug-Fix + IST=SOLL-Flag + Goal-Achievability-Trigger | ~150 Zeilen |
| ⏳ **PR C** | Disclaimer.tsx + Inhaltsverzeichnis.tsx + Sidebar.tsx + Routing | ~400 Zeilen |
| ⏳ **PR D** | Ausgangslage.tsx + Positionen.tsx + Schweizer Number-Formatter | ~350 Zeilen |
| ⏳ **PR E** | BarChartIstSoll + chartTheme.ts (Recharts-Foundation) | ~200 Zeilen |

**Was du bei jedem PR tust:**
- PR-Beschreibung lesen (5 min)
- GitHub-Diff überfliegen — keine Branding-Verstöße, keine Garantieversprechen
- Wenn alles passt: Claude macht das CI-Watch + Merge

**Falls Codex einen Fehler macht:** kommentiere am PR, ich mache den Fix.

---

## 2. Visual-Check der neuen Sektionen

**Sobald U-P23 PR C gemerged ist** (Disclaimer + TOC + Sidebar):

```bash
cd 5eyes-electron/frontend/reporting
# Falls Vite-Dev-Server noch läuft:
# Im Terminal: Strg+C → npm run dev
```

Dann in der **Electron-Hauptapp**:
- Mandat öffnen → Portfolio → „Advisory-Report"
- Browser-Tab öffnet sich → linke Sidebar mit 15 Sektionen sichtbar
- Klick auf „Disclaimer" → 7 Hinweise gerendert
- Klick auf „Inhaltsverzeichnis" → 12 Kapitel-Liste
- **Visueller Check (5 Punkte):**
  - Editorial-Look stimmt (Serif Headlines, Sans Body, viel Whitespace)?
  - Schweizer Datums-Format (DD.MM.YYYY)?
  - Print-Vorschau (Strg+P) sauber?
  - Sidebar bleibt sticky beim Scrollen?
  - Branding-Compliance (keine Dritt-Marken)?

**Falls etwas nicht passt:** sag mir konkret was — ich mache den Fix.

---

## 3. Stage 8 Owner-Verifikation (sobald reale Mandate Shadow-Daten haben)

**Voraussetzung:** Mindestens 3-4 reale Mandate (1 Foundation + 3 Archetypen
gemäss Methodology §2) müssen unter `OPTIMIZER_MODE=shadow_stochastic`
einmal eine Allokation berechnet haben — dadurch sind Shadow-Daten
persistiert.

**Workflow:**
1. Admin-Modal → System → Optimizer-Mode = `shadow_stochastic`
2. Pro Mandat: Asset Allokation → „Anlagestrategie berechnen"
3. Admin-Modal → Sub-Section **„Shadow-Vergleich Aggregat"** öffnen
   (Codex U-P22 Phase 2)
4. Counts ablesen: GREEN/YELLOW/RED + `default_switch_ready` Badge
5. Falls grünes Verdict: Compliance-Template ausfüllen
   (`docs/compliance/shadow-vergleich-template.md`)
6. `OPTIMIZER_MODE` auf `stochastic` umstellen + committen

**Volle Anleitung:** `docs/compliance/stage8-berater-runbook.md`

**Was es DIR bringt:** der Stochastic-Optimizer wird Default → bessere
Zielerreichungs-Wahrscheinlichkeiten für deine Kunden.

---

## 4. Daten-Pflege im Test-Mandat (optional)

**Befund Audit §3.1:** Test-Mandat `MX-FOUNDATION-01` (Daniel Beispiel)
hat folgende leere Felder, die im Advisory-Report als „—" / „0" auftauchen:

| Feld | Stand jetzt | Soll-Wert | Quelle |
|---|---|---|---|
| `client.date_of_birth` | 1976-09-18 ✅ | — | bereits gepflegt |
| `mandate.retirement_year` | wahrscheinlich leer | 2041 | manuell setzen |
| `mandate.life_expectancy_year` | wahrscheinlich leer | 2060 (BFS-Wert) | manuell setzen |
| `mandate.primary_goal_label` | existiert nicht als Spalte | — | wird von U-P30 abgeleitet aus Goal mit rank=1 |
| `mandate.investment_horizon_years` | existiert nicht als Spalte | — | wird von U-P30 abgeleitet aus retirement_year |
| `mandate.liquidity_need_rappen` | existiert nicht als Spalte | — | wird von U-P30 abgeleitet aus Cashflows × 6 Monate |

**Optionen:**

**A) Warten auf U-P30** (Codex-Sprint, ~3-5 h) — alle 4 abgeleitet
**B) Manuelle SQL-Pflege jetzt** — schneller, aber wieder überschrieben
   wenn U-P30 kommt:

```sql
-- Im SQLite-Browser oder via Admin-UI
UPDATE mandates
SET retirement_year = 2041,
    life_expectancy_year = 2060
WHERE mandate_number = 'MX-FOUNDATION-01';
```

Mein Vorschlag: **Option A** — warten, weniger Arbeit.

---

## 5. NPM install + Vite-Restart nach U-P23 PR E

**Wenn Codex U-P23 PR E mergt** (Recharts-Foundation), kommt Recharts als
neue Dependency in `5eyes-electron/frontend/reporting/package.json`.
**Du musst einmalig:**

```bash
cd 5eyes-electron/frontend/reporting
npm install      # zieht Recharts nach
# Strg+C im laufenden Vite-Dev
npm run dev      # neue Bundle
```

**Sonst:** Browser zeigt „Failed to resolve module: recharts" beim
nächsten Reload.

---

## Was Codex die nächsten Tage abarbeitet (autonom — DU musst nichts tun)

```
Heute:       U-P23 PR B (Bugs)
             U-P23 PR C (Disclaimer + TOC + Sidebar)
Morgen:      U-P23 PR D (Ausgangslage + Positionen)
             U-P23 PR E (BarChartIstSoll)
Übermorgen:  U-P24 (Sektionen 6-10 + Charts)
Tag 3:       U-P25 (Sektionen 11-15 + Sidebar-Polish)
Tag 4-5:     U-P30 (Ausgangslage-Felder ableiten) + U-P28 (Berater-Overrides)
Tag 6-10:    U-P26 (Server-PDF — der grosse Sprint)
Tag 11-15:   U-P29 (State-of-the-art Erweiterungen)
Tag 16:      U-P27 (Electron-Window-Polish, Schluss)
```

**Ungefähre Gesamt-Dauer:** 2-3 Arbeitswochen Codex-Zeit (107-151 Stunden).

Bei Codex' Token-Knappheit übernimmt Claude einzelne PRs.

---

## Was passiert wenn du gar nichts tust?

Codex arbeitet autonom durch die 8 Briefings. Claude (= ich) merge die
PRs sobald CI grün ist (haben heute schon 11x bewiesen dass es
funktioniert). **Ohne dein Zutun kommen die Sektionen sukzessive auf
develop.**

Was du dann **erst am Ende** machen musst:
- Stage 8 Owner-Verifikation (Schritt 3 oben)
- Default-Mode-Switch commit (in deinem Code-Editor)

**Bis dahin:** du kannst dich auf deine Beratungs-Termine konzentrieren.

---

## Wichtige Pfade & URLs (zur Referenz)

```
Audits:
  docs/audits/2026-05-25-advisory-report-audit.md            (Erst-Audit)
  docs/audits/2026-05-25-final-audit-after-briefings.md      (Final-Audit)
  docs/audits/2026-05-25-owner-handover.md                   (= diese Datei)

Codex-Briefings (alle 2026-05-25):
  docs/planning/...-codex-sprint-u-p23-advisory-frontend-phase1.md
  docs/planning/...-codex-sprint-u-p24-advisory-frontend-phase2-charts.md
  docs/planning/...-codex-sprint-u-p25-advisory-frontend-phase3-final.md
  docs/planning/...-codex-sprint-u-p26-advisory-report-pdf.md
  docs/planning/...-codex-sprint-u-p27-electron-window-integration.md
  docs/planning/...-codex-sprint-u-p28-mandate-report-notes.md
  docs/planning/...-codex-sprint-u-p29-state-of-art-extensions.md
  docs/planning/...-codex-sprint-u-p30-ausgangslage-derived-fields.md

Compliance:
  docs/compliance/stage8-berater-runbook.md                  (Stage 8 Workflow)
  docs/compliance/shadow-vergleich-template.md               (Default-Switch-Doku)

Dev-URLs (lokal):
  Backend FastAPI:        http://localhost:8000
  Reporting-Sub-App Dev:  http://localhost:5173
  Electron Hauptapp:      über npm start in 5eyes-electron/

GitHub:
  https://github.com/Mele98/5eyes
```

---

## Wenn dir was unklar ist

Frag mich (Claude) — ich kenne den aktuellen Stand. Codex kennt nur
sein aktuelles Sprint-Briefing. Bei Architektur-Fragen oder „warum ist
das so" → lieber mich fragen.

**Schluss für heute** — du hast eine vollständige, sauber dokumentierte
Pipeline mit klaren Verantwortungen. Gute Beratungs-Termine.
