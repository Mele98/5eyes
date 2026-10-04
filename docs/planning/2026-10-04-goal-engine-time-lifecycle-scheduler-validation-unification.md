# Goal-Engine: Valuation-Date, Occurrence-Scheduler, Lifecycle & MC-Validation Unification

## Meta

- Titel: Vereinheitlichung von Bewertungsstichtag, Occurrence-Scheduler, Goal-Lifecycle und Monte-Carlo-Validierung
- Datum: 2026-10-04
- Owner: Emanuele Konzelmann
- Quelle: `docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md` (Kontrollrunde 38, paralleler Codex/GPT-Audit), umgesetzt als 30 rote Tests in PR #521
- Branch-Vorschlag: `docs/goal-engine-time-lifecycle-validation-adr`

## Ziel

Die fünf in Kontrollrunde 38 bestätigten P1-Funde (`GOAL-RECURRING-EDITOR-CONTRACT-001`, `GOAL-RECURRENCE-SCHEDULE-001`, `GOAL-PAST-DATE-LIFECYCLE-001`, `GOAL-CALENDAR-HORIZON-PARITY-001`, `OPTIMIZER-POST-SELECTION-CERTIFICATION-001`) teilen vier gemeinsame, bislang ungeklärte Grundsatzfragen, die VOR jeder Implementierung entschieden werden müssen (Audit, "Empfohlene Implementierungsreihenfolge für Claude", Punkt 3: "Owner-ADR Time/Lifecycle"). Dieses Dokument beantwortet jede Frage mit einer begründeten, fachlich/mathematisch/rechtlich hergeleiteten Empfehlung und markiert sie trotzdem explizit als `OWNER-DECISION` — die Entscheidung bleibt bei dir, aber du entscheidest auf Basis einer fertigen Analyse, nicht auf leerem Blatt.

**Wichtiger Vorbehalt:** Ich bin kein zugelassener Schweizer Rechtsanwalt. Die rechtlichen Einordnungen unten sind Ingenieurs-Risikologik auf Basis bereits etablierter Projekt-Konventionen (siehe unten zitierte Memory-Einträge) und öffentlich bekannter FIDLEG/DSG/OR-Normtexte, keine Rechtsberatung. Vor Produktivsetzung sollte eine tatsächliche Rechtsprüfung (falls die Firma einen Rechtsbeistand hat) diese Annahmen bestätigen.

## Problem

Vier Schichten des Goal-Engine (Router, Optimizer, Reporting-MC, UI/PDF) treffen unabhängig, mit unterschiedlichen Formeln, dieselben vier Grundentscheidungen: **(1)** welcher Stichtag gilt, **(2)** wie eine wiederkehrende Zahlung in Jahres-Buckets zerlegt wird, **(3)** was mit einem vergangenen/überfälligen Ziel wirtschaftlich passiert, **(4)** ob eine auf einem MC-Würfel ausgewählte Erfolgswahrscheinlichkeit ohne unabhängige Evidenz als "sicher" gelten darf. Die 30 roten Tests in PR #521 beweisen, dass alle vier Fragen heute inkonsistent beantwortet werden. Ohne eine verbindliche Antwort pro Frage kann keiner der fünf Funde korrekt (statt scheinbar) gefixt werden — siehe die expliziten "Nicht ausreichende Scheinfixes" im Audit.

## Scope

- ADR-1: Bewertungsstichtag (`valuation_date`) und Kalenderjahr-Konvention
- ADR-2: Kanonischer Occurrence-Scheduler für wiederkehrende Ziele
- ADR-3: Goal-Lifecycle (vergangen/überfällig/storniert/erfüllt)
- ADR-4: Monte-Carlo Train/Validation-Vertrag für die Zielwahrscheinlichkeits-Zertifizierung
- ADR-5: React-Goal-Editor-Vertrag (discriminated union) — geringer Entscheidungsbedarf, der Vollständigkeit halber aufgenommen

## Nicht-Scope

- `GoalFundingPolicy` / `amount_funded` vs. `amount_due` (Runde 37, eigener, bereits offener Fund — dieses Dokument liefert nur den korrekten `amount_due`-Input dafür)
- Unterjährige Zahlungs-Präzision innerhalb eines Jahres-Buckets (`WITHDRAWAL-TIMING-001`, bewusst als separater P2-Vertrag abgegrenzt)
- Tatsächliche Implementierung der fünf Funde — folgt in eigenen PRs, nachdem dieses Dokument bestätigt ist

