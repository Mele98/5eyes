---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-optimizer-policy-version-identity-activation-completeness-and-runtime-binding-followup-audit"
status_as_of: "2026-10-04"
audit_started_on: "2026-10-04"
audit_completed_on: "2026-10-04"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "0697cf696f3ae564eafd3107708435ed982490a8"
prior_cma_audit_path: "docs/audits/2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md"
prior_engine_config_audit_path: "docs/audits/2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md"
prior_policy_ab_audit_path: "docs/audits/2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md"
prior_admin_audit_path: "docs/audits/2026-06-10-admin-menu-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md"
audit_mode: "read_only_static_schema_model_router_engine_reference_resolver_recommendation_backtest_and_publication_review_plus_ephemeral_sqlite_api_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "optimizer-policy immutable identity, active-policy edits, target-allocation and recommendation provenance, engine and fee binding, house-matrix and building-block completeness, clone fidelity, activation transaction and runtime readiness"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 2
confirmed_prior_p1_extension_groups: 3
deterministic_ephemeral_probe_tests_passed: 3
focused_existing_backend_tests_passed: 136
focused_existing_tests_failed: 0
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "keep policy edits, activation, new strategy generation, recommendation regeneration and policy A/B publication blocked until policy versions are immutable aggregate snapshots and activation is guarded by an atomic completeness certificate; migrate or quarantine mutable legacy policy lineage, then bind policy version/content hash and actual runtime configuration to every allocation, run and publication"
---

# Optimizer-Policy-Versionierungs- und Aktivierungsintegritätsaudit

## Geltung, Quellenrangfolge und Abgrenzung

Dieser additive Folgeaudit dokumentiert die einundvierzigste Read-only-
Kontrollrunde des Asset-Allocation-/Stochastic-Core. Geprüft wurde der
unveränderte Repository-Head
`0697cf696f3ae564eafd3107708435ed982490a8`. Produktcode, Migrationen und
dauerhafte Tests wurden nicht verändert. Drei kurzlebige Audit-Probes wurden
ausgeführt und danach vollständig entfernt. Nach der Prüfung werden
ausschließlich die fünf Pfade des Dokumentationsmanifests angepasst.

Die Runde prüft den Policy-Lebenszyklus als fachliches Aggregate aus:

- `OptimizerPolicy`,
- vollständiger House Matrix,
- jurisdiktions-/universumsbezogenen Building Blocks,
- Engine- und Fee-Konfiguration,
- TargetAllocation-/RecommendationRun-Bindung sowie
- atomarer Aktivierung.

Eine Policy-ID ist nur dann ein belastbarer Auditanker, wenn ihr Inhalt nach
einer Entscheidung unveränderlich bleibt. Ein `is_current`-Flag ist nur dann
ein Readinessnachweis, wenn der gesamte aktivierte Modellbestand vor dem
Umschalten geprüft wurde.

## Deduplizierung zu bestehenden Findings

Keine bestehende Finding-ID wird geschlossen oder umbenannt.

- Der Admin-Menü-Audit vom 10.06.2026 verlangte bereits, aktive Policy-Edits
  zu blockieren oder automatisch zu klonen. Der aktuelle Guard schützt jedoch
  nur `PUT .../house-matrix`; das allgemeine Policy-PUT mutiert weiterhin die
  aktive Zeile unter derselben ID. Der neue Befund dokumentiert den dadurch
  konkret entstehenden FK-, Stale- und Mixed-Version-Schaden.
- `ENGCFG-SNAPSHOT-001` verlangt die tatsächlich wirksame eingefrorene
  Engine-Konfiguration. Dass `optimizer_engine` beliebigen Text akzeptiert,
  die Ausführung aber ausschließlich `settings.optimizer_mode` folgt und der
  beliebige Text als `RecommendationRun.optimizer_version` gespeichert wird,
  bestätigt und erweitert diesen bestehenden P1; dafür wird keine dritte neue
  ID gezählt.
