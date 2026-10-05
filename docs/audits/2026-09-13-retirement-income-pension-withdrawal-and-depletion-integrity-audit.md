---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-retirement-income-pension-withdrawal-depletion-integrity-followup-audit"
status_as_of: "2026-09-13"
audit_started_on: "2026-09-07"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "6ab26b33656971da9af34651053e19b2bf2edffe"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-07-mortality-longevity-retirement-and-decumulation-integrity-audit.md"
prior_release_audit_commit: "6ab26b33656971da9af34651053e19b2bf2edffe"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md"
audit_mode: "read_only_static_ui_router_service_orm_schema_alembic_test_review_and_isolated_runtime_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "Retirement income, AHV and pension-goal semantics, pension-position availability and linkage, indexation, capital-withdrawal amount and timing evidence, deficit recovery, depletion publication, readiness and signature eligibility"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
static_findings_confirmed: 9
focused_existing_tests_passed: 521
focused_existing_tests_failed: 0
isolated_runtime_harness_executed: true
isolated_runtime_reproductions_confirmed: 8
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "introduce one immutable RetirementIncomeAndWithdrawalSnapshot bound to TargetAllocation and OptimizerRun; separate pension income, spending need and funding source; validate and reconcile AHV/BVG/3a/FZG benefits and linked positions; enforce availability dates and payout forms; net deficit before investing later inflows; bind gross/net/tax and intra-year timing to one cashflow event; publish depletion and runway through the strict API schema; make decumulation readiness mandatory and fail closed before PDF/signature"
---

# Retirement-Income-/Pensions-/Entnahme-/Depletion-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die neunundzwanzigste Read-only-
Kontrollrunde. Sie begann am 7. September 2026, wurde am 13. September 2026
abgeschlossen und prüfte den unveränderten Repository-Head `6ab26b3`.
Produktcode und Tests wurden nicht verändert.

Der Audit prüft nicht, welche konkrete AHV-, BVG-, 3a- oder
Freizügigkeitsleistung einer bestimmten Person zusteht und gibt keine
individuelle Vorsorge- oder Steuerberatung. Er prüft ausschließlich, ob die
Software ihren eigenen technischen und sichtbaren Vertrag konsistent erfüllt:

1. ob ein Pensionsbedarf von einer tatsächlich erfassten Einnahme oder
   Vorsorgeleistung gedeckt wird,
2. ob Vorsorgepositionen, Bezugsform, Bezugsalter, Verfügbarkeit und
   Zielverknüpfung in der Rechnung wirksam sind,
3. ob Indexierung und Kapitalbezugssteuer in Input, Snapshot, Projektion und
   Publikation identisch wirken,
4. ob Entnahmen und spätere Zuflüsse Defizite ökonomisch konsistent
   fortschreiben,
5. ob Tag-/Monatspräzision tatsächlich einen unterjährigen Effekt besitzt,
6. ob die berechnete Depletion-Wahrscheinlichkeit den API-Rand und die UI
   unverändert erreicht,
7. ob ein Decumulation-/Runway-Gate vor PDF und Signatur wirklich existiert,
8. und ob historische Ergebnisse mit einem unveränderlichen
   Retirement-Income-/Withdrawal-Context reproduzierbar sind.

Dieser Audit ergänzt und ersetzt insbesondere nicht:

1. den unmittelbar vorherigen
   [Mortalitäts-/Langlebigkeits-/Retirement-/Decumulation-Integritätsaudit](2026-09-07-mortality-longevity-retirement-and-decumulation-integrity-audit.md),
2. den
   [Steuerregime-/Parameter-/After-Tax-Publikationsintegritätsaudit](2026-09-05-tax-model-regime-parameter-and-after-tax-publication-integrity-audit.md),
3. den
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
4. den
   [Vertragsdokument-/E-Signatur-/signierte-Publikations-Integritätsaudit](2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md),
5. den historischen
   [Cashflow-in-Monte-Carlo-Audit](2026-06-07-cashflow-in-mc-audit.md),
6. sowie die weiterhin gültige
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code, Tests und Migrationen zuerst, danach
dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu früheren Findings

`RETIREMENT-CONTEXT-001` bleibt ausschließlich für die fehlerhafte Kopplung
des Optimizer-Decumulation-Signals an die Steuerkonfiguration zuständig.
`PENSION-AHV-001`, `PENSION-POSITION-001`,
`PENSION-AVAILABILITY-001` und `PENSION-INDEXATION-001` prüfen neue,
konkrete Funding- und Vorsorgeverträge.

`MC-CASHFLOW-CURRENCY-001` bleibt der allgemeine Vertrag für den verkürzten
Cashflow-/FX-/Tax-/Fee-Kontext eines Reporting-Kanals.
`DECUM-DEFICIT-001`, `WITHDRAWAL-AMOUNT-001` und
`WITHDRAWAL-TIMING-001` erweitern ihn um reproduzierte
Decumulation-Mechanik. Die historische `F6`-Aussage, beide Engine-Pfade seien
für ihren jeweiligen Use Case korrekt, wird für Defizit-Recovery ausdrücklich
eingeschränkt und insoweit durch `DECUM-DEFICIT-001` ersetzt. Das dort bereits
benannte Drift-Risiko hat sich in diesem Teilvertrag realisiert. `F7` bestätigt
weiterhin korrekt, dass die skalare Scenario-Engine negatives Vermögen nicht
wachsen lässt und spätere positive Cashflows dagegen verrechnet. Neu ist, dass
die Bucket-Simulation und die Reporting-Monte-Carlo-Simulation genau diese
Verrechnung nicht vornehmen. Die historische `F2`-Bewertung dokumentiert den
bewussten Jahresend-Cashflow-Vertrag. `WITHDRAWAL-TIMING-001` verwirft diese
Jahreskonvention nicht; der Befund erfasst enger den Widerspruch zwischen
gespeicherter und sichtbarer Tages-/Monatspräzision und einer Engine, die nur
das Jahr verwendet.

`GOAL-PUBLICATION-001` und `MC-CONTEXT-001` bleiben für allgemeine
Kanal- und Run-Provenienz maßgeblich. `DECUM-DEPLETION-001` erfasst die
engere, direkt reproduzierte API-Filterung der vier Depletion-Felder.

`SIGN-ELIGIBILITY-001` bleibt der übergeordnete Finalisierungsblocker.
`DECUM-READINESS-001` ergänzt den konkreten Ghost-Contract: Das Frontend
besitzt zwar Code für einen optionalen Reichweiten-Checklistenpunkt, der
Backendvertrag kann dessen Objekt aber nicht liefern. Es ist daher kein
Duplikat der allgemeinen Final-Eligibility-ID und kein Beleg für eine bereits
implementierte technische PDF-/Signatursperre.

