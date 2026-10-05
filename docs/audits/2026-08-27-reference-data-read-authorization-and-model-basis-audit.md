---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-reference-data-read-authorization-and-model-basis-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "63a0fd8256f8d675720bde2b6c033b976a01bcd7"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-advisory-workflow-and-temporal-integrity-audit.md"
prior_release_audit_commit: "63a0fd8256f8d675720bde2b6c033b976a01bcd7"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-reference-data-read-authorization-and-model-basis-audit.md"
audit_mode: "read_only_static_route_and_schema_inventory_isolated_http_reproductions_frontend_callgraph_and_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "authenticated client-role access to advisor/reference endpoints, cross-tenant CMA selection, and jurisdiction-correct Building-Block explanation in the active allocation UI"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 95
focused_adjacent_tests_failed: 0
required_next_action: "separate client-portal and staff read authorities, derive tenant and jurisdiction scope server-side, and make every Building-Block explanation consume the exact resolved or persisted allocation model basis"
---

# Referenzdaten-Leserechte und Modellbasisintegrität

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die elfte Read-only-Kontrollrunde auf
Repository-Head `63a0fd82`. Er ergänzt, ersetzt aber nicht:

1. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
2. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
3. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
4. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
5. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
6. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
7. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
8. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
9. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
10. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
11. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die elf vorgenannten Dokumente in dieser
Reihenfolge. Ein erfolgreich authentifizierter Request ist kein Nachweis, dass
die Rolle den Endpoint oder den vom Request gewählten Tenant-Scope lesen darf.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Zwei weitere P1-Verträge sind offen:

1. Ein Benutzer mit `role='client'` ist außerhalb des absichtlich eng
   begrenzten `/client-portal` auf mehrere interne Berater-/Referenzendpoints
   zugelassen. Der stärkste Repro war ein Client aus `firm-a`, der über
   `GET /capital-market-assumptions/current?jurisdiction=DE&tenant_id=firm-b`
   die tenantprivate CMA von `firm-b` einschließlich interner Quelle, Notizen,
   Status, Modellmomenten und Tenant-ID mit HTTP 200 erhielt. Derselbe Principal
   konnte Optimizer-Policies, House-Matrix, Building Blocks, den globalen
   Produktkatalog und tenantinterne Protokolltexte lesen.
2. `GET /building-blocks/current` liefert ungefiltert alle aktiven Bausteine der
   global aktuellen Policy. Mandat, Tenant, Jurisdiktion und explizites
   Investmentuniversum fehlen; das Response-Schema blendet die Jurisdiktion
   zusätzlich aus. Das aktive Cockpit lädt genau diesen Live-Datensatz parallel
   zu einer konkreten Mandatsallokation und zeigt ihn als Building-Block-
   Referenz. Damit kann ein CH- oder DE-Mandat eine gemischte beziehungsweise
   vom verankerten Solverkontext abweichende Modellbasis erklären.