- `BACKTEST-CONTEXT-001`, `STRESS-CONTEXT-001` und der Policy-A/B-Audit
  verlangen einen unveränderten Modellcontext. Der neue Befund liegt davor:
  Die referenzierte Policy-Identität selbst wird in-place umdefiniert.
- `COST-CONTEXT-001` beschreibt Live-Fee-Drift in Kostenevidence. Die hier
  gezeigte Policy-Mutation erklärt einen konkreten Upstream-Pfad, ist aber
  nicht auf Kosten beschränkt.
- Current-Anchor-Uniqueness verhindert zwei aktuelle Policy-Zeilen, beweist
  jedoch weder unveränderliche Versionen noch vollständige Aktivierbarkeit.
- Die Reference-Data-Fail-Closed-Tests schützen Mehrdeutigkeit und Non-CH-
  Fehlbestände. Sie verhindern weder eine leere CH-Policy noch den Verlust der
  Building Blocks beim Klonen.

Zwei neue Ursachen-IDs werden geführt:

- `POLICY-VERSION-IDENTITY-001`
- `POLICY-ACTIVATION-COMPLETENESS-001`

## Kurzurteil

Die Runde bestätigt **zwei neue release-blockierende P1**.

**`POLICY-VERSION-IDENTITY-001`:** Das allgemeine Admin-PUT darf eine aktive
Policy ändern. Vorher wird zwar eine Archivzeile angelegt, sie erhält aber
eine **neue** ID; anschließend werden Version, Gültigkeit, Caps,
`optimizer_engine`, Fee-Modell und Name der bisherigen aktiven Zeile unter
der **alten** ID mutiert. Bestehende `TargetAllocation.policy_id` und
`RecommendationRun.policy_id` bleiben deshalb formal FK-gültig, zeigen aber
danach auf Version 2 statt auf die tatsächlich verwendete Version 1. Der
echte Version-1-Snapshot ist unter einer anderen ID gespeichert und wird von
keinem bestehenden Run referenziert. House-Matrix- und Building-Block-Zeilen
werden überhaupt nicht auf die neue Archiv-ID kopiert; sie bleiben an der nun
mutierten Current-Zeile. Der vermeintliche Archivsnapshot ist daher kein
replayfähiges Policy-Aggregat. Weil dieselbe alte ID weiterhin current ist,
erkennen die Current-TA- und Recommendation-Gates den Policywechsel nicht als
Stale-Zustand. Moderne TA-Artefakte konservieren Targets und Constraints,
verhindern aber nicht, dass anschließend eine neue Recommendation mit den
alten TA-Constraints und den **neuen** Policy-Fee-/Engine-Angaben erzeugt wird.

**`POLICY-ACTIVATION-COMPLETENESS-001`:** Das Create-Schema erlaubt eine
leere House Matrix mit dem Kommentar, das Backend werde Default-Seeds
einsetzen. Der Create-Endpoint legt in diesem Fall jedoch weder House-Matrix-
noch Building-Block-Zeilen an und kann die Policy trotzdem sofort aktivieren.
Die bisher funktionierende Policy wird davor deaktiviert. Runtime-Seeding
greift nur, wenn **gar keine** Current-Policy existiert; eine vorhandene, aber
unvollständige Current-Policy wird unverändert zurückgegeben. Der erste
Strategielauf endet dann an `HouseMatrix unvollstaendig`. Zusätzlich kopiert
der offizielle Clone-Endpoint ausschließlich House-Matrix-Zeilen, aber keine
Building Blocks. Ein daraus aktivierter Klon besitzt zwar Bänder, verliert
aber seine Risikofraktionen und Jurisdiktions-/Universumsbasis; strikte
Sub-CMA-/Building-Block-Verbraucher blockieren oder laufen je nach Altpfad auf
abweichender Defaultbasis. Aktivierung besitzt keinen Readiness-Preflight und
kein Zertifikat für das Policy-Aggregat.