---

## ADR-1: Bewertungsstichtag und Kalenderjahr-Konvention

### Befund

Vier verschiedene Formeln sind heute aktiv:

| Ort | Formel | Mathematische Eigenschaft |
|---|---|---|
| `calendar_horizon.calendar_years_until(target, as_of)` | exakter Kalenderjahrestag-Vergleich, leap-aware | korrekt, aber nur wenn `as_of` explizit übergeben wird |
| `routers/wealth.py::_goal_horizon_from_date` | `max(1, (delta_days+364)//365)` | Tage-Ceiling, überzählt systematisch um +1 bei jedem überschrittenen Schaltjahr |
| `services/portfolio_engine_payload.py::_goal_projection_years` | identische Tage-Ceiling-Formel | dieselbe Verzerrung |
| `5eyes_v2.html` (Classic) | `365.25`-Tage-Näherung | driftet zusätzlich, da 365.25 selbst nur ein Mittelwert über den Gregorianischen Zyklus ist, kein Kalenderanker |
| `reporting/goalClassification.ts` / `pdf/components/goal_classification.py` | reine Kalenderjahr-Differenz (`target.year - as_of.year`) | ignoriert Monat/Tag komplett |

**Mathematische Einordnung:** Nur `calendar_years_until` mit explizitem `as_of` implementiert die in Aktuariats- und Pensionsrecht übliche "exact age" / Kalenderanniversar-Konvention (vergleichbar mit der Art, wie AHV/BVG-Altersgrenzen am Geburtsdatum, nicht an einem Tage-Mittelwert, gemessen werden). Die Tage-Ceiling- und 365,25-Formeln sind statistische Verzerrungen (systematischer Bias von bis zu +1 Jahr bei langen Horizonten mit mehreren Schaltjahren), keine neutralen Rundungsfehler.

**Rechtliche Einordnung:** FIDLEG Art. 8 (Dokumentationspflicht) und Art. 20/21 (Eignungs-/Angemessenheitsprüfung) setzen voraus, dass die dem Kunden gezeigte Projektion intern konsistent und reproduzierbar ist. Dass derselbe Fall je nach Kanal als "erreichbar" und "nicht erreichbar" erscheinen kann (Audit Repro 4), ist eine Darstellungs-Inkonsistenz, die im Streitfall als Sorgfaltspflichtverletzung (Art. 398 OR) ausgelegt werden könnte, wenn der Kunde sich auf die "günstigere" Ansicht verlassen hat.

### OWNER-DECISION 1a — Kanonische Formel

**Empfehlung:** `calendar_years_until(target, as_of)` wird die EINZIGE Horizont-Formel im gesamten System. Router, Optimizer, Reporting-MC, Reserve, UI und PDF rufen ausschliesslich diese eine Funktion auf (ggf. über einen zentralen Resolver, siehe ADR-2). Die drei anderen Formeln werden ersatzlos entfernt, nicht parallel weitergeführt.

**Begründung:** Es ist bereits die einzige der vier Formeln, die als Positivkontrolle im Audit bestätigt korrekt ist; die anderen drei haben nachweislich unterschiedliche, inkompatible Bias-Richtungen. Es gibt keine fachliche Rechtfertigung, mehr als eine Konvention zu pflegen.

☐ Bestätigt ☐ Abgelehnt — falls abgelehnt, bitte alternative Formel benennen.

### OWNER-DECISION 1b — Bindung des Stichtags

**Empfehlung:** Jeder Optimizer-Run / jede Report-Generierung bindet `valuation_date` explizit beim Zeitpunkt der User-Aktion (Klick auf "Anlagestrategie berechnen" / "Report generieren"), persistiert ihn im Run/Allocation-Datensatz, und jede Folgeberechnung (Replay, PDF-Reprint, UI-Reload) liest den GESPEICHERTEN Stichtag — niemals erneut `date.today()`. Ein Reload mit dem heutigen Tag muss explizit als neuer, separat benannter "Counterfactual-Run" angestossen werden, nicht automatisch beim Öffnen einer bestehenden Ansicht.

**Begründung:** Audit-Trail-Integrität (vgl. bereits etabliertes Projekt-Prinzip, siehe `project_5eyes_ceo_cfo_cio_audit_2026_08_07`-Memory: der Audit-Log-Unveränderlichkeits-Trigger-Bugfix wurde als kritisch eingestuft — dieselbe Logik gilt für Berechnungs-Stichtage: ein Replay darf nicht leise ein anderes wirtschaftliches Ergebnis liefern als beim ersten Lauf).