Der erste Befund vertieft `AUTH-TEN-06` und `TEN-COMP-001`, ist aber eine neue,
konkret reproduzierte **Read-Authorization-/Object-Scope-Fläche**. Der zweite
Befund ist kein Datenexpositionsduplikat: Er betrifft die fachliche
Erklärbarkeit und Replaytreue einer bereits erzeugten Allocation.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `REF-READ-001` | P1 | offen | Client-Portal-Principals dürfen ausschließlich die explizit freigegebenen, an ihre eigene Client-Akte gebundenen Portalprojektionen lesen; Berater-, Admin-, Policy-, CMA-, House-, Produkt- und Protokollbibliotheken besitzen eine explizite Rollen- und serverseitig abgeleitete Tenantgrenze |
| `REF-BASIS-001` | P1 | offen | Jede mandatsbezogene Building-Block-Anzeige stammt aus exakt derselben jurisdiktions-, universums-, Policy- und Snapshotauflösung wie die verankerte Allocation; ungefilterte Live-Referenzdaten dürfen keinen Solverkontext erklären |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Client-Portal als bewusst enge Read-only-Sicht | `5eyes-backend/routers/client_portal.py:1-16`, `:52-116` |
| allgemeine Auth akzeptiert auch `client` | `5eyes-backend/services/auth.py:145-243` |
| getrennte Client- und Advisor-Gates | `5eyes-backend/services/auth.py:269-272`, `:482-494` |
| House-/Policy-/Building-Block-/CMA-Read mit bloßem `get_current_user` | `5eyes-backend/routers/allocation.py:306-393` |
| historischer Policy-Read mit bloßem `get_current_user` | `5eyes-backend/routers/allocation.py:837-854` |
| requeststeuerbarer Non-CH-Tenant-CMA-Resolver | `5eyes-backend/services/jurisdiction/resolve.py:80-140` |
| kanonischer jurisdiktionsfähiger Building-Block-Resolver | `5eyes-backend/services/jurisdiction/resolve.py:143-270` |
| ungescopte Building-Block-Response ohne `jurisdiction` | `5eyes-backend/schemas/allocation.py:1023-1036` |
| CMA-Response mit internen Feldern und `tenant_id` | `5eyes-backend/schemas/allocation.py:704-776` |
| Policy-Response mit Fee-Modell und Notizen | `5eyes-backend/schemas/allocation.py:510-525` |
| Produktkatalog-Read mit bloßem `get_current_user` | `5eyes-backend/routers/review.py:1107-1179` |
| Protokollbibliothek-Read mit bloßem `get_current_user` | `5eyes-backend/routers/protocol_bausteine.py:132-163` |
| vollständige Protokollantwort inklusive `content_md` | `5eyes-backend/schemas/protocol_bausteine.py:23-34` |
| Cockpit lädt ungescopte Bausteine neben Mandatspayload | `5eyes-electron/frontend/5eyes_v2.html:21417-21443`, `:21555-21577` |
| Cockpit rendert Asset/Subasset/Universum/Risky-Fraction ohne Scope | `5eyes-electron/frontend/5eyes_v2.html:7502-7506` |

## `REF-READ-001` – Client-Rolle liest interne und fremde Referenzdaten

### Ist-Zustand

`get_current_user` authentifiziert den Token und setzt den Datenbank-
Tenantkontext, beschränkt aber die fachliche Rolle nicht. Genau dafür existieren
`require_client`, `require_advisor`, `require_admin` und `require_super_admin`.
Der Client-Portal-Router beschreibt seinen Vertrag ausdrücklich als eigene,
mandatgebundene Read-only-Sicht und erklärt Admin-Tabellen als nicht exposed.

Mehrere interne GET-Routen verwenden dennoch nur `get_current_user`:

- aktuelle und historische Optimizer-Policies;
- House-Matrix-Band;
- aktuelle Building Blocks;
- aktuelle CMA mit frei wählbarer Jurisdiktion und `tenant_id`;
- vollständiger Produktkatalog des eigenen/globalen Scopes;
- Protokollbausteine des eigenen/globalen Scopes.

Der Non-CH-CMA-Resolver behandelt `tenant_id` fachlich als gewünschte
Override-ID. Die Route leitet diesen Wert nicht aus dem Principal oder einem
autorisierten Mandat ab und prüft keine Plattformrolle. Da die CMA selbst keine
mandatsgebundene Ownership-Prüfung durchläuft, reicht ein fremder Identifier für
den tenantprivaten Treffer.

### Ausgeführte HTTP-Reproduktionen

In einer isolierten SQLite-Datenbank wurde ein aktiver Benutzer
`role='client', tenant_id='firm-a'` authentifiziert. Für `firm-b` lag eine
tenantprivate DE-CMA vor. Der echte FastAPI-Request ergab:

```text
GET /capital-market-assumptions/current?jurisdiction=DE&tenant_id=firm-b
HTTP 200

id=cma-b
tenant_id=firm-b
assumption_set_name=Firm B confidential
source=IC paper
notes=internal only
equity_home_return_bps=987
```

Eine zweite HTTP-Reproduktion mit demselben Client-Principal ergab:

```text
GET /optimizer-policies/current    -> 200, notes="IC confidential"
GET /optimizer-policies            -> 200, historische interne Policy
GET /building-blocks/current       -> 200, CH- und DE-Zeilen gemeinsam
GET /house-matrix/5                -> 200, max_risk_cap_bps=7777
GET /products                      -> 200, Provider/ISIN/TER/Exposures/Tenant-ID
GET /protocol-bausteine            -> 200, content_md="CONFIDENTIAL INTERNAL WORDING"
```

Die Reproduktion hat keine Produkt-, Test- oder persistente Workspace-Datei
verändert.

### Risiko

- Ein Kundenlogin überschreitet die dokumentierte Portalgrenze und erhält
  proprietäre IC-/Optimizer-/Produkt-/Protokollinformationen.
- Über den frei gewählten CMA-Tenantparameter entsteht ein direkter
  Cross-Tenant-Read unabhängig von der Client-Aktenbindung.
- Interne Notizen, Quellen, Fee-Modelle, Berechnungsmetadaten und
  Protokollformulierungen werden in unverengten Response-Schemas übertragen.
- Ein späteres UI-Verbergen oder Nichtverlinken der Routen schützt nicht gegen
  direkte HTTP-Aufrufe mit gültigem Bearer-Token.

### Verbindlicher Fixvertrag

1. Eine zentrale, explizite **Staff-Read-Authority** definiert die zulässigen
   Rollen. `client` darf außerhalb eigener Auth-/Recovery- und
   `/client-portal`-Projektionen keine Berater-/Referenzbibliothek lesen.
2. Jede betroffene Route verwendet die enge Authority; unbekannte Rollen
   scheitern ebenfalls fail-closed. UI-Sichtbarkeit ist kein RBAC-Ersatz.
3. Tenant- und Jurisdiktionsscope werden aus Principal und autorisiertem Mandat
   abgeleitet. Ein normaler Tenantnutzer darf `tenant_id` nie frei setzen.
   Cross-Tenant-Scope ist ausschließlich einer ausdrücklichen Plattformrolle
   mit eigener Auditspur vorbehalten.
4. Für advisor-facing Reads wird tenantprivate plus bewusst firmwide/global
   aufgelöst; fremde Tenantzeilen bleiben 404/403. CH-/DE-Resolversemantik und
   Committee-Status bleiben fachlich fail-closed.
5. Response-Schemas folgen Least Privilege. Interne Notizen, `source_detail`,
   `computed_by`, Tenant-IDs oder Fee-Modelle werden nur an Rollen geliefert,
   die sie fachlich benötigen.
6. Eine zentrale Rollen×Endpoint×Object-Scope-Matrix deckt auch Produkte und
   Protokollbibliotheken ab; keine neue GET-Route darf nur aufgrund
   erfolgreicher Authentifizierung staff-intern werden.

## `REF-BASIS-001` – Cockpit erklärt eine andere Building-Block-Basis

### Ist-Zustand

Der produktive Enginepfad besitzt bereits einen kanonischen Resolver:

- CH erhält shared `NULL` plus exakte CH-Zeilen;
- DE erhält shared `NULL` plus exakte DE-Zeilen;
- exakte Jurisdiktion überschreibt denselben logischen Shared-Key;
- gleichrangige Duplikate, fehlende explizite Non-CH-Basis und fehlendes
  explizites Investmentuniversum scheitern fail-closed.

`GET /building-blocks/current` verwendet diesen Resolver nicht. Die Route lädt
alle aktiven Building Blocks der global aktuellen Policy. Weder Mandat,
Jurisdiktion noch `investment_universe` sind Teil des Requests; Shared-/Exact-
Overrides werden nicht dedupliziert. `BuildingBlockResponse` enthält nicht
einmal `jurisdiction`.

Das aktive Strategie-Cockpit ruft diese Route sowohl beim Laden einer aktuellen
Allocation als auch beim Generate parallel zum Mandatspayload auf. Anschließend
rendert es die Resultate als „Building-Block-Referenz“ mit Assetklasse,
Subanlageklasse, Universum und Risky-Fraction. Der Benutzer kann nicht erkennen,
dass Zeilen aus verschiedenen Jurisdiktionen oder ein Shared-/Exact-Duplikat
nebeneinander stehen.

