# Claude-Spec — Stochastic Goal Engine: UX, Konflikt-Messages und Review-Cockpit

## Meta

- Titel: Konkrete UX, Copy-Strings und Konflikt-Meldungs-Katalog für die
  Stochastic Goal Engine
- Datum: 2026-05-23
- Owner: Emanuele Konzelmann
- Ergänzt: `docs/planning/2026-05-23-stochastic-goal-engine-spec.md` §5 + §7 + §9 Stufe 4 + Stufe 6
- Adressiert: Codex Stage 4 (Messages-Katalog) und Stage 6 (Frontend)
- Branch-Vorschlag: `codex/stochastic-stage4-messages` bzw. `-stage6-frontend`

## Zweck

Die Haupt-Spec definiert das WAS der Stochastik-Umstellung; dieses Dokument
definiert das WIE auf der Berater-/Kunden-Oberfläche. Konkret:

- 7 Konflikt-Codes mit **final formulierten** advisor-facing + kundentauglichen
  Texten (FINMA-bewusst, keine Aufforderung zur Risikoerhöhung).
- Goal-Editor mit **typabhängiger Feld-Sichtbarkeit** und Live-Diagnose.
- Review-Cockpit als visueller Zenit: Hauptziel, Limiting-Factor, Story.
- Konkrete Element-IDs, CSS-Klassen, JS-Funktionssignaturen, damit Codex
  Stage 6 ohne UX-Entscheidungen umsetzen kann.

## 1. Konflikt-Meldungs-Katalog (Stage 4 — final)

### 1.1 Datenvertrag

Jede Message ist ein Objekt mit fester Form, persistiert in
`TargetAllocation.optimizer_reasoning_json["messages"]`:

```json
{
  "code": "CONFLICT_PROFILE_LIMITS",
  "severity": "conflict" | "warning" | "info",
  "goal_id": "..." | null,
  "title": "Risikoprofil limitiert das Ziel",
  "body_advisor": "...",
  "body_client": "...",
  "actions": ["adjust_goal", "extend_horizon", "increase_savings", "review_riskprofile_with_assessment"]
}
```

`severity`-Mapping in Frontend:
- `conflict` = rote Banner-Card, blockiert Abschluss-Button visuell.
- `warning` = gelbe Inline-Card.
- `info` = graue Notiz unter dem KPI-Tile.

### 1.2 Die 7 Codes (final formuliert)

#### `OK_COMFORTABLE` — `info`

- **Title:** *"Alle Ziele komfortabel erreichbar"*
- **Body advisor:** *"Die optimierte Allokation erreicht alle harten und primären Ziele mit einer Wahrscheinlichkeit von 80% oder höher innerhalb des dokumentierten Risikoprofils."*
- **Body client:** *"Ihre Ziele sind innerhalb des für Sie passenden Risikorahmens komfortabel erreichbar."*

#### `OK_TIGHT` — `warning`

- **Title:** *"Ziel knapp erreichbar"*
- **Body advisor:** *"«{goal_label}» hat eine Eintrittswahrscheinlichkeit von ca. {prob}% — über der 50%-Schwelle, aber unter dem komfortablen Niveau von 80%. Hebel: Sparrate, Horizont, Zielbetrag, Hardness-Priorisierung."*
- **Body client:** *"Ihr Ziel «{goal_label}» ist erreichbar, aber mit ca. {prob}% knapper. Eine höhere Sparrate, ein längerer Horizont oder eine kleinere Zielsumme würden die Sicherheit erhöhen."*
- **Actions:** `["increase_savings", "extend_horizon", "adjust_goal"]`

#### `CONFLICT_PROFILE_LIMITS` — `conflict`

- **Title:** *"Risikoprofil limitiert das Ziel"*
- **Body advisor:** *"Das gewünschte Ziel «{goal_label}» ist mit dem aktuellen Risikoprofil «{profile_label}» nicht plausibel erreichbar (P ≈ {prob}%). Eine höhere Zielrendite würde ein höheres Risikobudget erfordern. Optionen: Ziel anpassen, Horizont verlängern, Sparrate erhöhen — oder im Rahmen einer neuen FINMA-Eignungsprüfung die Risikofähigkeit neu erheben."*
- **Body client:** *"Mit Ihrem heutigen Anlageprofil ist «{goal_label}» schwer erreichbar. Bevor wir mehr Risiko nehmen, sollten wir prüfen, ob das Ziel oder der Zeithorizont angepasst werden kann. Eine andere Risikoeinstufung ist nur nach einer neuen Eignungsprüfung möglich."*
- **Actions:** `["adjust_goal", "extend_horizon", "increase_savings", "review_riskprofile_with_assessment"]`

