# Stochastic Goal Engine - Stage 9 Spec: Solver-Robustifizierung + Rollback-Plan

## Meta

- Titel: Stage 9 - Solver-Robustifizierung vor und nach dem `stochastic`-Default
- Datum: 2026-05-24
- Owner: Emanuele Konzelmann
- Branch: `codex/stochastic-stage9-spec`
- Bezug:
  - `docs/planning/2026-05-23-stochastic-goal-engine-spec.md`
  - `docs/planning/2026-05-23-stochastic-shadow-comparison-methodology.md`
- Art: Spezifikation, kein Code

## Ziel

Diese Spec definiert das Sicherheitsnetz fuer die Phase nach dem Default-Wechsel
auf `OPTIMIZER_MODE=stochastic`. Sie beantwortet:

- Ab wann gilt `optimization_status != "converged"` als systematisches Problem?
- Welche Robustifizierungs-Hebel duerfen automatisch oder halbautomatisch
  eingesetzt werden?
- Welche Parameter muessen persistiert werden, damit jeder Run auditierbar
  bleibt?
- Wann wird der Default auf `house_matrix` zurueckgestellt?

Stage 9 ist bewusst kein Ersatz fuer Stage 8. Der Default-Wechsel bleibt erst
zulaessig, wenn der Shadow-Vergleich gemaess Methodology gruen ist. Stage 9
setzt danach die operative Leitplanke.

## Nicht-Ziel

- Keine Aenderung der fachlichen Risk-Matrix.
- Keine Lockerung des harten Risikobudget-Caps.
- Keine Renditeversprechen und keine Berater-Aufforderung, das Kundenrisiko zu
  erhoehen.
- Kein automatischer Default-Switch zurueck oder vorwaerts ohne Audit-Log.
- Keine stille Aenderung der Kunden- oder PDF-Aussagen ohne persistierten
  Reasoning-Trace.

## 1. Zweck + Trigger-Bedingungen

Stage 9 wird aktiv, wenn der Default auf `stochastic` gewechselt wurde oder ein
Shadow-/Pilot-Betrieb gezielt auf Solver-Stabilitaet ueberwacht wird.

### 1.1 Primaerer Monitoring-Indikator

Gemessen wird auf allen neu erzeugten `TargetAllocation`-Runs:

```text
non_converged_rate =
  count(optimization_status != "converged") / count(allocation_runs)
```

Rolling Windows:

- `rolling_24h`: fruehe Warnung.
- `rolling_7d`: operative Schwelle.
- `rolling_30d`: Governance- und Default-Entscheid.

### 1.2 Trigger-Stufen

| Stufe | Bedingung | Wirkung |
|---|---:|---|
| INFO | `non_converged_rate_24h > 0.5%` oder mindestens 1 `diverged` | Admin-Hinweis, keine Kundenwirkung |
| WATCH | `non_converged_rate_7d > 1.0%` | Robustifizierungs-Run aktivieren, Owner informieren |
| ACTION | `non_converged_rate_7d > 3.0%` oder 3 RED-Faelle in 7 Tagen | Stage-9-Fallback-Stages erzwingen, Review-Ticket |
| ROLLBACK | `non_converged_rate_30d > 2.0%` oder 1 harter Cap-Verstoss | Default zurueck auf `house_matrix` vorbereiten |

Ein harter Cap-Verstoss (`risky_fraction_bps_at_generation >
risk_budget_bps_at_generation`) ist immer ROLLBACK-relevant, unabhaengig von
der Quote.

### 1.3 Statuswerte

Stage 9 unterscheidet:

- `converged`: Solver lieferte ein gueltiges Ergebnis.
- `converged_robustified`: Solver konvergierte erst nach Stage-9-Hebel.
- `fallback_stochastic_light`: vereinfachter stochastic Run, aber weiterhin
  innerhalb Risk-Cap.
- `fallback_house_matrix`: finaler Fallback auf House-Matrix-Mid.
- `diverged`: Solver ohne gueltiges Ergebnis.
- `diverged_infeasible`: harte Constraints widersprechen sich oder Cap waere
  verletzt.

## 2. Robustifizierungs-Hebel

Die Hebel werden in fester Reihenfolge angewandt. Jeder Hebel muss seine
Parameter im Audit-Trail speichern.

