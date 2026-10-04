# Manual-Target-, Band- und Publikationssemantik-Integritätsaudit

**Kontrollrunde 45 · Stand 04.10.2026 · Status: Release-Hold**

## Kurzfazit

Der kanonische Engine-Generate-Pfad verarbeitet manuelle Min-/Max-Bänder im
stochastischen Modus grundsätzlich als harte Bounds. Die separate manuelle
Soll-Quote `target_bps` besitzt dagegen keinen eindeutigen Produktvertrag:

1. Classic UI, Schema, Engine-Reasoning und Kunden-PDF nennen den Wert
   „Ziel“, „Soll-Quote“ beziehungsweise „Simulations-Constraint“.
2. Der konvergierte stochastische Solver erhält den Wert überhaupt nicht. Er
   baut Context, Starts und Objective ausschließlich aus CMA, Goals, House
   Matrix, Risikoprofil, Cashflows, Sub-Allokationen und effektiven Min-/Max-
   Bounds.
3. Zwei gegensätzliche manuelle Soll-Sätze mit 20 versus 60 Prozent Aktien
   und 50 versus 10 Prozent Obligationen erzeugten deshalb bei identischen
   Bounds exakt dieselbe konvergierte Allocation und denselben Seed.
4. Bei einem kontrollierten technischen Solverausfall wurden dieselben
   `target_bps`-Werte dagegen eins zu eins zur aktiven House-Fallback-
   Allocation. Die Bedeutung der Beraterangabe wechselt damit abhängig vom
   technischen Solverstatus.
5. Der Strategie-PDF druckte für den ersten Fall weiterhin
   `equities ... Soll 20.0%`, während die effektive TargetAllocation 60 bis 70
   Prozent Aktien hielt. UI und PDF können somit zwei verschiedene Werte als
   „Soll“ ausgeben.
6. Das öffentliche Preferences-Schema erlaubt feldweise Teil-Overrides. Ein
   bindendes `equities.max_bps=2000` wird jedoch abgelehnt, wenn der
   unveränderte House-Baseline-Target bei 5000 liegt. Der Compiler versucht
   nicht, innerhalb des neuen Bounds neu zu optimieren, sondern verlangt
   implizit zusätzlich einen vollständigen, auf 100 Prozent summierenden
   Targetsatz.