#### `CONFLICT_GOAL_INCOMPATIBLE` — `conflict`

- **Title:** *"Ziele stehen im Konflikt"*
- **Body advisor:** *"Die Ziele «{goal_a}» und «{goal_b}» schliessen sich mit dem aktuellen Vermögen und Horizont mathematisch teilweise aus. Eine Priorisierung (Hardness) oder eine Anpassung eines der beiden Ziele ist nötig."*
- **Body client:** *"Sie haben zwei Ziele, die sich teilweise widersprechen. Wir sollten gemeinsam priorisieren, was Ihnen wichtiger ist."*
- **Actions:** `["prioritize_goals", "adjust_goal"]`

#### `CONFLICT_DATA_INSUFFICIENT` — `conflict`

- **Title:** *"Datenbasis reicht für das Ziel nicht aus"*
- **Body advisor:** *"Aus heutigem Vermögen, geplanten Zuflüssen und Anlagehorizont ist «{goal_label}» mathematisch nicht zu decken — unabhängig vom Risikoprofil. Bitte Eingaben prüfen: Anlagebetrag, Cashflows, Zielbetrag, Zeithorizont."*
- **Body client:** *"Mit dem heutigen Anlagebetrag und Ihren geplanten Einzahlungen erreichen wir «{goal_label}» auch bei höchstem Risikoprofil nicht. Wir müssten gemeinsam einen Hebel ansetzen — etwa Zielbetrag, Sparrate oder Zeitrahmen."*
- **Actions:** `["increase_savings", "extend_horizon", "adjust_goal"]`

#### `WARN_FALLBACK` — `warning`

- **Title:** *"Optimierer auf Bandbreiten-Mitte zurückgesetzt"*
- **Body advisor:** *"Der stochastische Optimierer konnte unter den aktuellen Constraints nicht konvergieren. Die Strategie verwendet stattdessen den Bandbreiten-Mittelwert des Risikoprofils. Bitte Ziele, Bandbreiten und Liquiditätsreserve prüfen."*
- **Body client:** *"Wir verwenden für Sie die bewährte Standardallokation Ihres Risikoprofils. Wenn Sie spezifische Zielvorgaben präzisieren, können wir die Allokation noch enger auf Sie zuschneiden."*
- **Actions:** `["adjust_goal", "review_constraints"]`

#### `WARN_OVERRIDE` — `warning`

- **Title:** *"Risikoprofil manuell übersteuert"*
- **Body advisor:** *"Das aus der Eignungsprüfung abgeleitete Risikoprofil wurde manuell auf «{override_label}» übersteuert (Begründung: «{reason}»). Die Allokation nutzt das übersteuerte Profil; die ursprüngliche Eignungsprüfung bleibt dokumentiert."*
- **Body client:** *"Wir haben gemeinsam mit Ihnen ein angepasstes Anlageprofil dokumentiert. Die ursprüngliche Einschätzung bleibt im Beratungsdossier erhalten."*
- **Actions:** `[]`

### 1.3 Verbotene Formulierungen (sprachlich gespiegelt)

In KEINEM Text darf vorkommen:
- *"Erhöhen Sie Ihr Risiko"* / *"raise your risk"* → ersetzt durch
  *"…im Rahmen einer neuen Eignungsprüfung prüfen"*.
- *"Das Ziel wird erreicht"* (Garantieversprechen) → ersetzt durch
  *"…mit X% Wahrscheinlichkeit erreichbar"*.
- *"Optimal"*, *"perfekt"*, *"Top-Strategie"* (Marketing-Sprache) → neutral
  *"…innerhalb Ihres Risikoprofils optimiert"*.
- *"Garantie"*, *"sicher"* (im Anlage-Kontext) → ersetzt durch
  *"hohe Wahrscheinlichkeit"*.

### 1.4 i18n-Hook

Codes sind stabile Schlüssel; Texte sind im Backend deutsch-fix (Spec-MVP),
aber die JSON-Struktur erlaubt späteres `body_advisor_en` / `body_client_en`
ohne Schemabruch.

## 2. Goal-Editor — Detailspez (Stage 6)

### 2.1 Element-Inventar