## Kurzurteil

Der aktuelle Stand darf **nicht** als AHV-/Vorsorge-finanzierte,
entnahmefeste oder runway-geprüfte Ruhestandsrechnung und nicht als
freigabefähige Depletion-Evidenz verwendet werden.

Bestätigt sind insbesondere:

1. Die UI beschreibt `Pensionsausgabe` als periodischen Bedarf. Allein die
   Auswahl `pension_pillar=AHV` macht jedoch jeden Betrag vollständig
   staatlich finanziert. Weder eine AHV-Leistung noch eine Deckungsrelation
   wird erfasst oder geprüft.
2. Ein isoliertes Ziel von CHF 1 Mio. pro Jahr erzeugt deshalb null
   Optimizer-Liability, null Reservebedarf sowie 100 Prozent Success,
   Funded Ratio und Score bei einem simulierten Pfadwert von null.
3. Pensionsart, Institut, technischer Zins, Bezugsalter, Bezugsform und
   WEF-Flag sind produktiv nur Eingabe-/Speicher- und teilweise
   Anzeigeattribute. Der technische Zins fehlt sogar im Response-Schema und
   geht beim API-Roundtrip verloren. Der Goal-Link `linked_position_id` darf
   auf eine nicht existierende Position zeigen und wird fachlich nicht
   aufgelöst.
4. Diese Pensionspositionsattribute fehlen zusätzlich im Strategy-
   Input-Snapshot. Ein Wechsel von Alter 63/Kapital/175 bp auf
   Alter 5/Rente/999999 bp erzeugte denselben Hash; Alter -999 wurde im
   getrennten Schema-Domain-Repro akzeptiert.
5. `is_available_for_goal_funding=1` summiert eine Vorsorgeposition sofort
   als frei verfügbares anderes Vermögen. Bezugsalter, Bezugsform und
   Verfügbarkeitsdatum werden nicht berücksichtigt. Ein CHF-80.000-Nahziel
   reduzierte dadurch seine externe Reserve reproduziert von CHF 70.000 auf
   null.
6. `PlanningAssumption.pension_indexation_bps` wird gespeichert und im
   Schema als simulations-/projektionswirksam kommentiert, besitzt aber keinen
   produktiven Engine-Consumer und keinen gebundenen Ergebnisnachweis.
7. Die Bucket- und Reporting-MC-Pfade akkumulieren eine Lebenslücke, reduzieren
   sie aber bei späteren positiven Cashflows nie. Danach können Assets neben
   einer eingefrorenen Schuld rebalanciert werden und Rendite erzielen. Der
   Repro endet bei 65 statt ökonomisch konsistent 55 Rappen.
8. Kapitalbezugsmetadaten verlangen nicht
   `netto = brutto - steuer`, sind nicht auf Kapitalzuflüsse beschränkt und
   wirken nicht in der Projektion. Netto 100, Brutto 350 und Steuer 30 wurde
   sogar für einen Expense akzeptiert; simuliert wurden nur 100.
9. Tag-/Monatspräzision wird gespeichert und sichtbar formatiert, die
   Jahresaggregation prüft bei Einmalflows aber nur das Jahr. 1. Januar und
   31. Dezember 2030 erzeugten dieselbe Jahresreihe.
10. Die Engine berechnet vier Depletion-Felder. `MonteCarloResponse`
    deklariert keines davon; der Pydantic-Repro entfernte alle vier. Die UI
    wandelt fehlende Werte anschließend in `0%` um.
11. Das Review-Cockpit fügt den Checklistenpunkt `Reichweite bestaetigt` nur ein,
    wenn `allocation.decumulation.decumulation_mode` existiert. Weder
    `TargetAllocationGenerateResponse` noch ein regulärer Response-Producer
    liefert dieses Objekt. Damit kann das Cockpit ohne Reichweitenprüfung
    `Meeting ist bereit fuer PDF und Signatur.` anzeigen. Die Checkliste
    sperrt PDF/Signatur technisch ohnehin nicht: Auch offene Punkte lassen
    `Trotzdem drucken` zu und beide Aktionen rufen `printReport()` auf.

Der fokussierte Bestands-Gate mit 521 bestandenen Tests bestätigt vorhandene
Teilfunktionen, widerlegt diese Findings aber nicht. Die AHV-Tests pinnen das
vollfinanzierte Verhalten ausdrücklich. Die Depletion-Tests prüfen den
internen Engine-Dict vor dem Response-Schema. Es fehlen Negativfälle für
Benefit-Reconciliation, orphaned pension links, Availability-as-of,
Defizittilgung, Gross/Tax-Reconciliation, unterjährige Timing-Parität,
API-Depletion-Erhalt und mandatory Decumulation-Readiness.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `PENSION-AHV-001` | P1 | bestätigt | Ein beliebig hoher Pensionsbedarf wird allein durch das AHV-Label ohne erfasste Leistung zu null Liability/Reserve und 100 Prozent Zielerfüllung. |
| `PENSION-POSITION-001` | P1 | bestätigt | Vorsorgepositionen und Goal-Links besitzen keinen wirksamen, validierten und gesnapshotteten Funding-/Payout-Vertrag. |
| `PENSION-AVAILABILITY-001` | P1 | bestätigt | Ein Goal-Funding-Flag macht auch zukünftiges/gesperrtes Vorsorgevermögen sofort und zu 100 Prozent reservefähig. |
| `PENSION-INDEXATION-001` | P1 | bestätigt | Die persistierte Pensionsindexierung ist trotz Wirksamkeitsclaim inert und nicht an TA/Run/Publikation gebunden. |
| `DECUM-DEFICIT-001` | P1 | bestätigt | Spätere Zuflüsse tilgen die akkumulierte Lebenslücke im Bucket-/Reporting-MC-Pfad nicht; Assets können neben eingefrorener Schuld Rendite erzielen. |
| `WITHDRAWAL-AMOUNT-001` | P1 | bestätigt | Netto, Brutto und Steuer werden nicht reconciliert oder fachlich auf Kapitalzuflüsse beschränkt; nur der Nettobetrag wirkt. |
| `WITHDRAWAL-TIMING-001` | P2 | bestätigt | Gespeicherte Tag-/Monatspräzision kollabiert in der Jahresprojektion; Januar- und Dezemberereignisse sind rechnerisch identisch. |
| `DECUM-DEPLETION-001` | P1 | bestätigt | Vier berechnete Depletion-Felder werden am API-Schema entfernt; Missing erscheint in der UI als 0 Prozent. |
| `DECUM-READINESS-001` | P1 | bestätigt | Der sichtbare Reichweiten-Checklistenpunkt hängt an einem nicht gelieferten `allocation.decumulation`-Objekt, kann vollständig entfallen und erzwingt keine PDF-/Signatursperre. |

