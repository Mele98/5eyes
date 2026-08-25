# Claude-Spec — Stochastic Goal Engine + Risk-Matrix als harte Suitability-Constraint

## Meta

- Titel: Stochastische Goal-Based Allocation als aktive Engine, Risk-Matrix als
  harter Suitability-Block (FINMA-konform)
- Datum: 2026-05-23
- Owner: Emanuele Konzelmann
- Antwort auf: `docs/planning/2026-05-23-stochastic-goal-engine-brief.md`
- Branch-Vorschlag: `codex/stochastic-active-engine`

## Ziel

Die Allocation-Engine vom `house_matrix`-Default auf eine **stochastische
Goal-Based-Optimierung** umstellen — methodisch näher an 3eyes — während die
**Risk-Matrix** (HouseMatrix.max_risky_fraction + BuildingBlock-Risky-Fractions)
zur **harten, FINMA-konformen Suitability-Schranke** ausgebaut wird. Das Risiko-
profil definiert das maximale Risikobudget; der Optimizer optimiert
Zielerreichung **innerhalb** dieses Budgets und meldet Zielkonflikte sauber,
statt das Profil zu übersteuern. House-Matrix bleibt Bandbreite, Plausibilitäts-
rahmen und Fallback. Frontend bleibt advisor-facing und ruhig.

## Problem

- `OPTIMIZER_MODE` ist heute `house_matrix`-Default; der vorhandene
  stochastische Solver (`services/optimizer/`, Phase 1-6 bereits gebaut) läuft
  nur opt-in. Damit fehlt 3eyes-Parität bei der Goal-Based-Allokation.
- Ein **Renditeziel** kann heute formal das Risikoprofil sprengen (es gibt
  keinen harten Optimizer-Constraint, der das Profil-Maximum gegen Renditeziele
  schützt — der Solver hat `build_risky_fraction_constraint`, aber sie wird
  nicht als unverletzliche Obergrenze gegen Ziel-Hardness geführt).
- Es existiert **keine saubere Trennung** der Zieltypen (Geldbetrag / Cashflow /
  Renditeprozent / abgeleitete Notwendigkeit). Der Goal-Editor erlaubt Felder,
  die je nach Typ irrelevant sind; Zieltyp-Feld-Isolation wird nicht durchge-
  setzt.
- **Zielkonflikte** (z.B. "5% Wunschrendite passt nicht ins Profil") werden
  nicht als Story erkannt — der Berater sieht keine klare Botschaft.
- Die `optimization_status`-Information landet in der TA, aber Review/PDF
  erklären dem Berater nicht in Kundensprache, **warum** die Allokation so
  aussieht und ob das Profil limitiert.

## Scope

- Risk-Matrix als Single Source of Truth (SSoT) für Risikogewichte; harte
  Constraint im Optimizer; identisch im Review/Reload/Report.
- Risikobudget aus Risikoprofil-Score (HouseMatrix.max_risky_fraction) als
  unverletzliche Schranke; jede Ziel-Hardness bleibt **untergeordnet**.
- Goal-Typ-Modell mit Feld-Isolation und Backend-Validierung (Schema-Level).
- Mehrziel-Logik: 1 Hauptziel (Pflicht) + bis zu 4 Nebenziele, Hardness-Levels
  bleiben (hart / primär / opportunistisch); klare Konflikt-Detektion.
- Stochastische Zielfunktion: bestehender Squared-Shortfall (objective.py)
  bleibt Primärtreiber; **Chance Constraint** `P(Hauptziel erreicht) ≥ τ`
  ergänzt (default τ=80%, owner-konfigurierbar pro Mandat).
- Konflikt-/Fehlermeldungen advisor-facing in Kundensprache, niemals als
  Aufforderung zur Risikoerhöhung.
- 3eyes-Parität: `stochastic` wird Default; `house_matrix` bleibt Fallback bei
  Solver-Divergenz; `shadow_stochastic` als Übergangsmodus.
- Frontend-Cockpit: Review/Zusammenfassung erklärt Hauptziel, Zielerreichungs-
  wahrscheinlichkeit, limitierender Faktor (Risikoprofil / Konflikt / Solver),
  Allokations-Treiber.
- API/Persistenz/Report-Vertrag pro Zieltyp.

## Nicht-Scope

- Kein neues Risikoprofil-Fragenwerk (FINMA-Vorlage bleibt).
- Kein Umbau der `services/optimizer/`-Architektur (Phase 1-6 ist gut); nur
  Constraint-Härte, Goal-Datenvertrag und Default-Mode ändern.
- Kein FX/Currency-Umbau der Allocation-Engine (Backtest U-P19b ist FX-korrekt;
  Allocation-Engine bleibt in CHF-Annahmen aus CMA).
- Kein Re-Design der Risk-Matrix-Werte selbst (BuildingBlock-Defaults stammen
  aus 3eyes-Slide 17, sind verifiziert).
- Keine Goal-Editor-UX-Revolution — nur Feld-Isolation und klare Konflikt-
  Anzeige, sonst bleibt der ruhige Stil.

## §1 Risikobudget-Logik