Das Modal `m-acf` (existierend) wird umgebaut, **ohne** den `ph-`-Header-Stil
zu brechen (siehe UI-Guardrails Handoff 2026-05-16):

```
m-acf
├── m-acf-type-select (NEU) — Dropdown "Zieltyp"
├── m-acf-family-hint (NEU) — Tooltip pro Typ
├── m-acf-fields
│   ├── m-acf-target-amount (vorhanden) — bedingt sichtbar
│   ├── m-acf-target-return-bps (NEU) — bedingt sichtbar
│   ├── m-acf-target-date (vorhanden)
│   ├── m-acf-frequency (vorhanden) — bedingt sichtbar
│   ├── m-acf-duration-years (vorhanden) — bedingt sichtbar
│   ├── m-acf-hardness (vorhanden) — Option "hart" bedingt disabled
│   ├── m-acf-priority-rank (NEU)
│   └── m-acf-success-prob-min (NEU, Details/Accordion)
├── m-acf-derived (NEU) — Live-Diagnose-Block
└── m-acf-save / m-acf-cancel (vorhanden)
```

### 2.2 Typabhängige Sichtbarkeit (JS-Pseudocode)

```javascript
const GOAL_TYPE_FIELDS = {
  Vermoegensziel:        {show: ["target-amount","target-date","hardness","priority-rank","success-prob-min"], required: ["target-amount","target-date"], hardness_hart: true},
  Einmalige_Ausgabe:     {show: ["target-amount","target-date","hardness","priority-rank","success-prob-min"], required: ["target-amount","target-date"], hardness_hart: true},
  Pensionsausgabe:       {show: ["target-amount","target-date","frequency","duration-years","hardness","priority-rank","success-prob-min"], required: ["frequency","target-date"], hardness_hart: true},
  Wiederkehrende_Ausgabe:{show: ["target-amount","target-date","frequency","duration-years","hardness","priority-rank","success-prob-min"], required: ["frequency"], hardness_hart: true},
  Renditeziel:           {show: ["target-return-bps","target-date","hardness","priority-rank","success-prob-min"], required: ["target-return-bps"], hardness_hart: false},
  Maximierung:           {show: ["hardness","priority-rank"], required: [], hardness_hart: false, hardness_default: "opportunistisch"},
};

function applyGoalTypeVisibility(typeValue){
  const cfg = GOAL_TYPE_FIELDS[typeValue] || GOAL_TYPE_FIELDS.Vermoegensziel;
  ["target-amount","target-return-bps","target-date","frequency","duration-years","hardness","priority-rank","success-prob-min"].forEach(function(name){
    var el = document.getElementById("m-acf-" + name);
    if(!el) return;
    var visible = cfg.show.indexOf(name) >= 0;
    el.closest(".m-acf-field").style.display = visible ? "" : "none";
    var input = el.querySelector("input,select,textarea") || el;
    if (input) input.required = cfg.required.indexOf(name) >= 0;
  });
  // Hardness 'hart' nur erlauben wenn cfg.hardness_hart
  var hartOpt = document.querySelector("#m-acf-hardness option[value='hart']");
  if (hartOpt) hartOpt.disabled = !cfg.hardness_hart;
  if (!cfg.hardness_hart && document.getElementById("m-acf-hardness").value === "hart") {
    document.getElementById("m-acf-hardness").value = cfg.hardness_default || "primär";
  }
  updateGoalDerivedDiagnostics();
}
```

### 2.3 Live-Diagnose (`m-acf-derived`)

Berechnet client-seitig (rein anzeigend, keine Persistenz):