## Positivkontrollen, die erhalten bleiben müssen

Die Reparatur darf folgende bestehende Kontrollen nicht zurückbauen:

1. Cashflow-Magnituden sind im Create-Schema nichtnegativ; die Richtung kommt
   aus `Income|Expense`.
2. Einmalige Cashflows benötigen ein syntaktisch gültiges Datum.
3. Cashflow-Frequenzen werden zentral normalisiert.
4. Fremdwährungs-Cashflows verlangen im Enginepfad eine explizite FX-Quelle;
   stilles 1:1 ist dort untersagt.
5. Inflation wird nur bei explizit inflation-linked Cashflows angewandt.
6. Negatives Vermögen wächst in der Scenario-Engine nicht und erhält dort
   keine Vermögenssteuer.
7. Die Bucketwerte selbst bleiben nichtnegativ; eine Lebenslücke wird
   separat sichtbar gehalten.
8. Der Reporting-MC-Engine-Dict berechnet Depletion für SOLL und IST.
9. Der Input-Snapshot bindet bereits Cashflow-Grossbetrag, Steuer,
   Timing-Präzision, Source und Origin sowie Goal-Pillar und Goal-Link.
10. AHV-, BVG-, 3a-, 1e- und FZG-Werte sind im Goal-Schema als Literal
    begrenzt.
11. Der Max-Pension-Spending-Endpunkt kennzeichnet seine Annuität ehrlich als
    deterministisch und verweist ausdrücklich auf eine spätere MC-basierte
    Sustainable-Withdrawal-Rate.
12. Der Review-Check kennt grundsätzlich einen P10-Reichweitenpunkt; er muss
    zu einem echten Pflichtvertrag ausgebaut, nicht ersatzlos entfernt werden.

## Tatsächlicher Retirement-/Withdrawal-Datenfluss

```text
Pensionsausgabe + pension_pillar=AHV
  |
  +-- Reserve: Goal wird übersprungen ----------------------> reserve = 0
  +-- Optimizer: state_funded, target=0, liability=[0...] --> keine Last
  +-- Reporting-MC: available := Zielbetrag ---------------> score = 100
  |
  '-- keine AHV-Leistung / kein Benefit-Abgleich / kein Link-Nachweis

Vorsorgeposition
  |
  +-- pension_type / rate / retirement_age / payout / WEF --> speichern + UI
  +-- linked_position_id ----------------------------------> speichern + Hash
  '-- is_available_for_goal_funding=1
        '-- voller aktueller Positionswert ----------------> sofortige Reserve-Deckung

Einmaliger Kapitalbezug
  |
  +-- amount_rappen ---------------------------------------> Jahrescashflow
  +-- gross/tax/timing_precision --------------------------> speichern + UI + Hash
  '-- Tag/Monat -------------------------------------------> im Enginepfad nur year

Reporting-Pfad
  |
  +-- Engine berechnet target/current depletion
  +-- MonteCarloResponse deklariert Felder nicht ----------> API entfernt sie
  +-- UI Number(undefined || 0) ---------------------------> "0%"
  '-- Readiness erwartet allocation.decumulation ----------> Punkt fehlt komplett
```

## Codeanker auf dem auditierten Head

| Vertrag | Verifizierter Anker |
|---|---|
| Pensionsausgabe ist sichtbarer periodischer Bedarf | `5eyes-electron/frontend/5eyes_v2.html:4635-4642,26280-26295` |
| AHV-Hinweis in der UI | `5eyes-electron/frontend/5eyes_v2.html:4743-4752,26263-26267` |
| AHV-Reserve-/Score-Semantik | `5eyes-backend/services/portfolio_engine_reserve.py:207-233,236-282,371-385` |
| AHV-Optimizer-Liability | `5eyes-backend/services/optimizer/goal_liabilities.py:43-65,294-299,504-527,535-555` |
| AHV-Reporting-MC | `5eyes-backend/services/portfolio_engine_mc_simulation.py:844-933` |
| Vorsorgepositionsfelder und API-Response | `5eyes-backend/models/wealth.py:10-57`; `5eyes-backend/schemas/wealth.py:12-120,123-230`; `5eyes-backend/routers/wealth.py:506-570` |
| Goal-Link ohne vollständige Semantikprüfung | `5eyes-backend/schemas/wealth.py:539-611`; `5eyes-backend/routers/wealth.py:260-339` |
| Foundation-Vorsorgebeispiele | `5eyes-backend/services/foundation_example.py:367-405` |
| sofortiger Unlocked-Pool | `5eyes-backend/services/portfolio_engine.py:1896-1915,5472-5484` |
| Reserveabsorption | `5eyes-backend/services/portfolio_engine_reserve.py:441-494` |
| Positions-/Cashflow-/Goal-Hashencoder | `5eyes-backend/services/portfolio_engine.py:2338-2518` |
| Pensionsindexierung | `5eyes-backend/models/wealth.py:174-182`; `5eyes-backend/schemas/wealth.py:647-680`; `5eyes-backend/services/foundation_example.py:288-301` |
| Bucket-Cashflow und Defizit | `5eyes-backend/services/portfolio_engine_mc_simulation.py:261-284,297-382,1298-1343,1425-1429` |
| korrekt nettender Vergleichspfad | `5eyes-backend/services/optimizer/scenario_engine.py:524-578` |
| Cashflow-Gross/Steuer/Timing-Schema | `5eyes-backend/schemas/wealth.py:257-319` |
| Cashflow-Normalisierung | `5eyes-backend/routers/wealth.py:75-139` |
| Jahresaggregation | `5eyes-backend/services/cashflow_timeline.py:93-157,194-235,238-339,374-383` |
| Kapitalbezug-UI | `5eyes-electron/frontend/5eyes_v2.html:22026-22068,22706-22805` |
| Engine-Depletion | `5eyes-backend/services/portfolio_engine_mc_simulation.py:1114-1129,1293-1296,1493-1510,1551-1619` |
| API-Monte-Carlo-Schema | `5eyes-backend/schemas/allocation.py:1206-1237` |
| API-Response-Model | `5eyes-backend/routers/allocation.py:147-163,497-505` |
| Depletion-Anzeige | `5eyes-electron/frontend/5eyes_v2.html:21074-21122` |
| Generate-Response ohne Decumulation | `5eyes-backend/schemas/allocation.py:1375-1436` |
| Ghost-Readiness | `5eyes-electron/frontend/5eyes_v2.html:23950-23980` |
| deterministische Annuitätsdisclosure | `5eyes-backend/routers/wealth.py:1182-1322` |

