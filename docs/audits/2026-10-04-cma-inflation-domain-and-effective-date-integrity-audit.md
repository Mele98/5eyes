---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-cma-inflation-domain-effective-date-and-model-input-integrity-followup-audit"
status_as_of: "2026-10-04"
audit_started_on: "2026-10-04"
audit_completed_on: "2026-10-04"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "f7b69ebc2b6940f7f835aa9228718a665b978805"
prior_inflation_parity_audit_path: "docs/audits/2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md"
prior_estimator_audit_path: "docs/audits/2026-09-22-stochastic-estimator-correlation-cache-and-stress-reproducibility-audit.md"
prior_reference_data_audit_path: "docs/audits/2026-08-27-reference-data-read-authorization-and-model-basis-audit.md"
prior_strategy_temporal_audit_path: "docs/audits/2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md"
audit_mode: "read_only_static_cma_schema_router_resolver_admin_ui_cashflow_goal_and_snapshot_review_plus_deterministic_schema_parser_sqlite_resolver_node_ui_and_optimizer_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "CMA inflation-path ingestion, admin UI, schema and runtime parser parity, economic and temporal domains, current/effective-date resolution, cashflow and real-goal propagation, snapshot evidence and publication"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 2
confirmed_prior_p1_extension_groups: 3
deterministic_reproduction_groups: 5
focused_backend_tests_passed: 193
focused_existing_tests_failed: 0
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "keep all new strategy, Monte Carlo, real-goal, cashflow and customer-publication runs blocked for unvalidated or temporally ineligible CMA inflation evidence; implement one strict shared inflation-path parser and an as-of-aware effective CMA resolver, quarantine legacy rows, then bind the validated raw path, resolved series and policy versions to every run and publication"
---

# CMA-Inflationsdomänen- und Effective-Date-Integritätsaudit

## Geltung, Quellenrangfolge und Abgrenzung

Dieser additive Folgeaudit dokumentiert die vierzigste Read-only-
Kontrollrunde des Asset-Allocation-/Stochastic-Core. Geprüft wurde der
unveränderte Repository-Head
`f7b69ebc2b6940f7f835aa9228718a665b978805`. Produktcode, Migrationen und
Tests wurden nicht verändert. Nach der Prüfung werden ausschließlich die fünf
Pfade des Dokumentationsmanifests angepasst.

Aktueller Code und direkt ausgeführte Produktivfunktionen haben Vorrang.
UI-Vorvalidierung ist kein Backendvertrag; ein administrativer
Modellinput muss unabhängig vom aufrufenden Client fail-closed validiert
werden. Ebenso ist `is_current=1` allein kein zeitlicher Gültigkeitsnachweis,
wenn das Modell zusätzlich `valid_from` und `valid_until` publiziert.

Die Runde beantwortet vier Kernfragen:

1. Wird `inflation_path_json` genauso streng validiert wie Korrelations- und
   Sub-Asset-CMA-JSON?
2. Können ökonomisch unmögliche Werte ein Ausgabenziel in einen Zufluss
   verwandeln oder Cashflowvorzeichen drehen?
3. Wählt der CMA-Resolver die am Bewertungsstichtag gültige Version oder nur
   eine technisch als current markierte Zeile?
4. Ist eine fehlende führende Jahresabdeckung explizit blockiert oder wird
   ein später Wert still rückwärts auf frühere Jahre angewendet?

## Deduplizierung zu bestehenden Findings

Keine bestehende Finding-ID wird geschlossen oder umbenannt.

- `GOAL-REAL-SPENDING-INFLATION-PARITY-001` setzt eine fachlich gültige,
  gebundene Inflationsserie voraus und beschreibt die abweichende Anwendung
  durch Optimizer, Reserve, Deterministik und MC. Das neue
  `CMA-INFLATION-PATH-DOMAIN-001` liegt davor: Die gemeinsame Quelle selbst
  kann malformed oder ökonomisch unmöglich sein.
- Finding #3 des Engine-Validierungsdokuments betrifft die Begin-/End-of-Year-
  Anzahl von Inflationstermen. Dieser Audit betrifft Typ, Wertebereich,
  Jahresabdeckung und zeitliche Zulässigkeit der Terme.