### 1.1 Risk-Matrix als Single Source of Truth

**Definition:** Die Risk-Matrix ist die Kombination aus
1. **HouseMatrix** (`models/allocation.py:242`) — pro Risikoprofil-Score-Bereich
   (`score_from..score_to`) ein **Band** mit `risky_fraction_bps` (Band-Mid)
   und `max_risky_fraction_bps` (harte Obergrenze).
2. **BuildingBlock.risky_fraction_bps** (`allocation.py:55`) — pro Asset-Klasse
   das Risikogewicht, aus dem die Portfolio-Risikogewichtung gebildet wird.

**Portfolio-Risikogewichtung** (in bps von 0 = risikolos bis 10000 = max risky):
```
risky_fraction_portfolio = Σ_b  w_b · risky_fraction_b
```
wobei `w_b ∈ [0,1]` die Asset-Klassen-Quote (bps/10000) und `risky_fraction_b`
aus dem aktiven BuildingBlock-Set des Mandats kommt (Standard / Alternativ).
Implementierung existiert in `services/optimizer/constraints.py:180`
(`bucket_risky_fractions_from_building_blocks`).

### 1.2 Risikobudget aus Risikoprofil

**Mapping:** `final_score_x10` (Risikoprofil 1.0–10.0) → `score_bucket` (1–10,
gerundet) → HouseMatrix-Zeile → `max_risky_fraction_bps`.

`max_risky_fraction_bps` ist die **unverletzliche Obergrenze**. Ein Override
(`is_overridden=1` mit `override_score_x10` und `override_reason`) **muss**
explizit dokumentiert sein; ohne dokumentierten Override darf das Profil nicht
nach oben übersteuert werden.

### 1.3 Harte Constraints für den Optimizer

Der Solver MUSS folgende Constraints in seinem Feasibility-Set durchsetzen:

1. **Sum-to-one:** `Σ w_b = 1` (bps-Summe = 10000) — `build_sum_to_one_constraint`.
2. **Band-Bounds:** pro Asset-Klasse `lo_b ≤ w_b ≤ hi_b` aus HouseMatrix-Band
   (oder OptimizerPolicy-Override) — `build_bounds`.
3. **Risikobudget-Cap:** `risky_fraction_portfolio ≤ max_risky_fraction_bps`
   des Profil-Buckets — `build_risky_fraction_constraint` (existiert; muss
   jetzt **immer** Teil des Constraint-Sets sein, nicht nur im stochastic-Modus).
4. **Liquiditäts-Mindestreserve:** `w_liquidity ≥ min_liquidity_bps` aus
   OptimizerPolicy/Goals-Reserve (bereits in `generate_target_allocation`).
5. **Konzentrationslimiten** je Asset-Klasse aus OptimizerPolicy
   (max_real_estate_bps, max_alternatives_bps).