Damit ist der vorgeschlagene Ersatzpfad aus Runde 44 – manuelle Editorwerte
über den kanonischen Preferences-/Generate-Pfad zu führen – noch nicht
freigabefähig. Vor der Umsetzung muss fachlich entschieden und technisch
durchgängig erzwungen werden, ob ein Target hart, weich oder nur informativ
ist. Reale Beratung, Publikation, Signatur und Handoff bleiben gesperrt.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
f497a1d
docs(audit): document allocation editor lifecycle gaps
```

Geprüft wurden insbesondere:

- Classic-UI „Soll-Quoten & Bandbreiten“;
- `AllocationPreferencesPayload` und `AllocationBandOverridePayload`;
- House-Matrix-Bandcompiler und partielle Overrides;
- retained OptimizerContext, effektive Bounds und Multi-Start-Erzeugung;
- konvergierter Solver- und technischer House-Fallback-Pfad;
- TargetAllocation-Versionierung und Current-Rollover;
- Preferences-, Engine-Reasoning- und PDF-Publikation;
- vorhandene Tests zu Preferences, Bounds, Fallback, Produktionsvertrag und
  Strategie-PDF.

Nicht verändert wurden Produktionscode, Schemas, Migrationen, Seed-Daten,
Tests oder UI. Die gezielte A/B-Probe wurde nach der Beweissicherung entfernt.

## Abgrenzung zu Runde 44

Runde 44 dokumentierte, dass der React-Editor seinen Draft über einen
inkompatiblen direkten TargetAllocation-POST speichert. Als Lösungsrichtung
wurde ein gemeinsamer kanonischer Compiler für Auto- und Manual-Intent
festgelegt.

Runde 45 widerruft diese Richtung nicht. Sie präzisiert die notwendige
Vorbedingung: Der heutige `preferences.bands.target_bps`-Pfad ist noch kein
korrekter Manual-Intent-Compiler. Ein bloßes Umverdrahten des React-Editors auf
den bestehenden Generate-Endpunkt würde die Datenintegrität verbessern, aber
manuelle Soll-Quoten im normalen stochastischen Erfolgsfall weiterhin
wirkungslos lassen.

## Abgrenzung zu harten Min-/Max-Bounds

Bestätigt und nicht beanstandet:

- Min-/Max-Bounds werden vor dem Solver auf globale Caps, Reserve und
  Illiquidität geprüft;
- `effective_bounds_bps` wird in den retained OptimizerContext übernommen;
- Aktivierungsvalidierung prüft den konkreten Solver-Kandidaten erneut gegen
  exakt diese Bounds;
- die effektiven Bounds werden in `effective_constraints_json` und
  `allocation_context_hash` gebunden.

Der P1-Befund betrifft nicht die allgemeine Solver-Bounds-Enforcement, sondern
die davon getrennte, öffentlich als Ziel/Soll kommunizierte `target_bps`-
Angabe.

## Stabiles Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `MANUAL-TARGET-SEMANTICS-001` | P1 | bestätigt | `target_bps` wird im konvergierten stochastischen Pfad nicht an Context, Initial Guesses, Objective oder Solver übergeben. Gegensätzliche Targets erzeugen bei gleichen Bounds dieselbe Allocation. Im technischen House-Fallback werden die Targets dagegen wirksam. Eine identische Beraterangabe besitzt damit methodenabhängig verschiedene Semantik. |
| `MANUAL-TARGET-PUBLICATION-001` | P1 | bestätigt | Classic UI, Engine-Reasoning und Strategie-PDF bezeichnen den ignorierten Wert als Ziel/Soll beziehungsweise Constraint. Der PDF kann gleichzeitig ein manuelles „Soll 20%“ und eine effektive Strategie mit 60–70% Aktien ausweisen. Requested/Preferred und Effective/Approved werden nicht getrennt. |
| `BAND-PARTIAL-OVERRIDE-001` | P2 | bestätigt | Das öffentliche Schema erlaubt optionale einzelne Min-/Target-/Max-Felder. Ein bindendes Max-only/Min-only-Override wird jedoch gegen den unveränderten Baseline-Target geprüft und abgelehnt, statt den Solver innerhalb des neuen Bounds rechnen zu lassen. Der API-Vertrag ist dadurch breiter als der Compilervertrag. |

## Aktiver UI- und API-Vertrag

### Classic UI

Die aktive Classic-Oberfläche zeigt ein Modal mit den Spalten:

```text
Ist | Min | Ziel | Max
```

Der Hinweis darüber lautet sinngemäß, manuelle Soll-Quoten seien eine
Simulation über der aktuellen House Matrix. Eine Eingabe markiert die
Strategie als dirty; „Neu berechnen“ sendet die gespeicherten Preferences an:

```text
POST /mandates/{id}/target-allocation/generate
{
  "preferences": {
    "bands": {
      "equities": {
        "min_bps": ...,
        "target_bps": ...,
        "max_bps": ...
      }
    }
  }
}
```

Damit ist `target_bps` kein unbenutztes internes Alt-Feld. Es ist ein sichtbarer
und aktiv versendeter Beratereingang.

### Schema

`AllocationBandOverridePayload` erlaubt für jeden Bucket unabhängig:

- `min_bps`;
- `target_bps`;
- `max_bps`.

Alle drei Felder sind optional. Das Schema prüft nur die innerhalb eines
Eintrags gleichzeitig vorhandenen Werte. Es gibt damit öffentlich den Vertrag
vor, dass auch `max_bps` ohne Target oder `min_bps` ohne Target gültige
Leitplanken sind.

## Reproduktion A: Gegensätzliche Soll-Quoten, identischer Solverentscheid

Die Probe verwendete einen echten, strategie-fertigen Score-8-Fall, echte
Policy/CMA/House Matrix/Building Blocks und den echten stochastischen Solver.
Nur der nachgelagerte Reporting-Monte-Carlo wurde zur Laufzeitverkürzung
deterministisch kurzgeschlossen.

Beide Läufe hatten exakt dieselben Bounds:

```text
equities      0..7000
bonds         0..7000
real_estate   0..1500
alternatives  0..1000
liquidity     200..3000
```

Manueller Sollsatz A:

```text
equities=2000, bonds=5000, real_estate=1000,
alternatives=1000, liquidity=1000
```

Manueller Sollsatz B:

```text
equities=6000, bonds=1000, real_estate=1000,
alternatives=1000, liquidity=1000
```

Ergebnis eines bestätigten Laufs:

```text
status A = converged
status B = converged
seed A   = seed B