### 2.1 Hebel A - n_paths-Verdoppelung

**Mechanik:** Anzahl Monte-Carlo-Pfade fuer einen zweiten Run verdoppeln.

Beispiel:

- Standard: `n_paths=2000`
- Robustified: `n_paths=4000`

**Nutzen:** stabilere Wahrscheinlichkeits- und Shortfall-Schaetzung bei Goals
nahe der Schwelle.

**Trade-off:** ungefaehr doppelte Simulationskosten; nur sinnvoll, wenn
Konvergenzproblem durch Pfad-Rauschen plausibel ist.

**Erlaubt bei:** `diverged`, `knapp`-Grenzfaellen, stark schwankender
Achievability.

**Nicht erlaubt als Ersatz fuer:** Risk-Cap-Verletzung oder fehlende
HouseMatrix-Daten.

### 2.2 Hebel B - n_starts-Verdoppelung mit Seeds-Shuffle

**Mechanik:** Multi-Start-Anzahl verdoppeln und Seed-Liste deterministisch
shufflen.

Beispiel:

- Standard: `n_starts=8`
- Robustified: `n_starts=16`
- Seeds: aus `base_seed` abgeleitet, aber Run-lokal neu sortiert.

**Nutzen:** reduziert lokale Optima und numerische Sackgassen.

**Trade-off:** hoehere Laufzeit; kann aus 4-6s schnell 10-14s machen.

**Erlaubt bei:** `diverged`, schlechter KKT-/Constraint-Slack-Diagnose,
instabiler SLSQP-Konvergenz.

### 2.3 Hebel C - Soft-Tau-Lockerung fuer genau einen Run

**Mechanik:** Fuer harte und primaere Goals darf `tau` im Retry einmalig um
maximal 5 Prozentpunkte reduziert werden.

Beispiel:

- Standard Wealth/Cashflow: `tau=0.80`
- Soft-Retry: `tau=0.75`
- Renditeziel: `tau=0.50` bleibt unveraendert, ausser Owner setzt explizit
  eine abweichende Policy.

**Nutzen:** verhindert numerische Blockade bei Zielen knapp an der
Feasibility-Grenze.

**Trade-off:** fachlich sensibel. Das Ziel wird nicht als "erreicht" verkauft;
die Kundenkommunikation muss neutral bleiben.

**Erlaubt bei:** `diverged` mit plausibel knappem Zielkonflikt und Cap-konformer
Allocation.

**Nicht erlaubt bei:**

- `hardness="hart"` und Ziel fachlich zwingend ohne dokumentierten Konflikt.
- `budget_compliance == false`.
- fehlender Audit-Persistenz.

### 2.4 Hebel D - Fallback-Stages

Wenn A-C keine gueltige Allocation liefern:

1. `stochastic_light`: reduziertes Problem mit weniger Nebenbedingungen, aber
   unveraendertem Risk-Cap und Sum-to-one.
2. `house_matrix_mid`: finaler Fallback, wie Stage 2 definiert.

`house_matrix_mid` ist kein Fehler im Kundenprozess, sondern ein konservativer
Sicherheitsmodus. Intern wird er aber als Monitoring-Event gezaehlt.

## 3. Eskalationslogik

### 3.1 Einzelner Run

Pro Allocation-Run gilt:

1. Standard stochastic Run.
2. Falls nicht `converged`: Hebel A.
3. Falls weiterhin nicht `converged`: Hebel B.
4. Falls weiterhin nicht `converged` und fachlich erlaubt: Hebel C.
5. Falls weiterhin nicht `converged`: Hebel D.

Maximales Budget:

- Ziel: < 8s fuer Standard.
- Robustified Run: < 15s.
- Harte Abbruchgrenze: 25s, danach `fallback_house_matrix`.

### 3.2 Aggregiertes Monitoring

Im Admin-Aggregat werden mindestens ausgewiesen:

- Anzahl Runs total.
- Anzahl `converged`.
- Anzahl `converged_robustified`.
- Anzahl `fallback_stochastic_light`.
- Anzahl `fallback_house_matrix`.
- Anzahl `diverged` / `diverged_infeasible`.
- Quote pro rolling window.
- Top 10 Beispiele mit Mandat-Pseudonym, limiting_factor, elapsed_ms,
  robustification_stage und reason.

