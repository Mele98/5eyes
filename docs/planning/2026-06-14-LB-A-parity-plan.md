# LB-B ≥ LB-A — Parity- & Überlegenheits-Plan (2026-06-14)

Ziel: LB-B' AA-Engine **vollkommen gleichwertig ODER überlegen** zu LB-A/iSAA (Swiss Life WM).
Grundlage: Vergleich gegen LB-A' eigenes iSAA-Methodik-Q&A (`individuel.pdf`) + AA-Screenshots.

**Leitprinzip:** Unseren **technischen Vorsprung behalten** (Chance-Constraints, Cornish-Fisher-Fat-Tails, deterministische Hash-Seeds, bedingte Ziele/Hardness, Hypothek-Amortisation, CHF-0-Daten, Tax-SDK) **UND LB-A' beste Beratungs-/Default-Stärken übernehmen**. Erst dann sind wir „gleich oder besser".

LB-A-Kern (belegt): Markowitz-Start → Suche → Simulation → Zielerreichung+Constraints prüfen → wiederholen. Zielfunktion = **beste Zielerreichung im schlechtesten Quartil (Downside)**, alle Ziele gemittelt. Constraints: Risk-Budget `%Aktien·0.79+%Obli·0.245+%Immo·0.5+%Alt·0.6`, max Immo 20%/Alt 10%, Building Blocks. Anzeige: **Zielerreichung ordinal + CHF-Fehlbetrag (Median & pessimistisch)**, Kennzahlen zweispaltig (Reinvermögen vs Beratungsvermögen).

---

## 🔴 P0 — die 3 großen Hebel (machen uns gleichwertig+)

- **PAR-1 [ENG] Stochastik-Optimizer zum Default machen.** Heute Default = House-Matrix+Tilt, Optimizer nur opt-in (`OPTIMIZER_MODE`). LB-A optimiert IMMER auf Zielerreichung. **Wie:** Shadow-Comparison §4-Gate (≥3 Mandate, GREEN-Mehrheit) auswerten → `optimizer_mode='stochastic'` als Default, House-Matrix bleibt garantierter Fallback (Status `fallback_house_matrix`). **Code:** config.optimizer_mode, services/optimizer/, portfolio_engine. **Risiko:** mittel (ändert Empfehlungen) → volle Regression + Shadow-Validierung zwingend. **Effort:** M.

- **PAR-2 [ENG] Downside-robuste Zielfunktion (schlechtestes Quartil).** LB-A optimiert Zielerreichung im Worst-Quartil, nicht im Erwartungswert. **Wie:** Objective-Term „goal_achievement @ P10/Worst-Quartil" ergänzen (wir haben MC-Pfade + Chance-Constraints schon); Zielerreichung = effektiv/gewünscht im Downside, gemittelt über Ziele (LB-A-Formel) — als wählbarer/zusätzlicher Objective-Mode. **Code:** services/optimizer/objective.py + goal_liabilities. **Risiko:** mittel. **Effort:** M.

- **PAR-3 [FE/BE] Zielerreichung ordinal + CHF-Fehlbetrag je Ziel (Median & pessimistisch).** LB-A' stärkste Beratungs-Darstellung. **Daten EXISTIEREN bereits:** `_monte_carlo_goal_summary` liefert P10/P50/P90 + success_rate je Ziel. **Wie:** pro Ziel `{median_achievement_pct, pessimistic_shortfall_rappen}` exponieren + Ordinalskala (0 / 0–7.5 / … / 95–100%); Frontend-Ziel-Tabelle wie LB-A (Spalten „Zielerreichung Median %" + „Fehlbetrag CHF (pessimistisch)"). **Code:** portfolio_engine goal-analysis payload + ares.html (Ziel-Sektion) + PDF. **Risiko:** niedrig (additiv, Anzeige). **Effort:** M (FE) + S (BE). → **bester Einstieg, sobald Codex committet hat.**

## 🟠 P1 — Feinabgleich an LB-A-Spec