```javascript
function updateGoalDerivedDiagnostics(){
  var type = getInputValue("m-acf-type-select");
  var initial = Number(currentMandate?.advisory_wealth_rappen || 0) / 100;
  var horizon = horizonYearsFromTargetDate();  // (target-date − today) in Jahren
  var hintEl = document.getElementById("m-acf-derived");
  if (!hintEl || initial <= 0 || horizon <= 0) { hintEl.textContent = ""; return; }

  if (type === "Renditeziel") {
    var rBps = Number(getInputValue("m-acf-target-return-bps") || 0);
    var rate = rBps / 10000;
    var impliedWealth = initial * Math.pow(1 + rate, horizon);
    hintEl.innerHTML = "≈ " + btFormatCHF(Math.round(impliedWealth * 100))
      + " impliziertes Zielvermögen in " + horizon.toFixed(1) + " Jahren";
  } else if (type === "Vermoegensziel" || type === "Einmalige_Ausgabe") {
    var target = Number(getInputValue("m-acf-target-amount") || 0) / 100;
    if (target > 0 && initial > 0) {
      var required = Math.pow(target / initial, 1 / horizon) - 1;
      hintEl.innerHTML = "≈ " + (required * 100).toFixed(2)
        + "% p.a. notwendige Rendite (Kennzahl, kein Garantieversprechen)";
    }
  } else if (type === "Pensionsausgabe" || type === "Wiederkehrende_Ausgabe") {
    // PV-Solver (Annuität) → notwendige Rendite, falls duration_years gesetzt
    var streamAmount = Number(getInputValue("m-acf-target-amount") || 0) / 100;
    var dur = Number(getInputValue("m-acf-duration-years") || 0);
    if (streamAmount > 0 && dur > 0) {
      hintEl.innerHTML = "PV des Stroms ≈ " + btFormatCHF(Math.round(streamAmount * dur * 100))
        + " (vereinfacht; präzise Rendite zeigt Optimizer-Resultat)";
    }
  } else {
    hintEl.textContent = "";
  }
}
```

### 2.4 Validierungs-Verhalten

- **Client-seitig:** Felder werden eingeblendet/ausgeblendet (§2.2); `required`
  setzt sich dynamisch. HTML5-Validation greift.
- **Server-seitig:** Pydantic-Validator (Spec §9 Stufe 1) lehnt verbotene
  Felder mit 422 + spezifischer Meldung ab. Frontend zeigt die Meldung
  modal-lokal via `showModalFeedback("m-acf", err.detail)`.

### 2.5 UI-Guardrail-Compliance

- Bestehende Klassen: `m-acf-field`, `fi`, `btn-p`, `btn`, `mhd`, `mbody`,
  `mfooter`. Keine neuen Navy-Gold-Inline-Styles.
- Hardness-Dropdown bleibt visuell unverändert; nur `disabled`-State der
  `hart`-Option ändert sich.
- `m-acf-derived` als schlichter grauer Hinweis (`color:var(--n5)`,
  `font-size:11px`).

## 3. Review-Cockpit — Detailspez (Stage 6)

### 3.1 Layout-Skizze (`page-rv`)