**OWNER-DECISION OD-A** *(setzen):* Der Risikobudget-Cap (#3) ist **strikt**,
ohne Slack-Toleranz. Eine Verletzung (auch numerische `1e-6`-Drift) → Constraint
ist gerissen → Solver-Status `diverged_infeasible` → Fallback auf
House-Matrix-Mid (siehe §1.5). Begründung: FINMA-Eignungsprüfung darf nicht
durch numerische Drift unterlaufen werden.

### 1.4 Konsistenz Frontend ↔ Backend ↔ Persistenz ↔ Reload ↔ Review

Die effektive Risikogewichtung wird **einmal** im Backend
(`compute_portfolio_risky_fraction_bps(allocation_bps, mandate)`) berechnet
und in `TargetAllocation.risky_fraction_bps_at_generation` (neue Spalte)
persistiert. Frontend (Strategiesummary, Review-KPI), Reload (`current/payload`)
und Report (PDF) lesen identisch aus dieser persistierten Zahl — kein
Re-Compute mit potenziell anderen Defaults.

### 1.5 Solver-Divergenz → Fallback

Wenn der Solver `diverged_infeasible` (Risikobudget nicht erreichbar) ODER
`diverged` (Konvergenzfehler) zurückgibt:
- Engine fällt auf **House-Matrix-Mid** zurück (existierender Pfad).
- `TargetAllocation.optimization_status = "fallback_house_matrix"`.
- Warnung in `warnings`: *"Optimizer konnte unter den aktuellen Constraints
  nicht konvergieren — Strategie auf Bandbreiten-Mittelwerte des
  Risikoprofils zurückgesetzt. Bitte Ziele/Constraints prüfen."*
- Review/PDF zeigen den Fallback-Status sichtbar.

## §2 Ziel- und Renditelogik

### 2.1 Zieltypen (kanonisch)

Drei Familien, die mathematisch unterschiedlich behandelt werden:

| Familie | Goal-Type-Werte | Liability-Schema (existiert) |
|---|---|---|
| **Vermögensziel** (Punkt-in-Zeit) | `Vermoegensziel`, `Einmalige_Ausgabe` | wealth_at_t |
| **Cashflow-Ziel** (Strom) | `Pensionsausgabe`, `Wiederkehrende_Ausgabe` | outflow_stream |
| **Renditeziel** (annualisiert) | `Renditeziel` | return_rate |
| **Wachstumsziel** (kein Target) | `Maximierung` | maximize |

`goal_liabilities.py` normalisiert Goal-Type-Strings bereits via
`_GOAL_TYPE_NORMS` (Z. 166). Die drei Familien existieren als Liability-Schemas.

### 2.2 Feld-Isolation pro Zieltyp

**Schema-Level-Regel (`schemas/wealth.py` GoalCreate/GoalUpdate):**

| Feld | Vermögensziel | Cashflow-Ziel | Renditeziel | Maximierung |
|---|---|---|---|---|
| `target_amount_rappen` | **Pflicht** | optional (Stream-Höhe) | verboten | verboten |
| `target_return_bps` *(NEU)* | verboten | verboten | **Pflicht** | verboten |
| `target_date` / `target_year` | **Pflicht** | optional | optional (Horizont) | verboten |
| `frequency` | verboten | **Pflicht** (`jährlich`/`monatlich`) | verboten | verboten |
| `duration_years` | verboten | optional (Bezugsdauer) | verboten | verboten |
| `hardness` | erforderlich | erforderlich | erforderlich (i.d.R. `Primär`) | erforderlich (`Opportunistisch`) |
| `priority_rank` | erforderlich | erforderlich | erforderlich | optional |
| `success_probability_min_x100` *(NEU)* | optional (default 80) | optional (default 80) | optional (default 50) | n/a |

**OWNER-DECISION OD-B:** Neues Feld `target_return_bps` (Integer) auf der `goals`-
Tabelle ergänzen (additive_columns), nullable. Existierende Felder bleiben
unverändert. Validierung in Schema lehnt verbotene Felder pro Typ mit klarer
Meldung ab ("Feld 'X' ist für Zieltyp 'Y' nicht erlaubt").

### 2.3 Übersetzung Rendite ↔ Geld

Der stochastische Engine arbeitet intern mit **Wealth-Pfaden** (CHF-Endwerte
je Szenario). Renditeziele werden konsistent übersetzt:

- **Renditeziel → implizites Vermögensziel:**
  `target_wealth = initial_value · (1 + target_return)^horizon`.
  Shortfall wird gegen dieses implizite Vermögensziel berechnet (kompatibel
  mit `wealth_at_t`-Liability).
- **Vermögens-/Cashflow-Ziel → notwendige Rendite (Diagnose):**
  `required_return = (target / initial_value)^(1/horizon) − 1` (für Punkt-
  Ziele) bzw. PV-Solver für Cashflow-Ziele. Wird im Review als
  *"Für dieses Ziel wären ≈ X% p.a. nötig"* angezeigt — **Kennzahl, nie
  Garantieversprechen**.

**OWNER-DECISION OD-C:** Renditeziele werden für die Optimierung intern auf
`wealth_at_t`-Liabilities gemappt (gemeinsame Zielfunktion). Die Anzeige
unterscheidet aber sauber zwischen "Wunschrendite" und "abgeleitete
notwendige Rendite" (Review-UX, siehe §7).

### 2.4 "Nicht plausibel erreichbar"

Ein Ziel `g` ist **nicht plausibel erreichbar**, wenn unter dem max. zulässigen
Risikobudget die Zielwahrscheinlichkeit unter eine harte Schwelle fällt:

```
P(wealth_T ≥ target_g | w*, max_risky_fraction) < τ_unreachable
```

**OWNER-DECISION OD-D:** `τ_unreachable = 50%`. Heißt: das Ziel hat selbst bei
voller Ausschöpfung des Risikobudgets ≤ 50% Eintrittswahrscheinlichkeit. Das
ist die Schwelle, ab der die Engine einen **harten Zielkonflikt** meldet (vs.
"knapp erreichbar" bei 50–80%, "komfortabel" bei ≥80%).

## §3 Mehrziel-Logik

### 3.1 Struktur

- **1 Hauptziel (Pflicht):** das Ziel mit höchstem `priority_rank=1`; ist
  Pflichtfeld beim Mandate-Save. Hardness in der Regel `Primär` oder `hart`.
- **0–4 Nebenziele:** `priority_rank ∈ {2,3,4,5}`; Hardness frei wählbar
  (typisch `Primär` oder `Opportunistisch`).
- Mehr als 5 Ziele → Schema lehnt mit klarer Meldung ab ("Maximal 1 Hauptziel
  und 4 Nebenziele für klare Beratung").

### 3.2 Hardness und Priorität

Bestehende Hardness-Multiplier bleiben (OD-1 aus 5.5.2026):
- `hart` = 10 × Shortfall-Gewicht
- `primär` = 1 × Shortfall-Gewicht
- `opportunistisch` = 0.2 × Shortfall-Gewicht

**Neu (OWNER-DECISION OD-E):** Zusätzlich Prioritäts-Gewicht
`priority_weight = 1.0 / priority_rank` (Hauptziel = 1.0, Nebenziel-2 = 0.5,
…). Die effektive Gewichtung im Objective:
```
weight_g = hardness_mult_g · priority_weight_g
```
Verhindert, dass ein hartes Nebenziel das Hauptziel mathematisch dominiert,
ohne dass der Berater bewusst die Hardness-Hierarchie setzt.

### 3.3 Welche Ziele dürfen "hart" sein

**OWNER-DECISION OD-F:** Nur **echte Bedarfsziele** dürfen `hart` sein:
- Liquiditätsreserve (immer hart, separater Mechanismus über
  `policy.min_liquidity_bps`).
- Lebenshaltungs-Entnahme im Ruhestand (`Pensionsausgabe`).
- Mindestkapital-Erhalt (`Vermoegensziel` mit `target_amount = initial_value`).

**Renditeziel darf NIE `hart` sein.** Schema enforced. Begründung: Hartes
Renditeziel würde Suitability-Bruch erzwingen — explizit verboten.

### 3.4 Zielkonflikt-Detektion

Ein **Zielkonflikt** liegt vor, wenn nach Optimierung mindestens ein Ziel mit
Hardness ≥ `primär` unter τ_unreachable fällt:
```
exists g where hardness_g ∈ {hart, primär}
       and P(g erreicht) < τ_unreachable
```
Konflikt-Klassen (für UX-Meldung):
- **Profil-Konflikt:** das Risikoprofil-Cap limitiert (Lösung: Ziel anpassen
  ODER Eignungsprüfung wiederholen ODER Sparrate/Horizont anpassen).
- **Mehrziel-Konflikt:** zwei Ziele schließen sich gegenseitig aus (z.B.
  hartes Pensionsziel + Wunsch nach Kapitalerhalt mit zu kurzem Horizont).
- **Datenkonflikt:** Initial-Kapital + Cashflow + Horizont liefern zu wenig
  PV gegen das Ziel — kein Optimizer-Problem, sondern Eingabeproblem.

### 3.5 Shortfall-Maß

**OWNER-DECISION OD-G:** Shortfall bleibt **absolut in CHF** (existierender
Squared-Shortfall in `objective.py`: `max(0, target − wealth)^2`). Begründung:
Beraterintuition, FINMA-Reporting, konsistent mit Wealth-Sim-Output. Relative
Shortfalls (% des Ziels) sind Anzeige-Kennzahl im Review, nicht
Optimierungs-Metrik.

## §4 Stochastische Zielfunktion

### 4.1 Primärobjective (unverändert, Slide 18)

```
L(w) = Σ_g  weight_g · (1/N) · Σ_n  max(0, target_g − wealth_g(w, n))^2
```
mit `weight_g = hardness_mult_g · priority_weight_g` (OD-E). Existiert in
`services/optimizer/objective.py`.

### 4.2 Chance Constraint (NEU)

Zusätzlich pro hartem oder primärem Ziel:
```
P(wealth_g(w) ≥ target_g) ≥ τ_g
```
mit `τ_g = goals.success_probability_min_x100 / 10000` (default 80% für
Vermögens-/Cashflow-Ziele, 50% für Renditeziele — OD-B). Implementiert als
Penalty mit Lagrange-Multiplikator `λ_chance` (statt harte Constraint im
SLSQP — analytisch nicht differenzierbar):

```
L'(w) = L(w) + λ_chance · Σ_g  max(0, τ_g − P_g(w))^2
```

**OWNER-DECISION OD-H:** `λ_chance = 1e6` (Soft-Strict: praktisch
unverletzlich, aber Solver kommt nicht in Sackgasse). Wenn Chance Constraint
nicht erfüllbar (Risikobudget zu klein) → Ziel als "nicht erreichbar"
klassifiziert (§2.4), Konflikt-Meldung (§3.4) — kein Suitability-Bruch.

### 4.3 Sekundärobjective (unverändert)

Wenn `L'(w) ≈ 0` (alle Ziele erfüllt), minimiert der Solver die Varianz des
Endvermögens (existierend in objective.py).

### 4.4 Sekundäre Risikomaße (Kennzahl, nicht Optimierung)

Volatilität, Max-Drawdown, P10/P50/P90 werden für jedes Solver-Ergebnis
berechnet und in der Response geliefert. Sie sind **Diagnose**, nicht
Optimierungs-Treiber (Vermeidung von Wechselwirkungen mit Squared-Shortfall).

### 4.5 Erklärbarkeit

Pro Solver-Lauf wird ein **Reasoning-Trace** (existierend Phase 6.2,
`target_allocations.optimizer_reasoning_json`) erweitert um:
- *Bindende Constraints* (Liste der aktiven KKT-Constraints am Optimum).
- *Treibendes Ziel* (höchstes `weight_g · marginal_shortfall_g`).
- *Limitierender Faktor* (eines aus: `risikoprofil`, `liquiditaetsreserve`,
  `bandbreite`, `zielkonflikt`, `solver_konvergenz`).

Format:
```json
{
  "binding_constraints": ["risky_fraction_cap", "liquidity_floor"],
  "driving_goal_id": "...",
  "limiting_factor": "risikoprofil",
  "achievability": [
    {"goal_id":"...", "probability":0.86, "status":"erreichbar"},
    {"goal_id":"...", "probability":0.42, "status":"nicht_erreichbar"}
  ]
}
```

## §5 Fehler- und Konfliktmeldungen

### 5.1 Meldungs-Katalog (advisor-facing)

| Code | Situation | Beispieltext |
|---|---|---|
| `OK_COMFORTABLE` | Alle harten/primären Ziele P ≥ 80% | *"Alle Ziele sind innerhalb des Risikoprofils komfortabel erreichbar (P ≥ 80%)."* |
| `OK_TIGHT` | Mindestens 1 Ziel 50–80% | *"Das Ziel «X» ist mit Ihrem Risikoprofil knapp erreichbar (≈ 65%). Eine höhere Sparrate, ein längerer Horizont oder eine Anpassung des Zielbetrags würde die Wahrscheinlichkeit erhöhen."* |
| `CONFLICT_PROFILE_LIMITS` | Hartes/primäres Ziel < 50%, Risikoprofil ist bindend | *"Das gewünschte Renditeziel ist mit dem aktuellen Risikoprofil nicht plausibel erreichbar. Eine höhere Zielrendite würde ein höheres Risikobudget erfordern. Bitte Ziel, Horizont, Sparrate, Entnahme oder Risikoprofil im Rahmen einer neuen Eignungsprüfung prüfen."* |
| `CONFLICT_GOAL_INCOMPATIBLE` | Zwei harte/primäre Ziele schließen sich aus | *"Die Ziele «Pensionsentnahme» und «Kapitalerhalt» stehen mit dem aktuellen Vermögen und Horizont im Konflikt. Eine Priorisierung oder Zielanpassung ist nötig."* |
| `CONFLICT_DATA_INSUFFICIENT` | Kapital + Cashflow + Horizont ergeben < PV des Ziels | *"Aus dem heutigen Vermögen, den geplanten Zuflüssen und dem Anlagehorizont lässt sich das Ziel «X» mathematisch nicht decken. Bitte Daten und Zielbetrag prüfen."* |
| `WARN_FALLBACK` | Solver divergent → House-Matrix-Mid | *"Optimierer hat nicht konvergiert. Strategie wurde auf die Bandbreiten-Mitte des Risikoprofils zurückgesetzt — bitte Constraints und Ziele prüfen."* |
| `WARN_OVERRIDE` | Risikoprofil-Override aktiv | *"Das Risikoprofil wurde manuell auf «X» übersteuert (Begründung: ...). Die Allokation nutzt diesen Override; die ursprüngliche Eignungsprüfung bleibt dokumentiert."* |

### 5.2 Verbote

- **Keine Aufforderung zur automatischen Risikoerhöhung.** Die Meldung darf
  Übersteuerung des Profils nur als advisor-geprüfte, dokumentierte Option
  nennen, nicht als Automatismus.
- **Keine Garantieversprechen.** "Erreichbar" ist immer als Wahrscheinlichkeit
  ausgewiesen, nie als "wird erreicht".

## §6 3eyes-Parität

### 6.1 Was 5eyes heute schon hat

- Stochastischer Solver (SLSQP + GA-Fallback, Phase 1-6 fertig).
- Cornish-Fisher Fat-Tail-Sampling.
- Goal-Liability-Konversion für 7 Goal-Typen.
- Scenario-Cache für Performance.
- Persistierte Audit-Anchor (method, status, seed, reasoning).
- Sensitivity-Endpoint (`/sensitivity`).
- House-Matrix als Fallback.

### 6.2 Echte methodische Lücken (Closing in dieser Spec)

| Lücke | Adressiert in §  |
|---|---|
| Risikobudget-Cap ist nicht hart durchgesetzt im Default-Mode | §1.3 (OD-A) |
| Renditeziel kann Profil mathematisch sprengen (hart erlaubt) | §3.3 (OD-F) |
| Zielwahrscheinlichkeit fließt nicht in Optimierung ein | §4.2 (Chance Constraint) |
| Konflikte werden nicht klassifiziert / als Story erklärt | §3.4 + §5 |
| Feld-Isolation pro Zieltyp fehlt | §2.2 (OD-B) |
| Review erklärt limitierenden Faktor nicht | §7 + Reasoning-Trace §4.5 |

### 6.3 Übergangsmodus `shadow_stochastic`

Bleibt für 1–2 Sprints als Vergleichsmodus: beide Engines laufen, House-Matrix
wird angezeigt, Stochastic in `TargetAllocation.shadow_optimization_json`
persistiert. Berater kann Drift evaluieren. Default-Wechsel auf `stochastic`
erst nach belastbarem Shadow-Vergleich (siehe §10 Acceptance).

## §7 Frontend / Advisor-Cockpit

### 7.1 Goal-Editor (`m-acf` / `m-nz`)

- Zieltyp-Dropdown wählt zuerst die Familie (Vermögens-/Cashflow-/Renditeziel).
- Felder werden **typabhängig ein-/ausgeblendet** (Feld-Isolation).
- Hardness-Dropdown: für `Renditeziel` ist `hart` ausgeblendet/disabled
  (OD-F enforced auch im UI).
- Live-Anzeige: *"≈ X% p.a. notwendig"* (abgeleitete Rendite) für
  Geld-/Cashflow-Ziele; *"≈ CHF Y nötig"* (impliziertes Vermögensziel) für
  Renditeziele.

### 7.2 Review-Cockpit (`page-rv` / `m-rv`)

Zenit der App. Sichtbar **ohne Klick**:
- **Hauptziel** als KPI-Tile mit Zielerreichungs-Wahrscheinlichkeit (Ampel:
  ≥80% grün, 50–80% gelb, <50% rot).
- **Limitierender Faktor** als Badge (aus Reasoning-Trace §4.5):
  *"Risikoprofil limitiert"* / *"Zielkonflikt"* / *"Bandbreite limitiert"*.
- **Zielerreichungs-Liste** (alle Ziele mit P + Hardness + Status).
- **Allokations-Treiber** als 1-Satz-Erklärung:
  *"Die Allokation maximiert die Wahrscheinlichkeit des Hauptziels innerhalb
  Ihres Risikoprofils. Hauptbindung: Risikobudget des Profils «Wachstum» (max
  72% risikobehaftet)."*

Komplexität (Solver-Iterations, Scenarios, KKT-Details) bleibt in
`<details>`-Accordion verborgen.

### 7.3 Asset-Allocation-Seite (`page-al`)

- Optimizer-Panel zeigt `optimization_status` + `limiting_factor` als
  Badges (schon teilweise da via Phase 6 FE).
- Konflikt-Meldungen (§5.1) erscheinen oben als Banner-Card mit klarer
  Handlungsaufforderung; nicht als verstreute Warnings.

### 7.4 Was NICHT auf den Hauptscreen darf

- Solver-Logs, KKT-Multiplier, Iterations-Counter, Scenario-Anzahl.
- Volatilitäts-bps, Sharpe-Decimals → in Details/Accordion.
- Mathematische Formeln, Lagrange-Sprache.

## §8 API-, Persistenz- und Report-Vertrag

### 8.1 Goal-Schema (Request/Response)

`POST /mandates/{id}/goals` und `GET .../goals`:

```json
{
  "id": "...",
  "goal_type": "Renditeziel" | "Vermoegensziel" | "Pensionsausgabe" | ...,
  "label": "...",
  "hardness": "hart" | "primär" | "opportunistisch",
  "priority_rank": 1,
  "target_amount_rappen": 1500000000,  // verboten für Renditeziel
  "target_return_bps": 500,             // NEU; nur für Renditeziel
  "target_date": "2040-01-01",
  "frequency": "jährlich",              // nur für Cashflow-Ziel
  "duration_years": 25,                 // nur für Cashflow-Ziel
  "success_probability_min_x100": 8000  // optional, default 80% / 50%
}
```

Schema validiert Feld-Isolation (§2.2). Backend lehnt mit 422 ab und gibt
das verletzte Feld + die Regel zurück.

### 8.2 TargetAllocation-Erweiterung

Additive Spalten (`additive_columns` in database.py):
- `risky_fraction_bps_at_generation` (INTEGER) — die effektive Risiko-
  gewichtung des persistierten Portfolios.
- `risk_budget_bps_at_generation` (INTEGER) — `max_risky_fraction_bps` des
  Profil-Buckets zum Zeitpunkt der Berechnung.
- `limiting_factor` (TEXT) — eines der §4.5-Werte.
- `goal_achievability_json` (TEXT) — Liste {goal_id, probability, status}.

### 8.3 Reload (`current/payload`)

Liefert deterministisch:
- `target_allocation` inkl. `risky_fraction_bps_at_generation`,
  `risk_budget_bps_at_generation`, `limiting_factor`.
- `goal_achievability` aus persistiertem JSON.
- `optimizer_reasoning` aus persistiertem JSON (Phase 6.2).
- `messages`: Liste von Konflikt-/Status-Meldungen (§5.1) — generierte Codes
  + ausformulierte Texte (i18n-fähig). Identisch im Review-UI **und** im PDF.

### 8.4 Report/PDF

- Anlagestrategie-PDF (`anlagestrategie.pdf`): zeigt im Strategiebegründungs-
  Abschnitt den `limiting_factor` + die `goal_achievability` als Tabelle.
- Risikoprofil-PDF (`risikoprofil.pdf`): unverändert (FINMA-Vorlage).
- Protokoll-PDF (`protokoll.pdf`): bei Konflikt-Codes
  (`CONFLICT_*`, `WARN_*`) Hinweistext aus Katalog.

Keine UI-Controls ohne Engine-Wirkung. Keine still verpuffenden Felder.

## §9 Codex-Umsetzungsplan

Reihenfolge ist wichtig — jede Stufe muss grün sein, bevor die nächste startet.

### Stufe 1 — Datenmodell + Schema (klein, isoliert, schnell testbar)

1. `models/wealth.py Goal`: Spalte `target_return_bps` (Integer, nullable),
   `success_probability_min_x100` (Integer, nullable).
2. `database.py additive_columns['goals']`: beide hinzufügen.
3. `schemas/wealth.py GoalCreate/GoalUpdate`: pro `goal_type` validate Feld-
   Isolation (§2.2-Tabelle). Verbotene Felder → 422 mit klarem Fehler.
4. `models/allocation.py TargetAllocation`: Spalten
   `risky_fraction_bps_at_generation`, `risk_budget_bps_at_generation`,
   `limiting_factor`, `goal_achievability_json` (alle nullable).
5. `additive_columns['target_allocations']` ergänzen.
6. Tests: 4–6 Schema-Validierungs-Tests (jeder verbotenen Feld-Kombi 1 Test).

### Stufe 2 — Risikobudget-Cap als immer-aktive Constraint

1. `services/optimizer/constraints.py`: `build_risky_fraction_constraint`
   liest jetzt zwingend aus HouseMatrix für den aktuellen Score-Bucket
   (heute scheinbar nur aus BuildingBlocks). Default-Mode `house_matrix` muss
   die Constraint **auch ohne stochastic** prüfen: nach jeder allocation-
   Generierung Validation-Step `assert_risk_budget_ok(allocation, mandate)`.
2. `services/portfolio_engine.py generate_target_allocation`: nach Build der
   Allocation (egal welcher Mode) `risky_fraction_portfolio` berechnen, gegen
   `max_risky_fraction_bps` prüfen; bei Verletzung → Fallback auf House-
   Matrix-Mid + Warning `WARN_FALLBACK`.
3. Persistieren: `risky_fraction_bps_at_generation` +
   `risk_budget_bps_at_generation` in jeder generierten TA.
4. Tests: synthetische Allocation, die das Cap reisst → Fallback; OK-Fall →
   Cap eingehalten.

### Stufe 3 — Chance Constraint + Achievability

1. `services/optimizer/objective.py`: Penalty-Term für Chance Constraint
   ergänzen (`λ_chance=1e6`, OD-H).
2. `services/optimizer/solver.py`: nach Konvergenz pro Goal
   `P(wealth_g ≥ target_g)` aus den Wealth-Pfaden berechnen; Liste in
   Solver-Result.
3. `generate_target_allocation`: `goal_achievability_json` befüllen + im
   Reasoning-Trace `limiting_factor` setzen (`risikoprofil` /
   `liquiditaetsreserve` / `bandbreite` / `zielkonflikt` / `solver_konvergenz`).
4. Tests: Goal-Set mit τ=99% (unerreichbar) → status `nicht_erreichbar`,
   limiting_factor `risikoprofil`. Goal-Set komfortabel → `erreichbar`,
   limiting_factor sinnvoll (z.B. `bandbreite`).

### Stufe 4 — Messages-Katalog + Konflikt-Detektion

1. Neues Modul `services/allocation_messages.py`:
   `classify_messages(allocation, achievability, optimization_status,
   mandate, assessment) -> list[Message]` mit allen 7 Codes aus §5.1.
2. In `generate_target_allocation` aufrufen, Resultat in Response unter
   `messages` + persistiert (z.B. als Teil von `optimizer_reasoning_json`).
3. Tests: jeder der 7 Codes mit synthetischem Fixture.

### Stufe 5 — Default-Mode-Wechsel + Shadow

1. `OPTIMIZER_MODE` Default bleibt zunächst `house_matrix`. Codex setzt im
   Code-Pfad einen feature-flag-Schalter, der den **Shadow-Lauf** (beide
   Engines, House-Matrix sichtbar, Stochastic protokolliert) jederzeit
   einschaltet.
2. `shadow_stochastic`-Mode (existiert konzeptionell) implementieren:
   beide Allocations berechnen, `TargetAllocation.shadow_optimization_json`
   persistieren (Drift-Vektor + Reasoning).
3. Admin-UI: ein Schalter in Optimizer-Policy "Modus: house_matrix /
   shadow_stochastic / stochastic"; Default-Wechsel auf `stochastic`
   bleibt der **letzte** Codex-Schritt nach erfolgreichem Shadow-Vergleich
   (§10 Acceptance).
4. Tests: Shadow-Mode persistiert beide Resultate, ändert sichtbare
   Allocation nicht.

### Stufe 6 — Frontend (Goal-Editor + Review)

1. `5eyes_v2.html m-acf` / Goal-Editor: typabhängige Feldsichtbarkeit
   (Renditeziel zeigt `target_return_bps`-Input, blendet `target_amount`
   aus). `hart`-Option in Hardness-Dropdown für Renditeziel disabled.
2. Live-Anzeige der abgeleiteten Rendite / des implizierten Vermögensziels
   (clientseitig, da nur Anzeige).
3. Review-Cockpit (`page-rv` / `m-rv`): KPI-Tile Hauptziel mit P-Ampel,
   `limiting_factor`-Badge, `messages`-Banner-Card.
4. Allocation-Page (`page-al`): Optimizer-Panel zeigt `limiting_factor` +
   `messages`.
5. Inline-JS-Parse 0 Fehler. Contract-Tests für jede sichtbare Komponente.

### Stufe 7 — PDF-Reports

1. `services/pdf/documents/anlagestrategie.py`: Sektion
   "Strategie-Begründung" zeigt `limiting_factor` + Achievability-Tabelle.
2. `services/pdf/components/`: ggf. neue Komponente `goal_achievability.py`.
3. Tests: PDF enthält die neuen Strings + Tabellen-Struktur (Struktur-
   Assertions, nicht nur `%PDF`).

### Stufe 8 — Verifikation

- `python -m pytest -p no:cacheprovider tests/ -q` → muss grün bleiben.
- Inline-JS-Parse 0 Fehler.
- Shadow-Vergleich auf Foundation-Fall: Drift in jedem Bucket < 10 Prozent-
  punkte (Smoke-Test); falls größer → Reasoning klärt warum.
- Mindestens 1 manueller E2E-Durchlauf in Electron mit jedem
  Konflikt-Szenario aus §5.1.

## §10 Acceptance Criteria

1. **Risikoprofil unverletzlich:** `risky_fraction_bps_at_generation ≤
   risk_budget_bps_at_generation` in **jeder** persistierten TA (Test:
   property-based über 100 Random-Mandate-Configs).
2. **Renditeziel kann nicht erzwungen werden:** ein Goal mit
   `goal_type=Renditeziel` + `hardness=hart` wird vom Schema mit 422
   abgelehnt.
3. **Zielkonflikt sichtbar:** ein Goal-Set mit harten unvereinbaren
   Zielen produziert ≥ 1 `CONFLICT_*`-Message + `limiting_factor` ≠
   `bandbreite`. Review-UI zeigt diese Message als Banner.
4. **Achievability persistiert:** `current/payload` liefert ohne neuen
   Solver-Lauf identische `goal_achievability` + `limiting_factor` wie
   die erste `generate`-Response.
5. **Geld- vs. Renditeziel sauber:** Schema-Tests für alle 4 verbotenen
   Feld-Kombinationen aus §2.2.
6. **Mehrziel-Priorität:** Test, dass ein hartes Nebenziel das
   Hauptziel **nicht** dominiert (Hauptziel-P bleibt ≥ Nebenziel-P unter
   Standardwerten).
7. **Shadow-Modus verändert sichtbare Allocation nicht:** in
   `shadow_stochastic` ist die Frontend-Allocation = House-Matrix-Resultat;
   nur `shadow_optimization_json` persistiert.
8. **Solver-Divergenz → Fallback sichtbar:** synthetischer Infeasible-Fall
   → `optimization_status=fallback_house_matrix` + `WARN_FALLBACK` in
   Messages + sichtbar im Review.
9. **PDF konsistent:** `anlagestrategie.pdf` enthält `limiting_factor`
   und Achievability-Tabelle; die Werte sind bit-identisch zu
   `current/payload`.
10. **Default-Wechsel auf `stochastic`** erst nach grünem Shadow-Vergleich
    auf Foundation-Case + 3 realen Mandaten (manueller Smoke-Test
    dokumentiert).

## Owner-Decisions (zusammengefasst)

- **OD-A:** Risikobudget-Cap ist strikt, ohne Slack. Verletzung → Fallback.
- **OD-B:** Neue Goal-Felder `target_return_bps` + `success_probability_min_x100`,
  Defaults 80% (Wealth/Cashflow) / 50% (Renditeziel).
- **OD-C:** Renditeziel intern als impliziertes `wealth_at_t`-Ziel.
- **OD-D:** Unreachability-Schwelle `τ_unreachable = 50%`.
- **OD-E:** Effektive Gewichtung `weight_g = hardness_mult · 1/priority_rank`.
- **OD-F:** `hardness=hart` für Renditeziel verboten.
- **OD-G:** Shortfall absolut in CHF (Squared).
- **OD-H:** Chance-Constraint-Lagrange `λ_chance = 1e6`.

## Risiken

- **Shadow-Vergleich kann zeigen, dass Stochastic systematisch von
  House-Matrix abweicht.** Dann ist OD-Diskussion mit Owner nötig vor
  Default-Wechsel.
- **Performance:** Chance Constraint zusätzlich erhöht Solver-Zeit.
  Spec-Budget: <8s je Solver-Run (war 5s in Phase 6).
- **Konflikt-Meldungen müssen sprachlich exakt sein** — Berater wird sie
  dem Kunden zeigen. Erster Wurf in §5.1; Review durch User vor Stufe 4.

## Offene Fragen an Owner

1. Soll `τ_g` (Min-Erreichbarkeitswahrscheinlichkeit) pro Goal vom Berater
   gesetzt werden, oder zentral fixiert (80% / 50%)? Vorschlag: Default
   zentral, pro-Goal Override im UI hinter Details.
2. Soll `priority_rank` strikt 1..5 oder erlaubt sind Lücken
   (z.B. 1, 3, 5)? Vorschlag: strikt, fortlaufend.
3. `shadow_stochastic` als opt-in oder als Default-Übergangsmodus
   für 1–2 Releases? Vorschlag: opt-in via Admin-Policy.