## Findings-Register

| ID | Priorität | Status | Verbindlicher Vertrag |
|---|---:|---|---|
| `POLICY-VERSION-IDENTITY-001` | P1 | bestätigt | Jede freigegebene Policy-Version ist ein unveränderliches Aggregate mit eigener stabiler ID und Content-Hash; bestehende Allocations/Runs bleiben exakt auf diese Version gebunden, während ein Rollover die alte Current-TA sichtbar stale macht |
| `POLICY-ACTIVATION-COMPLETENESS-001` | P1 | bestätigt | Create/Clone/Activate darf erst atomar current werden, wenn Policy, vollständige House Matrix, Building Blocks je erforderlichem Scope, Engine/Fee-Schema und CMA-Kompatibilität gemeinsam validiert und zertifiziert sind; ein Fehlschlag erhält die bisherige Current-Policy |

Bestätigte Erweiterungen bestehender P1:

| Bestehende ID | Erweiterung dieser Runde |
|---|---|
| `ENGCFG-SNAPSHOT-001` | Freier `optimizer_engine`-Text steuert die Ausführung nicht, wird aber als `optimizer_version` persistiert |
| `BACKTEST-CONTEXT-001` / `STRESS-CONTEXT-001` | Eine Policy-ID beweist keinen unveränderten Inhalt, solange die referenzierte Zeile in-place mutiert werden kann |
| `COST-CONTEXT-001` | Neue Recommendation-/Kostenpfade können alte TA-Entscheidungsartefakte mit dem neuen Fee-Modell derselben mutierten Policy-ID verbinden |

## Reproduktion A: bestehender Run wird auf eine andere Version umgebunden

Ein echter SQLite-/FastAPI-Probe legte an:

- aktive Policy `U103-Test`, ID `P`, Version 1,
- `max_real_estate_bps=2000`, `optimizer_engine=goal_based_v1`,
  `fee_model_json={"fee_bps":50}`,
- bestehenden RecommendationRun mit `policy_id=P`, eingefrorenem
  `optimizer_version=goal_based_v1` und Fee 50.

Danach wurde der echte Endpoint aufgerufen:

```http
PUT /admin/optimizer-policies/P
{
  "optimizer_engine": "unregistered-engine-v99",
  "max_real_estate_bps": 9000,
  "fee_model_json": "{\"fee_bps\":999}"
}
```

Ergebnis:

```text
HTTP status                         200
existing run.policy_id              P
row at id P.version                 2
row at id P.max_real_estate_bps     9000
row at id P.optimizer_engine        unregistered-engine-v99
row at id P.fee_model_json          {"fee_bps":999}
archive.version                     1
archive.id == run.policy_id         false
run.optimizer_version               goal_based_v1
run.fee_assumptions_json             {"fee_bps":50}
```

Der Archivinhalt existiert, aber die historische FK-Verknüpfung zeigt nicht
darauf. Auch Matrix und Building Blocks bleiben auf `P`; die neue Archiv-ID
besitzt keine Kindzeilen und kann die alte Policy nicht eigenständig replayen.
„FK-Integrität“ ist hier nur syntaktisch; semantisch wurde die referenzierte
Policy umgeschrieben.

## Reproduktion B: Stale-Erkennung wird umgangen

Der Current-Payload- und Recommendation-Pfad prüft, ob die von der TA
referenzierte Policy noch `is_current=1` ist. Bei einem echten neuen
Policy-Rollover erhält die neue Version eine neue ID; eine TA auf der alten
ID wird damit korrekt stale und muss neu berechnet werden.

Beim In-place-PUT gilt dagegen:

```text
TA.policy_id = P
P.is_current vor PUT = 1
P.is_current nach PUT = 1
P.version vor PUT = 1
P.version nach PUT = 2
```