- `MC-PSD-FACTOR-001` und der Estimatoraudit prüfen die Korrelationsmatrix,
  deren Faktor und Cachebindung. Die Inflation ist dort kein stochastischer
  Korrelationsinput und wird vom gemeinsamen Strict-CMA-Parser gerade nicht
  geprüft.
- Der Referenzdaten-Autorisierungsaudit betrifft Leserollen und frei wählbare
  Tenant-Scope-Parameter. `CMA-EFFECTIVE-DATE-001` gilt auch bei korrekter
  Autorisierung und richtigem Tenant: Der Resolver ignoriert das
  Gültigkeitsfenster.
- Der Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit betrifft andere
  Snapshot-Workflows und deren Perioden. Er definiert keinen as-of-fähigen
  CMA-Resolver.
- Current-Anchor-Uniqueness stellt höchstens eine aktuelle Zeile je Scope
  sicher. Genau eine **zeitlich unzulässige** Zeile bleibt dadurch weiterhin
  auswählbar.
- `GOAL-SNAPSHOT-001`, `MC-CONTEXT-001` und Publikationsfindings bleiben für
  die nachgelagerte Bindung offen. Die hier geforderten Raw-/Resolved-
  Inflationsevidenzen erweitern sie, sind aber nicht die Root Cause der zwei
  neuen Eingabefehler.

Zwei neue IDs grenzen die Ursachen ab:

- `CMA-INFLATION-PATH-DOMAIN-001`
- `CMA-EFFECTIVE-DATE-001`

## Kurzurteil

Die Runde bestätigt **zwei neue release-blockierende P1**.

**`CMA-INFLATION-PATH-DOMAIN-001`:**
`CapitalMarketAssumptionCreate` führt für vorhandene Korrelations- und
Sub-Asset-JSONs strikte Shared-Parser aus, behandelt
`inflation_path_json` aber als freien String. Malformed JSON wird im
Runtimehelper still durch 70 bps ersetzt; ein JSON-Array wird vom Schema
akzeptiert und scheitert später mit `AttributeError`; boolesche Werte werden
als 1 bps übernommen; Jahre und Werte besitzen keine fachliche Domain. Der
sichtbare Classic-Admin-Editor akzeptiert ebenfalls beliebige Prozentwerte.
Bei `−200 %` erzeugt der Inflationsfaktor `−1`. Ein reales Ausgabenziel von
10.000 Rappen wird zu einer Liability von `−10.000`, im Wealth-Pfad
subtrahiert und damit als **positiver Zufluss** gebucht. Bei Startvermögen null
endet der Pfad mit +10.000, Probability ist eins, Status `erreichbar` und
Penalty null. Derselbe ungültige Faktor kann inflation-linked Cashflows im
Vorzeichen drehen. Das ist falsche positive Beratungsevidence aus einem
administrativ erreichbaren Modellinput.

**`CMA-EFFECTIVE-DATE-001`:** Das Schema typisiert `valid_from` und
`valid_until` als Strings und vergleicht sie nur lexikografisch. Der
Versionierungsrouter markiert jede neue Zeile sofort `is_current=1` und
archiviert die vorherige; der zentrale Jurisdiktionsresolver filtert nur
`is_current` und `deleted_at`, niemals nach einem gebundenen `as_of` oder dem
Gültigkeitsfenster. Eine CMA mit `valid_from=2099-01-01` wird deshalb im Jahr
2026 sofort ausgewählt; eine seit 2020 abgelaufene Current-Zeile ebenfalls.
Der Inflationshelper initialisiert seine Lückenauffüllung zusätzlich mit dem
Wert des **maximalen** vorhandenen Jahres. Ein Zukunftspfad
`{2099: 1 %, 2100: 9 %}` wird so für 2026–2029 still zu `[9 %, 9 %, 9 %, 9 %]`.
Die gesamte Asset Allocation, Simulation, Cashflowprojektion und
Goal-Evidence kann damit auf einer noch nicht wirksamen oder abgelaufenen CMA
laufen, obwohl API und UI ein Gültigkeitsfenster anzeigen.