### Risiko

- Die Oberfläche kann ein anderes Risky-Fraction-/Universum erklären als der
  Solver tatsächlich verwendete.
- Spätere Live-Änderungen an Policy oder Building Blocks verändern die
  Erklärung einer bereits verankerten TargetAllocation.
- CH-/DE-Overridezeilen können gemeinsam erscheinen, obwohl der Solver genau
  eine priorisierte Zeile verwendet.
- Audit, Kundenbegründung und Replay verlieren eine gemeinsame Modellbasis,
  obwohl die Allocation ihre Suballokations-/Constraint-Artefakte bereits
  persistiert.

### Verbindlicher Fixvertrag

1. Eine mandatsbezogene Runtime-Route leitet Policy, Jurisdiktion, Tenant und
   Investmentuniversum serverseitig ab und verwendet exakt
   `resolve_building_blocks_for_jurisdiction`.
2. Für eine bestehende moderne Allocation kommt die Erklärung bevorzugt aus
   dem verifizierten, persistierten Allocation-Kontext beziehungsweise dem
   kanonischen Target-Payload, nicht aus einer neuen Live-Abfrage.
3. Wenn eine Admin-Referenzliste weiterhin nötig ist, ist sie ausdrücklich als
   Adminansicht gesichert und enthält `jurisdiction` sowie Scope. Sie darf nicht
   als mandatsbezogene Engineerklärung wiederverwendet werden.
4. Die Response bindet mindestens `mandate_id`, `policy_id`, Jurisdiktion,
   Investmentuniversum und einen Context-/Snapshot-Fingerprint. Der Client
   verwirft abweichende oder stale Resultate.
5. Shared-/Exact-Dedupe, Duplicate-Conflict und explizite-Universum-Missing-
   Semantik sind identisch mit dem Solver. Keine zweite Resolverlogik im Router
   oder Frontend.
6. Das Cockpit rendert ausschließlich die injizierte verifizierte Modellbasis;
   ein Metadatenfehler darf nicht still zu `[]` oder einer ungefilterten
   Referenzliste degradieren.

## Verbindliche Testmatrix

### Rollen- und Tenantgrenze

- Parametrisiert über House Matrix, aktuelle/historische Policy, Building
  Blocks, CMA, Produkte und Protokollbausteine: `client` erhält 403 und keinen
  Responseinhalt.
- Advisor/Admin erhalten nur die ausdrücklich erlaubte Projektion; unbekannte,
  deaktivierte und soft-gelöschte Principals scheitern.
- Firm-A-Staff mit `tenant_id=firm-b` im Query erhält niemals Firm-B-Daten.
- Platform-Operator-Cross-Tenant-Read ist, falls fachlich benötigt, explizit,
  protokolliert und separat getestet.
- Client-Portal-Happy-Path für die eigene verknüpfte Akte bleibt grün; fremdes
  Mandat und fremder Tenant bleiben 404 ohne Existenzleck.
- Response-Contracttests beweisen, dass staff-interne Felder nicht in einer
  kundenzulässigen Projektion vorkommen.

### Building-Block-Modellbasis

- CH-Mandat sieht nur shared+CH; DE-Mandat nur shared+DE. Fremde explizite
  Jurisdiktionen sind ausgeschlossen.
- Bei identischem `(asset_class, sub_asset_class, universe)` gewinnt exakt die
  Länderzeile; zwei gleichrangige Zeilen führen vor Rendering zu 409.
- Explizites Universum ohne vollständige Referenzdaten führt zu 409, niemals
  zum ungefilterten Fallback.
- Cockpit-Response und verifizierter Target-Payload besitzen dieselben IDs,
  Risky-Fractions und Subanlageklassen.
- Policy-/Building-Block-Änderung nach Allocation verändert den historischen
  Snapshot nicht; ein aktueller Preview zeigt die Drift ausdrücklich.
- Fehler beim Preflight führen zu sichtbarem 409 und verhindern die
  Building-Block-Darstellung; `Promise.allSettled` darf keinen Integritätsfehler
  in eine leere Liste verwandeln.

