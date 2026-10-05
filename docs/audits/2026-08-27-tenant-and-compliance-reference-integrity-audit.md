---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-tenant-and-compliance-reference-integrity-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "ad8b4b331e0a9f2360154fb96b10f2d662fec688"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-request-ingestion-and-resource-governance-audit.md"
prior_release_audit_commit: "ad8b4b331e0a9f2360154fb96b10f2d662fec688"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-tenant-and-compliance-reference-integrity-audit.md"
audit_mode: "read_only_static_source_existing_test_and_in_memory_service_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "Strict tenant identity at authorization boundaries, mandate-bound compliance evidence and reimbursed-inducement integrity"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 75
focused_adjacent_tests_failed: 0
required_next_action: "make missing tenant identity fail closed in strict mode, resolve every compliance evidence anchor against one mandate/client/tenant, and require immutable reimbursement evidence before reducing customer cost totals"
---

# Tenant- und Compliance-Referenzintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die siebte Read-only-Kontrollrunde auf
Repository-Head `ad8b4b33`. Er ergänzt, ersetzt aber nicht:

1. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
2. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
3. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
4. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
5. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
6. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
7. den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die sieben vorgenannten Dokumente in dieser
Reihenfolge. Historische Planning-Dokumente sind als Herkunftshinweis nützlich,
aber keine Freigabequelle.

Die Analyse hat keine Produkt- oder Testdatei verändert. Der vollständige grüne
Backend-Gate bleibt ein Regressionsnachweis für den eingecheckten
Optimizerstand. Er beweist weder die Tenant-Identität eines fehlerhaften
Altbestands noch die fachliche Zugehörigkeit frei übergebener Evidence-IDs.

## Kurzurteil

**Release bleibt hart blockiert.** Drei P1-Verträge sind offen:

1. Im effektiven Strict-/Multi-Tenant-Modus führt ein fehlender oder leerer
   `User.tenant_id` weiterhin zu einer ungefilterten Client-/Mandatsquery. Ein
   Admin mit leerer Tenant-ID erhielt in der Reproduktion einen Client aus
   `firm-B`; ein Client-Portal-User mit leerer Tenant-ID erhielt über eine
   fehlerhafte Linkage ebenfalls einen `firm-B`-Client.
2. Beratungsprotokolle und Suitability Checks übernehmen mehrere Evidence-IDs,
   ohne deren Mandat, Client, Tenant, Status oder Currentness aufzulösen. Ein
   AdvisoryLog für Mandat A wurde erfolgreich mit Trigger, Dokument,
   Suitability Check und Conflict Disclosure aus Mandat B gespeichert und mit
   einem gültigen Integritätshash versehen.
3. Eine behauptete Rückerstattung von Retrozessionen braucht weder Zahlungs-
   noch Dokumentnachweis. Ein ungegrenzter Betrag wird bei
   `reimbursed_to_client=true` negativ in die jährlichen Gesamtkosten
   eingerechnet. Die Reproduktion erzeugte dadurch ausgewiesene Kosten von
   `-999999999999` Rappen.

`TEN-COMP-001` war als Designrisiko bereits im Planning-Dokument vom
3. Juli 2026 beschrieben. Der aktuelle Code enthält den Fail-open-Zweig aber
weiterhin, und die kanonische Release-Ledger-Kette dokumentierte ihn bisher
nicht als offen. Der Befund wird deshalb als aktuell reproduzierter, weiterhin
offener Vertrag aufgenommen und nicht als neue historische Entdeckung
ausgegeben.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `TEN-COMP-001` | P1, bei realem Tier-2-Altbestand konditional P0 | offen | Strict-/Multi-Tenant-Autorisierung verlangt eine nichtleere, gültige Principal-Tenant-ID; fehlende Tenant-Identität darf niemals eine Query entscopen |
| `TEN-COMP-002` | P1 | offen | Advisory-, Suitability- und Dokumentationsanker werden vollständig gegen dasselbe Mandat, denselben Client und Tenant sowie den zulässigen Status aufgelöst, bevor ein Beweisdatensatz entsteht |
| `TEN-COMP-003` | P1 | offen | Rückvergütungen reduzieren Kosten nur mit positivem, begrenztem Betrag und einem unveränderlichen, mandateigenen Zahlungsnachweis; negative Gesamtkosten werden fail-closed blockiert |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Tenant-Scoping | `5eyes-backend/services/auth.py:291-409`, `:497-551`; `5eyes-backend/models/users.py:9-14` |
| AdvisoryLog-Request und Speicherung | `5eyes-backend/schemas/review.py:70-130`; `5eyes-backend/routers/review.py:762-805`; `5eyes-backend/services/advisory_log_service.py:163-198` |
| AdvisoryLog-Referenzfelder/Hash | `5eyes-backend/models/review.py:72-149`; `5eyes-backend/services/advisory_log_service.py:84-109` |
| Suitability-Request und Speicherung | `5eyes-backend/schemas/profiling.py:185-210`; `5eyes-backend/routers/profiling.py:410-445`; `5eyes-backend/models/profiling.py:121-141` |
| Conflict-/Retrozessionsinput | `5eyes-backend/schemas/review.py:297-315`; `5eyes-backend/routers/review.py:1063-1098`; `5eyes-backend/models/review.py:168-193` |
| Kostenminderung und Summen | `5eyes-backend/services/cost_disclosure.py:359-440` |