## 4. Audit-Trail und Persistenz

Jede Robustifizierung muss im bestehenden Audit-Pfad nachvollziehbar sein.

### 4.1 TargetAllocation

Persistiert oder im bestehenden Reasoning-JSON eingebettet:

```json
{
  "optimization_status": "converged_robustified",
  "robustification": {
    "enabled": true,
    "stage": "n_starts_double",
    "attempts": [
      {
        "attempt": 1,
        "status": "diverged",
        "n_paths": 2000,
        "n_starts": 8,
        "seed": 12345,
        "tau_adjustment_bps": 0,
        "elapsed_ms": 4210,
        "reason": "solver_no_convergence"
      },
      {
        "attempt": 2,
        "status": "converged",
        "n_paths": 4000,
        "n_starts": 16,
        "seed": 812345,
        "tau_adjustment_bps": 0,
        "elapsed_ms": 11240,
        "reason": "retry_success"
      }
    ],
    "final_reason": "retry_success"
  }
}
```

### 4.2 AuditLog

Ein `AuditLog`-Eintrag ist Pflicht bei:

- Wechsel in `converged_robustified`.
- jeder Soft-Tau-Lockerung.
- jedem `fallback_stochastic_light`.
- jedem `fallback_house_matrix`.
- jedem Default-Rollback.

Mindestens:

- `action`: `STOCHASTIC_ROBUSTIFICATION`, `STOCHASTIC_SOFT_TAU_RETRY`,
  `STOCHASTIC_FALLBACK`, `OPTIMIZER_MODE_ROLLBACK`.
- `old_value`, `new_value`.
- `mandate_id` oder pseudonymisierte Referenz.
- `actor`: System oder Owner.
- `reason`.

## 5. UX-Auswirkungen

Kunden- und Beratertexte bleiben neutral. Keine Formulierung darf eine
Renditegarantie oder eine Risikoerhoehungsaufforderung enthalten.

### 5.1 Berater-facing bei Robustifizierung

Bei `converged_robustified`:

> Die Berechnung wurde mit erweiterter numerischer Pruefung abgeschlossen. Die
> Strategie bleibt innerhalb des dokumentierten Risikoprofils.

Bei Soft-Tau-Retry:

> Ein Ziel liegt nahe an der rechnerischen Erreichbarkeitsgrenze. Die Strategie
> wurde konservativ innerhalb des Risikoprofils berechnet; die reduzierte
> Mindestwahrscheinlichkeit ist intern dokumentiert.

Bei `fallback_house_matrix`:

> Die stochastische Berechnung konnte fuer dieses Mandat nicht stabil
> abgeschlossen werden. Die Strategie wurde auf Basis der dokumentierten
> Risikomatrix erstellt.

### 5.2 Kunden-PDF

Im Kunden-PDF wird keine technische Solver-Diagnose gezeigt. Sichtbar sind nur:

- Strategie innerhalb Risikoprofil.
- Zielerreichung, falls valide berechnet.
- neutraler Hinweis, falls House-Matrix-Fallback verwendet wurde.

Technische Details gehoeren in den internen Report / Audit-Trail.

## 6. Acceptance-Kriterien

Stage 9 gilt als spezifiziert und spaeter implementierbar, wenn:

1. Trigger fuer INFO/WATCH/ACTION/ROLLBACK sind messbar und eindeutig.
2. Kein Robustifizierungs-Hebel kann den Risk-Cap lockern.
3. Soft-Tau ist maximal ein Retry, maximal -5 Prozentpunkte, auditpflichtig.
4. Jeder Retry speichert `n_paths`, `n_starts`, Seed, Status, elapsed_ms und
   reason.
5. Aggregat-Endpoint kann rolling 24h/7d/30d Quoten bilden.
6. `fallback_house_matrix` zaehlt als Monitoring-Event, aber bleibt
   kundenprozessfaehig.
7. Bei jedem Cap-Verstoss ist Rollback-Review Pflicht.
8. Kunden-UI enthaelt keine technischen Solverdetails.
9. Interner Report kann die komplette Entscheidungskette rekonstruieren.
10. Default-Rollback ist dokumentiert und auditierbar.

## 7. Rollback-Plan