Das Gate sieht weiterhin dieselbe current ID. Der persistierte
`allocation_context_hash` bindet nur `policy_id`, nicht Policyversion oder
Policy-Content-Hash. `effective_constraints_json` schützt zwar die alten
Targets/Bänder und die darin gespeicherten Risikokoeffizienten, erkennt die
Policy-Umdefinition aber nicht.

Der nachgelagerte Recommendation-Pfad lädt `allocation.policy_id`, akzeptiert
sie wegen `is_current=1`, baut den Target-Payload aus den persistierten alten
TA-Artefakten und speichert anschließend:

```text
RecommendationRun.optimizer_version = policy.optimizer_engine
RecommendationRun.fee_assumptions_json = policy.fee_model_json
```

Damit ist eine Mixed-Version-Entscheidung erreichbar: alte Allokationsbasis,
neue Policy-Metadaten und neue Gebühren unter derselben Policy-ID.

## Reproduktion C: leere Policy wird erfolgreich aktiviert

Ausgeführt wurde:

```http
POST /admin/optimizer-policies?activate=true
{"policy_name":"Round41 Empty Active"}
```

Ergebnis:

```text
HTTP status                         201
new policy.is_current              1
active HouseMatrix rows            0
active BuildingBlock rows          0
ensure_runtime_reference_data      returns this policy unchanged
HouseMatrix score 5                ValueError: HouseMatrix unvollstaendig fuer Score 5
previous working policy            is_current=0
```

Das ist kein bloßer Admin-Anzeigefehler. Das Aktivieren ersetzt den
funktionierenden globalen Modellanker und macht die Strategieerzeugung bis
zur manuellen Reparatur oder Rückaktivierung unbenutzbar.

## Reproduktion D: Klon verliert Building Blocks

Ein Policy-Quellstand mit aktivem Building Block
`Aktien/Aktien Global`, `risky_fraction_bps=4321` wurde über den echten
Clone-Endpoint geklont:

```http
POST /admin/optimizer-policies/{source_id}/clone
```

Ergebnis:

```text
source BuildingBlock rows           1
clone BuildingBlock rows            0
clone HouseMatrix behavior          rows are copied when present
activation preflight                none
```

Der Code bestätigt die Asymmetrie: `source_rows` fragt nur `HouseMatrix` ab;
für `BuildingBlock` existiert im Clone-Pfad keine Kopierschleife. Bei der
Default-CMA führt ein leerer Building-Block-Bestand bereits in der
Sub-CMA-Universe-Prüfung zu einem Konflikt; spätestens die Anreicherung der
Sub-Allokationen verlangt für jede verwendete Subklasse eine gültige
Risikofraktion. Für Non-CH blockiert der Resolver fehlende exakte
Jurisdiktionszeilen ausdrücklich. Der Clone ist somit keine vollständige
Policy-Version.

## Reproduktion E: deklarierte Engine ist nicht die ausgeführte Engine

Das Schema akzeptiert `optimizer_engine` als beliebigen String. Der Probe
persistierte `unregistered-engine-v99` mit HTTP 200. Die tatsächliche
Ausführungswahl erfolgt jedoch an anderer Stelle ausschließlich über:

```python
optimizer_mode = settings.optimizer_mode
run_stochastic = optimizer_mode in {"stochastic", "shadow_stochastic"}
apply_stochastic = optimizer_mode == "stochastic"
```