## `PENSION-AHV-001` – Ein Label ersetzt den AHV-Leistungsnachweis

### Beobachtung

Das Goal-UI definiert `Pensionsausgabe` als periodischen Bedarf mit Betrag,
Beginn und Frequenz. Wird für denselben Bedarf `AHV` ausgewählt, erklärt das
UI pauschal, es sei keine Portfolioreserve nötig.

Der Reservepfad erkennt lediglich Goal-Typ und Pillar. Er prüft keinen
Leistungsbetrag, keine Person, kein Bezugsjahr, keine laufende AHV-Einnahme,
keinen Deckungsanteil und keinen verknüpften Nachweis. Danach:

- überspringt die Gesamtreserve das Ziel,
- erzeugt der Optimizer `target_kind=state_funded`, Target null und einen
  vollständig leeren Liability-Pfad,
- und verwendet der Reporting-MC-Pfad den Zielbetrag selbst als
  `available`, wodurch Success und Funded Ratio 100 Prozent werden.

### Isolierte Reproduktion

```text
input:
  goal_type=Pensionsausgabe
  pension_pillar=AHV
  target_amount_rappen=100000000
  frequency=jährlich
  advisory_wealth_rappen=10000000
  simulated_path_value=0

output:
  goal_reserve_for_score=100000000
  reserve_needed_external=(0, 0)
  liability_kind=state_funded
  liability_target=0
  liability_path=[0,0,0,0,0,0,0,0,0,0]
  mc_success=100
  mc_funded_ratio=1.0
  mc_score=100
```

Ein zusätzlich erfasster AHV-Einnahmecashflow würde normal zum Vermögen
addiert, während der markierte Bedarf weiterhin vollständig entfernt bleibt.
Es existiert keine Reconciliation, die diese Doppeloptimierung verhindert.

### Wirkung

Der zentrale Pensionierungsbedarf kann unabhängig von realer Deckung
verschwinden. Zielwahrscheinlichkeit, Reserve, Solverziel und Kundenanzeige
werden gleichzeitig zu optimistisch.

### Fixvertrag

Pensionsbedarf, Einkommensquelle und Funding-Deckung müssen getrennte Objekte
sein. Ein Benefit enthält Person, Säule, Brutto/Netto, Start, Ende,
Indexierung, Survivor-Regel, Evidenz und Source-as-of. Nur der explizit
reconciliierte Benefit-Anteil reduziert den Bedarf. Missing, invalid oder
unbestätigt blockiert einen Vollfinanzierungsclaim.

### Pflichttests

- Bedarf 100, AHV 0/40/100/120 mit sichtbarem Restbedarf;
- Benefit startet vor/nach dem Bedarf;
- Hauptperson/Partner/Survivor;
- Cashflow plus Benefit darf nicht doppelt zählen;
- Goal-Link fehlt, ist fremd, gelöscht oder falsche Säule;
- Optimizer, Reserve, MC, API, UI und PDF reconciliieren exakt.

## `PENSION-POSITION-001` – Vorsorgeposition und Goal-Link sind fachlich inert

### Beobachtung

`WealthPosition` speichert Pensionsart, Institut, technischen Zins,
Bezugsalter, Bezugsform und WEF-Möglichkeit. Die UI kann diese Felder erfassen
und mehrere davon wieder anzeigen. `pension_technical_rate_bps` fehlt jedoch
in `WealthPositionResponse`; der persistierte Wert wird nach dem API-Roundtrip
nicht an die UI zurückgeliefert. Die produktive Backend-Suche findet außerhalb
von Schema, Model, Router-Boolnormalisierung und Foundation-Seed keinen
Engine-Consumer.

`Goal.linked_position_id` ist ein freier String. Er ist weder Foreign Key
noch Teil der vollständigen Router-Semantikvalidierung. Im Enginepfad wird er
nur in den Goal-Hash geschrieben, aber nie auf eine Position aufgelöst.

Auch der Positionshash enthält zwar
`is_available_for_goal_funding`, nicht aber Pensionsart, technischen Zins,
Bezugsalter, Bezugsform oder WEF-Flag.

### Isolierte Reproduktionen

```text
WealthPositionCreate accepted:
  pension_type=anything
  pension_technical_rate_bps=999999999
  pension_retirement_age=-999
  pension_payout_form=teleport

GoalCreate accepted:
  pension_pillar=BVG
  linked_position_id=does-not-exist
```

```text
hash(age=63, payout=Kapital, rate=175)
  8857b7f314f0fd24aa050351cb27c0d56daec7dc43c0df26f081828ec8302e5b

hash(age=5, payout=Rente, rate=999999, type=beliebig)
  8857b7f314f0fd24aa050351cb27c0d56daec7dc43c0df26f081828ec8302e5b

hash_changed=false
```

### Wirkung

Die Oberfläche vermittelt einen Vorsorgevertrag, den die Rechnung nicht
besitzt. Änderungen an Bezugsform oder Alter können ein Ergebnis fachlich
grundlegend ändern, ohne Enginewirkung oder Input-Drift auszulösen.

### Fixvertrag

Es braucht validierte, versionierte PensionPosition-Subtypen mit
Säule, Eigentümer, Provider, Anspruchs-/Verfügbarkeitszeit, Kapital-/Renten-/
Mischbezug, Conversionfaktor, garantierter/nicht garantierter Komponente,
Indexierung, Steuerbezug und Evidence. Goal-Links sind echte mandategebundene
Referenzen und werden atomar validiert. Alle wirksamen Felder gehen in den
Snapshot-Hash ein.

## `PENSION-AVAILABILITY-001` – Zukunftsvermögen deckt heutigen Reservebedarf

### Beobachtung

Der Loader summiert jede aktive Position mit Assignment
`Anderes Vermögen` und `is_available_for_goal_funding=1` vollständig in
`unlocked_other_assets_rappen`. Positionstyp, Bezugsalter, Bezugsform,
`liquidity_available_from`, Sperrfrist, Haircut und realisierbarer Anteil
werden nicht berücksichtigt.

Der Reservepfad zieht diesen Pool danach eins zu eins vom externen
Reservebedarf ab. Das Foundation-Beispiel markiert eine Säule-3a-Position mit
Bezugsalter 63 und Kapitalbezug als verfügbar und weist zugleich darauf hin,
dass der künftige Bezug zusätzlich als datierter Cashflow modelliert wird.

### Isolierte Reproduktion

```text
advisory wealth:             10000000
near-term spending goal:      8000000
SAA liquidity ceiling:           1000 bps

without unlocked other assets:
  reserve_needed=8000000
  external_reserve=7000000

with 8000000 age-63 pension value counted as unlocked:
  reserve_needed=8000000
  external_reserve=0
```