```
┌─────────────────────────────────────────────────────────────────┐
│ Review & Abschluss                              [Print] [Done] │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ HAUPTZIEL ──────────────┐  ┌─ LIMITING FACTOR ────────────┐ │
│ │ {goal_label}             │  │ {limiting_factor_badge}      │ │
│ │ ● 86% erreichbar         │  │ z.B. "Risikoprofil limitiert"│ │
│ │ Horizont: 12 Jahre       │  │                              │ │
│ └──────────────────────────┘  └──────────────────────────────┘ │
│                                                                 │
│ ┌─ ALLOKATIONS-STORY ───────────────────────────────────────┐  │
│ │ Die Allokation maximiert die Wahrscheinlichkeit Ihres    │  │
│ │ Hauptziels innerhalb Ihres Risikoprofils «Wachstum»      │  │
│ │ (max. 72% risikobehaftet).                               │  │
│ └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌─ KONFLIKT/HINWEIS-BANNER (nur wenn conflict/warning) ──────┐ │
│ │ ⚠ Renditeziel knapp erreichbar (P ≈ 62%) — Sparrate oder │ │
│ │   Horizont prüfen.                                       │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─ ZIELERREICHUNGS-LISTE ────────────────────────────────────┐ │
│ │ ● Pensionsentnahme   Pflichtbedarf      P=92%  komfortabel│ │
│ │ ● Hauskauf 2032      Vermögensziel      P=78%  knapp      │ │
│ │ ○ Renditeziel 5%     Wunsch             P=62%  knapp      │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ <details> Allokations-Details + Reasoning + Stress-Scenarios   │
│           Solver-Status, KKT, Iterations …            </details>│
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Neue/erweiterte Element-IDs

| ID | Inhalt | Datenquelle |
|---|---|---|
| `rv-main-goal-label` | Text-Label des Hauptziels | `goals[priority_rank=1].label` |
| `rv-main-goal-prob` | "{prob}%" + Ampel | `goal_achievability[main].probability` |
| `rv-main-goal-prob-icon` | ●/◐/○ Ampel-Symbol | derived from prob (≥80, 50-80, <50) |
| `rv-limiting-factor-badge` | Badge mit `limiting_factor`-Text | `target_allocation.limiting_factor` |
| `rv-allocation-story` | 1-Satz-Story-Text | gebaut aus `limiting_factor` + Risikoprofil-Label + max_risky |
| `rv-message-banner` | Banner-Card (nur wenn conflict/warning) | `messages[severity in {conflict,warning}][0]` |
| `rv-goal-achievability-list` | UL mit Zielerreichungs-Items | `goal_achievability[]` |
| `rv-details-accordion` | `<details>` für Solver-Details | bestehend |

### 3.3 Ampel-Logik (JS)

```javascript
function rvGoalProbBadge(prob){
  // prob: float in [0,1]
  if (prob >= 0.80) return {icon: "●", color: "var(--pos)", label: "komfortabel"};
  if (prob >= 0.50) return {icon: "◐", color: "var(--warn)", label: "knapp"};
  return {icon: "○", color: "var(--neg)", label: "nicht plausibel"};
}
```

### 3.4 Allokations-Story-Builder (JS)

Erzeugt aus `limiting_factor` + Profil + max_risky einen 1-Satz-Text:

```javascript
function rvBuildAllocationStory(targetAllocation, riskAssessment){
  var factor = targetAllocation.limiting_factor;
  var profile = riskAssessment.final_profile;
  var maxRisky = (targetAllocation.risk_budget_bps_at_generation / 100).toFixed(0);
  var realRisky = (targetAllocation.risky_fraction_bps_at_generation / 100).toFixed(0);

  if (factor === "risikoprofil") {
    return "Die Allokation schöpft das Risikobudget Ihres Profils «" + profile +
           "» (max. " + maxRisky + "%) bewusst aus, um die Zielerreichung zu maximieren. " +
           "Effektiv risikobehaftet: " + realRisky + "%.";
  }
  if (factor === "liquiditaetsreserve") {
    return "Ihre Liquiditätsreserve wirkt als Untergrenze — der Optimierer hält den " +
           "geforderten Mindestanteil sicherer Anlagen ein. Effektiv risikobehaftet: " +
           realRisky + "%.";
  }
  if (factor === "bandbreite") {
    return "Die Allokation liegt komfortabel innerhalb Ihrer Profilbandbreiten. " +
           "Risikoprofil «" + profile + "» ist nicht bindend. Effektiv: " + realRisky + "%.";
  }
  if (factor === "zielkonflikt") {
    return "Mindestens zwei Ihrer Ziele schliessen sich teilweise aus — die Allokation " +
           "ist ein Kompromiss. Siehe Hinweisbanner für Details.";
  }
  if (factor === "solver_konvergenz") {
    return "Der Optimierer konnte nicht konvergieren. Strategie nutzt den Bandbreiten-" +
           "Mittelwert Ihres Profils «" + profile + "».";
  }
  return "Strategie auf Risikoprofil «" + profile + "» ausgerichtet.";
}
```

### 3.5 Limiting-Factor-Badge-Mapping

| `limiting_factor` (Backend) | Badge-Text | Farbe |
|---|---|---|
| `risikoprofil` | "Risikoprofil limitiert" | rot |
| `liquiditaetsreserve` | "Liquiditätsreserve bindend" | gelb |
| `bandbreite` | "Innerhalb der Bandbreiten" | grün |
| `zielkonflikt` | "Zielkonflikt erkannt" | rot |
| `solver_konvergenz` | "Bandbreiten-Mittelwert (Fallback)" | gelb |

## 4. Asset-Allocation-Page (page-al)

### 4.1 Konflikt-Banner-Integration

Wenn `messages` Einträge mit `severity in {conflict, warning}` enthält,
oberhalb des Optimizer-Panels eine Banner-Card einblenden:

```html
<div id="al-message-banner" class="al-banner-conflict" style="display:none">
  <div class="al-banner-icon">⚠</div>
  <div class="al-banner-content">
    <div class="al-banner-title"></div>
    <div class="al-banner-body"></div>
    <div class="al-banner-actions"></div>
  </div>
</div>
```

Sichtbar nur wenn mindestens eine `conflict`- oder `warning`-Message vorliegt.
`conflict` rendert mit `.al-banner-conflict` (rotes Border-Left), `warning`
mit `.al-banner-warning` (gelb).

### 4.2 Optimizer-Panel-Erweiterung

Das existierende `#al-optimizer-panel` (Phase 6) zeigt zusätzlich:
- `limiting_factor` als Badge im Panel-Header.
- `goal_achievability[]` als kompakte Tabelle unter Reasoning-Trace.

