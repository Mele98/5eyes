# Goal-Engine & CMA/Policy-Infrastruktur: Zeit-, Lifecycle-, Validierungs- und Identitäts-Unification

## Meta

- Titel: Vereinheitlichung von Bewertungsstichtag, Occurrence-Scheduler, Goal-Lifecycle, Monte-Carlo-Validierung, CMA-Gültigkeit und Policy-Versionsidentität
- Datum: 2026-10-04 (ADR-6 bis ADR-8 ergänzt am 2026-10-04, nach Kontrollrunde 40)
- Owner: Emanuele Konzelmann
- Quelle Teil 1 (ADR-1 bis ADR-5): `docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md` (Kontrollrunde 38), umgesetzt als 30 rote Tests in PR #521
- Quelle Teil 2 (ADR-6 bis ADR-8): drei Folgeaudits vom 2026-10-04 (`2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md`, `2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md`, `2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md`, Kontrollrunde 39/40), umgesetzt als 13 rote Tests in PR #523
- Branch-Vorschlag: `docs/goal-engine-time-lifecycle-validation-adr`

## Ziel

Acht insgesamt bestätigte P1-Funde über zwei Audit-Wellen (Kontrollrunde 38: `GOAL-RECURRING-EDITOR-CONTRACT-001`, `GOAL-RECURRENCE-SCHEDULE-001`, `GOAL-PAST-DATE-LIFECYCLE-001`, `GOAL-CALENDAR-HORIZON-PARITY-001`, `OPTIMIZER-POST-SELECTION-CERTIFICATION-001`; Kontrollrunde 39/40: `CMA-INFLATION-PATH-DOMAIN-001`, `CMA-EFFECTIVE-DATE-001`, `GOAL-VALUE-MODE-ROUNDTRIP-001`, `GOAL-REAL-SPENDING-INFLATION-PARITY-001`, `POLICY-VERSION-IDENTITY-001`, `POLICY-ACTIVATION-COMPLETENESS-001`) teilen insgesamt sieben gemeinsame, bislang ungeklärte Grundsatzfragen, die VOR jeder Implementierung entschieden werden müssen. Dieses Dokument beantwortet jede Frage mit einer begründeten, fachlich/mathematisch/rechtlich hergeleiteten Empfehlung und markiert sie trotzdem explizit als `OWNER-DECISION` — die Entscheidung bleibt bei dir, aber du entscheidest auf Basis einer fertigen Analyse, nicht auf leerem Blatt.

**Wichtiger Vorbehalt:** Ich bin kein zugelassener Schweizer Rechtsanwalt. Die rechtlichen Einordnungen unten sind Ingenieurs-Risikologik auf Basis bereits etablierter Projekt-Konventionen (siehe unten zitierte Memory-Einträge) und öffentlich bekannter FIDLEG/DSG/OR-Normtexte, keine Rechtsberatung. Vor Produktivsetzung sollte eine tatsächliche Rechtsprüfung (falls die Firma einen Rechtsbeistand hat) diese Annahmen bestätigen.

## Problem

Vier Schichten des Goal-Engine (Router, Optimizer, Reporting-MC, UI/PDF) treffen unabhängig, mit unterschiedlichen Formeln, dieselben vier Grundentscheidungen: **(1)** welcher Stichtag gilt, **(2)** wie eine wiederkehrende Zahlung in Jahres-Buckets zerlegt wird, **(3)** was mit einem vergangenen/überfälligen Ziel wirtschaftlich passiert, **(4)** ob eine auf einem MC-Würfel ausgewählte Erfolgswahrscheinlichkeit ohne unabhängige Evidenz als "sicher" gelten darf. Die 30 roten Tests in PR #521 beweisen, dass alle vier Fragen heute inkonsistent beantwortet werden.

Dieselbe Krankheit (unabhängige, inkonsistente Implementierungen derselben Grundfrage) betrifft zwei weitere, eng verwandte Bereiche: **(5)** welche CMA-Version an einem Stichtag tatsächlich gilt und ob ihr Inflationspfad überhaupt ökonomisch sinnvoll ist, **(6)** ob reale (inflationsbereinigte) Ausgabenziele konsistent über alle Konsumenten hinweg behandelt werden, **(7)** ob eine Policy-Version, auf die bestehende Allocations/Runs verweisen, tatsächlich unveränderlich bleibt. Die 13 roten Tests in PR #523 beweisen, dass auch diese drei Fragen heute inkonsistent beantwortet werden. Ohne eine verbindliche Antwort pro Frage kann keiner der acht Funde korrekt (statt scheinbar) gefixt werden — siehe die expliziten "Nicht ausreichende Scheinfixes" im Kontrollrunde-38-Audit, deren Logik unverändert auch für die Kontrollrunde-39/40-Funde gilt.