Später wird der freie Policy-String trotzdem als
`RecommendationRun.optimizer_version` gespeichert. Das ist keine neue ID,
sondern eine direkte Bestätigung von `ENGCFG-SNAPSHOT-001`: deklarierte
Version und tatsächlich ausgeführte Methode sind nicht durch einen
registrierten, gehashten Runtimevertrag verbunden.

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Archiv erhält neue ID und kopiert nur skalare Policyspalten | `5eyes-backend/routers/allocation.py:67-99` |
| Aktives Policy-PUT archiviert und mutiert dieselbe ID auf Version +1 | `5eyes-backend/routers/allocation.py:1113-1147` |
| Nur House-Matrix-PUT blockiert aktive Policy | `5eyes-backend/routers/allocation.py:1149-1173` |
| TA bindet nur `policy_id`, keine Policyversion/-hash | `5eyes-backend/models/allocation.py:76-107` |
| Context-Hash enthält `policy_id`, aber keinen Policy-Content-Hash | `5eyes-backend/services/portfolio_engine.py:3963-3988` |
| Context-Verifikation rekonstruiert erneut nur mit `allocation.policy_id` | `5eyes-backend/services/portfolio_engine.py:4338-4364` |
| Current-TA-Gate prüft nur Existenz und `is_current` | `5eyes-backend/routers/allocation.py:161-171` |
| Recommendation akzeptiert Policy derselben ID als current | `5eyes-backend/services/portfolio_engine.py:6479-6491` |
| Run übernimmt Live-Engine-/Fee-Felder aus der Policy | `5eyes-backend/services/portfolio_engine.py:6561-6579` |
| Cost Disclosure löst Run-Policy erneut live per ID auf | `5eyes-backend/services/cost_disclosure.py:74-83` |
| Schema behauptet bei leerer Matrix Backend-Default-Seeds | `5eyes-backend/schemas/allocation.py:451-477` |
| Create legt nur übergebene House-Matrix-Zeilen und nie Building Blocks an | `5eyes-backend/routers/allocation.py:1053-1110` |
| Aktivierung besitzt keinen Aggregate-Readiness-Preflight | `5eyes-backend/routers/allocation.py:1193-1230` |
| Clone kopiert ausschließlich House Matrix | `5eyes-backend/routers/allocation.py:1232-1310` |
| Runtime seedet Matrix/Building Blocks nur beim Erzeugen einer fehlenden Policy | `5eyes-backend/services/portfolio_engine.py:1630-1666` |
| Vorhandene unvollständige Policy wird unverändert zurückgegeben | `5eyes-backend/services/portfolio_engine.py:1667-1731` |
| Fehlende Scoreabdeckung blockiert erst im Strategielauf | `5eyes-backend/services/portfolio_engine_house_matrix.py:1217-1231` |
| CH erlaubt leere Building-Block-Auflösung als Bestandsfall | `5eyes-backend/services/jurisdiction/resolve.py:229-251` |
| Sub-Allokation verlangt später strikt eine Risikofraktion je Subklasse | `5eyes-backend/services/portfolio_engine_house_matrix.py:318-352` |
| Tatsächlicher Solvermodus stammt aus globalen Settings | `5eyes-backend/services/portfolio_engine.py:3137-3139` |

## Warum bestehende Schutzmechanismen nicht genügen

### Der Archive-Snapshot ist nicht referenziert

Der alte Inhalt ist physisch vorhanden. Ohne Repointing oder eine von Anfang
an immutable Version-ID beweist jedoch kein bestehender Foreign Key, welche
Archivzeile zu einem Run gehört. Namen und Versionsnummern sind nicht global
eindeutig genug, um diese Beziehung nachträglich belastbar zu erraten. Zudem
liegen House Matrix und Building Blocks weiter unter der mutierten ID; der
skalare Archivdatensatz allein ist kein rekonstruierbares Aggregate.

### Effektive Constraints schützen nur einen Teil

Moderne TAs speichern Sub-Allokationen, Bounds, Risikobudget und Context-Hash.
Das verhindert einige numerische Rebuild-Drifts. Nicht gebunden sind aber die
Policyversion, ihr vollständiger Content-Hash, Fee-/Enginevertrag und die
vollständige Policy-Kindmenge. Außerdem bleibt der Stale-Check wirkungslos,
wenn dieselbe ID current bleibt.

### Ein grünes `is_current` ist kein Readinesszertifikat

Die DB-Unique-Constraint garantiert höchstens eine aktuelle Policy. Sie sagt
nichts über Scoreabdeckung, Building-Block-Coverage, Jurisdiktion, Universum,
Engine-Registry, Fee-JSON oder CMA-Kompatibilität aus.