## 5. PDF-Integration (Stage 7 — Vorgabe)

### 5.1 Anlagestrategie-PDF

In der Sektion "Strategie-Begründung" (existierend) neu am Schluss:

- **Limiting-Factor**-Zeile: *"Limitierender Faktor: {limiting_factor_label}"*
- **Zielerreichungs-Tabelle**: Spalten Ziel / Typ / Hardness / Wahrscheinlichkeit / Status.

Komponenten-Vorschlag: neue Datei
`services/pdf/components/goal_achievability.py` mit
`make_goal_achievability_table(achievability_list) -> Table`.

### 5.2 Protokoll-PDF

Bei `messages` mit `severity=conflict`: Pflichthinweistext am Ende des
Protokolls *"Im Beratungsgespräch wurde folgender Zielkonflikt
dokumentiert: ..."*.

## 6. CSS-Hinweise (Codex)

Neue Klassen — sparsam, im bestehenden Stil:

```css
/* Banner-Cards */
.al-banner-conflict, .al-banner-warning {
  display: flex; gap: 10px; padding: 10px 12px; border-radius: 6px;
  margin-bottom: 12px; font-size: 12px; line-height: 1.5;
}
.al-banner-conflict { background: var(--neg-lt); border-left: 3px solid var(--neg); color: var(--neg); }
.al-banner-warning  { background: var(--warn-lt); border-left: 3px solid var(--warn); color: var(--n8); }

/* Review-Cockpit */
.rv-goal-prob-icon { font-size: 18px; margin-right: 6px; }
.rv-limiting-badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
                     font-size: 11px; font-weight: 600; }
.rv-goal-list      { display: grid; gap: 6px; font-size: 12px; }
.rv-goal-list-item { display: grid; grid-template-columns: 24px 1fr auto auto;
                     gap: 8px; padding: 6px 8px; border: 1px solid var(--b1);
                     border-radius: 4px; }

/* Goal-Editor */
.m-acf-field          { display: block; margin-bottom: 10px; }
.m-acf-derived        { margin-top: 6px; font-size: 11px; color: var(--n5); }
.m-acf-derived strong { color: var(--n8); }
```

Kein neues Navy-Gold-CSS, keine Inline-Styles für Standard-Komponenten.

## 7. Acceptance-Kriterien (UX-spezifisch, ergänzend zu Haupt-Spec §10)

1. **Goal-Editor zeigt typabhängige Felder.** Test: Inline-JS prüft per
   Type-Switch, dass nur die richtigen `.m-acf-field` sichtbar sind.