Die Zeilenangaben beziehen sich ausschließlich auf
`audited_repository_head`. Nach einem Fix müssen Funktionsnamen, Tests und
Migrationen als stabilere Traceability-Anker zusätzlich dokumentiert werden.

## Reproduktions- und Evidenzledger

| Prüfung | Beobachtung | Ergebnis |
|---|---|---|
| Strict Admin ohne `tenant_id`, fremder Client `firm-B` | `get_client_for_user_or_404()` gab `c-b` zurück | `TEN-COMP-001` bestätigt |
| Strict Client-Portal-User ohne `tenant_id`, Link auf `firm-B` | `get_linked_client_for_user_or_404()` gab `c-b` zurück | `TEN-COMP-001` bestätigt |
| AdvisoryLog Mandat A mit vier Evidence-Ankern aus Mandat B | Commit erfolgreich, `integrity_hash_present=True` | `TEN-COMP-002` bestätigt |
| Conflict Disclosure mit `999999999999` Rappen und behaupteter Rückerstattung | Schema akzeptiert; Jahres- und Erstjahreskosten `-999999999999` | `TEN-COMP-003` bestätigt |
| bestehender Client-Portal-/Advisory-/Suitability-/Kostenring | 75 bestanden, 0 fehlgeschlagen, 1 Deprecation-Warnung | bestehende Positivverträge grün; neue Negativgrenzen fehlen |
| Frontend-HTML-Sinks | dynamische Client-/Produkt-/Goal-/Auditwerte waren in den geprüften Pfaden escaped oder via `textContent` gesetzt | kein neues Stored-XSS-P1 |
| direkte Mandats-ID-Helfer | Recommendation-/Review-Direkt-IDs waren in den geprüften Standardpfaden überwiegend mandategebunden | kein zusätzliches allgemeines IDOR-P1 |
| dynamische SQL-/Server-URL-Pfade | geprüfte Identifier waren intern; Provider-Hosts fest oder Operator-Konfiguration | kein neues bestätigtes SQLi-/SSRF-P1 |

Die letzten drei Zeilen sind bewusst dokumentierte Negativbefunde. Sie dürfen
nicht zu einer pauschalen XSS-, IDOR-, SQLi- oder SSRF-Freigabe umgedeutet
werden; sie grenzen nur diese Kontrollrunde ab.

## Detailbefunde

### `TEN-COMP-001` – Leere Principal-Tenant-ID schaltet Strict Scoping aus

#### Ist-Zustand

`services/auth.py` entscheidet zwar über einen effektiven Strict-Modus, prüft
die Tenant-ID aber in den beiden Query-Helfern vorher:

- `_apply_tenant_filter_to_client_query()` gibt bei fehlender oder leerer
  `current_user.tenant_id` die Query unverändert zurück;
- `_apply_tenant_filter_to_mandate_query()` tut dasselbe;
- erst danach würde der Strict-Zweig auf exakten Tenant-Match filtern;
- `has_global_client_access()` behandelt jede Rolle `admin` als global, sodass
  ein Admin ohne Tenant-ID tatsächlich alle nicht gelöschten Clients erreichen
  kann;
- der Client-Portal-Helper lehnt eine falsche Linkage im Strict-Modus nur ab,
  wenn die User-Tenant-ID truthy ist.

Die Modellspalte `User.tenant_id` ist weiterhin nullable. Ein fehlerhafter
Import, Altbestand oder unvollständiger Provisioningpfad kann den Zustand daher
persistieren. Das Planning-Dokument
`docs/planning/2026-07-03-top10-implementation-specs.md` nennt sowohl die
fehlende Client-Login-Tenant-ID als auch den Zweig „Legacy-User: kein Filter“;
der heutige Code enthält diese Semantik weiterhin.