## Reproduktion A: Schema-/Runtime-Matrix

Direkt ausgeführt wurden `CapitalMarketAssumptionCreate` und
`_inflation_path_series()`:

```text
malformed
  schema_accepted=True
  engine_series=[70, 70, 70]

list_top_level
  schema_accepted=True
  engine_error=AttributeError: 'list' object has no attribute 'items'

negative_200pct
  schema_accepted=True
  engine_series=[-20000, -20000, -20000]

future_only {2030:100, 2031:200}, start_year=2026
  schema_accepted=True
  engine_series=[200, 200, 200]

bool_value
  schema_accepted=True
  engine_series=[1, 1, 1]
```

Die fünf Fälle beweisen fünf verschiedene Fail-open-Verhalten:

1. stille Modellsubstitution,
2. verspäteter Runtime-Crash,
3. fehlender ökonomischer Wertebereich,
4. Rückwärtsfüllung aus der Zukunft und
5. Python-/JavaScript-Bool-als-Zahl-Koerzierung.

## Reproduktion B: falscher grüner Optimizerentscheid

Eingabe:

- `Einmalige_Ausgabe`, `value_mode="real"`,
- Rohbetrag 10.000 Rappen,
- Fälligkeit im nächsten Zieljahr,
- CMA-Inflation `−20.000` bps,
- Startvermögen null, Renditen null, Cashflow null,
- hartes Ziel mit `tau=0,80`.

Ausgeführt wurden die echten Produktionsfunktionen `goal_to_liability`,
`simulate_wealth_paths`, `goal_probability_per_path` und
`chance_constraint_penalty`:

```json
{
  "liability_target": -10000,
  "liability_path": [-10000],
  "wealth_path": [[0.0, 10000.0]],
  "probability": [1],
  "penalty": 0.0,
  "status": "erreichbar"
}
```

Der Fehler ist mechanisch eindeutig:

```text
factor = 1 + (-20000 / 10000) = -1
liability = 10000 * -1 = -10000
wealth_next = 0 + 0 - (-10000) = +10000
```

Die Liability-Dokumentation definiert positive Werte ausdrücklich als
Outflow. Ein negativer Wert darf diesen Vertrag niemals erreichen.

## Reproduktion C: produktiver Adminpfad

Der sichtbare Classic-Adminpfad ist nicht nur eine rohe API-Theorie:

- `5eyes_v2.html:10679-10690` normalisiert Jahr/Wert über `Number()` und
  `Math.round()`, ohne Wertebereich oder Bool-Ausschluss.
- `10846-10864` rendert die fünf Inflationsinputs als `type="number"` mit
  `step="0.1"`, aber ohne `min` oder `max`.
- `10876-10885` baut daraus den JSON-Pfad.
- `11233-11269` übernimmt ihn in den CMA-Payload.
- `11364-11375` sendet ihn nach einer allgemeinen Risikobestätigung an
  `PUT /capital-market-assumptions`.

Die direkt gegen die extrahierten Produktionshelper ausgeführte Node-Matrix
ergab:

```text
{"2026":-20000}       -> {"2026":-20000}
{"2026":true}         -> {"2026":1}
[100,200]              -> null
not-json               -> null
{"2099":100,"2100":900} -> unverändert akzeptiert
```

Die normale Grid-Eingabe `-200` Prozent wird durch
`adminPercentInputToBps()` zu `-20000` und passiert dieselbe Payloadkette.
Frontendvalidierung schützt daher gerade den wirtschaftlich gefährlichsten
Fall nicht. Selbst vollständige UI-Validierung würde den erforderlichen
Backendvertrag nicht ersetzen.

## Reproduktion D: Future-/Expired-CMA wird current

Das Pydantic-Schema akzeptierte jeweils:

```text
valid_from="not-a-date"                       -> accepted
valid_from="2099-01-01"                       -> accepted
valid_from="2020-01-01", valid_until="2020-12-31" -> accepted
```

Danach wurde eine echte `CapitalMarketAssumption` mit
`valid_from=2099-01-01`, `valid_until=2099-12-31`, `is_current=1` in eine
In-Memory-SQLite-Datenbank geschrieben und durch
`resolve_cma_for_jurisdiction(db, "CH")` aufgelöst:

```json
{
  "selected_id": "future-cma",
  "valid_from": "2099-01-01",
  "valid_until": "2099-12-31",
  "is_current": 1
}
```

Der Resolver hat keinen Stichtagsparameter und kann deshalb semantisch nicht
zwischen aktiv, geplant, abgelaufen und historisch unterscheiden.

## Reproduktion E: zeitlicher Inflation-Leak

Direkt ausgeführt:

```text
future current path {2099:100, 2100:900}, request 2026..2029
  -> [900, 900, 900, 900]

expired current path {2019:50, 2020:250}, request 2026..2029
  -> [250, 250, 250, 250]
```

Die zweite Zeile könnte als explizite trailing extension policy vertretbar
sein, wenn die CMA am Stichtag gültig und die Policy versioniert wäre. Die
erste ist eine unzulässige Rückwärtsprojektion: Der letzte Wert einer noch
nicht wirksamen Kurve wird vor deren erstem Jahr verwendet.

## Codebelege

### Schema und Persistenz

- `schemas/allocation.py:532-555`: CMA-Create nutzt freie Strings für
  Gültigkeit und `inflation_path_json`.
- `schemas/allocation.py:666-700`: Der Modelvalidator prüft Vola, Returns,
  lexikografische Datumsreihenfolge, Korrelation, Sub-Assets, Nelson-Siegel
  und KGV – aber nicht den Inflationspfad.
- `models/allocation.py:240-265`: `valid_from`, `valid_until`, `is_current` und
  `inflation_path_json` besitzen keine Datenbankdomain, die diese Fehler
  abfangen würde.
- `routers/allocation.py:391-486`: Update übernimmt den validierten Pydantic-
  Payload, deaktiviert die Vorgängerzeile und persistiert die neue Zeile
  sofort mit `is_current=1`, unabhängig vom Gültigkeitsfenster.

Der Unterschied zum Korrelationsvertrag ist besonders relevant:
`tests/test_cma_strict_runtime_contract.py` sagt ausdrücklich, dass jedes
vorhandene optionale CMA-JSON als Modellinput malformed/non-finite fail-closed
ablehnen muss. Diese Regel ist für Korrelation/Sub-Assets umgesetzt, für
Inflation nicht.

### Runtime und Rechenkern

- `services/portfolio_engine_cma.py:668-688`: JSON-Decodefehler werden auf
  `{}` reduziert; schlechte Einträge werden übersprungen; der Fallback nimmt
  das maximale Jahr oder 70 bps.
- `services/cashflow_timeline.py:166-191`: Inflation wird ohne Domainprüfung
  direkt in einen multiplikativen Faktor überführt.
- `services/optimizer/goal_liabilities.py:254-280`: Der Optimizer dupliziert
  dieselbe unbeschränkte Multiplikation.
- `goal_liabilities.py:388-423` und `428-478`: Realwertige Einmal- und
  recurring Ausgaben übernehmen den resultierenden negativen Betrag in den
  Liability-Pfad.
- `_real_series_from_nominal()` in
  `portfolio_engine_cma.py:691-702` behandelt nichtpositive Faktoren nochmals
  anders, indem der Nenner auf `0.0001` geklemmt wird. Ein ungültiger Pfad
  kann deshalb gleichzeitig negative Goal-Liabilities und extrem hohe
  Realwertserien erzeugen.

### Effective-Date-Auflösung

- `services/jurisdiction/resolve.py:55-61`: Die Current-Basisquery filtert nur
  `is_current=1` und `deleted_at IS NULL`.
- `resolve.py:74-145`: Jurisdiktion und Tenant werden sauber aufgelöst; ein
  `as_of` und Gültigkeitsprädikat fehlen vollständig.
- `routers/allocation.py:359-389`: Auch der öffentliche Current-CMA-Endpunkt
  delegiert an diesen zeitlosen Resolver.
- Viele Enginepfade binden später die ausgewählte CMA-ID. Das verbessert
  Reproduzierbarkeit, beweist aber nicht, dass die CMA am Entscheidungsdatum
  gültig war.