### Wirkung

Eine heutige Liquiditätswarnung kann durch Mittel verschwinden, die erst
später, teilweise, anders besteuert oder als Rente statt Kapital verfügbar
sind. Wird der spätere Kapitalbezug zusätzlich als Cashflow geführt, droht
außerdem Doppelzählung.

### Fixvertrag

Verfügbarkeit wird pro Cashflowperiode und Szenario aus einem
`available_from/as_of`-, Payout-, Ownership-, Tax-, Haircut- und
Encumbrance-Vertrag abgeleitet. Ein Flag darf nur eine fachliche Prüfung
anstoßen, nie den vollen Wert sofort freischalten.

## `PENSION-INDEXATION-001` – Persistierte Indexierung ohne Wirkung

### Beobachtung

`PlanningAssumption.pension_indexation_bps` wird persistiert, validiert und
im Foundation-Beispiel mit 100 bp gesetzt. Der Schemakommentar behauptet, die
Planning-Assumption-Felder flössen in MC-Simulation und Zielprojektion jedes
Berichts ein.

Die produktive Suche findet für `pension_indexation_bps` jedoch nur Model,
Schema, Migration, Seed und Tests der Speicherung/Bounds. Kein Loader,
Liability-Builder, Cashflow-Timeline-, Optimizer-, Reporting-, PDF- oder
Snapshotpfad konsumiert den Wert.

### Wirkung

Eine sichtbare Planungsannahme kann geändert und versioniert werden, ohne den
Pensionspfad zu ändern. Nutzer und historische Reviewer können nicht erkennen,
dass die Eingabe inert war.

### Fixvertrag

Pensionsindexierung gehört zur konkreten Benefit-/Pension-Komponente, nicht als
unklarer globaler Float in eine PlanningAssumption. Der Snapshot speichert
Quelle, Basisjahr, Nominal-/Realmodus, Cap/Floor und die tatsächlich verwendete
Jahresreihe. Bis zur Umsetzung muss die Eingabe als nicht rechenwirksam
gekennzeichnet oder entfernt werden.

## `DECUM-DEFICIT-001` – Spätere Zuflüsse tilgen die Lebenslücke nicht

### Beobachtung

`_apply_cashflow_to_bucket_values()` legt positive Cashflows vollständig in
Liquidität und gibt null zurück. Negative Cashflows verbrauchen die Buckets und
geben einen Rest zurück. Die aufrufenden Pfade addieren diesen Rest zu
`accumulated_deficit`, `current_deficit` oder `target_deficit`.

Kein positiver Cashflow reduziert einen bestehenden Defizitstand. Assets und
Defizit können dadurch gleichzeitig bestehen. Bei Rebalancing wird der
positive Zufluss investiert und wächst, während die alte Schuld nominal
eingefroren bleibt.

Der Optimizer-Scenario-Pfad verwendet dagegen einen skalaren Wealth-Wert:
Negativer Wealth wächst nicht, ein positiver Cashflow wird direkt addiert und
tilgt daher zuerst die Lücke. Das ist die vom historischen `F7` geprüfte
Mechanik. Der neue Repro schränkt zugleich die breite historische
`F6`-Bewertung ein, wonach beide Engine-Pfade für ihren jeweiligen Use Case
korrekt seien: Für Defizit-Recovery ist diese Aussage im Bucket-/Reporting-
Pfad nicht haltbar; das bereits unter `F6` dokumentierte Drift-Risiko ist hier
eingetreten.

### Isolierte Reproduktion

```text
start assets:       0
cashflows:          [-100, +150, 0]
target:             100% equities
equity return:      +10%
rebalance mode:     calendar

bucket/reporting engine totals:
  [0, -100, 50, 65]

economically netted path:
  year 1: -100
  year 2: +150 repays 100, leaves +50
  year 3: 50 * 1.10 = 55

engine terminal=65
expected terminal=55
```

### Wirkung

Recovery-Szenarien, spätere Kapitalbezüge und Rentenstarts können Endvermögen
und Runway überzeichnen. Decision- und Reportingpfad besitzen außerdem
verschiedene Defizitsemantik.

### Fixvertrag

Ein positiver Cashflow bedient zuerst offenen Defizit-/Finanzierungsbedarf.
Nur der Rest geht in investierbare Buckets. Alternativ wird ein explizites
Debt-Instrument mit Zins, Tilgungsrang und Kosten modelliert. Optimizer und
Reporting müssen denselben Zustandsautomaten verwenden oder ihre Abweichung
quantitativ reconciliieren.

### Pflichttests

- Defizit vollständig, teilweise und übertilgt;
- Zufluss vor/nach Wachstum sowie vor/nach Rebalancing;
- Steuer, Transaktionskosten und Zins auf explizite Schuld;
- SOLL, IST und Total Wealth;
- Deterministik plus Monte Carlo mit identischen Nullrenditen;
- Runway-/Depletion-Parität zwischen Decision und Reporting.

## `WITHDRAWAL-AMOUNT-001` – Netto, Brutto und Steuer reconciliieren nicht

### Beobachtung

Das Schema erlaubt Grossbetrag, Steuer und Timing auf jedem Income- oder
Expense-Cashflow. Die Routernormalisierung prüft lediglich:

- Gross und Steuer sind nicht negativ,
- Gross ist nicht kleiner als `amount_rappen`,
- Steuer ist nicht größer als Gross.

Sie verlangt weder `amount = gross - tax` noch eine Kapitalbezugs-Kategorie
oder `Income + einmalig`. Die UI beschriftet `amount_rappen` bei erkannten
Kapitalbezügen als Nettozufluss und zeigt Gross/Steuer als Evidenz. Die
Cashflow-Timeline konsumiert ausschließlich `amount_rappen`.

### Isolierte Reproduktion

```text
accepted:
  cashflow_type=Expense
  amount_rappen=100
  gross_amount_rappen=350
  tax_amount_rappen=30

gross - tax=320
simulated amount=100
```

### Wirkung

Anzeige, Tax-Evidence und tatsächlich projizierter Betrag können drei
verschiedene Wahrheiten enthalten. Ein gespeicherter Steuerbetrag beweist
nicht, dass er berechnet, abgezogen oder im After-Tax-Modell berücksichtigt
wurde.

### Fixvertrag

Kapitalbezug ist ein strikt typisiertes Event mit
`gross, tax_components, net, currency, date, source_position_id`.
Serverseitige Reconciliation ist Pflicht. Eine manuelle Steuer braucht
Override-Evidence; eine berechnete Steuer braucht Parameter-/Regime-/Source-
Snapshot. Unzulässige Kombinationen und unbekannte Legacyzeilen blockieren.