### PostgreSQL/RLS und Parallelität

- Zwei echte Tenants unter einer Nicht-Owner-/Nicht-BYPASSRLS-Approlle testen
  alle Reads zusätzlich zur Applikationsauthority.
- Queryparameter können die gesetzte Tenant-GUC nicht erweitern.
- Ein Policy-/Referenzrollover zwischen Preflight und Response erzeugt einen
  Fingerprintkonflikt oder einen konsistenten Snapshot, nie einen Hybrid.

## Empfohlene Umsetzungsreihenfolge

1. Rollen×Endpoint×Scope-Matrix und zentrale Staff-Read-Authority definieren;
   alle betroffenen GET-Routen und Schemas darauf umstellen.
2. Freie `tenant_id`-Auswahl aus normalen CMA-Reads entfernen und den Scope aus
   Principal beziehungsweise zugreifbarem Mandat ableiten.
3. Mandats-/Allocation-bezogenen Building-Block-Payload aus dem kanonischen
   Resolver beziehungsweise dem verifizierten Allocation-Snapshot erzeugen.
4. Cockpit auf diesen Payload umstellen und stille `allSettled`-Degradation für
   Integritätsfehler entfernen.
5. HTTP-RBAC-, Cross-Tenant-, Resolver-, UI-Contract- und echte PostgreSQL-
   RLS-/Paralleltests ergänzen.
6. Erst danach Produkt-/Protokoll-/Policy-Dokumentation und Operatoransichten
   synchronisieren.

## Definition of Done

`REF-READ-001` und `REF-BASIS-001` gelten erst als geschlossen, wenn
gleichzeitig:

- ein `client` ausschließlich explizite eigene Client-Portal-Projektionen
  lesen kann;
- alle internen Referenzreads eine benannte Staff-Authority verwenden;
- kein normaler Request fremde Tenant-IDs oder Jurisdiktionsscopes wählen kann;
- interne Policy-/CMA-/Produkt-/Protokollfelder least-privilege projiziert sind;
- die Building-Block-Anzeige exakt denselben Resolver- oder Snapshotkontext wie
  die Allocation verwendet;
- Live-Referenzdrift niemals eine historische Modellbasis ersetzt;
- Rollen×Endpoint×Tenant-, CH/DE-/Universums-, UI-Contract- und echte
  PostgreSQL-RLS-/Concurrency-Tests grün sind;
- der vollständige Backend- und Frontend-Gate auf dem Fixcommit erneut grün
  ist; und
- dieser Audit mit Fixcommit, Migrationen, Testzahlen und Restpunkten
  aktualisiert oder durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an Referenzdaten-GETs, Client-Portal, CMA, Building Blocks,
Produkten oder Protokollbausteinen:

1. Diesen Audit vollständig lesen.
2. `REF-READ-001`, `REF-BASIS-001`, `AUTH-TEN-06` und `TEN-COMP-001` gemeinsam
   behandeln.
3. `get_current_user` nicht mit einer fachlichen Leseberechtigung verwechseln.
4. Tenant-ID, Jurisdiktion und Universum nicht aus untrusted Queryparametern in
   einen Resolver übernehmen.
5. Keine zweite Building-Block-Auswahl im Router oder Frontend implementieren.
6. Historische Allocation-Erklärungen nicht aus aktuellen Live-Referenzen
   rekonstruieren.
7. Client-, Staff-, Platform- und Cross-Tenant-Negativtests vor Positivtests
   schreiben.
8. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline- und Audit-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Der fokussierte bestehende Nachbarschaftsring auf dem auditierten Head ergab:

```text
95 passed, 1 warning in 77.05s
```

Abgedeckt waren Jurisdiktionsresolver, CMA-Queryparameter, DE-Engine-Wiring,
Protokollbausteine, Produktuniversum und Client-Portal-Tenantisolation. Diese
grünen Tests widerlegen die Findings nicht: Ihnen fehlen die beschriebene
Client-gegen-Staff-Negativmatrix, der fremde CMA-Tenantparameter und die
Parität zwischen Cockpit-Building-Blocks und verankertem Allocation-Kontext.