## Root Cause

Die CMA besitzt drei unterschiedliche, nicht geschlossene Verträge:

1. **Speichervertrag:** freie String-/JSON-Spalten,
2. **UI-Vertrag:** tolerante Normalisierung und Vorschau,
3. **Runtimevertrag:** stiller Default, Entry-Skip und Last-Value-Fill.

Es existiert kein gemeinsamer `InflationPath`-Parser und kein gemeinsamer
`EffectiveReferenceContext(as_of=...)`. `is_current` vermischt dabei
Versionierungszeiger und zeitliche Wirksamkeit. Die Gültigkeitsfelder sind
deskriptiv, nicht entscheidungswirksam.

Snapshot-Hashes können diesen Fehler konservieren, aber nicht korrigieren:
Eine exakt reproduzierbare Entscheidung auf einer zukünftigen oder
wirtschaftlich unmöglichen CMA bleibt falsch.

## Verbindlicher Lösungsweg für Claude

### 1. Einen Shared-Parser einführen

`parse_inflation_path()` muss von Pydantic-Schema, Admin-API, Runtime,
Migration/Legacy-Audit und Tests gemeinsam verwendet werden. Anforderungen:

- fehlend/leer wird als expliziter Zustand behandelt;
- vorhandener Payload muss ein JSON-Objekt sein;
- Jahre sind kanonische vierstellige Integerjahre, keine booleschen,
  Float-, Whitespace- oder Aliasduplikate;
- Werte sind endliche Integer-bps, bool ist verboten;
- Baseline-CPI muss strikt größer als `-10000` bps sein und einen
  owner-freigegebenen oberen Bereich besitzen; der bestehende
  Planning-Assumption-Bereich `[-1000,3000]` ist ein naheliegender, aber vom
  Owner ausdrücklich zu bestätigender Kandidat;
- Stressinflation außerhalb der Baseline-Domain gehört in einen getrennten,
  typisierten Stressvertrag und niemals in die Current-CMA-Baseline;
- malformed, non-finite, out-of-range und semantisch leere Eingabe liefert
  422/CMA-Domainfehler, keinen 70-bps-Ersatz;
- Runtime revalidiert Legacy-/DB-Daten fail-closed.

### 2. Gültigkeitssemantik entscheiden

Eine Owner-ADR muss eine der folgenden konsistenten Varianten wählen:

- **Aktiv-now-Vertrag:** `is_current=1` bedeutet am heutigen gebundenen
  `as_of` wirksam. Dann darf Aktivierung nur erfolgen, wenn
  `valid_from <= as_of <= valid_until|null`; zukünftige Versionen bleiben
  Draft/Scheduled und archivieren die aktuelle Version noch nicht.
- **Effective resolver:** Mehrere versionierte Zeilen können geplant sein;
  ein eindeutiger Resolver wählt für das obligatorische `as_of` genau die
  Zeile, deren halb-offenes Gültigkeitsintervall den Stichtag enthält.

In beiden Varianten:

- `valid_from`/`valid_until` sind echte `date`-Typen im Schema;
- DB-Checks sichern Bool-/Datums-/Intervallgrundlagen;
- keine Lücken oder Überlappungen im aktiven Scope ohne sichtbaren
  Governanceentscheid;
- Aktivierung/Supersede erfolgt atomar;
- Current-API, Generate, Rebuild, PDF, Sensitivity, Stress und Replay nutzen
  denselben Resolver mit demselben gebundenen Stichtag.

### 3. Jahresabdeckung explizit machen

- Keine Rückwärtsfüllung aus `max(normalized_year)`.
- Fehlt die Abdeckung am Bewertungsjahr, wird entweder fail-closed blockiert
  oder eine owner-freigegebene, benannte Extrapolationspolicy verwendet.
- Führende, innere und nachlaufende Lücken sind getrennte Zustände.
- Eine erlaubte trailing extension muss Quelle, Ausgangsjahr, Wert und
  Policyversion in der Evidence tragen.
- Der Projektionshorizont muss vollständig abgedeckt oder explizit
  extrapoliert sein; stille Entry-Skips sind verboten.

### 4. Rechenkern defensiv härten

