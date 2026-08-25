# Shadow-Vergleichs-Report — Template

> **Verwendung:** Pro Mandat einmal **kopieren** und ausfüllen. Datei-Name nach
> Konvention `shadow-vergleich-<YYYY-MM-DD>-<pseudonym>.md` in `docs/compliance/`
> ablegen. Bezug: Methodology
> `docs/planning/2026-05-23-stochastic-shadow-comparison-methodology.md` §6.
>
> **Pseudonymisierung:** Mandat-Nr. und Kundenname dürfen NICHT im Report
> stehen. Stattdessen `archetype-<n>` (`archetype-1`, `archetype-2`, …) oder
> `foundation` für den deterministischen Foundation-Case.

---

## Mandat: `<pseudonym>`

- **Datum des Vergleichs:** YYYY-MM-DD
- **Berater:** (Name oder Initialen)
- **Archetyp:** ☐ Foundation-Case · ☐ Defensiv-Pensionär · ☐ Wachstumsorientiert mit Vermögensziel · ☐ Dynamisch-Akkumulation
- **Risikoprofil:** `<final_score_x10>` → `<profile_label>`
- **Override aktiv:** ☐ Nein · ☐ Ja → Override-Score `<override_score_x10>`, Begründung: `<…>`
- **Beratungsvermögen:** ca. CHF `<betrag>`
- **Goals:** `<n>` Stück (`<n_hart>` hart, `<n_primaer>` primär, `<n_opportunistisch>` opportunistisch)
- **Cashflows:** `<n>` Einträge
- **Datenquelle (Per-Mandat):** API `GET /admin/system/shadow-comparison/{mandate_id}` (Roh-JSON anhängen, falls hilfreich)
- **Datenquelle (Aggregat über alle Mandate, für Gesamt-Verdikt):** API `GET /admin/system/shadow-comparison-aggregate` — liefert `counts`, `examples`, `default_switch_ready`, `default_switch_reason` gemäß Methodology §4

### Allokations-Vergleich

| Bucket | House-Matrix (bps) | Stochastic (bps) | Drift (bps) |
|---|---:|---:|---:|
| equities | | | |
| bonds | | | |
| real_estate | | | |
| alternatives | | | |
| liquidity | | | |
| **total_drift_bps (max \|·\|)** | — | — | |

### Risikobudget

| Metrik | House-Matrix | Stochastic | Drift |
|---|---:|---:|---:|
| risky_fraction_bps | | | |
| risk_budget_bps (Cap) | | | (Limit) |
| budget_compliance | ☐ ✓ ☐ ✗ | ☐ ✓ ☐ ✗ | — |

### Sekundäre Risikomaße

| Metrik | House-Matrix | Stochastic | Drift |
|---|---:|---:|---:|
| expected_volatility_bps | | | |
| expected_terminal_p50_rappen | | | |
| elapsed_ms (Run-Zeit) | | | |
| optimization_status | n/a | `<converged\|diverged\|fallback_house_matrix>` | — |
| limiting_factor | n/a | `<risikoprofil\|liquiditaetsreserve\|bandbreite\|zielkonflikt\|solver_konvergenz>` | — |

### Goal-Achievability (nur Stochastic)

| Goal-Label | Goal-Typ | Hardness | P (%) | Status |
|---|---|---|---:|---|
| `<…>` | `<…>` | `<…>` | | ☐ erreichbar · ☐ knapp · ☐ nicht_erreichbar |
| `<…>` | `<…>` | `<…>` | | ☐ erreichbar · ☐ knapp · ☐ nicht_erreichbar |

- **n_hard_unreachable_st:** `<n>` (MUSS 0 sein, sonst RED — außer dokumentierter Berater-Konflikt)

### Stochastic-Messages (advisor-facing, falls vorhanden)

(Aus `shadow_optimization_json.messages`, falls Codex Stage 5 das mit-persistiert hat.)

- `<code>` — `<title>` — `<body_advisor>`
- …

### Verdikt: ☐ 🟢 GREEN · ☐ 🟡 YELLOW · ☐ 🔴 RED

**Begründung (welche Schwellen aus Methodology §4 wurden über-/unterschritten):**

- `<…>`

### Berater-Notiz (fachliche Würdigung der Drift)

Erklärt der Berater die Drift fachlich? Akzeptiert er die Stochastic-Empfehlung für dieses Mandat?

```
<…>
```

### Owner-Entscheid bei YELLOW (sonst leer lassen)

| Frage | Antwort |
|---|---|
| Drift ist fachlich erklärbar? | ☐ ja ☐ nein |
| Reklassifikation auf GREEN? | ☐ ja ☐ nein |
| Wenn nein: Block-Grund | `<…>` |

---

### Signatur

| Rolle | Name / Initialen | Datum |
|---|---|---|
| Berater (durchgeführt) | | |
| Owner (gegengeprüft) | | |

---

## Gesamt-Verdikt-Aggregation (nur im Schluss-Report über alle 4 Mandate)

> Nur in `shadow-vergleich-<YYYY-MM-DD>-gesamt.md` ausfüllen, der die Einzel-
> Reports zusammenführt. Methodology §4 Gesamt-Verdikt: Default-Wechsel
> freigegeben wenn Foundation = GREEN UND ≥ 2/3 reale = GREEN UND 0 = RED.

| Mandat | Verdikt | Notiz |
|---|---|---|
| foundation | ☐ 🟢 ☐ 🟡 ☐ 🔴 | |
| archetype-1 (Defensiv-Pensionär) | ☐ 🟢 ☐ 🟡 ☐ 🔴 | |
| archetype-2 (Wachstumsorientiert) | ☐ 🟢 ☐ 🟡 ☐ 🔴 | |
| archetype-3 (Dynamisch) | ☐ 🟢 ☐ 🟡 ☐ 🔴 | |

**Default-Wechsel auf `OPTIMIZER_MODE=stochastic` freigegeben:** ☐ ja ☐ nein

**Begründung:** `<…>` (bei "ja" zwingend zitieren: `default_switch_reason` aus dem Aggregate-Endpoint zum Zeitpunkt der Freigabe — sollte mit den vier Einzel-Verdikten oben konsistent sein.)

**Owner-Signatur + Datum:** `<…>`