### Runtime-Autoseeding heilt keine Teilbestände

Das Seeding ist bewusst nur ein Entwicklungsbootstrap bei komplett fehlender
Policy. Es ergänzt keine vorhandene unvollständige Policy. Genau deshalb ist
der Schema-Kommentar zum leeren Create falsch und darf nicht als Vertrag
verwendet werden.

## Verbindlicher Lösungsweg für Claude

### 1. Policy-Versionen unveränderlich machen

- Jede fachliche Änderung erzeugt eine neue `OptimizerPolicy`-Zeile mit neuer
  ID; freigegebene oder bereits referenzierte Zeilen sind append-only.
- Eine stabile `policy_family_id`, monotone Version, `parent_policy_id`,
  Status und kanonischer `policy_content_hash` machen die Lineage explizit.
- House Matrix, Building Blocks, Enginekonfiguration und Fee-Modell gehören
  zum selben versionierten Aggregate und in denselben Hash.
- DB-Trigger beziehungsweise Berechtigungen verhindern In-place-Updates an
  aktivierten/referenzierten Versionen, nicht nur der API-Guard.
- Ein Update auf einer aktiven Policy ist entweder 409 mit „zuerst klonen“
  oder atomar `clone -> edit draft`; niemals Mutation derselben ID.
- Bestehende Runs/TAs bleiben auf ihrer alten ID. Ein Rollover auf neue ID
  macht eine aktuelle TA sichtbar stale und erzwingt Neuberechnung vor einer
  neuen Recommendation.

### 2. Einen Policy-Aggregate-Validator bauen

Ein gemeinsamer `validate_policy_candidate()` muss Create, Clone, Activate,
Import, Migration und Runtime-Preflight speisen. Er prüft mindestens:

- exakt lückenlose und nicht überlappende Scoreabdeckung 1..10;
- Banddomänen, Summen, min/target/max und Policy-Cap-Kompatibilität;
- vollständige aktive Building Blocks je erforderlicher Jurisdiktion und je
  explizitem Investmentuniversum;
- eindeutige Asset-/Sub-Asset-/Universe-/Jurisdiction-Schlüssel;
- `risky_fraction_bps` und alle verwendeten Risikokoeffizienten;
- vollständige Übereinstimmung mit Sub-CMA-Labels und Sub-Allokationsplan;
- registrierte Engine-ID plus exakte ausführbare Version/Settings;
- strikt typisiertes Fee-Modell;
- keine provisorischen Daten für einen finalen Aktivierungsstatus, sofern die
  Governance dies nicht explizit als getrennten Status erlaubt.

### 3. Aktivierung atomar und fail-closed machen

- Candidate vollständig validieren, **bevor** die bisherige Current-Policy
  deaktiviert wird.
- Aktivierung, Deaktivierung und Zertifikat in einer Transaktion unter Lock/
  CAS durchführen.
- Bei jedem Fehler bleibt die bisherige Current-Policy unverändert aktiv.
- Persistiere ein `PolicyActivationCertificate` mit Content-Hash,
  Validatorversion, Scope-Coverage, Zeit, Actor und Ergebnis.
- Production Runtime akzeptiert nur eine aktuelle Policy, deren Content-Hash
  zum gültigen Zertifikat passt.

### 4. Create und Clone semantisch eindeutig machen

- Leeres Create entweder 422 zurückweisen oder explizit aus einer benannten,
  versionierten Template-Policy **das vollständige Aggregate** kopieren.
- Den falschen Default-Seed-Kommentar entfernen; nie implizit eine nicht
  ausgeführte Reparatur versprechen.
- Clone kopiert House Matrix **und** Building Blocks samt Universum,
  Jurisdiktion, Provisorik-, Rollen- und Risikofeldern.
- Alternativ separate Clone-Modi anbieten, deren unvollständiger Draftstatus
  sichtbar ist und niemals aktivierbar bleibt.