#### Reproduktion

Zwei In-Memory-SQLite-Reproduktionen liefen mit aktivierter
`strict_tenant_isolation`:

```text
{'strict': True, 'role': 'admin', 'user_tenant': None,
 'foreign_client_tenant': 'firm-B', 'released_client_id': 'c-b'}
```

```text
{'strict': True, 'user_tenant': None, 'client_tenant': 'firm-B',
 'released_client_id': 'c-b'}
```

Die erste Reproduktion nutzte einen Admin ohne Tenant-ID und einen Client aus
`firm-B`. Die zweite nutzte einen Client-Portal-User ohne Tenant-ID und eine
`ClientLogin`-Zeile, die auf einen `firm-B`-Client zeigte. In beiden Fällen
wurde das fremde Objekt freigegeben.

#### Risiko

Die Tenant-ID eines authentifizierten Principals ist eine Sicherheitsgrenze,
kein optionaler Suchfilter. Ein fehlender Wert darf im Strict-Modus nicht mehr
Berechtigung erzeugen als ein gültiger Wert. In einem echten Shared-Cloud-
Altbestand kann der Fehler zu tenantübergreifender Offenlegung führen; deshalb
ist er dort konditional releasekritisch bis P0.

#### Verbindlicher Fixvertrag

1. Eine zentrale Principal-Validierung muss vor jeder tenantgebundenen Query
   laufen. Effektiver Strict-/Multi-Modus plus fehlende, leere oder unbekannte
   Tenant-ID endet fail-closed.
2. Ein Operator-/`super_admin`-Bypass muss eine explizite, getrennte
   Berechtigungsabhängigkeit sein. `tenant_id=None` darf nie als globales
   Zugriffsmerkmal dienen.
3. Client-, Mandats-, User-, Client-Portal- und Repository-Helfer verwenden
   denselben aufgelösten Tenant-Kontext; keine lokale Legacy-Ausnahme darf die
   Query entscopen.
4. Tenant-eigene Principals erhalten nach einem vorangestellten NULL-/Linkage-
   Audit eine versionierte `NOT NULL`-/FK-Invariante. Fehlerhafte Altzeilen
   werden nicht pauschal `main` zugeordnet, sondern aus ihrer belegbaren
   Client-/Tenant-Kette abgeleitet oder zur manuellen Klärung blockiert.
5. Non-Strict-Legacy-Kompatibilität darf nur als ausdrücklich getesteter
   Single-Tenant-Modus bestehen. Sie darf nicht durch Tier-/Config-Drift in
   Tier 2 aktiv werden.

### `TEN-COMP-002` – Compliance-Evidence-IDs sind nicht an Mandat und Client gebunden

#### Ist-Zustand

`AdvisoryLogCreate` akzeptiert unter anderem:

- `trigger_id`,
- `document_id`,
- `conflict_disclosure_ids`,
- `suitability_check_id`,
- `recommendation_run_id`.

Der Router validiert nur die optionale RecommendationRun-ID gegen das Mandat.
Die übrigen vier Anker werden an `create_advisory_log()` weitergereicht und dort
direkt persistiert. Der Integritätshash schützt anschließend gespeicherte IDs,
beweist aber nicht, dass diese IDs fachlich zu Mandat, Client und Tenant des
Protokolls gehören. `trigger_id` und `document_id` sind darüber hinaus nicht
Teil des derzeitigen Hash-Payloads.

Der Suitability-Pfad besitzt dieselbe Bypassklasse. `SuitabilityCheckCreate`
akzeptiert Knowledge Assessment, Risk Assessment, Recommendation Run,
AdvisoryLog und Dokument als freie optionale IDs. Der Router kopiert sie in
eine neue Zeile für das URL-Mandat, ohne Existenz, Mandats-/Client-/Tenant-
Zugehörigkeit, Status oder Currentness aufzulösen. Die Modellfelder sind
überwiegend einfache Strings statt durchgängiger referenzieller Verträge.

#### Reproduktion

In einer In-Memory-Datenbank kontrollierte derselbe Advisor Mandat A und B.
Trigger, Vertragsdokument, Suitability Check und Conflict Disclosure wurden für
Mandat B angelegt. Anschließend wurde ein AdvisoryLog für Mandat A mit genau
diesen vier B-IDs erstellt:

```text
{'advisory_mandate': 'ma', 'trigger_mandate': 'mb',
 'document_mandate': 'mb', 'suitability_mandate': 'mb',
 'conflict_mandate': 'mb', 'integrity_hash_present': True}
```

Die Speicherung und Hashbildung waren erfolgreich. Der Hash macht den
mandatsfremden Beleg dadurch dauerhaft konsistent falsch.

#### Risiko

Ein FINMA-/FIDLEG-Protokoll oder Suitability Check kann behaupten, eine konkrete
Warnung, Empfehlung, Prüfung, Offenlegung oder ein Dokument gehöre zur
Kundenentscheidung, obwohl es einen anderen Kunden oder ein anderes Mandat
betrifft. Das ist keine reine Anzeigeabweichung: Signatur, Audit-Export,
Kundenbericht und spätere Beweisführung können auf den falschen Ankern
aufbauen.

#### Verbindlicher Fixvertrag

1. Ein zentraler `resolve_compliance_evidence_context()`-Vertrag löst alle
   angegebenen IDs vor Speicherung auf.
2. Jeder Anker muss existieren, nicht gelöscht sein und exakt zu Mandat,
   Client und Tenant des Zielrecords gehören. Status, Currentness,
   Finalisierung und zeitliche Reihenfolge werden pro Artefakttyp geprüft.
3. Unbekannte oder unsichtbare IDs enden ohne Existenz-Leak als 404;
   bekannte, aber fachlich inkonsistente Anker als stabiler 409. Es wird kein
   partieller Protokoll-/Suitability-Datensatz gespeichert.
4. Composite-FKs, Constraints oder Trigger sichern die wesentlichen
   Mandats-/Clientanker zusätzlich in der Datenbank, soweit das Modell dies
   ohne unversionierte Imperativmigration erlaubt.
5. Ein versionierter Integritätshash v2 umfasst sämtliche Evidence-IDs und
   deren unveränderliche Content-/Dokumenthashes. Das Hashen einer vom Request
   frei gewählten ID allein ist kein Evidence-Nachweis.
6. Ein Suitability-Ergebnis darf nicht unabhängig von den referenzierten
   Knowledge-/Risk-/Recommendation-Artefakten behauptet werden. Der Service
   rekonstruiert und prüft die Ergebnissemantik aus dem exakten Kontext.

### `TEN-COMP-003` – Behauptete Rückvergütung erzeugt unbegrenzt negative Kosten

#### Ist-Zustand

`ConflictDisclosureCreate.inducement_amount_rappen` ist ein optionaler Integer
ohne Unter-/Obergrenze. `reimbursed_to_client` ist ein optionales Boolean; die
Dokument- und Waiver-IDs werden nicht gegen das Mandat oder einen
Zahlungsnachweis geprüft. Der Router persistiert die Felder direkt.

Die Kostenberechnung liest positive Retrozessionsbeträge. Sobald
`reimbursed_to_client` truthy ist, erzeugt sie ein Cost Item mit negativem
Betrag. Jährliche Items werden ohne Untergrenze in `annual_rappen` und
`first_year_rappen` summiert. Ein Nachweis, dass Geld an genau diesen Kunden
bezahlt wurde, ist dafür nicht nötig.

#### Reproduktion

Das Requestmodell akzeptierte:

```python
ConflictDisclosureCreate(
    conflict_type="Retrozession / Inducement",
    description="x",
    inducement_amount_rappen=999999999999,
    inducement_frequency="jährlich",
    reimbursed_to_client=True,
    waiver_document_id="foreign-or-missing",
)
```

Bei einem Beratungsvermögen von `10000000` Rappen und keinen anderen Positionen
lieferte die Kostenberechnung:

```text
{'schema_accepted': True, 'amount': 999999999999,
 'waiver_document_id': 'foreign-or-missing',
 'annual_total': -999999999999,
 'first_year_total': -999999999999}
```

#### Risiko

Die kundenseitige Ex-ante-Kostenoffenlegung kann beliebig günstige bis massiv
negative Kosten ausweisen, obwohl keine Rückzahlung belegt ist. Ein
Waiver-Dokument ist zudem begrifflich kein Zahlungsnachweis. Der Fehler kann
Kosten, Suitability-Kommunikation und Beratungsprotokoll gleichzeitig
verfälschen.

#### Verbindlicher Fixvertrag

1. Der Betrag ist ein exakter Non-Bool-Integer, strikt positiv, fachlich
   begrenzt und mit eindeutiger Währung sowie Periode versehen.