2. **Renditeziel kann nicht `hart` gewählt werden** (UI-Disabled-Test +
   Server 422 schon in Haupt-Spec Acceptance #2).
3. **Review-Cockpit zeigt Hauptziel + Wahrscheinlichkeit + Ampel.**
   Contract-Test: HTML enthält `#rv-main-goal-prob` mit Element für Wert.
4. **Limiting-Factor-Badge sichtbar.** Contract-Test: HTML enthält
   `#rv-limiting-factor-badge`.
5. **Konflikt-Banner sichtbar wenn `messages` `conflict`/`warning`.**
   Contract-Test: `#al-message-banner` und `#rv-message-banner` vorhanden,
   JS bindet `messages[0]`.
6. **Allokations-Story-Text wird gerendert.** Test: `#rv-allocation-story`
   enthält den Profil-Namen und die Risikoquote.
7. **Inline-JS-Parse 0 Fehler.**
8. **Keine verbotenen Formulierungen.** Grep-Test über die 7 Message-Bodies
   stellt sicher, dass kein "Erhöhen Sie Ihr Risiko" / "garantiert" /
   "perfekt" vorkommt.
9. **Bestehende Frontend-Contracts grün** (Header-Tests, Navigation, Risk-
   Questionnaire, Admin-Market-Data, Asset-Class-Prices-Panel).

## 8. Codex-Taskliste — Konsolidiert für Stage 4 und Stage 6

### Stage 4 (Messages-Katalog, Backend)

1. Neues Modul `services/allocation_messages.py`:
   - Enum/Konstanten für die 7 Codes.
   - `classify_messages(allocation, achievability, optimization_status, mandate, assessment) -> list[Message]` mit den Texten aus §1.2.
   - Placeholder-Substitution: `{goal_label}`, `{prob}`, `{profile_label}`, `{override_label}`, `{reason}`, `{goal_a}`, `{goal_b}`.
2. In `generate_target_allocation` (portfolio_engine.py) aufrufen, Resultat in der Response (`messages`) und persistieren als Teil von `optimizer_reasoning_json` (oder neuem Feld `messages_json` — siehe Haupt-Spec §8.2).
3. Tests: `tests/test_allocation_messages.py` mit je 1 Test pro Code (synthetisches Fixture).

### Stage 6 (Frontend)

1. `5eyes_v2.html m-acf` umbauen:
   - `m-acf-type-select` als erstes Feld.
   - Neue Felder `m-acf-target-return-bps`, `m-acf-priority-rank`, `m-acf-success-prob-min` (letzteres in Details/Accordion).
   - `m-acf-derived` Block für Live-Diagnose.
   - JS: `applyGoalTypeVisibility(type)` aus §2.2.
   - JS: `updateGoalDerivedDiagnostics()` aus §2.3.
   - Event-Listener: `m-acf-type-select.change` → `applyGoalTypeVisibility` + `updateGoalDerivedDiagnostics`.
2. `5eyes_v2.html page-rv` umbauen:
   - Hauptziel-KPI-Tile (`rv-main-goal-*` IDs).
   - Limiting-Factor-Badge (`rv-limiting-factor-badge`).
   - Allokations-Story (`rv-allocation-story`) — Builder aus §3.4.
   - Konflikt-Banner (`rv-message-banner`).
   - Zielerreichungs-Liste (`rv-goal-achievability-list`).
   - Solver-Details in `<details>` Accordion verschieben.
3. `5eyes_v2.html page-al`:
   - `al-message-banner` über `al-optimizer-panel`.
   - `al-optimizer-panel` zeigt zusätzlich `limiting_factor`-Badge und
     `goal_achievability`-Mini-Tabelle.
4. CSS-Klassen aus §6 ergänzen (nicht inline).
5. Contract-Tests `tests/test_frontend_goal_editor_isolation.py`,
   `tests/test_frontend_review_cockpit.py`, `tests/test_frontend_messages_banner.py`.

### Stage 7 (PDF) — Vorgabe

1. Neue Komponente `services/pdf/components/goal_achievability.py`.
2. In `services/pdf/documents/anlagestrategie.py` Sektion
   "Strategie-Begründung" um `limiting_factor` + Achievability-Tabelle
   erweitern.
3. Protokoll-PDF: Pflichthinweistext bei `conflict`-Messages.
4. Tests in `tests/test_backtest_pdf.py` analog ergänzen (Struktur-
   Assertions, nicht nur `%PDF`).

## 9. Verifikation (Stage 6+7 Ende)

- `python -m pytest -p no:cacheprovider tests/ -q` grün.
- `node -e "…"` Inline-JS-Parse 0 Fehler.
- Manuell in Electron:
  1. Foundation-Mandat öffnen, Renditeziel anlegen → `hart` ist disabled.
  2. Wachstumsorientiertes Profil + zu hohes Renditeziel → `CONFLICT_PROFILE_LIMITS` Banner sichtbar.
  3. Review öffnen → Hauptziel-Ampel, Limiting-Factor-Badge, Allokations-Story sichtbar.
  4. PDF generieren → Sektion "Strategie-Begründung" enthält Achievability-Tabelle.

## 10. Offene UX-Fragen an Owner

1. **Banner-Permanenz:** Soll der Banner bei `conflict` den Abschluss-Button
   blockieren (visuell + funktional), oder nur warnen? Vorschlag: visuelle
   Stärke (rot, Border-Left) + Hinweis im Tooltip, aber Abschluss bleibt
   möglich. Berater dokumentiert mit.
2. **`priority_rank`-UI:** Slider 1-5 oder Drag&Drop in einer Goal-Liste?
   Vorschlag: zunächst Slider 1-5 im Goal-Editor (einfach), Drag&Drop später
   wenn Bedarf entsteht.
3. **Success-Probability-Override:** Soll `success_probability_min_x100` pro
   Goal überhaupt im UI sichtbar sein, oder nur Backend-Default? Vorschlag:
   im Details/Accordion-Bereich, advanced advisor only.