- **PAR-4 [ENG] Alternatives-Risk-Budget 0.8 → 0.5 angleichen** (LB-A-konform, konservativer). **Achtung:** unsere 0.8 ist bewusst (PE+Krypto bis 100%). **Wie:** entweder auf 0.5 angleichen ODER dokumentierte, fachlich begründete Abweichung beibehalten (Maxime: konservativer Wert) — User-Entscheid. **Code:** risk_matrix / BB-Spec. **Risiko:** niedrig-mittel. **Effort:** S.
- **PAR-5 [ENG] Markowitz-informierter Startpunkt im Multi-Start.** LB-A startet von der Effizienzgrenze. **Wie:** eine MV-optimale Initial-Allokation (max Sharpe unter Constraints) zum bestehenden Multi-Start-Set (House-Matrix-Mid/Conservative/Aggressive/Risky-Edge) hinzufügen → bessere Konvergenz, Methodik-Parität. **Code:** services/optimizer/solver.py. **Risiko:** niedrig (nur zusätzlicher Startpunkt). **Effort:** M.
- **PAR-6 [ENG] Zielerreichungs-Definition exakt nach LB-A** (effektiv/gewünscht, Worst-Quartil, Mittelung) als referenzierbarer Modus — neben unserem feineren hardness-gewichteten Score. **Effort:** S (haben die Bausteine).

## 🟡 P2 — Output-/Beratungs-Parität (Berater-tauglich)

- **PAR-7 [FE] Kennzahlen zweispaltig „Reinvermögen vs. Beratungsvermögen"** (genau LB-A-Screenshot: Erwartete Rendite, Median-CAGR, Volatilität, Max Drawdown, VaR — beide Scopes). Wir haben `ub-return-rein/beratung` (zwei CAGRs) + SOLL/IST-Tabelle; ergänzen: vollständige 5-Kennzahlen-Spalten auch für die Scope-Sicht (total vs advisory). **Risiko:** niedrig. **Effort:** M.
- **PAR-8 [FE] Pessimistisches Szenario explizit** als eigene Spalte/Sicht (Median + Pessimistisch nebeneinander), nicht nur Best/Haupt/Worst der Kurve. **Effort:** S.
- **PAR-9 [FE] Age-Achse + Ziel-Marker** auf der Reinvermögens-Kurve — bei uns vorhanden (goalMarkers-Plugin, Age-Axis); gegen LB-A-Screenshot final eichen. **Effort:** S.
- **PAR-10 [PDF] Zielerreichung + Fehlbetrag + zweispaltige KPIs ins PDF** (abgestimmt mit Codex' Kostenausweis-Cluster). **Effort:** M.

## 🟢 P3 — Reife/Vertrauen (um „überlegen" statt nur „gleich" zu sein)

- **PAR-11 [DOC] Methodik-Whitepaper** (wie LB-A' `individuel.pdf`): unsere Engine erklärt (Solver, Chance-Constraints, Fat-Tails, Reproduzierbarkeit, Reserve, Ziel-Scoring) — für FINMA/Berater-Vertrauen.
- **PAR-12 [QA] Engine-Backtest** der Empfehlungen vs. realisierte Marktdaten (wir haben Backtest-Infra) → empirischer Überlegenheits-Nachweis.
- **PAR-13 [SEC] Externer Pentest + Audit** (LB-A ist FINMA-erprobt; das ist unser Reife-Rückstand).
- **PAR-14 [ENG] Building-Blocks-/Produkt-Universum erweitern** (LB-A/Swiss Life hat ein großes kuratiertes Universum).

---

## Wo wir bereits ÜBERLEGEN sind (halten/ausspielen!)
Chance-constrained Solver + DE-Fallback · Cornish-Fisher-Fat-Tails · deterministische Hash-Seeds (Audit) · bedingte Ziele/Hardness/AHV-Sonderfall · Hypothek-Amortisation in Projektion · SOLL-vs-IST-Vergleich · CHF-0-Datenstack · offene Tax-Plugin-SDK · Reasoning-Trace/Shadow-Gate.

## Reihenfolge-Empfehlung
**PAR-3** (Anzeige, additiv, sofort, kein Engine-Risiko) → **PAR-7/PAR-8** (Output-Parität) → **PAR-2 + PAR-1** (Downside-Objective, dann Optimizer-Default, mit Shadow-Validierung) → **PAR-5** (Markowitz-Start) → **PAR-4** (Risk-Budget-Entscheid) → P3 (Reife). Nach jedem Engine-Schritt volle Regression + Shadow-Vergleich.