2. `reimbursed_to_client` wird nicht allein als Boolean-Evidence verwendet.
   Eine tatsächliche Rückzahlung verlangt ein unveränderliches Artefakt mit
   Betrag, Datum, Empfänger, Zahlungsstatus und Content-Hash.
3. Zahlungs- und gegebenenfalls Waiver-Dokument müssen existieren, final oder
   unterzeichnet, nicht gelöscht und exakt demselben Mandat/Client/Tenant
   zugeordnet sein. Ein Waiver belegt die zulässige Einbehaltung, nicht die
   erfolgte Rückzahlung.
4. Die Kostenberechnung blockiert inkonsistente Retrozessionszeilen und
   negative Gesamtbeträge. Sie publiziert keinen partiellen oder künstlich
   günstigen 200-Payload.
5. Finaler Advisory-/Kosten-Publikationskontext friert Offenlegung,
   Zahlungsnachweis und Berechnung in einem versionierten Snapshot-/Hashvertrag
   ein.

## Empfohlene Umsetzungsreihenfolge

### Block A – Tenant-Principal fail-closed machen

1. Rote Service- und Endpointtests für leere Principal-Tenants erstellen.
2. Zentralen aufgelösten Tenant-Kontext vor Queries erzwingen.
3. Expliziten Operatorpfad von tenantgebundenen Adminrechten trennen.
4. Altbestand inventarisieren, kontrolliert reparieren und die DB-Invariante
   versioniert migrieren.
5. Echten PostgreSQL-/RLS-Zwei-Tenant-Test ausführen; SQLite allein genügt
   nicht.

### Block B – Compliance-Anker zentral auflösen

1. Evidence-Typen, erlaubte Status und Ownership-Matrix festlegen.
2. Einen read-only Resolver für AdvisoryLog und Suitability implementieren.
3. API- und Raw-Servicepfade auf denselben Resolver zwingen.
4. Hashschema v2 und DB-Constraints additiv migrieren.
5. Report-, Signatur-, DSG-Export- und Advisory-Publikationspfade auf den
   verifizierten Kontext umstellen.

### Block C – Retrozession und Kosten beweisbar machen

1. Betrags-/Frequenz-/Währungsdomäne test-first schließen.
2. Rückzahlungs- und Waiver-Artefakte fachlich trennen.
3. Mandateigene, immutable Evidence verlangen.
4. Negative Total-Gates vor API, PDF und Advisory-Renderer setzen.
5. Finalisierung und Publikationshash an denselben Snapshot binden.

### Block D – Gemeinsamer Zielumgebungs-Gate

1. Cross-Mandate- und Cross-Tenant-Matrix auf PostgreSQL mit echter
   Nicht-Owner-/RLS-Approlle ausführen.
2. Race-/Rolloverfälle für Evidence und Finalisierung parallel testen.
3. Migration, Backfill, Rollback-/Restore-Notfallpfad und Auditexport prüfen.
4. Vollständigen Backend-Gate und relevante Browser-/PDF-Suites auf demselben
   Fixcommit ausführen.

## Verbindlicher Testvertrag

Neue oder erweiterte Suites mindestens:

- `5eyes-backend/tests/test_strict_tenant_principal_contract.py`
- `5eyes-backend/tests/test_client_portal_tenant_isolation.py`
- `5eyes-backend/tests/test_compliance_evidence_context.py`
- `5eyes-backend/tests/test_advisory_log_endpoints.py`
- `5eyes-backend/tests/test_suitability_evidence_integrity.py`
- `5eyes-backend/tests/test_cost_disclosure_reimbursement_evidence.py`
- `5eyes-backend/tests/test_compliance_reference_postgres.py`

Pflichtfälle:

1. Strict Admin, Advisor und Client-Portal-User ohne/mit leerer Tenant-ID sehen
   keine tenantgebundenen Zeilen; der Querypfad wird nicht ungescoped
   ausgeführt.
2. Ein expliziter `super_admin`-Operatorpfad funktioniert nur über die dafür
   vorgesehene Dependency und nicht über `tenant_id=None`.
3. Jede Advisory-/Suitability-Evidence-ID wird gegen fehlend, gelöscht,
   anderes Mandat, anderen Client, anderen Tenant, falschen Status und stale
   Currentness parametrisiert.
4. Ein Fehler erzeugt 404/409, keinen Insert, keinen Audit-/Hash-Scheinbeleg und
   ruft keinen Renderer auf.
