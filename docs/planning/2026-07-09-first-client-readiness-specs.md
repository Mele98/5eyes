# 5eyes — Spec: „Bereit für den ersten echten Beratungskunden"

**Datum:** 2026-07-09 · **Kontext:** Der Berater (Eigennutzer) will 5eyes seinen **eigenen realen
Beratungskunden** lokal präsentieren (nicht Software-Interessenten). Maßgeblich ist deshalb
**korrekte Zahlen + professioneller FIDLEG-Report + Stabilität im Live-Termin** — NICHT Hosting,
Multi-Tenancy, Skalierung.

**Grundlage (im Code verifiziert):** Der Default-Modus ist bereits `deployment_tier="tier1"`
(self-hosted, single-advisor, Mandant `main`, kein Tenant-UI) mit `allow_real_client_data=True`
(config.py:213/243). Das gesamte P1 der Master-Roadmap (Postgres/RLS/VPS/Pentest/Monitoring/AVV…)
ist für diesen Fall **irrelevant**.

---

## Statusübersicht — was WIRKLICH offen ist

| # | Task | Status (im Code geprüft) | Rest-Aufwand |
|---|------|--------------------------|--------------|
| **A1** | Crash-Wurzelfix „Maximum call stack" | offen (Symptom abgefangen, Wurzel nicht) | ~0,5–1 Tag nach Repro |
| **A2** | End-to-End-Visual-Smoke | QA (Checkliste unten) | ~1–2 Tage |
| **A3** | Pilot-Trockenlauf (1 realer Kunde) | QA/Prozess | ~1 Tag + Fixes |
| **B1** | Steuer in Cashflow/Netto-Rendite (#39) | **echt offen — einzige Code-Task** | ~2–4 Tage |
| **B2** | Miete inflationsindexiert (#34) | **✅ BEREITS FERTIG** (inkl. FE) | 0 (nur A2-Verifikation) |
| **B3** | goal_scope Gesamtvermögen (#33) | **✅ implementiert** (konservativ, #83) | 0 (nur Methodik-Entscheid) |

**Fazit:** Von 6 Punkten ist **genau einer** (B1) echte Code-Arbeit. B2/B3 sind bereits gebaut
(Roadmap-Doc vom 14.06. ist stale). A1 wartet auf einen Repro, A2/A3 sind QA.

---

## A1 — Crash-Wurzelfix „Maximum call stack"

### Ist-Zustand
- Guard `__chartStep(name, fn)` in `5eyes-electron/frontend/5eyes_v2.html:19305–19317`: wrappt jeden
  Render-Schritt in try/catch, loggt bei Fehler `CHART_RENDER_FAILED [<name>] — <msg>\n Zyklus: …\n <stack>`
  und lässt den Strategie-Lauf **sauber** enden (`return true`). Das Symptom ist also abgefangen —
  die Wurzel (rekursierende Funktion) nicht gefixt.
- Die 4 gewrappten Schritte + ihre Funktionen:
  1. `projection-overlay` → `updateProjectionChartsFromSimulation(result)` (~17697)
  2. `fan-montecarlo` → `upgradeFanChartWithMonteCarlo(result)`
  3. `aacurrent-montecarlo` → `upgradeCurrentAaChartWithMonteCarlo(result)`
  4. `strategy-tail` → inline (5eyes_v2.html:19315 ff.), ruft u.a. `buildCurrentBaselineProjection`,
     `buildCurrentWealthProjection('total',…)`, `buildImprovedTotalProjectionFromStrategy`,
     `updateAllocationProjectionComparison`.

### Diagnose (2 Minuten, liefert den Punkt-Fix)
1. `cd 5eyes-electron && npm start`, Kunde/Mandat laden, **Strategie berechnen**.
2. DevTools-Konsole öffnen (Ctrl+Shift+I). Bei Absturz erscheint **`CHART_RENDER_FAILED [<name>]`**.
3. `<name>` nennt exakt einen der 4 Schritte oben → die rekursierende Funktion ist bekannt.
4. Die `Zyklus:`- und Stack-Zeilen zeigen die konkrete Selbstaufruf-Kette.

### Umsetzung (je nach Step, Punkt-Fix)
- **Häufigste Ursache (Chart.js):** ein `chart.update()` in einem `onResize`/`afterRender`/Plugin-Hook,
  der seinerseits wieder `update()` auslöst → Endlosschleife. Fix: Re-Entrancy-Flag setzen
  (`if(chart.__updating)return; chart.__updating=true; try{…}finally{chart.__updating=false;}`) ODER
  den Update aus dem Hook entkoppeln (`requestAnimationFrame`, nur bei echter Datenänderung updaten —
  vgl. bestehendes Muster `5eyes_v2.html:17106`).
- **Projektions-Funktionen (`buildCurrent*`/`buildImproved*`):** falls eine dieser Funktionen sich
  bei fehlenden/rekursiven `sim.year_labels` selbst aufruft → Basisfall/Abbruch ergänzen (Länge 0 →
  frühzeitig leeres Ergebnis).
- **Wichtig:** Punkt-Fix an der EINEN rekursierenden Funktion, nicht am Guard. Der Guard bleibt als
  Sicherheitsnetz.

### Tests / Akzeptanz
- Vor Fix: Konsole zeigt `CHART_RENDER_FAILED [<name>]` (reproduziert).
- Nach Fix: **10×** „Strategie berechnen" (verschiedene Mandate: mit/ohne IST-Vermögen, kurzer/langer
  Horizont) **ohne** `CHART_RENDER_FAILED` und ohne UI-Freeze.
- Optional: Monolith-Inventar-Snapshot nach HTML-Änderung regenerieren
  (`python scripts/audit_html_monolith.py` bzw. der Snapshot-Regen in `test_monolith_inventory_stable`).

---

## A2 — End-to-End-Visual-Smoke (Klick-Checkliste)

Ziel: die komplette Beraterkette einmal systematisch mit einem realistischen Testkunden durchklicken,
jede Rauheit notieren, dann fixen. Erwartetes Ergebnis je Schritt in Klammern.

1. **Start** `npm start` (App öffnet, Backend healthy, kein Konsolen-Error beim Boot).
2. **Login/2FA** (falls aktiv) (Login klappt, 2FA-Code akzeptiert).
3. **Mandat anlegen/öffnen** (Stammdaten speicherbar, Kanton wählbar).
4. **Vermögen erfassen** — inkl. **1 Immobilie mit Mietertrag** + Checkbox „Miete teuerungsindexiert"
   (Position speichert, Mietertrag erscheint als AUTO-Cashflow — siehe B2).
5. **Cashflows** — AUTO-Zeilen (Mietertrag/Hypothekarzins) erscheinen, manuelle Posten hinzufügbar
   (Doppelerfassungs-Warnung erscheint bei Bedarf; Summen-Kacheln = Summe der Zeilen).
6. **Risikoprofil** (§2) — Fragebogen ausfüllbar, Score + Profil-Label plausibel, kein Absturz beim
   Speichern.
7. **Strategie berechnen** (SAA/Optimizer) → **hier A1 scharf beobachten** (keine
   `CHART_RENDER_FAILED`); Donut + Kennzahlen-Tabelle + Projektionscharts rendern.
8. **SOLL/IST-Popup** öffnen (Vergleich rendert, Best/Worst-Endwert P90/P10, Sharpe je Spalte,
   Ziel-Erfolgswahrscheinlichkeit SOLL vs IST).
9. **Hover-Sync** über die Charts (Tooltips synchron, kein Ruckeln/Freeze).
10. **PDF-Report** erzeugen (anlagestrategie/assetallocation/risikoprofil) — öffnet, Zahlen stimmen mit
    der UI überein, Beträge in CHF, keine „USD"-Zeilen (vgl. #348), keine „CHF NaN" (vgl. #347).
11. **Klient wechseln** und zurück (KPIs/Charts zeigen den RICHTIGEN Klienten, kein „voriger Klient
    bleibt sichtbar" — vgl. #347/#351).

Jede Auffälligkeit als `Befund → Reproduktion → erwartet vs. ist` notieren (Bug-Report-Format).

---

## A3 — Pilot-Trockenlauf (1 echter Kunde)

Der eigentliche Freigabe-Schritt. Du bist der Fachexperte — wenn DU dem Report vertraust, bist du bereit.
1. Erfasse **einen** realen Kunden vollständig (Stammdaten, Vermögen inkl. Immobilie/Hypothek, Cashflows,
   Ziele, Risikoprofil).
2. Berechne die Strategie, öffne SOLL/IST + PDF.
3. **Gegenprüfung (fachlich):** stimmen Reinvermögen/Beratungsvermögen, die Cashflow-Summen, die
   Zielerreichung, die Kostenangaben (FIDLEG) mit deiner manuellen Erwartung überein?
4. Findings sammeln (erfahrungsgemäß 2–5 kleine UX/Fachpunkte) → als Task-Liste fixen.
5. **Freigabe:** wenn der Report fachlich korrekt + nachvollziehbar ist → bereit für den echten Termin.

---

## B1 — Steuer in Cashflow/Netto-Rendite (#39)  ← EINZIGE echte Code-Task

### Ist-Zustand (im Code)
- **Cashflow-Projektion:** Endpoint `routers/clients.py:397 cashflow_projection` aggregiert je Jahr
  `recurring_income/expense`, `income/expense`, `net`. Es gibt bereits ein **Muster für additive
  Jahres-Anpassungen**: `mortgage_interest_adjustment_series(...)` wird pro Jahr auf
  `recurring_expense`/`net` verrechnet (clients.py ~435–453). **Dieses Muster ist die Vorlage für die
  Steuer.**
- **Engine-Konsistenz:** dieselbe Serie muss an den Engine-Ladestellen mitgerechnet werden (wie #31
  es für die Hypothek an BEIDEN Ladestellen tat), damit SOLL/IST-Strategiekurven + MC + Reserve
  konsistent bleiben. Referenz: `portfolio_engine.py:2211 cashflow_projection_series_rappen`.
- **Tax-Plugin (fertig, #305):** `services/tax/registry.py:108 get_jurisdiction("CH")` →
  `estimate_income_tax(profile)` / `estimate_wealth_tax(profile)` (`jurisdictions/ch.py:133/167`),
  Eingabe `TaxProfileInput` (u.a. `taxable_income_rappen`, `taxable_wealth_rappen`, `canton`), Ausgabe
  `TaxEstimateResult` (`total_tax_rappen`). Private Kapitalgewinne sind korrekt steuerfrei.
- **Vorhandene Daten:** `models/clients.py:21 canton` ist da. **`taxable_income`/`taxable_wealth` sind
  NICHT erfasst** → für v1 aus vorhandenen Daten ableiten (kein neues UI nötig).

### Umsetzung — Schritt für Schritt
1. **Neue Service-Funktion** `services/tax_projection.py` (neu) —
   `annual_tax_expense_series(client, wealth_positions, cashflow_rows, horizon_years, start_year) -> list[int]`,
   analog zu `mortgage_interest_adjustment_series`:
   - `taxable_wealth_rappen` = Netto-Vermögen aus `wealth_positions` (Summe Assets − Liabilities), pro
     Jahr ggf. konstant (v1) oder mit der Projektion fortgeschrieben (v2).
   - `taxable_income_rappen` = Summe der **recurring-income**-Cashflows des Jahres (Erwerb/AHV/Rente;
     Mietertrag optional). Nutze die bereits vorhandene Jahres-Aggregation.
   - `regime = get_jurisdiction(client.country or "CH")`; baue `TaxProfileInput(taxable_income_rappen=…,
     taxable_wealth_rappen=…, canton=client.canton, …)`.
   - `tax = regime.estimate_income_tax(profile).total_tax_rappen + regime.estimate_wealth_tax(profile).total_tax_rappen`.
   - Rückgabe: Liste `[tax_year0, tax_year1, …]` (Rappen, ≥0).
2. **Endpoint** `clients.py cashflow_projection`: analog `_mort_adj` eine
   `_tax = annual_tax_expense_series(...)` bilden; pro Jahr `recurring_expense += _tax[i]`,
   `net -= _tax[i]`. **Hinter Flag** (siehe 4).
3. **Engine-Ladestellen:** dieselbe `_tax`-Serie additiv auf `cashflow_projection_series_rappen` an
   den zwei Engine-Ladestellen einrechnen (Muster #31 B), damit SOLL/IST-Kurven konsistent sind.
4. **Opt-in-Flag:** `include_tax_in_projection` — entweder Query-Param am Endpoint
   (`include_tax: bool = False`) ODER ein Feld am Client/Mandat (persistiert). Default **aus**
   (Rückwärtskompatibilität; nicht jeder Berater will die Schätzung).
5. **Frontend:** Toggle „Steuer in Projektion einrechnen" (Cashflow-/Strategie-Seite); bei aktiv eine
   AUTO-Ausgabe-Zeile „Steuern (geschätzt, CH)" mit dem Jahres-Betrag. Hinweistext: „Schätzung nach
   CH-Referenzwerten, keine Steuerberatung."
6. **(v2, optional)** explizite Felder `taxable_income_rappen`/`taxable_wealth_rappen` am Client für
   höhere Genauigkeit statt Ableitung — Model + additive_columns-Migration (Muster
   `database.py:216/249`) + Schema + FE.

### Tests / Akzeptanz
- `annual_tax_expense_series`: deterministisch; CH-Beispiel (z.B. Kanton ZH, Einkommen 150k, Vermögen
  1 Mio) liefert eine plausible Größenordnung; ≥0; steuerfreie Kapitalgewinne nicht enthalten.
- Endpoint: mit Flag sinkt `net_rappen` um exakt die Steuer-Serie; **ohne** Flag Projektion unverändert.
- Engine-Konsistenz: SOLL-Kurve auf der Strategie-Seite == Cashflow-Seiten-Kurve (wie #31 B-2).
- Regression: bestehende cashflow-projection- + tax-Tests bleiben grün.

---

## B2 — Miete inflationsindexiert (#34)  ✅ BEREITS FERTIG

Im Code verifiziert — **nichts zu tun außer im A2-Smoke gegenprüfen**:
- Model: `models/wealth.py:32 property_rental_inflation_linked` (INTEGER, server_default "0").
- Migration: `database.py:249 ('property_rental_inflation_linked','INTEGER',0)`.
- Ableitung: `services/wealth_cashflows.py:236` setzt beim abgeleiteten `rental_income`-Cashflow
  `inflation_linked=int(pos.property_rental_inflation_linked)`.
- Schema: `schemas/wealth.py:31/94/142` + Validator.
- **Frontend:** Checkbox `maw-immo-rent-inflation` (`5eyes_v2.html:4482`), Laden `:15420`, Speichern
  `:21408 payload.property_rental_inflation_linked`.
- **A2-Check:** Immobilie mit aktivierter Checkbox → Mietertrag-Cashflow wächst in der Projektion mit
  der Teuerung.

---

## B3 — goal_scope Gesamtvermögen (#33)  ✅ IMPLEMENTIERT (konservativ, #83)

Im Code verifiziert — **kein Code nötig, nur eine bewusste Methodik-Entscheidung**:
- `models/wealth.py:132 goal_scope` (Default „Beratungsvermögen"), Schema-Literal
  `["Beratungsvermögen","Gesamtvermögen"]` (`schemas/wealth.py:432`).
- `portfolio_engine.py:2689 _build_goal_analysis` hat `total_wealth_rappen` + rechnet
  `external_wealth_rappen = total − advisory` (:2709). Bei `goal_scope='Gesamtvermögen'` werden externe
  Assets **zusätzlich** berücksichtigt — aber **konservativ nur mit Teuerung (real 0 %, keine Vola)**,
  bewusst (ASIP §3.2; verhindert Drift zwischen deterministischer und MC-Bewertung). Kommentar
  `portfolio_engine.py:2713–2720`.
- **Entscheidung (nur falls gewünscht):** Willst du externe Assets MIT Wachstum (Aktien-Rendite)
  projizieren, ist das eine bewusste Methodik-Änderung — fachlich fragil, aktuell absichtlich NICHT so.
  Sonst: nichts zu tun.

---

## Zeitachse bis „erster echter Beratungskunde"
- **Nur Tier A (A1+A2+A3):** ~1 Woche (dominiert von deinem A1-Repro + dem A3-Pilotfall).
- **+ B1 (Steuer), falls für deine Kunden relevant:** +2–4 Tage.
- **B2/B3:** 0 (bereits gebaut).

## Empfohlene Reihenfolge
1. **A2 + A3 in einem Durchgang** (echter Fall) → sammelt gleichzeitig den A1-Repro + die Findings.
2. **A1-Punkt-Fix** aus der `CHART_RENDER_FAILED`-Zeile.
3. **B1** nur wenn deine ersten Kunden steuer-sensibel sind.
4. Termin.