### 5. Runtime- und Evidence-Bindung schließen

An TA, OptimizerRun, RecommendationRun, Sensitivity, Backtest, Stress und jede
Publikation gehören mindestens:

- Policy-ID, Family-ID, Version und Content-Hash,
- House-Matrix-/Building-Block-Manifesthash,
- tatsächliche Engine-ID, Code-/Modellversion und wirksame Settings,
- Fee-Model-ID/Version/Hash,
- Activation-Certificate-ID,
- Scope aus Jurisdiktion, Tenant und Investmentuniversum.

Der tatsächlich ausgeführte Modus darf nicht aus globalen Live-Settings
stammen, während ein unabhängiger Policy-Text als Version publiziert wird.
Entweder steuert ein validierter Policyvertrag die Ausführung oder die Policy
referenziert unveränderlich den externen Runtimekonfigurationssnapshot.

### 6. Legacy-Migration

- Alle Policy-Familien auf wiederverwendete IDs und Versionen scannen.
- Archive anhand Auditlog, Zeitintervallen, Runs und vorhandener Snapshots
  bestmöglich zuordnen; keine unsichere Zuordnung als sicher deklarieren.
- Allocations/Runs mit nicht beweisbarer Policyversion quarantänisieren oder
  aus vollständigen Inputevidenzen replayen.
- Unvollständige Current-Policies nicht automatisch mit heutigen Defaults
  auffüllen; entweder gegen eine freigegebene Quelle reparieren oder sperren.
- Nach Migration Content-Hash und Zertifikat neu bilden und alle abhängigen
  Publikationen invalidieren beziehungsweise neu erzeugen.

## Zuerst zu materialisierende rote Tests

### Immutable Identity

1. PUT auf aktive Policy mutiert niemals dieselbe ID;
2. PUT auf bereits referenzierte historische Policy ist blockiert;
3. neue Version erhält eigene ID, Family-ID, Parent-ID und monotone Version;
4. alter RecommendationRun löst weiterhin exakt Version 1 auf;
5. alter TargetAllocation-Context-Hash bindet Version und Policy-Content-Hash;
6. Rollover macht TA auf alter Policy vor neuer Recommendation stale;
7. direkte DB-Mutation einer aktivierten/referenzierten Version scheitert;
8. Concurrent Edit/Activate erzeugt keine verlorene oder doppelte Version.

### Aggregate und Activation

9. leeres Create mit `activate=true` ergibt 409/422 und erhält die alte
   Current-Policy;
10. fehlender Score, Lücke, Overlap und doppelte aktive Row blockieren;
11. fehlende Building Blocks blockieren CH und Non-CH vor Deaktivierung der
    alten Policy;
12. fehlende Jurisdiktions- oder Universe-Coverage blockiert präzise;
13. ungültige Risikofraktion, Fee-JSON oder Engine-ID blockiert;
14. Sub-CMA-Label ohne aktiven Building Block und umgekehrt blockiert;
15. Clone kopiert alle Building-Block-Felder byte-/semantikgleich;
16. Clone-Hash unterscheidet sich erst nach einer echten Draftänderung;
17. Aktivierungsfehler rollt vollständig zurück;
18. zwei parallele Aktivierungen enden deterministisch mit exakt einer
    zertifizierten Current-Policy.

### Runtime und Evidence

19. tatsächlicher Solvermodus entspricht dem gebundenen Enginevertrag;
20. unbekannter `optimizer_engine`-String wird nicht gespeichert;
21. Mutation von Policy, Matrix, Building Block, Engine oder Fee ändert den
    Content-Hash;
22. TA, OptimizerRun und RecommendationRun tragen dieselbe Policyversion und
    denselben Hash;
23. neue Recommendation kombiniert nie alte TA-Artefakte mit neuem Fee-/
    Enginevertrag;
