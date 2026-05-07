# Spec — HIGH-1: WILLINGNESS_SCORE_TO_PROFILE Korrekturen

## Meta
- Titel: Risikobereitschaft-Profil-Labels an Scoring-Logik angleichen
- Datum: 2026-04-17
- Owner: Emanuele
- Branch-Vorschlag: `codex/high1-willingness-profile`
- Priorität: HOCH — falsche Profil-Labels werden dokumentiert und dem Kunden gezeigt

---

## Problem

`WILLINGNESS_SCORE_TO_PROFILE` in `risk_scoring.py` verwendet andere Schwellenwerte
als die Funktion `_profile_from_score` die den gleichen `score_x10` Wert als Endprofil
ausgibt. Resultat: Ein Berater sieht "Sicherheitsorientiert" in der Willingness-Zusammenfassung,
aber "Kapitalschutz" im Endprofil — obwohl es identische Scores sind.

### Ursache

`_willingness_profile(score_x10)` bildet Scores auf Labels ab mit:
```python
(0, 30): "Sicherheitsorientiert"  # ← score_x10=10 ergibt "Sicherheitsorientiert"
```

`_profile_from_score(score_x10)` macht:
```python
score = score_x10 / 10        # 10 → 1.0
rounded = math.floor(1.0 + 0.5)  # → 1
# SCORE_TO_PROFILE[(1,2)] → "Kapitalschutz"
```

Gleicher Input (score_x10=10), zwei verschiedene Labels.

### Korrekte Schwellenwerte

Die Schwellenwerte für `WILLINGNESS_SCORE_TO_PROFILE` müssen exakt zu
`_profile_from_score` passen (die `math.floor(score + 0.5)`-Logik):

| score_x10 Bereich | score (÷10) | gerundet | Korrektes Profil |
|---|---|---|---|
| 10–24 | 1.0–2.4 | 1–2 | Kapitalschutz |
| 25–44 | 2.5–4.4 | 3–4 | Defensiv |
| 45–64 | 4.5–6.4 | 5–6 | Ausgewogen |
| 65–84 | 6.5–8.4 | 7–8 | Wachstumsorientiert |
| 85–94 | 8.5–9.4 | 9 | Dynamisch |
| 95–100 | 9.5–10.0 | 10 | Aktien |

---

## Scope

Nur `risk_scoring.py`: 1 Dict, 1 Fallback. Keine anderen Dateien.

---

## Betroffene Datei

| Datei | Art |
|---|---|
| `5eyes-backend/services/risk_scoring.py` | ÄNDERN |

---

## Änderung 1 — WILLINGNESS_SCORE_TO_PROFILE (Zeile ~34)

**Grep zum Lokalisieren:**
```
grep -n "WILLINGNESS_SCORE_TO_PROFILE" 5eyes-backend/services/risk_scoring.py
```

**Alt:**
```python
WILLINGNESS_SCORE_TO_PROFILE = {
    (0, 30): "Sicherheitsorientiert",
    (31, 50): "Ausgewogen",
    (51, 70): "Wachstumsorientiert",
    (71, 100): "Dynamisch",
}
```

**Neu:**
```python
WILLINGNESS_SCORE_TO_PROFILE = {
    (10, 24): "Kapitalschutz",
    (25, 44): "Defensiv",
    (45, 64): "Ausgewogen",
    (65, 84): "Wachstumsorientiert",
    (85, 94): "Dynamisch",
    (95, 100): "Aktien",
}
```

---

## Änderung 2 — Fallback in _willingness_profile (Zeile ~134)

**Grep zum Lokalisieren:**
```
grep -n "_willingness_profile\|return.*Sicherheitsorientiert" 5eyes-backend/services/risk_scoring.py
```

**Alt:**
```python
def _willingness_profile(score_x10: int) -> str:
    for (lo, hi), name in WILLINGNESS_SCORE_TO_PROFILE.items():
        if lo <= score_x10 <= hi:
            return name
    return "Sicherheitsorientiert"
```

**Neu:**
```python
def _willingness_profile(score_x10: int) -> str:
    for (lo, hi), name in WILLINGNESS_SCORE_TO_PROFILE.items():
        if lo <= score_x10 <= hi:
            return name
    return "Kapitalschutz"
```

---

## Implementierungs-Checkliste für Codex

1. `WILLINGNESS_SCORE_TO_PROFILE`: altes Dict (4 Einträge) durch neues Dict (6 Einträge) ersetzen
2. `_willingness_profile` Fallback: "Sicherheitsorientiert" → "Kapitalschutz"
3. Verifikation: `python -c "from services.risk_scoring import compute_scores, WILLINGNESS_SCORE_TO_PROFILE; print('OK')"` → OK
4. Verifikation: Alle 6 Profile erscheinen als Values in `WILLINGNESS_SCORE_TO_PROFILE`

---

## Akzeptanzkriterien

1. `compute_scores(q_income_points=0, q_obligations_points=0, q_savings_points=0, q_wealth_points=0, investment_horizon_label='Bis 2 Jahre', q_investment_goal_points=1, q_risk_preference_points=1, q_risk_behavior_points=1)` → `risk_willingness_profile == "Kapitalschutz"`
2. `compute_scores(..., q_investment_goal_points=4, q_risk_preference_points=4, q_risk_behavior_points=4)` → `risk_willingness_profile == "Aktien"`
3. `risk_willingness_profile` stimmt immer mit dem erwarteten `final_profile` überein wenn `capacity_score >= willingness_score`
4. Kein "Sicherheitsorientiert" mehr in `WILLINGNESS_SCORE_TO_PROFILE`
