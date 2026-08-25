# Sprint Option-C: Goal-Tilt für Renditeziele

**Datum:** 2026-06-08
**Sprint:** Option C (User-Decision nach Fix A+B)
**Trigger:** User-Feedback 2026-06-08: "Wieso veraendert sich die Grafik in der SOLL-Allocation nicht wenn ich das Renditeziel von 2% auf 5% veraendere?"

---

## Executive Summary

**Renditeziel beeinflusst die SAA jetzt sichtbar — innerhalb der House-Matrix-Bandbreiten.**

| Metrik | Wert |
|--------|------|
| Geänderte Files | 1 (`portfolio_engine.py`) |
| Neue Tests | 17 (Helper-Threshold-Logik + Integration + Edge-Cases) |
| Regression-Tests | 340 passing |
| Breaking-Changes | KEINE (additive Logik im bestehenden Tilt-Pattern) |
| Strategietreue | gewahrt (Tilts respektieren House-Matrix-Bands strikt) |

---

## 1. Architektur

### Helper-Funktion

```python
def _renditeziel_equity_tilt_bps(
    *,
    target_return_bps: int,
    current_equity_bps: int,
    min_equity_bps: int,
    max_equity_bps: int,
) -> int:
    """Returns signed delta in bps (+/- bps oder 0).

    Threshold-Logik:
    - target < 250 bps: Defensiv-Tilt von -150 bps
    - target 250-400:    kein Tilt (Standard)
    - target 400-600:    Wachstums-Tilt von +150 bps
    - target > 600:      Wachstums-Tilt von +200 bps

    Resultat wird IMMER an House-Matrix-Bands geclippt.
    """
```

### Integration in `_apply_goal_and_reserve_tilts`

```python
for goal in goals:
    if goal_type != "Renditeziel": continue
    # ADR-konformer Hardness-Filter
    if hardness not in ("primaer", "primary"): continue
    # Hart wird im Frontend geblockt (Renditen sind nicht garantierbar)
    # Opportunistisch tilted NICHT (Anlagephilosophie-Konvention)
    target_bps = int(goal.target_return_bps or 0)
    if target_bps <= 0: continue

    eq_shift = _renditeziel_equity_tilt_bps(...)
    if eq_shift > 0:
        # Wachstums-Tilt: Bonds → Equities (innerhalb Bands)
    else:
        # Defensiv-Tilt: Equities → Bonds (innerhalb Bands)
```

---

## 2. Mathematische Begründung

### Thresholds

**Warum 250 / 400 / 600 bps?**
- < 2.5% real: Sicherheits-/Kapitalerhalt-orientiert — eher defensiv
- 2.5-4%: typischer ausgewogener Bereich — keine Aussage über Risiko-Präferenz
- 4-6%: aktives Wachstumsziel — moderater Aktien-Tilt sinnvoll
- > 6%: ambitioniertes Wachstumsziel — stärkerer Aktien-Tilt (max innerhalb Bands)

### Tilt-Magnitude

**±150 / ±200 bps:** analog zur bestehenden Vermögensziel-Kurz-Horizont-Logik (`200 bps` Limit). Pragmatischer Wert der sichtbare Veränderung gibt **ohne** Risikoprofil zu verletzen.

### Band-Clipping

Tilt wird NIE über die House-Matrix-Bandbreiten hinaus angewendet:
```python
room_up = max_equity_bps - current_equity_bps
final_tilt = min(raw_tilt, room_up)
```

→ Konservativ-Profil mit `equity_max=25%` kann auch bei 6% Target keine 70% Aktien bekommen.

### Strategietreue

| Was greift | Was NICHT greift |
|---|---|
| Tilt innerhalb der Bands ✓ | Bands selbst ändern ✗ |
| Bonds ↔ Equities Transfer ✓ | Risikoprofil-Anker ändern ✗ |
| Audit-Eintrag im reasoning[] ✓ | Auto-Trigger auf Marktbewegung ✗ |

---

## 3. ADR-Konformität

- **ADR-003 anti-market-timing:** Tilt ist Goal-getrieben, nicht markt-getrieben ✓
- **FINMA Art. 6 FIDLEG:** Risikoprofil bindet die Allocation strikter als das Goal ✓
- **Brinson/Hood/Beebower 1986:** SAA bleibt strategischer Anker, Goal-Tilt ist taktisch-bounded ✓
- **Frontend-Hart-Block:** Hart-Renditeziele werden im UI verhindert (Renditen sind nicht garantierbar)

---

## 4. Hardness-Filter