☐ Bestätigt ☐ Abgelehnt

### OWNER-DECISION 1c — Snapshot-Hash-Bindung

**Empfehlung:** `_compute_input_snapshot_hash()` nimmt `valuation_date` (und die Resolver-/Bucket-Konventions-Version aus 1a) als Pflicht-Input auf. Eine Änderung des Stichtags muss den Hash sichtbar ändern.

☐ Bestätigt ☐ Abgelehnt

---

## ADR-2: Kanonischer Occurrence-Scheduler

### Befund

`goal_liabilities._build_recurring_outflow()` zählt berührte Kalenderjahr-LABELS (`target_date.year - start_date.year + 1`) und bucht den vollen Jahresbetrag in jedes Label. `cashflow_timeline.contribution_for_year()` enumeriert stattdessen echte Fälligkeitstermine (Anker-Datum + Frequenz-Schritt, bis Ende) und summiert nur die tatsächlich fälligen Beträge pro Jahr — bereits korrekt, bereits mit Property-Tests abgesichert (Audit Positivkontrolle #3).

**Mathematische Formalisierung des Soll-Vertrags:** Für eine Serie mit Anker `t_0 = start_date`, Periodenlänge `Δ` (z.B. 1/12 Jahr bei monatlich) und Ende `t_end`:

```
Occurrences: t_k = t_0 + k·Δ  für k = 0, 1, 2, ...  solange t_k ≤ t_end (inklusiv)
amount_due[bucket(j)] = Σ { amount : t_k ∈ Jahr j }   mit bucket(d) = ⌊calendar_years_until(d, as_of)⌋
```

Dies ist exakt, was `contribution_for_year()` bereits berechnet. Der Fix besteht NICHT darin, eine neue Formel zu erfinden, sondern `goal_liabilities.py` auf den bestehenden, bereits korrekten Enumerator umzustellen.

### OWNER-DECISION 2a — Endpunkt-Inklusivität

**Empfehlung:** Inklusiv (`t_k ≤ t_end`, nicht `<`). Dies ist bereits die etablierte Projekt-Konvention für `valid_until` bei Cashflows (siehe `feedback_conservative_values`/`project_5eyes_cashflow_konventionen`-Memory: "valid_until INKLUSIV"). Keine neue Entscheidung nötig — nur Bestätigung, dass dieselbe Konvention für Goals gilt.

☐ Bestätigt ☐ Abgelehnt

### OWNER-DECISION 2b — Granularität der Engine-Buckets

**Empfehlung:** Jahres-Buckets bleiben die Simulationsauflösung (keine Umstellung auf monatliche Pfad-Schritte) — das beträfe die gesamte stochastische Kern-Architektur und ist bewusst nicht Teil dieses Fixes. Innerhalb eines Jahres-Buckets wird aber die ANZAHL und SUMME der Occurrences exakt (nicht approximiert) berechnet. Unterjährige Platzierungs-Präzision (wann GENAU im Jahr das Geld fehlt) bleibt der separate `WITHDRAWAL-TIMING-001`-P2-Vertrag.

☐ Bestätigt ☐ Abgelehnt

### OWNER-DECISION 2c — Konsolidierung

**Empfehlung:** `goal_liabilities.py` ruft `cashflow_timeline`s Enumerator direkt auf (oder beide nutzen einen gemeinsam extrahierten Kern), statt eine zweite, parallele Implementierung zu pflegen. `portfolio_engine_mc_simulation.py`s eigene Duplikat-Logik (Audit: "wiederholt die falsche Summenlogik unabhängig vom Optimizer") wird ersatzlos entfernt und ersetzt durch denselben Aufruf.

☐ Bestätigt ☐ Abgelehnt

---

## ADR-3: Goal-Lifecycle

### Befund

Die Goal-Domain kennt nur `is_active` (Boolean) und `deleted_at` (Soft-Delete). Es gibt keinen Zustand für "vergangen, aber nie bestätigt", "überfällig", "erfüllt" oder "storniert". `max(1, calendar_years_until(...))` verwandelt jedes vergangene Datum silently in "Jahr 1 ab jetzt" — ein 2020 abgelaufener dreijähriger Zahlungsstream wird so 2026 als drei NEUE Jahre Zahlungspflicht wiederbelebt (Audit Repro 3).

### OWNER-DECISION 3a — Lifecycle-Zustände

**Empfehlung:** Mindestens `planned` | `due` | `overdue` | `fulfilled` | `cancelled` | `historical_unknown` (letzterer nur für Legacy-Migration, nie für neue Goals). Transitionen append-only auditiert (Actor, Zeitstempel, Grund) — konsistent mit dem bereits etablierten Audit-Log-Unveränderlichkeits-Prinzip dieses Projekts.

☐ Bestätigt ☐ Abgelehnt

### OWNER-DECISION 3b — Overdue-Policy (die wichtigste Einzelentscheidung dieses Dokuments)

Drei Optionen, wie ein überfälliges Ziel (Zieldatum vergangen, keine Lifecycle-Entscheidung dokumentiert) behandelt wird:

1. **Sofortiger t0-Bedarf**: der fällige Betrag wird als sofortige Belastung im aktuellen Simulationsjahr gebucht.
2. **Neu verhandeltes Fälligkeitsdatum**: der Berater muss explizit ein neues Datum setzen; bis dahin bleibt das Ziel im Zustand `overdue` ohne Liability-Beitrag.
3. **Blockierender Klärungszustand**: die gesamte Berechnung für dieses Mandat wird blockiert (bzw. das Ziel wird mit einer harten Warnung aus der aktiven Berechnung ausgeschlossen), bis der Berater explizit entscheidet.

**Empfehlung: Variante 3 als Fail-Closed-Default, mit Variante 1 oder 2 als die beiden einzigen zulässigen, vom Berater explizit gewählten Auflösungen.**

**Begründung (rechtlich/fachlich):** Die aktuelle Silent-Reaktivierung erzeugt ein wirtschaftliches Bild, das mit der Realität nichts zu tun hat — eine 2020-2022 bereits abgelaufene Verpflichtung als drei NEUE Jahre 2026-2028 zu buchen, ist keine konservative Schätzung, sondern eine erfundene Tatsache. Eine Beratungssoftware, die FIDLEG-relevante Eignungs-/Angemessenheitsprüfungen auf Basis einer erfundenen Verpflichtung durchführt, exponiert sowohl den Berater (persönliche Sorgfaltspflicht, Art. 398 OR) als auch die Firma gegenüber einem Kunden, der sich auf eine falsche Liquiditätsplanung verlässt. Dieses Projekt hat dieses Prinzip bereits mehrfach selbst angewendet (Memory: "Fail-open→closed x3", "Backend-Complete-State-Guard blockiert... heute mit 422" als explizit zu erhaltende Positivkontrolle) — Variante 3 ist die konsequente Fortsetzung dieses bereits etablierten Hauses-Standards, nicht eine neue Philosophie.

**Kosten der Empfehlung:** zusätzliche UX-Reibung (Berater muss aktiv klären, bevor eine Berechnung für ein Mandat mit überfälligen Zielen läuft). Das ist der richtige Trade-off für Finanzberatungssoftware.

☐ Variante 3 (fail-closed, empfohlen) ☐ Variante 1 ☐ Variante 2 ☐ Andere: ___________

### OWNER-DECISION 3c — Nachweis für `fulfilled`/`cancelled`

**Empfehlung:** Pflichtfeld Begründungstext + Zeitstempel + Actor, append-only. Kein Ziel darf ohne diesen Nachweis in einen Terminal-Zustand wechseln.

☐ Bestätigt ☐ Abgelehnt

---

## ADR-4: Monte-Carlo Train/Validation-Vertrag

### Befund

`chance_constraint_penalty()` zertifiziert `probability >= tau` sofort als "erreichbar", ohne Berücksichtigung der endlichen Stichprobengrösse. Dieselbe Stichprobe, die zur Kandidatenauswahl diente, wird auch zur finalen Zertifizierung verwendet — ein klassischer Winner's-Curse-/Post-Selection-Bias (Audit Repro 7: Trainings-Zertifizierung ~97-98/100, unabhängige Validierung nur ~53-57/100 bei identischer wahrer Erfolgswahrscheinlichkeit).

### Mathematische Herleitung der Empfehlung

**Warum unabhängige Validierung ausreicht (und keine komplexere Post-Selection-Inference-Korrektur nötig ist):** Der Bias entsteht ausschliesslich dadurch, dass dieselbe Zufallsstichprobe zur Auswahl UND zur Zertifizierung verwendet wird. Eine Stichprobe, die an der Auswahl NICHT beteiligt war, ist per Konstruktion unabhängig von der Auswahlentscheidung — unabhängig davon, wie viele Kandidaten verglichen wurden oder wie die Auswahl getroffen wurde. Eine einfache unabhängige Validierungs-Stichprobe ist daher mathematisch hinreichend; aufwändigere Verfahren (z.B. formale Post-Selection-Inference nach Berk et al. 2013, oder eine Bonferroni-Korrektur über die Kandidatenzahl) sind nicht erforderlich und würden nur zusätzliche, fehleranfällige Komplexität einführen.

**Warum die Validierungs-Stichprobe NICHT antithetisch/IS-gewichtet sein sollte:** Common Random Numbers und Importance Sampling sind für den TRAINING-Vergleich zwischen Kandidaten korrekt und sollen erhalten bleiben (Audit-Positivkontrolle #5/#7). Für die Validierung ist aber eine saubere, unverzerrte Unsicherheits-Quantifizierung wichtiger als Varianzreduktion — eine gewöhnliche (nicht gepaarte, nicht gewichtete) i.i.d.-Stichprobe erlaubt den Einsatz exakter, textbook-standardisierter Konfidenzintervalle statt einer aufwändigeren Cluster-robusten/Delta-Methoden-Varianzschätzung für korrelierte Paare.

**Welches Konfidenzintervall:** Wilson-Score-Intervall (Wilson 1927; Standardempfehlung seit Agresti & Coull 1998 gegenüber dem naiven Wald/Normal-Intervall, das insbesondere nahe `p≈0.8-0.9` bei moderaten `n` zu optimistisch ist — exakt der hier relevante Bereich). Bereits als Referenz-Formel in PR #521s rotem Test für dieses Finding verwendet.

### OWNER-DECISION 4a — Konfidenzniveau

**Empfehlung:** α = 0.05 (einseitiges 95%-Lower-Bound). Dies ist eine Risikoappetit-Entscheidung der Firma (kein reiner Mathematik-Fakt) — 95% ist der in Finanz-/Aktuariatspraxis übliche Standardwert, sofern keine andere interne Risikopolitik existiert.

☐ 95% (empfohlen) ☐ 90% ☐ 99% ☐ Anderer Wert: ______

### OWNER-DECISION 4b — Umgang mit der Unsicherheitszone

Wenn der Lower Bound zwischen `TAU_UNREACHABLE` (0.50) und `tau` liegt:

**Empfehlung (v1):** Status `statistisch_unsicher` anzeigen und stoppen — keine sequenzielle Pfad-Erweiterung. Eine feste Validierungs-Pfadzahl (empfohlen: 20'000–50'000, siehe 4c) macht "unsicher" in der Praxis selten. Sequenzielle Erweiterung mit korrektem Alpha-Spending (O'Brien-Fleming/Pocock) ist mathematisch möglich, aber deutlich komplexer und fehleranfälliger — als v2-Option vormerken, falls "unsicher" operativ zu oft auftritt.

☐ v1 (fix, kein Alpha-Spending, empfohlen) ☐ v2 (sequenziell mit Alpha-Spending) direkt umsetzen

### OWNER-DECISION 4c — Validierungs-Pfadzahl

**Empfehlung:** 20'000 Pfade. Begründung: Wilson-Intervall-Halbbreite bei `p=0.8`, `n=20'000`, `α=0.05` beträgt ≈ 0,0057 (< 1 Prozentpunkt) — deutlich enger als die Distanz zwischen `tau` und `TAU_UNREACHABLE` (0.80 vs. 0.50), sodass die Unsicherheitszone in der Praxis nur bei wirklich grenzwertigen Fällen greift. Rechenkosten: einmalig pro finalem Kandidaten (nicht pro Trainings-Iteration), vertretbar.

☐ 20'000 (empfohlen) ☐ Andere Zahl: ______

### OWNER-DECISION 4d — Persistenz

**Empfehlung:** `OptimizerRun` erhält zusätzlich `validation_seed`, `validation_n_paths`, `validation_cube_hash`, `validation_lower_bound_x10000`, `validation_alpha_x10000`, `reliability_verdict`. Ein fehlender oder manipulierter Validierungs-Anker blockiert Reload/Publikation (fail-closed, konsistent mit ADR-3b).

☐ Bestätigt ☐ Abgelehnt

### Einordnung zu `OPTIMIZER-IS-ESS-001` (bereits offen, keine neue Entscheidung)

Die ESS-Schwelle für die TRAINING-seitige Objective-/Penalty-Berechnung (nicht die Validierung, die laut 4a/4c keine IS-Gewichte verwendet) folgt der Standard-Heuristik `ESS/N < 10%` ⇒ `unreliable` (Kong 1992; Liu 2001) — dies ist die übliche Daumenregel in der Importance-Sampling-Literatur und keine neue Owner-Entscheidung, sondern Teil der bereits offenen `OPTIMIZER-IS-ESS-001`-Umsetzung.

---

## ADR-5: React-Goal-Editor-Vertrag

Geringer Entscheidungsbedarf — primär Software-Architektur, keine Fachentscheidung:

- `GoalFormInput` wird eine diskriminierte Union pro `goal_type` (TypeScript `type GoalFormInput = { goal_type: "Wiederkehrende_Ausgabe"; amount: number; startDate: string; endSemantics: {kind:"ongoing"} | {kind:"finite"; endDate:string} } | ...`).
- `stateFromRecord()`, sichtbare Controls, `toFormInput()`, `buildGoalPayload()` roundtrippen exakt dieselben Felder.
- Classic (`5eyes_v2.html`) und React senden für denselben fachlichen Input denselben normalisierten Payload (bereits in PR #521 als Red-Test `goalForm.classicParity.test.ts` dokumentiert).

**OWNER-DECISION 5a:** Keine zu treffen — Implementierungsfreigabe genügt, sobald ADR-1 bis ADR-4 bestätigt sind (der Editor sendet ja erst dann sinnvolle Felder, wenn Backend-Vertrag und Lifecycle stehen).

---

## Betroffene Module / Dateien

- Backend: `services/calendar_horizon.py`, `services/optimizer/goal_liabilities.py`, `services/cashflow_timeline.py`, `services/portfolio_engine_payload.py`, `services/portfolio_engine_mc_simulation.py`, `services/portfolio_engine.py` (Snapshot-Hash), `services/optimizer/objective.py`, `services/optimizer/solver.py`, `models/wealth.py` (Goal-Lifecycle-Spalten), `models/allocation.py` (OptimizerRun-Validierungs-Spalten), `routers/wealth.py`
- Frontend: `reporting/src/sections/goals/GoalWizard.tsx`, `reporting/src/lib/goalForm.ts`, `reporting/src/lib/goalClassification.ts`, `5eyes_v2.html` (Classic-Parität)
- Datenmodell: Migration für Goal-Lifecycle-Spalten + OptimizerRun-Validierungs-Spalten
- Tests: die 30 bereits in PR #521 vorhandenen roten Tests dienen als Akzeptanzkriterium — sie müssen nach Implementierung grün werden (xfail-Marker entfernt, `strict=True` erzwingt das ohnehin als harten Fehler bei stillem Grünwerden ohne Entfernen des Markers)

## Akzeptanzkriterien

1. Alle vier ADRs (1-4) sind vom Owner entschieden (☐-Kästen oben ausgefüllt).
2. Jede Entscheidung ist in genau einem zentralen Resolver-Modul implementiert, nicht pro Caller dupliziert.
3. Alle 30 roten Tests aus PR #521 werden grün (xfail-Marker entfernt).
4. Kein bestehender grüner Test regressiert (volle Backend- + Frontend-Suite).
5. Legacy-Daten (bestehende Goals/Allocations ohne die neuen Felder) werden beim nächsten Zugriff repariert oder sichtbar als `historical_unknown`/`validation_unknown` markiert, nie stillschweigend als "neu gültig" interpretiert.

## Risiken

- UX-Reibung durch Fail-Closed-Overdue-Policy (ADR-3b) — bewusst in Kauf genommen, siehe Begründung dort.
- Migration bestehender Mandate mit bereits vergangenen/überfälligen Zielen erzeugt kurzfristig sichtbare Klärungsbedarfe im Berater-Alltag — sollte vor Rollout kommuniziert werden.
- Validierungs-Cube (ADR-4) verdoppelt grob die Rechenzeit pro finaler Allokation (ein zusätzlicher MC-Lauf) — bei 20'000 Pfaden auf modernem Hardware im Sekundenbereich, nicht geschäftskritisch, aber im Performance-Budget-Test (`test_performance_budget.py`) zu berücksichtigen.

## Offene Fragen an Owner

Siehe die sechzehn `OWNER-DECISION`-Markierungen oben (1a-1c, 2a-2c, 3a-3c, 4a-4d, 5a). Jede trägt eine konkrete Empfehlung; die Kästen sind zum Ankreuzen/Kommentieren gedacht.