24. Current-Rebuild, Sensitivity, Stress und A/B verwenden denselben Scope;
25. Policy-A/B vergleicht zwei immutable Aggregate statt Live-Kindtabellen;
26. UI, PDF, Signed Artifact und Handoff zeigen dieselbe Version/Engine/Fee-
    Basis;
27. fehlendes oder nicht passendes Activation Certificate blockiert Runtime;
28. Legacy-Mixed-Version-Evidence wird sichtbar quarantänisiert.

## Verifikation dieser Audit-Runde

Zuerst wurden drei kurzlebige, danach entfernte Audit-Probes gegen echte
SQLite-/FastAPI-/Servicepfade ausgeführt:

1. Run-FK nach aktivem Policy-PUT,
2. leeres `create?activate=true` plus Runtime-/House-Matrix-Auflösung,
3. Building-Block-Verlust beim echten Clone-Endpoint.

Alle drei Probes waren grün, das heißt: Die erwarteten Gegenbeispiele wurden
deterministisch bestätigt.

Danach liefen die angrenzenden Bestands-Suites:

```powershell
python -m pytest -q --disable-warnings `
  tests/test_optimizer_policy_archive.py `
  tests/test_current_anchor_uniqueness.py `
  tests/test_reference_data_fail_closed_gates.py `
  tests/test_risk_matrix_data_foundation.py `
  tests/test_backtest_ab.py `
  tests/test_asset_allocation_reference_integrity_edges.py `
  tests/test_asset_allocation_current_integrity_contracts.py `
  tests/test_asset_allocation_remaining_integrity_edges.py `
  tests/test_optimizer_production_contract.py
```

Ergebnis: **136 passed**, 0 failed, 99,87 Sekunden. Zusammen mit den drei
einmaligen Probes wurden 139 unterschiedliche Checks ausgeführt.

Die grünen Bestandstests bestätigen Archive-Existenz, gleiche ID als bewusstes
Sollverhalten, House-Matrix-Editguard, Current-Uniqueness und zahlreiche
Allocation-Context-Invarianten. Sie beweisen damit gerade nicht die neuen
Verträge: `test_put_policy_preserves_id_for_fk_integrity` schreibt die
semantisch problematische ID-Wiederverwendung ausdrücklich fest; kein
Bestandstest verlangt, dass ein Clone Building Blocks kopiert oder dass eine
Aktivierung Aggregate-Readiness nachweist.

Nicht ausgeführt wurden vollständige Backend-/Frontend-Suites, echte Browser-
E2E, PostgreSQL-Concurrency/Trigger, Electron-Packaging, PDF-Pixelvergleich
und Zielumgebungs-Replay. Diese gehören zur Implementierungsabnahme.

## Definition of Done

Der Release-Hold dieser Runde kann erst aufgehoben werden, wenn:

1. beide neuen Finding-IDs durch rote Vorher-/grüne Nachher-Tests geschlossen
   sind;
2. aktivierte und referenzierte Policy-Versionen immutable sind;
3. jede Version eigene ID, Family-/Parent-Lineage und Content-Hash trägt;
4. House Matrix, Building Blocks, Engine und Fee-Modell ein gemeinsames
   versioniertes Aggregate bilden;
5. Aktivierung vor Deaktivierung der alten Policy vollständig validiert und
   atomar zertifiziert wird;
6. Create/Clone keine still unvollständigen aktivierbaren Policies erzeugt;
7. Rollover alte Current-TAs zuverlässig stale macht;
8. ausgeführter Solvermodus und publizierte Engineversion identisch gebunden
   sind;
9. TA, Runs, Backtests, Sensitivity, Stress und alle Publikationskanäle exakt
   dieselbe Policy-Evidence verwenden;
10. Legacy-Mixed-Versionen und unvollständige Policies repariert, replayt oder
    quarantänisiert sind; und
11. fokussierte, vollständige, Browser-, Electron-, PDF-, PostgreSQL- und
    Zielumgebungs-Abnahmen grün sind.

## Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen durch die Runde verändert werden:

1. `docs/audits/2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`