Auch nach Ingestion-Validierung gilt Defense in depth:

- jeder kumulative CPI-Faktor muss endlich und strikt positiv sein;
- jede effektive reale Liability bleibt `>= 0`;
- Cashflowvorzeichen darf sich ausschließlich durch den fachlichen
  Income-/Expense-Typ ändern, nie durch CPI;
- Verletzungen werfen einen typisierten `CMAValidationError` beziehungsweise
  `OptimizerInputError` vor Solver, Allocation-Persistenz und Publikation;
- keine Komponente darf denselben ungültigen Faktor unterschiedlich klemmen,
  überspringen oder fortsetzen.

### 5. Evidence vollständig binden

Je Run/Allocation/Publikation sind mindestens zu binden:

- CMA-ID, Version, Jurisdiktion, Tenant, Status und Quelle,
- `as_of`, `valid_from`, `valid_until` und Resolverversion,
- kanonischer Raw-Path-Hash,
- tatsächlich aufgelöste Jahresserie,
- Abdeckungs-/Extrapolationsstatus und Policyversion,
- Planning-Assumption-Override samt explizitem Scope,
- finaler Goal-/Cashflow-Inflationsplanhash.

Ein Hash über die aufgelöste Serie ist nötig, ersetzt aber Raw-Path- und
Resolverprovenienz nicht.

### 6. UI und Legacy

- Admin-Grid erhält fachliche min/max-Werte, sichtbare Einheit und
  Erklärungen für Baseline versus Stress.
- Future-/Expired-/Draft-/Active-Status wird sichtbar; eine künftige Version
  darf nicht als sofortige Current-Aktivierung erscheinen.
- Vorschau zeigt führende/innere/trailing Abdeckung und den effektiven
  Stichtagspfad, nicht nur Durchschnitt und sortierte Keys.
- Direkte API bleibt unabhängig strikt.
- Alle vorhandenen CMA-Zeilen werden gescannt. Malformed, außerhalb der Domain,
  future-current, expired-current, überlappend oder lückenhaft wird nicht
  automatisch uminterpretiert, sondern repariert, replayt oder quarantänisiert.
- Abgeleitete Allocations, Runs, PDFs und Signaturen auf invaliden Zeilen sind
  stale/invalid und dürfen nicht als belastbare Evidence fortleben.

## Zuerst zu materialisierende rote Tests

### Inflationsdomain

1. malformed JSON, Array, Scalar und `null` als vorhandener Payload;
2. boolesche Jahre/Werte, Floatjahre, nichtnumerische und non-finite Werte;
3. Werte bei `-10000`, darunter sowie oberhalb des freigegebenen Maximums;
4. normalisierte Jahresduplikate und nichtkanonische Keys;
5. führende, innere und trailing Lücken separat;
6. UI-Grid `-200 %` und Experten-JSON `true` gegen echten Backend-422;
7. direkt persistierte Legacy-Korruption blockiert Runtime trotz Schema-
   Umgehung;
8. Property-/Cashflow-/Goal-/Real-Series-Consumer verwenden denselben Parser.

### Rechenkern-Invarianten

9. Kein gültiger CPI-Pfad erzeugt Faktor `<= 0` oder non-finite;
10. keine reale positive Ausgabe wird negativ;
11. kein positiver Income-/Expense-Betrag wechselt durch CPI das Vorzeichen;
12. die dokumentierte `−200 %`-Gegenprobe scheitert vor der Simulation;
13. fehlender Path verwendet nur einen expliziten, gebundenen Defaultstatus;
14. Parser-, Cashflow- und Goal-Faktoren sind für denselben Timingvertrag
    identisch.

### Effective Date

15. ISO-invalides `valid_from`/`valid_until` ergibt 422;
16. future-current wird nicht vorzeitig gewählt oder aktiviert;
17. expired-current wird am Stichtag nicht gewählt;
18. exakte Boundary für halb-offenes oder geschlossenes Intervall laut ADR;
19. Gap, Overlap und zwei effektive Zeilen ergeben deterministischen 409;
20. CH, Non-CH, Tenant-Override und firmwide Fallback nutzen dieselbe
    As-of-Semantik;