effective A = {
  equities: 6000,
  bonds: 0,
  real_estate: 0,
  alternatives: 1000,
  liquidity: 3000
}

effective B = effective A
```

In weiteren Wiederholungen mit neu erzeugten Seed-Daten wählte der Solver
andere effektive Punkte innerhalb derselben Bounds; innerhalb jedes A/B-Paars
blieben A und B jedoch exakt identisch. Das Ergebnis hängt also wie erwartet
von den übrigen Mandatsinputs ab, aber nicht vom manuellen `target_bps`.

Beide unterschiedlichen Targetsets wurden dennoch unverändert in
`preferences_json` und damit in den Allocation-Context-Hash aufgenommen.

## Reproduktion B: Technischer Fallback kehrt die Semantik um

Mit denselben produktiven Pfaden wurde ausschließlich `run_solver()` durch
einen kontrollierten `SolverTechnicalError` in den ausdrücklich zulässigen
House-Sicherheitsfallback geführt.

Ergebnis:

```text
status A = fallback_house_matrix
effective A = requested A

status B = fallback_house_matrix
effective B = requested B
```

Damit gilt:

```text
Solver konvergiert  -> target_bps ohne Wirkung
Solver technisch aus -> target_bps bestimmt die aktive Allocation
```

Diese Umschaltung ist fachlich besonders kritisch, weil ein technisches
Ereignis keine neue Kunden- oder Beraterentscheidung darstellt. Dennoch ändert
es, ob die gespeicherte Soll-Vorgabe bloße Dokumentation oder tatsächlich
aktive Portfolioquote ist.

## Reproduktion C: PDF publiziert den ignorierten Wert als Soll

Der produktive Preferences-Renderer wurde mit dem gespeicherten Snapshot aus
Lauf A aufgerufen. Er erzeugte unter „Individuelle Bandbreiten“:

```text
equities: Min 0.0% / Soll 20.0% / Max 70.0%
bonds: Min 0.0% / Soll 50.0% / Max 70.0%
```

Die effektive TargetAllocation desselben Laufs hielt dagegen 60 bis 70 Prozent
Aktien und 0 bis 28 Prozent Obligationen, abhängig vom Seed-Datensatz.

Die Strategie-PDF-Datenquelle liest:

- `target_allocation_bps` aus den effektiven TA-Spalten;
- `allocation_preferences` separat aus `TargetAllocation.preferences_json`.

Der Template-Ablauf druckt zuerst die Preferences mit `target_bps` als „Soll“
und anschließend die Vermögensstruktur mit der effektiven TA ebenfalls als
Soll-Allokation. Der Widerspruch ist daher nicht nur theoretisch im Snapshot
gespeichert, sondern als zwei kundenlesbare Aussagen im selben Dokument
angelegt.

Die Classic UI besitzt dieselbe Dualität: Sie setzt die effektive Allocation
als Baseline, überschreibt in der Eingabemaske aber die sichtbare Zielspalte
mit dem gespeicherten manuellen `target_bps`.

## Reproduktion D: Bindendes Max-only wird vom Compiler abgelehnt

Das öffentliche Schema akzeptierte:

```json
{
  "bands": {
    "equities": {"max_bps": 2000}
  }
}
```

Bei einer gültigen House-Baseline von 5000 bp Aktien lehnte der
Bandcompiler denselben Input ab:

```text
Bandbreiten fuer Aktien sind inkonsistent:
Min 0 / Ziel 5000 / Max 2000.
```

Das Max-only-Override ist gerade dann nicht nutzbar, wenn es bindend werden
soll. Um es zu verwenden, muss der Caller zusätzlich ein neues Aktien-Target
und genügend Targets anderer Buckets liefern, damit alle fünf Ziele wieder
exakt 10000 bp ergeben. Diese Zusatzpflicht ist im Schema nicht ausgedrückt.

## Root Cause A: Target fehlt vollständig im OptimizerContext

`generate_target_allocation()` setzt den manuellen Targetwert zunächst in
einem lokalen `optimizer_targets`-Dict. `_run_stochastic_optimizer_pass()`
übergibt an `build_optimizer_context()` und `run_solver()` jedoch nur:

- CMA und Goals;
- House-Matrix-Zeile und Score;
- Vermögens-/Cashflow-/Inflationskontext;
- Sub-Allokationsplan und Risky Fractions;
- effektive Min-/Max-Bounds;
- Mortalitäts- und Steuerparameter.

Ein Preferred-/Requested-Target existiert im SolverContext nicht.

Auch `build_initial_guesses()` erzeugt seine Starts ausschließlich aus:

- Mitte der Bounds;
- Minimum-Risk;
- Maximum-Equities;
- Risk-Cap-Edge;
- Equal Weight;
- optional Markowitz Minimum Variance.

Der manuelle Targetsatz ist daher entgegen dem bestehenden Testkommentar nicht
einmal eine „starting preference“.

## Root Cause B: Fallback verwendet das lokale Pre-Solver-Target

Bei `SolverTechnicalError` baut `_run_stochastic_optimizer_pass()` seinen
Fallback-Result aus dem lokalen `targets`-Dict. Der normale Solver ignoriert
dieses Dict; der Fallback gibt es als aktive Gewichte zurück.

Somit besitzen Erfolgs- und Fehlerpfad verschiedene Quellen für denselben
fachlichen Output:

```text
success: OptimizerContext + Objective + Bounds
fallback: lokales House-/Manual-Target-Dict
```

Ein einheitlicher Targetvertrag kann so nicht entstehen.

## Root Cause C: Requested und Effective werden nicht typisiert

Der persistierte Snapshot enthält `preferences.bands.*.target_bps`, während
die TA-Spalten die effektive Allocation enthalten. Es fehlt aber eine explizite
Semantik wie:

```text
requested_target_bps
preferred_target_bps
effective_target_bps
approved_target_bps
```

Renderer und UI müssen deshalb aus Feldnamen und Kontext raten. Der PDF-
Renderer nennt den Preferences-Wert „Soll“; die SAA-Tabelle nennt den
effektiven Wert ebenfalls Soll.

## Root Cause D: Partial Bounds werden gegen ein implizites Target geprüft

`_apply_band_preferences()` übernimmt zuerst optionale Felder in Baseline-
Dicts. Danach verlangt es für jeden Bucket:

```text
min <= target <= max
```

und über alle Buckets:

```text
sum(target) == 10000
```

Wenn der Caller nur einen Maxwert liefert, bleibt das Target implizit die
House-Baseline. Der neue Bound wird dadurch nicht als Constraint kompiliert,
sondern als angeblich fehlerhafte Kombination mit einem Target behandelt, das
der Caller nie übermittelt hat.

## Konsequenzen

### Beratungsentscheidung

- Ein Berater kann eine sichtbare Soll-Quote ändern, ohne dass der normale
  Solverentscheid reagiert.
- Ein technischer Solverausfall kann dieselbe Quote plötzlich aktiv machen.
- Der technische Status beeinflusst damit die Bedeutung eines fachlichen
  Inputs.

### Current- und Recommendation-Lifecycle

In der A/B-Probe erzeugte die wirkungslose Targetänderung dennoch:

- eine neue TargetAllocation-ID;
- Version 2 statt Version 1;
- `old.is_current=0` und `new.is_current=1`;
- unterschiedliche Preferences-/Context-Hashes bei identischen effektiven
  Gewichten.

Nach dem bestehenden korrekten Current-Anchor-Vertrag werden Empfehlungen der
alten TA dadurch stale. Eine ökonomisch wirkungslose Änderung kann also eine
neue Recommendation verlangen und den bisherigen Current-Publikationspfad
unterbrechen.

### Audit und Erklärung

- Reasoning behauptet, Soll-Quoten und Bänder würden als
  Simulations-Constraint berücksichtigt; tatsächlich trifft dies nur auf
  Min/Max zu.
- Ein Auditor kann aus `preferences_json` nicht erkennen, ob `target_bps`
  wirksam, ignoriert oder nur fallbackwirksam war.
- Der Context-Hash beweist die Anwesenheit des Inputs, nicht seine Wirkung.

### Kundenpublikation

- UI und PDF können gleichzeitig zwei verschiedene „Soll“-Quoten zeigen.
- Eine Signatur könnte einen Preferences-Target bestätigen, der nicht der
  aktiven Strategie entspricht.
- Ein Handoff könnte die effektive TA handeln, während das Beratungsdokument
  einen anderen manuellen Sollwert ausweist.

## Verbindlicher Lösungsvertrag für Claude

### 1. Fachliche Semantik einmal entscheiden

Für jedes manuelle Target muss genau eine der folgenden Varianten gewählt und
im Typnamen sichtbar werden:

| Semantik | Technischer Vertrag |
|---|---|
| harte Zielquote | `requested_target_bps` wird als Gleichheitsconstraint beziehungsweise `min=max=target` kompiliert; Infeasibility blockiert vor Solve |
| weiches Wunschziel | `preferred_target_bps` plus explizites Penalty-Gewicht/Policy wird Bestandteil von OptimizerContext, Objective, Evaluation und Explainability |
| reiner Startpunkt | `initial_guess_bps` wird ausschließlich als zusätzlicher Multi-Start verwendet; darf niemals als Soll/Constraint publiziert werden |
| informative Referenz | `reference_target_bps` beeinflusst keine Rechnung und wird klar als nicht entscheidungswirksam gekennzeichnet |

Für einen sichtbaren Berater-Editor ist „hart“ oder „weich mit offengelegter
Abweichung“ plausibel. Ein unbenannter Start-/Info-Hinweis ist für die aktuelle
Soll-UX nicht ausreichend.

### 2. Dieselbe Semantik in Success und Fallback erzwingen

- Ein technischer Fallback darf die Bedeutung des Targets nicht wechseln.
- Harte Targets gelten in beiden Pfaden oder blockieren beide.
- Weiche Targets werden in beiden Pfaden nach derselben Policy bewertet; der
  Fallback weist Abweichung und Grund explizit aus.
- Ein reiner Startpunkt darf auch im Fallback nicht still zur finalen
  Allocation werden.
- Activation-Validation prüft den finalen Kandidaten gegen den typisierten
  Intentvertrag.

### 3. Requested, Effective und Approved getrennt persistieren

Der immutable Allocation-Context soll mindestens binden:

- normalisierten Manual Intent samt Actor, Zeitpunkt, Grund und Basis-TA;
- Target-Semantik und gegebenenfalls Penalty-Policy;
- effektive Bounds nach allen globalen Regeln;
- effektive Solver-/Fallback-Gewichte;
- Abweichung requested/preferred versus effective je Bucket;
- Eligibility-/Approval-Entscheid für genau diesen Output.

`preferences_json` allein ist kein ausreichendes Decision-Evidence-Modell.

### 4. Partial-Bounds-Vertrag schließen

Für echte Partial-Overrides:

- fehlendes Target nicht mit einer bindenden Baseline-Vorgabe verwechseln;
- Min/Max zunächst unabhängig kompilieren;
- globale Machbarkeit früh prüfen:
  `sum(min) <= 10000 <= sum(max)`;
- vorhandene Targets nach ihrer typisierten Semantik behandeln;
- fehlende Targets vom Solver innerhalb der Bounds bestimmen lassen;
- Fehler mit Bucket, Quelle und Reparaturhinweis zurückgeben.

Alternativ muss das Schema einen vollständigen Fünf-Bucket-Targetsatz als
Pflichtmodell verlangen. Das heutige optionale Schema bei impliziter
Vollständigkeit ist unzulässig.

### 5. UI, API, Reasoning und PDF angleichen

- Classic und React verwenden dieselben Begriffe und denselben Intent-Payload.
- „Ziel/Soll“ bezeichnet ausschließlich die effektive beziehungsweise
  freigegebene Allocation.
- Ein Wunschwert wird als „gewünschtes Ziel“ und seine Abweichung sichtbar
  dargestellt.
- Engine-Reasoning unterscheidet harte Bounds, weiches Target, Startpunkt und
  effektiven Entscheid.
- PDF, API, UI, Signatur und Handoff publizieren genau dieselbe Effective-/
  Approved-TA; Requested-Werte erscheinen nur zusätzlich und eindeutig
  beschriftet.

### 6. Semantische Idempotenz berücksichtigen

Wenn eine Intentänderung weder effektive Allocation noch Eligibility-Evidence
ändert, darf sie nicht still die bisher publizierte Strategie verdrängen.
Mindestens ist zu trennen zwischen:

- gespeichertem Draft-Intent;
- neuem validierten Kandidaten;
- freigegebener/aktiver Allocation.

Dies ergänzt den Proposed-/Approved-/Active-Vertrag aus Runde 44.

## Erwartete Red/Green-Tests

### Engine

- Zwei verschiedene harte Targets erzeugen verschiedene exakte Ergebnisse
  oder einen klaren Infeasibility-Fehler.
- Zwei verschiedene weiche Targets verändern Objective/Ergebnis oder liefern
  eine explizite, quantifizierte Abweichung.
- Ein Startpunkt ist im OptimizerContext/Multi-Start nachweisbar, aber nie als
  Constraint/Soll publiziert.
- Success und technischer Fallback besitzen identische Targetsemantik.
- Activation-Validation prüft die Targetsemantik zusätzlich zu Bounds,
  Summe, Risiko und Domainconstraints.

### Partial Bounds

- bindendes Max-only und Min-only werden ohne künstlichen Targetfehler
  kompiliert;
- `sum(min)>10000` und `sum(max)<10000` blockieren vor teurem Solve;
- globale Caps, Reservefloor und Illiquiditätscap bleiben vorrangig und
  nachvollziehbar;
- vollständige und partielle Payloads besitzen eindeutige Schemas.

### UI/API

- Browser-E2E ändert nur ein Target und beweist die definierte Enginewirkung;
- Browser-E2E ändert nur ein bindendes Maximum und erhält einen berechneten
  Kandidaten innerhalb des Caps;
- React und Classic senden denselben normalisierten Intent;
- No-op/semantisch wirkungslose Änderungen ersetzen nicht automatisch Active.

### Publikation

- PDF und UI zeigen pro Bucket exakt ein freigegebenes Soll;
- Requested/Preferred wird nur mit explizitem Label und Abweichung angezeigt;
- Reasoning nennt keinen Input Constraint, der nicht im SolverContext liegt;
- Signatur- und Handoff-Payload sind an Effective/Approved gebunden.

## Ausgeführte Verifikation

Temporäre A/B- und Fallback-Probe:

```text
3 passed in 4.41s
```

Bestehende Preferences-/Optimizer-/Validation-Regressionen:

```text
213 passed in 42.22s
```

Bestehende Strategie-PDF-Regressionen:

```text
6 passed in 1.29s
```

Insgesamt waren damit 219 bestehende Tests grün. Sie widerlegen die Findings
nicht:

- Der vorhandene Runtime-Test schreibt ausdrücklich fest, dass `target_bps`
  nur eine „starting preference“ sei, prüft aber lediglich das effektive
  Min-/Max-Band und nicht, ob dieser Startwert den Solver erreicht.
- Die Produktionsvertragstests prüfen Bounds, Kandidatenaktivierung und
  Fallbackintegrität, nicht die A/B-Wirkung verschiedener Targets bei
  identischen Bounds.
- Die PDF-Tests prüfen Struktur und ausgewählte Inhalte, nicht die semantische
  Identität von Preferences-„Soll“ und effektiver TA.

## Definition of Done

Der Befund ist erst geschlossen, wenn:

- `target_bps` durch einen eindeutig benannten harten, weichen, Start- oder
  Informationsvertrag ersetzt ist;
- der gewählte Vertrag im OptimizerContext, Solver, Fallback,
  Activation-Validation und Evidence-Snapshot identisch gilt;
- partielle Min-/Max-Overrides dem öffentlichen Schema entsprechend
  kompilierbar sind oder das Schema bewusst vollständig gemacht wurde;
- UI, API, Reasoning, PDF, Signatur und Handoff Requested/Preferred,
  Effective und Approved nicht vermischen;
- ein kundenlesbares Dokument nie zwei verschiedene Werte als Soll ausgibt;
- semantisch wirkungslose Intents nicht ungeprüft die aktive Strategie und
  ihre Recommendation verdrängen;
- die genannten Red/Green-, Browser-E2E-, PDF- und PostgreSQL-
  Aktivierungstests auf der Zielumgebung grün sind.

Bis dahin bleibt der Release-Hold bestehen.