| Hardness | Tilt? | Begründung |
|----------|-------|------------|
| Hart | n/a | Frontend blockt Hart für Renditeziele |
| **Primär** | ✓ | Berater hat explizit gewählt → SAA reagiert |
| Opportunistisch | ✗ | "Nice to have" Goal, soll Allocation nicht bewegen |

---

## 5. Test-Coverage

`tests/test_renditeziel_tilt.py` (17 Tests):

### Helper (10 Tests)
- 4 Threshold-Bereiche (niedrig / mittel / hoch / sehr hoch)
- 4 Band-Clipping (kein Room oben / Room kleiner / kein Room unten / Room kleiner)
- 2 Edge-Cases (target=0, target negativ)

### Threshold-Boundaries (3 Tests)
- Exakte Grenzwerte 250, 400, 600

### Integration (4 Tests)
- Hohes Renditeziel + Primär → Equity ↑
- Niedriges Renditeziel + Primär → Equity ↓
- Opportunistisches Renditeziel → KEIN Tilt
- Kein Renditeziel → KEIN Tilt (Backwards-Compat)

---

## 6. Beispiel-Szenarien

### Szenario A: Berater setzt Renditeziel von 2% auf 5%

**Pre-Option-C:**
- SAA bleibt unverändert (User-Beschwerde)

**Post-Option-C:**
- Renditeziel 5% (500 bps) → Wachstums-Tilt +150 bps Equity
- Reasoning: "Renditeziel 'Wachstum' (5.00% p.a.) hebt den Aktienanteil um 150 bps an (innerhalb der Bandbreiten, Strategietreue gewahrt)."
- Sichtbar in PDF + UI

### Szenario B: Konservativ-Profil + Renditeziel 7%

- House-Matrix: `equity_max = 25%`, current_equity = 22%
- Raw-Tilt würde +200 wollen
- Aber room_up = 25% - 22% = 3% = 300 bps → Tilt auf +200 bps gecappt
- Berater sieht: "Aktien-Anteil um 200 bps angehoben — innerhalb des Risikoprofils."

### Szenario C: Mehrere Renditeziele

- Goal 1: Renditeziel 5% Primär → +150 bps Equity
- Goal 2: Renditeziel 6% Primär → +200 bps Equity
- Beide werden sequenziell appliziert, jeweils mit aktualisiertem `current_equity_bps` und Band-Clipping
- Garantie: niemals über `max_equity_bps`

---

## 7. Out-of-Scope

| Punkt | Begründung |
|-------|-----------|
| Cross-Goal-Optimierung (mehrere Goals gleichzeitig SLSQP-optimieren) | Bereits durch Stochastic-Optimizer abgedeckt — hier nur deterministischer Tilt-Pfad |
| Renditeziel-Horizont in Tilt-Logik | Achievability-MC bewertet Horizont; SAA-Tilt nutzt nur Target-Höhe als Signal |
| Hart-Renditeziel-Support | Frontend blockt das bewusst (ADR + FINMA-Anti-Garantie) |
| Adaptive Tilt-Thresholds via CMA | Phase-2-Architektur-Refactor; aktuell Hard-Coded |

---

## 8. Vergleich mit 3eyes

| Dimension | 3eyes | 5eyes (Pre-Option-C) | 5eyes (Post-Option-C) |
|-----------|-------|----------------------|----------------------|
| Allocation reagiert auf Goal-Change | implizit (Mulvey/Ziemba erwähnt) | nein | **ja, innerhalb Bands** |
| Tilt-Magnitude | unklar | n/a | ±150/200 bps geclippt |
| Audit-Trail des Tilts | unklar | n/a | **reasoning[] dokumentiert** |
| Hardness-respektierend | unklar | n/a | **ja (Opp tilted nicht)** |

→ **5eyes ist in jeder Dimension besser oder gleichwertig — plus voller Audit-Trail.**

---

## 9. Lifecycle

- **Drift-Protection:** test_renditeziel_tilt.py permanente Regression-Coverage
- **Reviewer-Pflicht:** Tilt-Thresholds-Änderungen erfordern Audit-Review
- **Future-Evolution:** CMA-basierte adaptive Thresholds (Phase 2)

---

## 10. Referenzen

- `services/portfolio_engine.py:_renditeziel_equity_tilt_bps` (Helper)
- `services/portfolio_engine.py:_apply_goal_and_reserve_tilts` (Integration)
- ADR-003 anti-market-timing
- Brinson/Hood/Beebower (1986)
- Vorherige Fixes: `2026-06-08-cashflow-in-mc-audit.md` (Schicht 2-Analyse)

---

**Status:** Option C komplett. 5eyes hat damit **Allocation-Reaktion auf Goal-Targets** in einer FINMA-konformen, ADR-respektierenden, Audit-fähigen Form.