21. Backdated Replay wählt die damals gültige, nicht die heute aktuelle CMA;
22. Future-Pfad wird niemals rückwärts auf 2026 gefüllt.

### Evidence und Publikation

23. Mutation von Path, Datum, Status oder Resolverpolicy ändert Context-Hash;
24. Generate, Current-Rebuild, Sensitivity, Stress und PDFs lösen dieselbe
    CMA für denselben Stichtag auf;
25. invalid/future/expired Evidence blockiert UI, API, PDF, Signatur und
    Handoff mit demselben Reason Code;
26. Legacy-Allocation ohne überprüfbare Raw-/Resolved-Evidence wird replayt
    oder sichtbar quarantänisiert.

## Verifikation dieser Audit-Runde

Ausgeführt:

```powershell
python -m pytest -q --basetemp ..\.pytest_tmp_round40 `
  tests/test_cma_validation.py `
  tests/test_cma_strict_runtime_contract.py `
  tests/test_cma_correlation_matrix_validation.py `
  tests/test_cma_jurisdiction_query_param.py `
  tests/test_cma_data_pipeline.py `
  tests/test_cma_approval_endpoint.py `
  tests/test_cashflow_projection.py `
  tests/test_audit_b1_cashflow_inflation.py `
  tests/test_optimizer_goal_liabilities.py `
  tests/test_optimizer_production_contract.py `
  tests/test_wave13_planning_fx_bounds.py
```

Ergebnis: **193 passed**, 0 failed, 60,43 Sekunden.

Zusätzlich wurden fünf deterministische Reproduktionsgruppen direkt gegen
Produktionscode ausgeführt:

1. Schema-/Runtime-Inflationsmatrix,
2. negativer Goal-Liability-/Probability-Flip,
3. extrahierte Classic-Admin-Normalisierung,
4. echte SQLite-CMA-Auflösung einer Zukunftszeile und
5. Future-/Expired-Path-Auflösung auf den Projektionsstart.

Die 193 grünen Bestandstests prüfen strikte CMA-Returns, Vola,
Korrelationen, Sub-Assets, Jurisdiktion, Pipeline, Approval, Cashflowinflation,
Goal-Liabilities und Produktionskontext. Sie enthalten aber keinen der fünf
neuen Gegenbeispielverträge. Im Testbestand existiert insbesondere keine
Inflation-Path-Negativmatrix und kein as-of-basierter CMA-Resolver-Test.

Nicht ausgeführt wurden vollständige Backend-/Frontend-Suites, echte Browser-
E2E, PostgreSQL-Concurrency, Electron-Packaging, PDF-Pixelvergleich und
Zielumgebungs-Replay. Diese gehören zur Implementierungsabnahme.

## Definition of Done

Der Release-Hold dieser Runde kann erst aufgehoben werden, wenn:

1. beide neuen Finding-IDs durch rote Vorher-/grüne Nachher-Tests geschlossen
   sind;
2. ein Shared-Parser Schema, API, Runtime und Legacy-Daten fail-closed prüft;
3. Inflationswerte, Jahre, Abdeckung und Extrapolation einen versionierten
   Ownervertrag besitzen;
4. kumulative Faktoren und reale Liabilities strikt positiv beziehungsweise
   nichtnegativ bleiben;
5. ein obligatorischer `as_of`-Resolver genau eine zeitlich gültige CMA je
   Scope auswählt;
6. Future-/Expired-/Gap-/Overlap-Zustände vor jeder Rechnung blockieren;
7. Raw Path, resolved series, Stichtag, Gültigkeitsfenster und Policyversion
   an Run, Allocation, Sensitivity, Stress und Publikation gebunden sind;
8. UI/API/PDF/Signatur/Handoff dieselben Zustände und Reason Codes verwenden;
9. Legacy-CMAs und alle davon abgeleiteten Entscheidungen repariert, replayt
   oder quarantänisiert sind; und
10. fokussierte, vollständige, Browser-, Electron-, PDF-, PostgreSQL- und
    Zielumgebungs-Abnahmen grün sind.

## Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen durch die Runde verändert werden:

1. `docs/audits/2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`