## `WITHDRAWAL-TIMING-001` – Exaktes Datum ohne unterjährige Semantik

### Beobachtung

Router und UI speichern `day|month` und zeigen den konkreten Zeitpunkt.
`contribution_for_year()` prüft für Einmalflows aber ausschließlich
`event_date.year == year`. Danach wenden deterministische und
Monte-Carlo-Projektion den aggregierten Jahresbetrag nach dem Jahreswachstum
an. Der historische Befund `F2` bewertete diese Jahresend-Konvention für ein
reines Jahresmodell ausdrücklich als korrekt. Dieser Befund bleibt bestehen.
Die neue Abweichung entsteht erst dadurch, dass API und UI inzwischen eine
genauere Tages-/Monatssemantik speichern und sichtbar versprechen, ohne sie in
der Rechnung zu verwenden.

### Isolierte Reproduktion

```text
one-off Expense 100 on 2030-01-01 -> series [-100]
one-off Expense 100 on 2030-12-31 -> series [-100]
```

### Wirkung

Die gespeicherte Präzision suggeriert einen Rendite-, Liquiditäts- und
Steuerzeitpunkt, den das Modell nicht verwendet. Besonders bei großen
Kapitalbezügen kann der Unterschied materiell sein.

### Fixvertrag

Entweder wird auf echte Monats-/Tagesperioden mit eindeutiger
Beginning-/End-of-Period-Konvention umgestellt, oder UI/API kennzeichnen das
Datum ausdrücklich nur als Dokumentationsmetadatum und zeigen die verwendete
Jahreskonvention. Der P2 darf erst geschlossen werden, wenn UI, Engine,
Reserve, Tax, PDF und Snapshot dieselbe Timingbasis nennen.

## `DECUM-DEPLETION-001` – Berechnet, am API-Rand entfernt, als null angezeigt

### Beobachtung

Die Reporting-Engine berechnet und returned:

- `target_depletion_probability_pct`,
- `target_depletion_median_year`,
- `current_depletion_probability_pct`,
- `current_depletion_median_year`.

Die Generate- und Reload-Endpunkte verwenden
`TargetAllocationGenerateResponse`. Dessen `monte_carlo` ist als
`MonteCarloResponse` typisiert. Diese Klasse enthält keines der vier Felder.
Pydantic ignoriert die zusätzlichen Keys beim Modellbau.

Die UI liest die fehlenden Felder und formatiert
`Number(pct || 0)`; Missing wird damit positiv als `0%` publiziert.

### Isolierte Reproduktion

```text
engine_input_depletion:
  target_depletion_probability_pct=100
  target_depletion_median_year=2027
  current_depletion_probability_pct=100
  current_depletion_median_year=2027

MonteCarloResponse output:
  api_schema_output_depletion={}
  fields_survive=false
```

### Wirkung

Ein intern erkanntes vollständiges Aufzehrungsrisiko kann beim Nutzer als
kein Risiko erscheinen. Direkte Engine-Unit-Tests bleiben grün, weil sie vor
dem Response-Schema prüfen.

### Fixvertrag

Die vier Felder werden mit Bounds und Nullable-Vertrag in
`MonteCarloResponse` aufgenommen. Missing/invalid wird in UI und PDF als
`nicht verfügbar/blockiert`, niemals als null gerendert. Ein End-to-End-Test
muss einen nichtnulligen Enginewert durch Generate, Reload, JSON, UI und PDF
bis zur sichtbaren Zahl verfolgen.

## `DECUM-READINESS-001` – Der Reichweiten-Checklistenpunkt ist ein Ghost-Contract

### Beobachtung

`renderReadinessChecklist()` startet mit vier allgemeinen Punkten. Nur wenn
`allocation.decumulation.decumulation_mode` vorhanden ist, ergänzt es
`Reichweite bestaetigt` und vergleicht `runway_p10_year` mit
`longevity_horizon_years`.

`TargetAllocationGenerateResponse` enthält kein `decumulation`-Feld. Der
Backendcode besitzt zwar allgemeine Decumulation-Bezüge, aber keinen Producer
für ein `allocation.decumulation`-Responseobjekt und keine exakten
`runway_p10_year`-/`longevity_horizon_years`-Keys. Der Branch ist für reguläre
API-Antworten damit unerreichbar.

Sind die vier allgemeinen Punkte erfüllt, zeigt dieselbe Funktion:
`Meeting ist bereit fuer PDF und Signatur.` und
`Alles erledigt → PDF`. Das ist ausschließlich sichtbare Readiness-Copy, keine
technische Sperre: Bei offenen Punkten bleibt `Trotzdem drucken` verfügbar,
und beide Buttons rufen `printReport()` auf.

### Wirkung

Gerade im Ruhestandsfall kann die sichtbare Governance positiv sein, obwohl
keine P10-Reichweite geprüft wurde und die Depletion-Felder zusätzlich am
Schema verloren gehen. Dies erweitert `SIGN-ELIGIBILITY-001`.

### Fixvertrag

Der Backend-Response enthält einen versionierten DecumulationReadiness-
Vertrag mit:

- `applicable|not_applicable|missing|invalid`,
- Retirement-/Life-Course-Snapshot-ID,
- Withdrawal-Policy und Cashflow-/Pension-Snapshot-ID,
- P10-/P50-Runway und Horizon mit gemeinsamer Zeitbasis,
- Depletion-Definition, Simulation-/Run-ID und Model-Basis,
- Evidence-Hash und as-of.

Für applicable Ruhestandsfälle muss dieser Punkt obligatorisch sein. Missing
oder invalid muss Finalisierung, PDF, Signatur und Handoff serverseitig
blockieren.

## Ergänzende Methodikgrenzen der Depletion-Kennzahl

Auch nach reinem Schemafix ist die Kennzahl noch nicht vollständig
freigabefähig:

1. Depletion wird auf Advisory-SOLL/-IST-Pfaden bestimmt, während
   Total-Wealth-Pfade separat vorliegen.
2. Der Defizitfehler aus `DECUM-DEFICIT-001` wirkt vor der Ermittlung.
3. Pensionseinnahmen, Availability und Indexierung sind wegen der übrigen
   Findings nicht verlässlich.
4. Mortalität, Survivor und Estate sind wegen Runde 28 nicht kanalgleich.
5. Der Median bei gerader Anzahl betroffener Pfade ist der obere mittlere Wert,
   nicht der Mittelwert beider mittleren Werte; dies ist aktuell testgepinnt.
6. Der Kunden-PDF-Vertrag publiziert keine gleichwertige, snapshotgebundene
   Depletion-/Runway-Evidenz.

Der API-Feldfix ist daher notwendig, aber nicht hinreichend für die
Releasefreigabe.

## Remediation-Reihenfolge