Rollback bedeutet: `OptimizerPolicy.optimizer_mode` wird kontrolliert von
`stochastic` auf `house_matrix` gesetzt. Bereits persistierte Allocations werden
nicht rueckwirkend geaendert.

### 7.1 Harte Rollback-Trigger

Rollback-Review ist zwingend bei:

- einem einzigen Risk-Cap-Verstoss.
- `non_converged_rate_30d > 2.0%`.
- `fallback_house_matrix_rate_7d > 3.0%`.
- zwei realen Mandaten mit nicht erklaerbarem `zielkonflikt` innerhalb von 7
  Tagen.
- wiederholter Soft-Tau-Nutzung: `soft_tau_retry_rate_7d > 1.0%`.

### 7.2 Rollback-Ablauf

1. Owner prueft Admin-Aggregat und Beispiele.
2. Compliance-Notiz unter `docs/compliance/` erfassen.
3. `OptimizerPolicy.optimizer_mode = "house_matrix"`.
4. AuditLog: `OPTIMIZER_MODE_ROLLBACK`.
5. Nach Fix: erneuter Shadow-Vergleich gemaess Methodology, bevor
   `stochastic` wieder Default werden darf.

### 7.3 Was nicht zurueckgerollt wird

- Risk-Matrix-Daten.
- Goal-Schema-Feld-Isolation.
- PDF-/Review-Anzeigen, die bereits persistierte Werte korrekt wiedergeben.

## 8. Tests und Verifikation

Spaetere Stage-9-Implementation braucht mindestens:

- Unit-Tests fuer Trigger-Klassifikation.
- Unit-Tests fuer Retry-Reihenfolge A-B-C-D.
- Tests, dass Risk-Cap auch in Robustified Runs strikt bleibt.
- Tests fuer AuditLog bei Soft-Tau und Fallback.
- Aggregat-Endpoint-Tests fuer rolling 24h/7d/30d.
- Frontend-Static-Tests fuer neutrale Texte ohne verbotene Phrasen.
- Regression: bestehende Stage-1-bis-8-Tests bleiben gruen.

Manuelle Verifikation:

- Ein synthetischer `diverged`-Run fuehrt zu `converged_robustified`.
- Ein synthetischer infeasible Run fuehrt zu `fallback_house_matrix`.
- Admin-Aggregat zeigt beide korrekt.
- Kunden-PDF zeigt keine internen Solverparameter.

## 9. Branch-Strategy und Umsetzung

Diese Datei ist Stage 9 Spec-only.

Implementierung spaeter in separaten Branches:

1. `codex/stochastic-stage9-telemetry`
   - Persistenz / AuditLog / Aggregat-Metriken.
2. `codex/stochastic-stage9-retry-engine`
   - Retry-Orchestrierung A-B-C-D.
3. `codex/stochastic-stage9-admin-monitoring`
   - Admin-Aggregat fuer rolling windows und Beispiele.
4. `codex/stochastic-stage9-pdf-internal-report`
   - interne technische Nachvollziehbarkeit.

Kein Implementierungs-Branch darf den Default selbst umstellen. Der
Default-Switch und ein eventueller Rollback bleiben Owner-Entscheide mit
Compliance-Trail.

## 10. Reviewer und Glossar

### Reviewer

- Owner: Emanuele Konzelmann.
- Fachreview: Anlage-/Suitability-Logik, besonders Soft-Tau.
- Tech-Review: Solver, Persistenz, AuditLog, Admin-Aggregat.
- Compliance-Review: Kundentexte, Rollback-Notiz, interne Reports.

### Glossar

- **Risk-Cap:** maximale risikogewichtete Quote aus HouseMatrix und
  Risikoprofil.
- **Robustified Run:** stochastic Run, der erst nach Retry-Hebel konvergiert.
- **Soft-Tau:** einmalige, auditierte Lockerung der
  Zielerreichungswahrscheinlichkeit fuer numerische Stabilitaet.
- **Stochastic-Light:** vereinfachter stochastic Fallback ohne Lockerung des
  Risk-Caps.
- **House-Matrix-Mid:** konservativer finaler Fallback auf das Profil-Mid der
  Risk-Matrix.
- **Rollback:** Rueckstellung des Defaults von `stochastic` auf `house_matrix`
  nach dokumentiertem Owner-Entscheid.
