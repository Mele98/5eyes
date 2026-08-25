# Decision: shadow_stochastic als Default?

User-Decision-Framework fuer den Wechsel des `optimizer_mode`
Default-Werts von `house_matrix` zu `shadow_stochastic`.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #101 (ENG, User-Decision)
**Format:** Architecture Decision Record (ADR-aehnlich, aber als
Entscheidungs-Vorbereitungs-Dokument)

---

## Kontext

`config.settings.optimizer_mode` hat 3 erlaubte Werte:

| Modus | Verhalten | Default heute |
|-------|-----------|---------------|
| `house_matrix` | Pure House-Matrix-Default-Allokation pro Risikoprofil. Kein Solver. | ✅ |
| `shadow_stochastic` | House-Matrix-Targets bleiben. Solver laeuft im Hintergrund, schreibt `shadow_optimization_json` fuer Compliance-Audit. | — |
| `stochastic` | Solver-Output ersetzt House-Matrix-Targets. Berater sieht Solver-Allocation direkt. | — |

`shadow_stochastic` wurde mit U-72 Sprint 4 (2026-05-15) implementiert
als **vorsichtige Migrationsstufe** vor `stochastic` Default.

## Stand der Evidence

### Was wir wissen
- `services/shadow_comparison.py` aggregiert Shadow-vs-Aktive-Allocation
  pro Mandat (siehe Aggregator-Sektion 20 `methodology_models`)
- `aggregate_shadow_comparisons()` (system.py-Endpoint
  `/admin/system/shadow-comparison-aggregate`) liefert
  GREEN/YELLOW/RED-Counts ueber alle Mandate
- Stochastic-Optimizer ist Phase 4 fertig (U-72 + Folge-Sprints)
- Sub-App zeigt Methoden-Audit (U-73+U-74) bei Compliance-Drilldown

### Was wir NICHT wissen
- **Empirischer Track-Record:** wie viele Sprints/Live-Tage hat
  shadow_stochastic ohne Probleme gelaufen?
- **GREEN-Quote ueber Mandate:** wieviele Mandate liefern stabil GREEN
  vs YELLOW/RED?
- **Berater-Akzeptanz:** wurden die Shadow-Daten dem Kunden gezeigt?

## Decision-Optionen

### Option A: house_matrix bleibt Default (Status Quo)

**Pro:**
- Kein Risiko fuer bestehende Mandate
- Berater muss aktiv `OPTIMIZER_MODE=shadow_stochastic` setzen wenn er
  das Audit-Pattern will
- Kompatibel mit allen historischen TAs

**Contra:**
- Shadow-Comparison-Daten fehlen fuer Mandate die Berater nicht
  explizit umstellt -> Compliance-Audit-Trace nicht vollstaendig
- Stochastic-Optimizer wird nicht "geuebt"

**Recommended-Trigger fuer Re-Evaluation:** wenn FINMA Methodology-
Audit eine vollstaendige Shadow-Trace fordert.

### Option B: shadow_stochastic als Default (vorsichtige Migration)

**Pro:**
- Compliance-Audit-Trace fuer ALLE neuen TAs vollstaendig
- Stochastic-Engine wird konsistent gegen House-Matrix verglichen
- Keine Verhaltens-Aenderung fuer Berater (Targets bleiben
  House-Matrix-basiert)

**Contra:**
- Solver-Laufzeit pro TA-Generierung +~100-300ms (siehe
  `services.optimizer.solver` Phase 4)
- Solver-Errors koennen TA-Generierung blockieren wenn nicht graceful
- Pro Mandat zusaetzlich ein OptimizerRun-Eintrag in DB (Storage
  +~1KB/Mandat/Lauf)

**Recommended-Trigger:** sobald Shadow-Comparison-Aggregate >= 80%
GREEN ueber Test-Mandate zeigt.

### Option C: stochastic als Default (volle Migration)

**Pro:**
- Stochastic-Optimizer liefert mathematisch optimale Allocation
- Berater sieht Stochastic-Output, nicht mehr House-Matrix
- Echte Anwendung des Stochastic-Optimizers

**Contra:**
- Verhaltens-Aenderung: Targets sind nicht mehr House-Matrix
- Berater muss verstehen warum Allokation anders ist
- Solver-Errors blockieren ALLE TA-Generierungen
- Riskanter Schritt — Empfehlung NICHT vor mehrwoechigem
  shadow_stochastic-Probelauf

**Recommended-Trigger:** mindestens 3 Monate shadow_stochastic-Stand
mit >= 90% GREEN-Quote.

## Empfehlung des Engineering-Teams

**Empfehlung: Option A heute, Option B vorbereitet.**

Begruendung:
1. **Empirische Evidence fehlt** — wir haben den Stochastic-Optimizer
   technisch fertig, aber keine "field-tested"-Trace ueber Wochen.
2. **Berater-Konsultation** noetig vor Verhaltens-Aenderung — der
   Compliance-Officer muss zustimmen.
3. **Migration-Pfad ist vorbereitet** — wenn der Owner-Verifikations-
   Sprint (Stage 8 Foundation, siehe
   `docs/compliance/shadow-vergleich-template.md`) abgeschlossen ist,
   ist Option B mit einem Setting-Change moeglich.

## Was der User entscheiden muss

1. **Ist die Compliance-Audit-Trace heute wichtig?** Wenn ja ->
   Option B als naechster Schritt nach Owner-Verifikation
2. **Welcher Trigger soll fuer Option B gelten?** GREEN-Quote? Anzahl
   Mandate? Anzahl Wochen?
3. **Sollen wir Option B unter einem `--experimental`-Flag in
   Production schalten?** (z.B. nur fuer Mandate mit
   `mandate_type='Discretionary'`)

## Wie aktivieren (wenn entschieden)

```python
# config.py
optimizer_mode: Literal[...] = "shadow_stochastic"  # ehemals 'house_matrix'
```

Plus:
- Berater-Doku in BERATER_README.md anpassen
- Monitoring-Job: Daily `aggregate_shadow_comparisons` Run + Alarm
  bei GREEN-Quote-Drop
- 1-Monat-Probelauf gegen Test-Mandate vor Production-Rollout

## Bewusst NICHT in diesem Doc

- Konkrete Implementation der Migration (das ist Folge-Sprint sobald
  User entschieden hat)
- Stochastic-Optimizer-Math-Erklaerung (siehe
  `project_5eyes_optimizer.md` Memory + Methodology-Audit-Slides)
- Performance-Benchmarks (separater Sprint sobald shadow_stochastic
  >= 3 Monate Live-Daten hat)

## Weiterfuehrendes

- [project_5eyes_optimizer.md Memory](../../../Users/Emanuele/.claude/projects/C--Users-Emanuele/memory/project_5eyes_optimizer.md)
- `services/shadow_comparison.py`
- `routers/system.py` `/admin/system/shadow-comparison-aggregate`
- ADR-001 — Aggregator-Pattern (Methodology_models Sektion 20)
- ADR-003 — Anlagephilosophie (keine Markt-Timing-Auto-Trigger)
