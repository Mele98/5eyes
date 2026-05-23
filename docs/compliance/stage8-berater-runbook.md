# Stage 8 — Berater-Runbook für den Default-Mode-Wechsel

> **Zweck:** Schritt-für-Schritt-Anleitung für den Berater/Owner, um den Default
> von `OPTIMIZER_MODE=house_matrix` auf `stochastic` umzustellen.
> Bezug:
> - Spec `docs/planning/2026-05-23-stochastic-goal-engine-spec.md` §10 Acceptance #10
> - Methodology `docs/planning/2026-05-23-stochastic-shadow-comparison-methodology.md`
> - Template `docs/compliance/shadow-vergleich-template.md`
>
> **Zeitbedarf:** ca. 30–45 Minuten, sobald 4 Mandate (1 Foundation + 3 reale Archetypen)
> Shadow-Daten persistiert haben.

---

## Voraussetzungen-Checkliste

Vor Start MUSS gelten:

- [ ] Stages 1-7 + Stage 8 Foundation gemerged auf `develop` (commit ≥ `bf0f4b2`).
- [ ] Stage 8 Phase 2 Admin-UI gemerged (PR-Titel: *„feat(ui): Stage 8 Phase 2 — Admin-UI fuer Shadow-Aggregat-Endpoint"*).
- [ ] Backend-Test-Suite lokal grün (`python -m pytest -q` → 1762+ passed).
- [ ] Admin-Account aktiv, Electron-App startet auf `develop`-Stand.

---

## Schritt 1 — Modus auf `shadow_stochastic` umschalten (einmalig)

1. Electron-App öffnen → Admin-Modal (Zahnrad-Icon oben rechts).
2. Sub-Section **„System"** → Feld **„Optimizer-Modus"** auf `shadow_stochastic` setzen.
3. Speichern. Audit-Log-Eintrag `OPTIMIZER_MODE_CHANGE` erscheint.

Effekt: Ab sofort liefert „Anlagestrategie berechnen" weiterhin die House-Matrix-
Allokation an die UI, persistiert aber zusätzlich die Stochastic-Empfehlung in
`TargetAllocation.shadow_optimization_json`.

---

## Schritt 2 — Foundation-Case + 3 reale Mandate durchlaufen

### 2.1 Foundation-Case (deterministisch)

1. Admin-Modal → Sub-Section **„Foundation-Beispiel"** → Button **„Foundation-Case neu erzeugen"**.
2. Mandat öffnen → Asset Allokation → **„Anlagestrategie berechnen"**.

### 2.2 Drei reale Archetypen

Für jedes der 3 Mandate (Auswahl gemäß Methodology §2.2):
- **Defensiv-Pensionär** (Score ≤ 4, ≥ 1 hartes Cashflow-Ziel, BV ≥ CHF 500k).
- **Wachstumsorientiert mit Vermögensziel** (Score 6-8, ≥ 1 primäres Vermögensziel mit Horizont 8-15J).
- **Dynamisch-Akkumulation** (Score ≥ 8, Hauptziel Maximierung/Renditeziel, KEIN hartes Renditeziel — OD-F).

Pro Mandat:
1. Mandat öffnen.
2. Asset Allokation → **„Anlagestrategie berechnen"** klicken.
3. Optional: PDF generieren (Anlagestrategie + Protokoll) zur visuellen Kontrolle der
   Stage-7-Render-Pipeline (Strategie-Begründung-Block + Konflikt-Hinweis-Block).

---

## Schritt 3 — Aggregat-Sicht öffnen + Verdikt ablesen

1. Admin-Modal → Sub-Section **„Shadow-Vergleich Aggregat"** (von Codex in Stage 8 Phase 2 gebaut).
2. Reload-Button drücken.
3. **3 KPI-Karten** zeigen:
   - GREEN: `<n>` Mandate (`<x>` %)
   - YELLOW: `<n>` Mandate (`<x>` %)
   - RED: `<n>` Mandate (`<x>` %)
4. **default-switch-Badge** zeigt:
   - `Default-Wechsel freigegeben` (grün) — *oder* —
   - `Default-Wechsel blockiert: <reason>` (rot) mit Methodology-§4-Begründung.

### Direkter Endpoint-Aufruf (falls UI nicht verfügbar)

```bash
curl -H "Cookie: <admin-session>" \
  http://localhost:8000/admin/system/shadow-comparison-aggregate | jq
```

Antwort-Schema:
```json
{
  "counts": {"green": 3, "yellow": 1, "red": 0, "total": 4},
  "percentages": {"green": 75.0, "yellow": 25.0, "red": 0.0, "total": 4},
  "examples": {
    "green": [{"mandate_id": "...", "verdict": "green", "limiting_factor": "...", ...}],
    "yellow": [{"mandate_id": "...", "verdict": "yellow", "verdict_notes": [...], ...}],
    "red": []
  },
  "default_switch_ready": false,
  "default_switch_reason": "GREEN-Anteil 3/4 unter 2/3 — Owner-Review für YELLOW-Mandate nötig.",
  "errors": []
}
```

---

## Schritt 4 — Compliance-Template ausfüllen

1. Pro Mandat eine Kopie von `docs/compliance/shadow-vergleich-template.md` anlegen:
   - Dateiname: `shadow-vergleich-<YYYY-MM-DD>-<pseudonym>.md`
   - `<pseudonym>` ∈ {`foundation`, `archetype-1`, `archetype-2`, `archetype-3`}
2. Pro Mandat den Per-Mandat-Endpoint aufrufen für die Detail-Felder:
   ```bash
   curl -H "Cookie: <admin-session>" \
     http://localhost:8000/admin/system/shadow-comparison/<mandate_id>
   ```
3. Felder im Template ausfüllen, Verdikt 🟢/🟡/🔴 setzen, Berater-Notiz schreiben.
4. Bei YELLOW: Owner-Review-Block ausfüllen (Drift fachlich erklärbar? Reklassifikation
   auf GREEN möglich?).

---

## Schritt 5 — Gesamt-Report + Owner-Entscheid

1. Datei `docs/compliance/shadow-vergleich-<YYYY-MM-DD>-gesamt.md` anlegen.
2. Tabelle der 4 Einzel-Verdikte einkopieren (aus den Einzelreports).
3. **Default-Wechsel-Entscheid** eintragen — MUSS mit `default_switch_ready` aus dem
   Aggregate-Endpoint übereinstimmen:
   - `default_switch_ready: true` → 🟢 freigeben.
   - `default_switch_ready: false` → 🔴 blockieren, Reason zitieren.
4. Owner-Signatur + Datum eintragen.

---

## Schritt 6 — Default-Switch committen (nur bei freigegebenem Wechsel)

> **WICHTIG:** Dieser Commit ist die Owner-Aktion. NICHT von Codex oder Claude
> automatisch ausführen lassen — nur nach grünem Gesamt-Verdikt händisch.

1. Admin-Modal → Sub-Section **„System"** → Feld **„Optimizer-Modus"** auf `stochastic`.
2. Speichern. Audit-Log `OPTIMIZER_MODE_CHANGE: shadow_stochastic → stochastic`.
3. Code-Default-Wert in `config/settings.py` auf `optimizer_mode = "stochastic"`
   anpassen (damit neue Installationen direkt stochastic nutzen).
4. Commit-Message (Konvention):
   ```
   feat(stochastic): Default-Mode-Wechsel — OPTIMIZER_MODE=stochastic

   Gemäß Methodology §4 Gesamt-Verdikt erfüllt:
   - Foundation: GREEN
   - archetype-1 (...): GREEN/YELLOW
   - archetype-2 (...): GREEN/YELLOW
   - archetype-3 (...): GREEN/YELLOW
   - 0 RED
   - default_switch_ready: true

   Compliance-Dossier: docs/compliance/shadow-vergleich-<YYYY-MM-DD>-gesamt.md
   ```
5. Pushen + PR gegen `develop` (CI-grün abwarten + Owner-Selbst-Merge).

---

## Schritt 7 — Post-Switch-Monitoring (eine Woche)

1. Täglich Audit-Log auf `OPTIMIZER_FALLBACK`-Einträge prüfen
   (fallback_house_matrix = Solver hat versagt; > 1 % der Runs ist Stop-Bedingung).
2. Bei Berater-Beschwerden über "ungewöhnliche Allokationen": Per-Mandat-Endpoint
   für das betroffene Mandat abrufen und den Reasoning-Trace prüfen.
3. Bei Häufung von `optimization_status != "converged"`: Stage-9-Spec für
   Solver-Robustifizierung eröffnen (kein Roll-Back, aber Bug-Fix-Sprint).

---

## Bei RED: Bug-Fix-Sprint statt Default-Switch

Wenn `default_switch_ready: false` UND ≥ 1 RED:
1. RED-Beispiele aus Aggregate-Endpoint zitieren (`examples.red[*].verdict_notes`).
2. Per-Mandat-Endpoint für RED-Mandate abrufen → vollen Reasoning-Trace anschauen.
3. Bug-Klasse bestimmen (Solver-Konvergenz / Daten-Fehler / Spec-Lücke).
4. Stage-Number für Fix-Spec vergeben (z.B. Stage 9 / 9.x).
5. Default bleibt `house_matrix`, bis Fix + erneuter grüner Aggregat-Run.