## Scope

- ADR-1: Bewertungsstichtag (`valuation_date`) und Kalenderjahr-Konvention
- ADR-2: Kanonischer Occurrence-Scheduler für wiederkehrende Ziele
- ADR-3: Goal-Lifecycle (vergangen/überfällig/storniert/erfüllt)
- ADR-4: Monte-Carlo Train/Validation-Vertrag für die Zielwahrscheinlichkeits-Zertifizierung
- ADR-5: React-Goal-Editor-Vertrag (discriminated union) — geringer Entscheidungsbedarf, der Vollständigkeit halber aufgenommen
- ADR-6: CMA-Inflationsdomäne und Effective-Date-Resolver
- ADR-7: Goal-Value-Mode-Roundtrip und Inflations-Konsumenten-Parität — geringer Entscheidungsbedarf, analog zu ADR-5
- ADR-8: Policy-Versionsidentität und Aktivierungs-Vollständigkeit

## Nicht-Scope

- `GoalFundingPolicy` / `amount_funded` vs. `amount_due` (Runde 37, eigener, bereits offener Fund — dieses Dokument liefert nur den korrekten `amount_due`-Input dafür)
- Unterjährige Zahlungs-Präzision innerhalb eines Jahres-Buckets (`WITHDRAWAL-TIMING-001`, bewusst als separater P2-Vertrag abgegrenzt)
- Stress-Inflationsszenarien (separate, typisierte Stress-Verträge außerhalb der Current-CMA-Baseline, siehe ADR-6a)
- Tatsächliche Implementierung der acht Funde — folgt in eigenen PRs, nachdem dieses Dokument bestätigt ist

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

## ADR-6: CMA-Inflationsdomäne und Effective-Date-Resolver

### Befund

Verifiziert direkt gegen `develop` (nicht nur aus dem Audit übernommen): `services/portfolio_engine_cma.py::_inflation_path_series()` behandelt `inflation_path_json` als freien String — anders als `correlation_matrix_json`/`sub_asset_class_assumptions_json`, die einen strikten Shared-Parser durchlaufen (`schemas/allocation.py::_validate_cma`, Zeile ~669). Direkt reproduziert:

- Malformed JSON (`"not-json"`) → stiller Fallback auf 70 bps (hartcodierte Konstante).
- Ein JSON-Array statt eines Objekts → unbehandelter `AttributeError` im Runtime-Helper.
- `{"2026": true}` → `int(True)==1`, 1 bps übernommen.
- `{"2026": -20000}` (-200%/Jahr) → keine Wertebereichsprüfung; verkettet mit `goal_liabilities.py` dreht das die Liability eines realen Ausgabenziels ins Negative, die im Wealth-Pfad als Zufluss gebucht wird (`probability=1`, `status="erreichbar"`, `penalty=0` für eine tatsächlich ungedeckte Ausgabe — PR #523).
- `{"2099":100,"2100":900}`, angefragt für 2026-2029 → Rückwärtsauffüllung aus dem **maximalen** (nicht dem frühesten) Jahr: alle vier Jahre erhalten 900, nicht 100.

Separat: `services/jurisdiction/resolve.py::resolve_cma_for_jurisdiction()` filtert ausschließlich `is_current==1` und `deleted_at IS NULL` — kein `as_of`-Parameter, keine Prüfung von `valid_from`/`valid_until`. Verifiziert: eine Zeile mit `valid_from="2099-01-01"` wird heute sofort ausgewählt; eine seit Jahren abgelaufene ebenso.

### OWNER-DECISION 6a — Shared-Parser und Wertebereich

**Empfehlung:** `parse_inflation_path()` analog zu den bestehenden Parsern, verbindlich für Schema, Admin-API, Runtime und Legacy-Revalidierung. Jahre als kanonische vierstellige Integer, Werte als endliche Integer-bps, `bool` explizit verboten (gleiches Muster wie die bereits existierenden `_reject_boolean_market_inputs`/`_reject_boolean_advanced_model_parameters`-Validatoren in `schemas/allocation.py`). Wertebereich: **`[-1000, 3000]` bps** (-10 % bis +30 % pro Jahr) — kein willkürlich neuer Wert, sondern identisch zum bereits etablierten Präzedenzfall `schemas/wealth.py:829` (`inflation_assumption_bps: Optional[int] = Field(..., ge=-1000, le=3000)`), der exakt dasselbe ökonomische Konzept für Planning-Assumptions bereits einschränkt. Stress-Inflationsszenarien ausserhalb dieser Baseline-Domain gehören in einen separaten, typisierten Stress-Vertrag, niemals in die Current-CMA-Baseline.

☐ Bestätigt (Bereich `[-1000, 3000]` bps) ☐ Anderer Bereich: ______

### OWNER-DECISION 6b — Gültigkeitssemantik

**Empfehlung:** Dies ist dieselbe Grundfrage wie ADR-1, nur auf die CMA statt auf Goals angewendet — und sollte deshalb symmetrisch gelöst werden: `resolve_cma_for_jurisdiction()` erhält ein PFLICHT-`as_of`-Argument (dasselbe gebundene `valuation_date` aus ADR-1b, nicht erneut `date.today()`), die Query ergänzt `valid_from <= as_of AND (valid_until IS NULL OR valid_until >= as_of)`. Von den beiden im Audit vorgeschlagenen Varianten ("Aktiv-now-Vertrag" vs. "Effective-Resolver") wird **"Effective-Resolver"** empfohlen: mehrere versionierte Zeilen (geplant, aktuell, historisch) dürfen koexistieren, der Resolver wählt pro `as_of` die inhaltlich passende — das ist konsistent mit dem bereits bestehenden `version`-Spalten-Muster der CMA-Tabelle und erfordert keine zusätzliche Draft/Scheduled-Zustandsmaschine.

☐ Bestätigt (Effective-Resolver mit Pflicht-`as_of`) ☐ Aktiv-now-Vertrag stattdessen

### OWNER-DECISION 6c — Jahresabdeckung

**Empfehlung:** Keine Rückwärtsauffüllung aus irgendeinem anderen Jahr als dem frühesten real vorhandenen. Fehlt die Abdeckung vor dem ersten echten Datenpunkt, wird das explizit als "keine Abdeckung" behandelt (Fehler oder dokumentierter Baseline-Default von 0 bps), niemals aus einem späteren Jahr geraten — das eliminiert den Max-Jahr-Bug als Spezialfall einer allgemeineren, korrekten Regel, nicht durch eine gezielte Ausnahme.

☐ Bestätigt ☐ Abgelehnt

---

## ADR-7: Goal-Value-Mode-Roundtrip und Inflations-Konsumenten-Parität

### Befund

Geringer Entscheidungsbedarf — primär Implementierungs-Konsistenz, keine neue Fachentscheidung. Verifiziert: `reporting/src/lib/goalForm.ts` Zeile ~194 überschreibt `value_mode` für jeden Nicht-Vermögenszieltyp hart auf `nominal` (`wealth ? (input.value_mode ?? 'nominal') : 'nominal'`), selbst wenn der geladene Datensatz `real` trägt — ein No-op-Speichern ändert so die Kaufkraftsemantik. Backend (`services/goal_semantics.py` Zeile ~160) akzeptiert `real` bereits korrekt für jeden Zieltyp (Positivkontrolle bestätigt, PR #523). Separat: der Optimizer inflationiert reale Ausgabenziele (`goal_liabilities.py`), Reserve/Deterministik/allgemeine MC tun das nicht — verifizierter Repro: dieselbe reale CHF-100-Ausgabe, 2 Jahre, 10 %/10 % Inflation, CHF 110 Vermögen → Optimizer `nicht_erreichbar`, Reserve `achievable=True`.

### OWNER-DECISION 7a — Frontend-Fix

**Empfehlung:** `goalForm.ts` entfernt die `wealth ?`-Gate für `value_mode`; der Wert wird für JEDEN Zieltyp aus `input.value_mode` übernommen (Default weiterhin `nominal`, wenn nicht gesetzt). Keine neue Fachentscheidung — das Backend-Vertrag existiert bereits, das Frontend muss ihn nur nicht mehr verschweigen.

☐ Bestätigt ☐ Abgelehnt

### OWNER-DECISION 7b — Konsolidierung der Inflations-Anwendung

**Empfehlung:** Reserve, deterministische Zielanalyse und allgemeine Reporting-MC rufen dieselbe (bereits korrekte) Inflations-Helper-Funktion auf, die der Optimizer heute schon für reale Ausgabenziele nutzt (`_is_real_value_mode()` + `_inflate_at_year()` in `goal_liabilities.py`), statt den Rohbetrag unabhängig zu verwenden. Keine neue Formel nötig — dieselbe Konsolidierungslogik wie ADR-2c (gemeinsamer Scheduler-Kern), hier für die Inflations-Anwendung.

☐ Bestätigt ☐ Abgelehnt

### OWNER-DECISION 7c — `goal_analysis_json`-Korrektur

**Befund:** `routers/pdf_reports.py` liest `TargetAllocation.goal_analysis_json`, ein Modellattribut, das nicht existiert (`getattr(..., None)` verhindert einen Crash, liefert aber immer `None`). Das real existierende, befüllte Schwesterfeld `goal_achievability_json` trägt vermutlich bereits den beabsichtigten Inhalt (verifiziert: hat eine echte Spalte, eine Alembic-Migration und echte Writer in `services/portfolio_engine.py`).

**Empfehlung:** `pdf_reports.py` liest `goal_achievability_json` statt des nicht existierenden Feldnamens — mutmaßlich ein Tippfehler, keine fehlende Funktionalität. Eine neue, separate Spalte nur anlegen, falls `goal_achievability_json` inhaltlich tatsächlich etwas anderes abdecken soll (bei einer kurzen Durchsicht der beiden Konzepte nicht ersichtlich).

☐ Bestätigt (Tippfehler-Korrektur auf `goal_achievability_json`) ☐ Separate neue Spalte nötig, weil: ______

---

## ADR-8: Policy-Versionsidentität und Aktivierungs-Vollständigkeit

### Befund

Verifiziert: `routers/allocation.py::update_optimizer_policy()` archiviert die bisherige Policy-Konfiguration unter einer **neuen** `id` (`_archive_policy_snapshot`, `id=new_uuid()`), mutiert aber danach das ORIGINALE ORM-Objekt (ALTE `id`) direkt mit den neuen Feldwerten. Bestehende `TargetAllocation.policy_id`/`RecommendationRun.policy_id` zeigen danach weiterhin formal gültig auf die alte ID — deren Inhalt ist aber jetzt Version N+1, nicht die Version N, unter der die Allocation/der Run tatsächlich berechnet wurde. Zusätzlich: `_archive_policy_snapshot()` kopiert nur die Policy-eigenen Skalarfelder, NICHT die zugehörigen `HouseMatrix`- oder `BuildingBlock`-Zeilen (beide per rotem Test in PR #523 bestätigt) — der "archivierte Snapshot" ist damit kein eigenständig lauffähiges Policy-Aggregat.

**Wichtig — echter Zielkonflikt, keine einseitige Korrektur:** Ein bereits bestehender, grüner Test (`tests/test_optimizer_policy_archive.py::test_put_policy_preserves_id_for_fk_integrity`) bestätigt explizit das heutige Verhalten ("PUT ändert dieselbe ID, neuer Wert sofort unter dieser ID lesbar") als beabsichtigtes CRUD-Verhalten — und das ist für sich genommen eine vernünftige Eigenschaft eines einfachen "Policy bearbeiten"-Endpunkts. Der eigentliche Fehler ist, dass `policy_id` auf `TargetAllocation`/`RecommendationRun` ZWEI widersprüchliche Rollen gleichzeitig tragen soll: (a) "Zeiger auf die aktuell editierbare Live-Policy" (muss mutierbar sein) und (b) "Referenz auf die exakte historische Konfiguration, unter der dieser Run berechnet wurde" (muss unveränderlich sein). Eine einzelne ID kann mathematisch nicht beide Eigenschaften gleichzeitig erfüllen.

### OWNER-DECISION 8a — Identitätsmodell (die wichtigste Einzelentscheidung in diesem Abschnitt)

Zwei konsistente Varianten:

1. **Content-addressed unveränderliche Versionen:** Jede Bearbeitung erzeugt eine komplett NEUE `id`; die ALTE `id` wird nie wieder mutiert (`is_current=0`, Werte bleiben für immer wie zum Archivierungszeitpunkt). "Aktuelle Policy für Name X abrufen" wird zu einer Abfrage nach `(policy_name, is_current=1)` statt nach einer stabilen `id` — eine kleine, gut eingegrenzte Änderung, da Aktivierung/Deaktivierung bereits heute über `policy_name`-Gruppen läuft. Bestehende `TargetAllocation.policy_id`/`RecommendationRun.policy_id`-Referenzen zeigen danach automatisch korrekt auf die zum Erstellungszeitpunkt eingefrorene, nie wieder veränderte Version.
2. **Getrennter mutierbarer Zeiger + separate Versionstabelle:** `policy_id` bleibt ein stabiler "Slot" ("aktuell gültige Policy unter diesem Namen"); ein NEUES Feld (z. B. `policy_version_id`) auf `TargetAllocation`/`RecommendationRun` erfasst die konkrete, unveränderliche Version zum Erstellungszeitpunkt. Erfordert eine Migration (Backfill bestmöglich, sonst `historical_unknown` analog ADR-3a) und zwei statt einer Code-Stelle, die synchron gehalten werden müssen.

**Empfehlung: Variante 1 (content-addressed).** Begründung: einfacher (ein ID-Raum statt zwei synchron zu haltenden Feldern), folgt demselben mathematischen Grundsatz wie ADR-1 (Stichtag-Bindung) und ADR-4 (persistierte Validierungs-Evidenz) — "eine Referenz auf historische Evidenz muss unveränderlich sein, sonst ist sie keine Evidenz". **Wichtig:** `test_put_policy_preserves_id_for_fk_integrity` muss dabei bewusst UMGESCHRIEBEN (nicht nur ignoriert) werden, da seine Prämisse genau das Verhalten ist, das abgeschafft wird — explizit hier vermerkt, damit das beim Umsetzen nicht übersehen wird.

☐ Variante 1 (content-addressed, empfohlen) ☐ Variante 2 (getrennter Zeiger + Versionsfeld)

### OWNER-DECISION 8b — Vollständige Versions-Snapshots

**Empfehlung:** Unabhängig von 8a: jede neue unveränderliche Version (Archiv heute, neue ID unter Variante 1) muss ihre eigenen `HouseMatrix`- UND `BuildingBlock`-Zeilen erhalten, nicht nur die Policy-Skalarfelder. Durch zwei unabhängige rote Tests bestätigt (PR #523) — kein Interpretationsspielraum, beide Zeilentypen gehören zum Aggregat.

☐ Bestätigt ☐ Abgelehnt

### OWNER-DECISION 8c — Aktivierungs-Vollständigkeit (Readiness-Gate)

**Empfehlung:** Create/Clone/Activate validieren ATOMAR, bevor die bisherige Current-Policy deaktiviert wird: (a) mindestens eine House-Matrix-Zeile pro vom Engine erwarteten Score-Bereich (verifiziert: `services/portfolio_engine_house_matrix.py::_house_matrix_or_default()` wirft sonst `"HouseMatrix unvollstaendig fuer Score {bucket}"` beim nächsten echten Strategielauf für JEDES Mandat), (b) Building-Block-Zeilen für jeden vom Engine benötigten Jurisdiktions-/Universums-Scope, (c) CMA-Kompatibilität unter dem ADR-6b-Resolver. Bei jedem Fehlschlag bleibt die bisherige Current-Policy aktiv, die Anfrage wird abgelehnt (fail-closed — dieselbe Begründungslogik wie ADR-3b: eine "aktuelle" Policy, mit der kein echter Strategielauf funktioniert, darf nie existieren).

☐ Bestätigt ☐ Abgelehnt

---

## Betroffene Module / Dateien

- Backend (ADR-1 bis ADR-4): `services/calendar_horizon.py`, `services/optimizer/goal_liabilities.py`, `services/cashflow_timeline.py`, `services/portfolio_engine_payload.py`, `services/portfolio_engine_mc_simulation.py`, `services/portfolio_engine.py` (Snapshot-Hash), `services/optimizer/objective.py`, `services/optimizer/solver.py`, `models/wealth.py` (Goal-Lifecycle-Spalten), `models/allocation.py` (OptimizerRun-Validierungs-Spalten), `routers/wealth.py`
- Backend (ADR-6 bis ADR-8): `schemas/allocation.py` (CMA-Create-Validator, Policy-Create/Update-Schemas), `services/portfolio_engine_cma.py` (`_inflation_path_series`), `services/jurisdiction/resolve.py` (`resolve_cma_for_jurisdiction`), `models/allocation.py` (CMA `valid_from`/`valid_until` als echte Date-Typen, OptimizerPolicy-Identitätsmodell), `routers/allocation.py` (`update_optimizer_policy`, `_archive_policy_snapshot`, `create_optimizer_policy`, `clone_optimizer_policy`), `services/portfolio_engine_house_matrix.py`, `routers/pdf_reports.py` (`goal_analysis_json`-Korrektur)
- Frontend: `reporting/src/sections/goals/GoalWizard.tsx`, `reporting/src/lib/goalForm.ts`, `reporting/src/lib/goalClassification.ts`, `5eyes_v2.html` (Classic-Parität)
- Datenmodell: Migration für Goal-Lifecycle-Spalten + OptimizerRun-Validierungs-Spalten (ADR-1/3/4); CMA `valid_from`/`valid_until` auf echten `date`-Typ (ADR-6b); OptimizerPolicy-Identitätsmodell je nach ADR-8a-Entscheidung
- Tests: die 30 roten Tests aus PR #521 (ADR-1 bis ADR-5) plus die 13 roten Tests aus PR #523 (ADR-6 bis ADR-8) dienen gemeinsam als Akzeptanzkriterium — sie müssen nach Implementierung grün werden (xfail-Marker entfernt, `strict=True` erzwingt das ohnehin als harten Fehler bei stillem Grünwerden ohne Entfernen des Markers). Zusätzlich muss `test_optimizer_policy_archive.py::test_put_policy_preserves_id_for_fk_integrity` bei Wahl von ADR-8a Variante 1 bewusst umgeschrieben werden (siehe ADR-8a).

## Akzeptanzkriterien

1. Alle acht ADRs (1-8) sind vom Owner entschieden (☐-Kästen oben ausgefüllt).
2. Jede Entscheidung ist in genau einem zentralen Resolver-/Parser-Modul implementiert, nicht pro Caller dupliziert.
3. Alle 30 roten Tests aus PR #521 UND alle 13 roten Tests aus PR #523 werden grün (xfail-Marker entfernt).
4. Kein bestehender grüner Test regressiert (volle Backend- + Frontend-Suite) — mit der bewussten, dokumentierten Ausnahme von `test_put_policy_preserves_id_for_fk_integrity` (ADR-8a), falls Variante 1 gewählt wird.
5. Legacy-Daten (bestehende Goals/Allocations/CMA-Zeilen/Policies ohne die neuen Felder bzw. mit dem alten Identitätsmodell) werden beim nächsten Zugriff repariert oder sichtbar als `historical_unknown`/`validation_unknown` markiert, nie stillschweigend als "neu gültig" interpretiert.

## Risiken

- UX-Reibung durch Fail-Closed-Overdue-Policy (ADR-3b) und Fail-Closed-Aktivierungs-Gate (ADR-8c) — bewusst in Kauf genommen, siehe Begründung dort.
- Migration bestehender Mandate mit bereits vergangenen/überfälligen Zielen erzeugt kurzfristig sichtbare Klärungsbedarfe im Berater-Alltag — sollte vor Rollout kommuniziert werden.
- Validierungs-Cube (ADR-4) verdoppelt grob die Rechenzeit pro finaler Allokation (ein zusätzlicher MC-Lauf) — bei 20'000 Pfaden auf modernem Hardware im Sekundenbereich, nicht geschäftskritisch, aber im Performance-Budget-Test (`test_performance_budget.py`) zu berücksichtigen.
- ADR-8a Variante 1 (content-addressed) ändert die Semantik eines bestehenden, dokumentierten Admin-Endpunkt-Verhaltens (`PUT /admin/optimizer-policies/{id}`) und erfordert das bewusste Umschreiben eines heute grünen Tests — Admin-Tooling/Dokumentation, die sich auf "PUT ändert dieselbe ID" verlässt, muss vor Rollout geprüft werden.
- CMA-Wertebereich `[-1000, 3000]` bps (ADR-6a) könnte bestehende, bereits erfasste CMA-Zeilen mit Werten ausserhalb dieses Bereichs als ungültig markieren — vor Rollout eine Bestandsaufnahme der echten CMA-Daten empfehlenswert.

## Offene Fragen an Owner

Siehe die insgesamt 23 `OWNER-DECISION`-Markierungen oben (1a-1c, 2a-2c, 3a-3c, 4a-4d, 5a, 6a-6c, 7a-7c, 8a-8c). Jede trägt eine konkrete Empfehlung; die Kästen sind zum Ankreuzen/Kommentieren gedacht.