### Phase 0 – Falsch-positive Publikation sofort stoppen

1. Missing Depletion als `unavailable`, nie als 0 Prozent rendern.
2. Decumulation-Readiness für applicable Mandate fail-closed erzwingen.
3. AHV-Vollfinanzierungsclaim ohne Benefit-Evidence entfernen.
4. Vorsorgevermögen ohne zeitliche Verfügbarkeit nicht zur heutigen Reserve
   zählen.
5. Gross/Tax-Metadaten ohne Reconciliation nicht als Steuerbeleg anzeigen.

### Phase 1 – Kanonisches Retirement-Income-Modell

1. PensionBenefit, PensionPosition, SpendingNeed und WithdrawalEvent trennen.
2. Person/Household/Survivor/Estate, Säule, Source, as-of und Evidenz binden.
3. Benefit-Start/-Ende, Indexierung und Kapital-/Renten-/Mischbezug definieren.
4. Goal- und Position-Referenzen als echte, mandategebundene FK-/Domain-
   Beziehungen validieren.
5. Legacywerte explizit als unknown/inert migrieren.

### Phase 2 – Gemeinsamer Zustandsautomat

1. Defizit, Liquidität, investierbare Assets und explizite Schuld in einem
   gemeinsamen State modellieren.
2. Positive Flows tilgen zuerst Defizit nach definierter Rangfolge.
3. Timingkonvention für Wachstum, Flow, Tax, Kosten und Rebalancing festlegen.
4. Optimizer und Reporting nutzen denselben Automaten oder eine formal
   reconciliable Approximation.

### Phase 3 – Immutable Snapshot und Kanalparität

1. `RetirementIncomeAndWithdrawalSnapshot` an Mandat, Client, TA,
   OptimizerRun, CMA, Policy, TaxModel und MortalityAndLifeCourseSnapshot
   binden.
2. Rohe Inputs und aufgelöste Jahres-/Periodenreihen separat hashen.
3. Depletion, Runway, Goal Funding und Reserve referenzieren dieselbe
   Snapshot-ID.
4. Generate, Reload, API, Electron, React, PDFs, Signatur und Handoff publizieren
   denselben Stand oder blockieren.

### Phase 4 – Abnahme

1. Unit-, Property- und Golden-Tests für jede Formel.
2. End-to-End-API-Tests mit Response-Model-Serialisierung.
3. Browser-/DOM-Tests für Missing, 0, 100 Prozent und Retirement-Readiness.
4. PDF-/Signatur-/Handoff-Golden- und Tampertests.
5. SQLite-/PostgreSQL-Parität, Migration und echte Race-Tests.
6. Erst danach Gesamtgate und Releaseentscheidung.

## Acceptance-Checkliste

- [ ] Pensionsbedarf und Pensionsleistung sind getrennte, typisierte Objekte.
- [ ] AHV/BVG/3a/1e/FZG reduziert nur mit konkretem Benefit den Bedarf.
- [ ] Teildeckung und Überdeckung werden sichtbar reconciliert.
- [ ] Person, Säule, Provider, Source und as-of sind Pflicht.
- [ ] Goal-Position-Links sind mandategebunden und referenziell valide.
- [ ] Bezugsalter, Bezugsform und Verfügbarkeit wirken periodengenau.
- [ ] Gesperrtes Vorsorgevermögen deckt keine frühere Reserve.
- [ ] Kapitalbezug wird nicht zusätzlich als Position und Cashflow doppelt gezählt.
- [ ] Pensionsindexierung wirkt oder ist sichtbar inert.
- [ ] Alle rechenwirksamen Felder ändern den Snapshot-Hash.
- [ ] Netto entspricht serverseitig reconciliert Brutto minus Tax-Komponenten.
- [ ] Gross/Tax ist nur für passende Kapitalereignisse zulässig.
- [ ] Steuer-Evidence ist an Regime, Parameter und Override gebunden.
- [ ] Tag-/Monatspräzision entspricht der tatsächlichen Periodenrechnung.
- [ ] Positive Zuflüsse tilgen zuerst bestehendes Defizit.
- [ ] Decision und Reporting besitzen dieselbe Defizitsemantik.
- [ ] Depletion-Felder überleben Generate und Reload unverändert.
- [ ] Missing Depletion erscheint niemals als 0 Prozent.
- [ ] Runway und Depletion haben dieselbe Snapshot-/Zeit-/Modellbasis.
- [ ] Applicable Decumulation erzwingt ein serverseitiges Readiness-Gate.
- [ ] Missing/invalid blockiert PDF, Signatur und Handoff.
- [ ] UI und PDF verwenden denselben Evidence-State.
- [ ] Legacyrows sind explizit unknown/unverified.
- [ ] SQLite und PostgreSQL erzwingen denselben Fachvertrag.
- [ ] Browser-, PDF-, Tamper-, Replay- und Race-Tests sind grün.
- [ ] Vollständiger Backend-/Frontend-/Electron-Gate ist grün.

## Claude-/GPT-Startcheckliste

Vor der Umsetzung muss Claude/GPT diese Reihenfolge einhalten:

1. Diesen Audit vollständig lesen.
2. Runde 28 sowie `MC-CASHFLOW-CURRENCY-001`,
   `GOAL-PUBLICATION-001`, `TAX-CONTEXT-001`,
   `SIGN-ELIGIBILITY-001` und die historischen `F2`, `F6` und `F7`
   mitlesen.
3. Keinen früheren Blocker allein durch diesen Audit als geschlossen markieren.
4. Zuerst Bedarf, Benefit, Position, Kapitalbezug und Withdrawal-Policy
   fachlich trennen.
5. Vor Schemaänderung Ownership, Availability, Payout und Legacy-Migration
   entscheiden.
6. Missing-Depletion-, Ghost-Readiness- und AHV-Falschclaims zuerst schließen.
7. Den bestehenden Cashflow-/Goal-Hash erweitern, nicht ersetzen.
8. Defizitverrechnung an einem gemeinsamen State-Machine-Testvektor festlegen.
9. Gross/Net/Tax serverseitig reconciliieren; UI-Berechnung allein genügt nicht.
10. Unterjährige Semantik explizit entscheiden; keine scheinpräzise Eingabe
    ohne wirksames Modell.
11. Depletion-End-to-End durch das echte FastAPI-Response-Model testen.
12. Readiness und Finalisierung auch serverseitig erzwingen.
13. Max-Pension-Spending nicht fälschlich als bestehende MC-SWR behandeln; die
    aktuelle deterministische Disclosure erhalten.
14. Erst nach Math-, API-, Browser-, PDF-, Snapshot-, Tamper-, Replay- und
    echten PostgreSQL-Tests einen Blocker schließen.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