5. Retrozessionsbetrag `None`, 0, negativ, Bool, übergroß und falsche Frequenz
   wird fachlich korrekt behandelt oder abgelehnt.
6. Behauptete Rückerstattung ohne, mit fremdem oder nicht finalem
   Zahlungsnachweis endet fail-closed.
7. Eine gültig belegte Rückzahlung kann Kosten reduzieren, aber kein
   unplausibles negatives Gesamttotal erzeugen.
8. Zwei parallele Evidence-/Finalisierungsvorgänge können keinen hybriden oder
   doppelt aktuellen Beweisstand erzeugen.

## Definition of Done

Dieser Block ist erst geschlossen, wenn:

- [ ] kein Strict-/Multi-Tenant-Principal ohne gültige Tenant-ID eine
      tenantgebundene Query erreicht;
- [ ] globale Operatorrechte explizit rollen- und scopegebunden statt über
      NULL-Sentinels vergeben werden;
- [ ] Tenant-Principal-Altbestand vollständig inventarisiert und kontrolliert
      migriert ist;
- [ ] AdvisoryLog und Suitability jeden Evidence-Anker gegen denselben Mandats-
      /Client-/Tenant-Kontext prüfen;
- [ ] Hash v2 alle Anker samt immutable Content-Nachweis umfasst;
- [ ] unbekannte oder fremde Anker keinen partiellen Compliance-Datensatz
      hinterlassen;
- [ ] Rückerstattungen nur mit mandateigenem, finalem Zahlungsnachweis
      kostenmindernd wirken;
- [ ] Kosten-API, Advisory und PDF negative oder inkonsistente Totals
      fail-closed blockieren;
- [ ] SQLite- und echter PostgreSQL-/RLS-Zwei-Tenant-Gate grün sind;
- [ ] fokussierte Suites und vollständiger Backend-Gate auf demselben
      Fixcommit grün sind;
- [ ] Compliance, Security und fachlicher Owner Evidence-/Retrozessionsvertrag
      abgenommen haben.

## Claude-Startcheckliste

1. Dieses Dokument und danach alle sieben Vorgängerdokumente vollständig lesen.
2. `TEN-COMP-001` nicht als durch einen Config-Strict-Flag geschlossen ansehen;
   der blanke Principal-Zweig muss vor der Query enden.
3. `tenant_id=None` niemals als Operator- oder globale Berechtigung verwenden.
4. Einen Integritätshash nicht mit fachlich validierter Evidence verwechseln.
5. AdvisoryLog und Suitability nicht getrennt reparieren; beide brauchen
   denselben Evidence-Resolver.
6. Waiver und tatsächliche Rückzahlung fachlich trennen.
7. Keine Kostenkorrektur durch Clamp auf null kaschieren; inkonsistente
   Evidence muss sichtbar fail-closed enden.
8. Jede Cross-Mandate-Matrix zusätzlich mit zwei echten Tenants prüfen.
9. Keine der früheren P0/P1 durch diesen Block als geschlossen markieren.
10. Pro Finding roten Test, Produktfix, Migrations-/PG-Nachweis, fokussierten
    Ring und vollständigen Gate auf demselben Commit dokumentieren.

## Dokumentationsmanifest dieser Runde

Dieses Dokumentationsbatch umfasst exakt:

1. `docs/audits/2026-08-27-tenant-and-compliance-reference-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit dieses Dokuments wird nicht in den eigenen Inhalt eingebettet.
Auflösung ausschließlich extern über `document_commit_resolution`.

## Dokumentations-QA vor Commit

- Strict-Admin- und Client-Portal-Reproduktionen: bestätigt;
- Cross-Mandate-AdvisoryLog-Reproduktion: bestätigt;
- negative Retrozessions-/Kostenreproduktion: bestätigt;
- bestehender angrenzender Ring: 75 von 75 Tests grün;
- Frontend-Sink-, direkter ID-, dynamischer SQL- und URL-Negativbefund:
  dokumentiert, ohne pauschale Freigabe;
- Finding-Register: 3 eindeutige IDs, 3 Detailsektionen;
- Produkt- und Testdateien: unverändert;
- lokale Links, Markdown-Fences, Manifest und `git diff --check`: vor Commit
  vollständig zu prüfen;
- die 53 bekannten ACL-unlesbaren `.pytest_tmp_*`-Verzeichnisse wurden weder
  gelesen noch verändert; deshalb kein globaler Clean-Claim.