```text
branch: codex/asset-allocation-stochastic-core
HEAD: 6ab26b33656971da9af34651053e19b2bf2edffe
visible tracked/untracked entries: 0
git status ACL warnings for historical pytest temp directories: 53
global clean claim: intentionally false
```

Die ACL-geschützten historischen `.pytest_tmp*`-/`.pytest-tmp*`-
Verzeichnisse wurden weder betreten noch verändert oder gelöscht. Dieser Audit
behauptet daher nur einen leeren sichtbaren Status, nicht globale Lesbarkeit
oder globale Sauberkeit.

### Isolierte Runtime-Reproduktionen

Alle acht Harnesses liefen direkt gegen importierte Produktfunktionen, ohne
Produktcode, Tests oder persistente Kundendaten zu verändern:

```text
R1 deficit recovery:
  engine_totals=[0,-100,50,65]
  economically_netted_expected_terminal=55

R2 arbitrary AHV need:
  reserve=(0,0)
  liability_kind=state_funded
  liability_target=0
  mc_success=100
  mc_funded_ratio=1.0
  mc_score=100

R3 pension value as immediate reserve:
  without_other_assets=(8000000,7000000)
  with_age63_pension_counted_unlocked=(8000000,0)

R4 API depletion filtering:
  four input fields
  zero output fields
  fields_survive=false

R5 withdrawal amount and timing:
  Expense net=100, gross=350, tax=30 accepted
  Jan series=[-100]
  Dec series=[-100]

R6 pension metadata snapshot:
  materially different pension metadata
  identical SHA-256 input hash

R7 pension position domain:
  arbitrary type/rate/age/payout accepted

R8 orphan goal link:
  linked_position_id=does-not-exist accepted
```

### Fokussierter Bestands-Gate

```text
command:
  python -m pytest
    tests/test_sprint_b_batch5.py
    tests/test_frontend_b3_pension_pillar.py
    tests/test_goals1_ahv_mc_path_consistency.py
    tests/test_sequence_of_returns_depletion.py
    tests/test_cashflow_timeline.py
    tests/test_cashflow_projection.py
    tests/test_cashflow_in_mc_integration.py
    tests/test_cashflow_annualization_properties.py
    tests/test_cashflow_summary_contract.py
    tests/test_cashflow_type_correction_contract.py
    tests/test_cashflow_editor_wiring_contract.py
    tests/test_goal_cashflow_ist_contract.py
    tests/test_frontend_goal_cashflow_ist_contracts.py
    tests/test_engine_reference_mandates.py
    tests/test_engine_input_sensitivity.py
    tests/test_optimizer_goal_liabilities.py
    tests/test_optimizer_solver.py
    tests/test_optimizer_phase6.py
    tests/test_optimizer_is_auto_activation.py
    tests/test_sprint_a_quick_wins.py
    tests/test_planning_assumption_data_classification_gate.py
    tests/test_wave13_planning_fx_bounds.py
    tests/test_aa10_max_drawdown_cashflow_neutral.py
    tests/test_aa6_annualized_return_depleted.py
    tests/test_aa4_year1_var_cashflow_neutral.py
    tests/test_per_path_tax_integration.py
    tests/test_tax_solver_wiring.py
    tests/test_wealth_cashflows_tax_estimate.py
    tests/test_wealth_cashflows.py
    tests/test_runtime_contracts.py
    tests/test_audit_z6_anchors.py
    -q
    --basetemp=C:\tmp\5eyes-round29-gate-20260907-1

result:
  521 passed in 168.41s
```

### Warum der grüne Gate die Findings nicht schließt

1. `test_sprint_b_batch5.py` und
   `test_goals1_ahv_mc_path_consistency.py` sichern die interne
   AHV-Vollfinanzierung, nicht den Benefit-Nachweis.
2. `test_sequence_of_returns_depletion.py` prüft den Engine-Dict, nicht das
   FastAPI-/Pydantic-Response-Model.
3. Cashflow-Timeline-Tests prüfen Jahresaggregation; kein Test fordert einen
   Unterschied zwischen Januar und Dezember.
4. Kein Test erzeugt zuerst Defizit, dann Überschuss und anschließend positive
   Rendite im Bucket-/Reportingpfad.
5. Input-Sensitivity-Tests decken die Pensionspositionsfelder und
   Pensionsindexierung nicht vollständig ab.
6. Frontend-Contracttests beweisen nicht, dass das Backend
   `allocation.decumulation` liefern kann.

### Nicht ausgeführte Prüfungen

- kein Browser-/DOM-Lauf gegen eine gestartete App;
- kein visueller PDF-Golden-Lauf;
- kein realer AHV-/BVG-/3a-Datensatz;
- keine echte PostgreSQL-Migration oder Concurrency-Prüfung;
- kein vollständiger Backend-/Frontend-/Electron-Gesamtgate;
- keine Steuerrechts- oder individuelle Leistungsberechnung.

Diese Grenzen schwächen die reproduzierten Code- und Schemafehler nicht. Sie
bleiben zusätzliche Voraussetzungen für eine spätere Freigabe.

## Dokumentationsmanifest und Commitvertrag

Diese Runde darf genau folgende fünf Dokumentationspfade verändern:

1. `docs/audits/2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Produktcode, Tests, Migrationen und historische ACL-Verzeichnisse bleiben
unverändert. Der Commit ist erst zulässig, wenn:

1. genau diese fünf Pfade im sichtbaren Status stehen,
2. `git diff --check` grün ist,
3. alle relativen Auditlinks auf existierende Dateien zeigen,
4. alle Codeanker auf dem auditierten Head auflösbar sind,
5. die neun neuen Finding-IDs zwischen Audit und Claude-Handoff exakt
   übereinstimmen,
6. der fokussierte Gate-Nachweis 521/521 lautet,
7. und eine unabhängige Read-only-QA keine unbelegte Schließung meldet.

## Releaseentscheidung

`BLOCKED_CONFIRMED_P1`.

Ein grüner Unit-Teststand, eine gespeicherte Vorsorgeposition, ein AHV-Badge,
ein intern berechneter Depletion-Wert oder ein 4/4-Reviewstatus ist kein
Freigabenachweis. Reale Pensionierungs-/Entnahmeberatung, positive
Runway-/Depletion-Claims, PDF, Signatur und Handoff dürfen auditseitig nicht
freigegeben werden, bis alle P1 dieses Audits und die referenzierten früheren
Blocker implementiert, kanalgleich nachgewiesen und auf der Zielumgebung
abgenommen sind. Der aktuelle Produktstand erzwingt diesen Governance-Hold
nicht vollständig serverseitig; genau das ist Teil von `DECUM-READINESS-001`.
