---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-client-classification-and-compliance-state-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "03c727bb8230b77471988e3128760bdc1cdf2ab3"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-tenant-and-compliance-reference-integrity-audit.md"
prior_release_audit_commit: "03c727bb8230b77471988e3128760bdc1cdf2ab3"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-client-classification-and-compliance-state-audit.md"
audit_mode: "read_only_static_source_existing_test_schema_and_in_memory_service_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "FIDLEG client classification transitions, advisory terminal states, customer acknowledgement provenance and suitability source-of-truth"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 98
focused_adjacent_tests_failed: 0
required_next_action: "centralize client-classification and advisory state transitions, derive customer acknowledgements from immutable evidence, and make suitability use one exact non-deleted assessment context"
---

# Kundenklassifikations- und Compliance-State-Audit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die achte Read-only-Kontrollrunde auf
Repository-Head `03c727bb`. Er ergänzt, ersetzt aber nicht:

1. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
2. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
3. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
4. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
5. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
6. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
7. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
8. den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die acht vorgenannten Dokumente in dieser
Reihenfolge. Der grüne Backend-Gate beweist den auditierten Optimizerstand,
nicht die juristische Herkunft oder semantische Konsistenz requestgesetzter
Compliance-Felder.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Drei weitere P1-Verträge sind offen:

1. Die FIDLEG-Kundenklassifikation samt Professional-Opt-out- und Qualified-
   Investor-Flag kann über den allgemeinen Client-PUT ohne Opt-History oder
   Beleg geändert werden. Der eigentliche Opt-History-Pfad akzeptiert freie
   Event-, Von- und Nachwerte, prüft den aktuellen Ausgangszustand nicht und
   setzt sogar eine außerhalb des Client-Enums liegende Zielklassifikation.
2. Ein AdvisoryLog kann direkt im terminalen Status `Umgesetzt` entstehen,
   obwohl spätere Updates einer Übergangsmatrix folgen. Derselbe Request kann
   `client_signed=true` mit beliebigem Zeitstring behaupten; die
   Versionierungsroute erzeugte sogar `client_signed=1` bei
   `client_signed_at=None`.
3. Suitability besitzt mehrere widersprüchliche Wahrheiten. Der Create-Pfad
   akzeptiert `Keine Prüfung / Geeignet / client_acknowledged=true` ohne einen
   einzigen Evidence-Anker. Der separate Compliance-Audit ignoriert diesen
   SuitabilityCheck und markierte stattdessen ein soft-gelöschtes, weiterhin
   `is_current=1` gesetztes Risikoprofil als `is_compliant=True`.

Die bereits dokumentierte Überschreibbarkeit echter ContractDocument-
Signaturen bleibt `REC-006`; die fehlende Bindung frei übergebener Compliance-
IDs bleibt `TEN-COMP-002`; Retention und Legal Hold bleiben `PRIV-003`. Dieser
Audit zählt sie nicht erneut, sondern schließt die bisher separat offene
**State- und Provenance-Semantik**.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `FIDLEG-STATE-001` | P1 | offen | Kundenklassifikation und Opt-in/-out ändern sich nur über einen atomaren, append-only, beleggebundenen Zustandsübergang; allgemeine Client-Updates dürfen ihn nicht umgehen |
| `FIDLEG-STATE-002` | P1 | offen | Advisory-Endzustände und Kundenbestätigungen entstehen nur über serverseitige Transitionen und immutable Signatur-/Portal-Evidence; Request-Flags und freie Zeitstrings sind keine Bestätigung |
| `FIDLEG-STATE-003` | P1 | offen | Suitability-Entscheid, Compliance-Audit und Publikation verwenden denselben exakten, aktuellen, nicht gelöschten Mandatskontext und können keine widersprüchlichen Ergebnisse ausgeben |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Client-Update-Bypass | `5eyes-backend/schemas/clients.py:36-65`; `5eyes-backend/routers/clients.py:126-148` |
| Opt-History-Schema und Mutation | `5eyes-backend/schemas/clients.py:111-130`; `5eyes-backend/routers/clients.py:211-254`; `5eyes-backend/models/clients.py:61-76` |
| Advisory-Create-/Updateschema | `5eyes-backend/schemas/review.py:70-187` |
| Advisory-Create und Übergangsmatrix | `5eyes-backend/routers/review.py:762-805`, `:815-821`, `:876-949` |
| Advisory-Versionierung | `5eyes-backend/services/advisory_log_service.py:201-267` |
| Suitability-Request und Persistenz | `5eyes-backend/schemas/profiling.py:185-210`; `5eyes-backend/routers/profiling.py:398-445` |
| Suitability-Compliance-Quelle | `5eyes-backend/services/suitability_audit.py:59-89`, `:132-263` |
| kanonischer strikter RA-Vergleichspfad | `5eyes-backend/services/portfolio_engine.py:380-402`; `5eyes-backend/routers/profiling.py:127-148` |

Die Zeilenangaben sind an `audited_repository_head` gebunden. Nach einem Fix
müssen Tests, Migrationen und stabile Funktionsnamen die Traceability tragen.

## Reproduktions- und Evidenzledger

| Prüfung | Beobachtung | Ergebnis |
|---|---|---|
| allgemeiner Client-PUT: Privatkunde → professionell, Opt-out und qualified | Änderung erfolgreich, `history_rows=0` | `FIDLEG-STATE-001` bestätigt |
| Opt-History mit freiem Event, falschem Ausgang, `BROKEN-CLASS`, fehlender Dokument-ID | gespeichert; Client-Endzustand `BROKEN-CLASS` | `FIDLEG-STATE-001` bestätigt |
| AdvisoryCreate direkt `Umgesetzt`, `client_signed=true`, Zeit `not-a-date` | Schema akzeptiert den vollständigen Terminalclaim | `FIDLEG-STATE-002` bestätigt |
| AdvisoryUpdate nur `client_signed=true` | neue Version: `client_signed=1`, `client_signed_at=None` | `FIDLEG-STATE-002` bestätigt |
| SuitabilityCreate `Keine Prüfung / Geeignet / bestätigt`, alle Anker leer | Schema akzeptiert; `client_acknowledged_at=None` | `FIDLEG-STATE-003` bestätigt |
| Compliance-Audit mit soft-gelöschter Current-RA | `is_compliant=True`, `logs_with_suitability=1`, nicht degraded | `FIDLEG-STATE-003` bestätigt |
| angrenzender Client-/Advisory-/Suitability-/Signaturring | 98 bestanden, 0 fehlgeschlagen, 1 Deprecation-Warnung | vorhandene Positivverträge grün; neue Negativfälle fehlen |

## Detailbefunde

### `FIDLEG-STATE-001` – Kundenklassifikation umgeht ihren eigenen Audit-Trail

#### Ist-Zustand

`ClientUpdate` erlaubt `client_classification`, `is_professional_opt_out` und
`is_qualified_investor` als gewöhnliche optionale Felder. Der Router setzt alle
übergebenen Werte direkt auf dem Client. Er legt weder eine Opt-History-Zeile an
noch verlangt er Kundenantrag, Beleg, Status oder Konsistenz zwischen den drei
Feldern.

Der vermeintlich dafür vorgesehene `/opt-history`-Pfad ist nicht strenger:

- `event_type`, `from_classification` und `to_classification` sind freie
  Strings;
- `from_classification` wird nicht gegen den aktuellen Clientzustand geprüft;
- `document_id` wird weder auf Existenz noch Client-/Tenant-Zugehörigkeit oder
  Signaturstatus geprüft;
- der Router setzt `client.client_classification` direkt auf den freien
  `to_classification`-String;
- es gibt keinen atomaren Versions-/CAS-Vertrag gegen parallele Änderungen.

Eine globale Codesuche zeigte zudem, dass Opt-out, Qualified-Investor-Flag und
Clientklassifikation außerhalb Client-Router/Beispieldaten praktisch nicht in
der Suitability- oder Publikationslogik verwendet werden. Das System speichert
damit eine rechtlich bedeutsame Klassifikation, ohne sie als konsistente
Entscheidungsinvariante zu behandeln.

#### Reproduktion

Ein Privatkunde wurde über den allgemeinen Updatepfad geändert:

```text
{'after_direct_put': 'Professioneller Kunde', 'opt_out': 1,
 'qualified': 1, 'history_rows': 0}
```

Danach akzeptierte der Opt-History-Pfad einen fachlich beliebigen Übergang:

```text
{'after_opt_history': 'BROKEN-CLASS', 'event': 'beliebig',
 'claimed_from': 'Institutioneller Kunde',
 'document_id': 'missing-or-foreign'}
```

#### Risiko

Kundenschutzpflichten, Produktuniversum, Informationsumfang und Eignungslogik
können von einer nicht belegten oder intern widersprüchlichen Klassifikation
ausgehen. Selbst wenn einzelne Pflichten heute nicht technisch von diesen
Feldern abhängen, erzeugen UI, Export und Audit einen rechtsrelevant wirkenden
Zustand ohne belastbare Herkunft.

#### Verbindlicher Fixvertrag

1. `client_classification`, Professional-Opt-out und Qualified-Investor-Status
   werden aus `ClientUpdate` entfernt oder dort ausdrücklich unveränderbar.
2. Ein zentraler `transition_client_classification()`-Service lädt und sperrt
   den aktuellen Client, leitet `from` serverseitig ab und führt Transition,
   Evidence, Clientzustand und Auditlog atomar aus.
3. Event und Zielklasse sind typisierte Enums. Jede Transition hat eine
   explizite erlaubte Matrix und fachliche Voraussetzungen.
4. Kundenantrag, Warnung, Widerruf und erforderliche signierte Dokumente werden
   als mandate-/client-/tenantgebundene immutable Evidence aufgelöst.
5. Die drei Klassifikationsfelder können keine semantisch unmögliche
   Kombination bilden. Entweder sind Flags abgeleitet oder ein zentraler
   Validator prüft den vollständigen Post-State.
6. Opt-History ist append-only, versioniert und besitzt DB-Constraints sowie
   einen CAS-/409-Vertrag für parallele Übergänge.
7. Suitability, Produktuniversum, Kosten-/Informationspflicht und Publikation
   nutzen denselben verifizierten Klassifikationssnapshot oder dokumentieren
   ausdrücklich, warum eine Klassifikation fachlich nicht wirkt.

### `FIDLEG-STATE-002` – Terminalstatus und Kundenbestätigung sind Requestclaims

#### Ist-Zustand

Für Updates existiert eine explizite Advisory-Statusmatrix:

`Empfohlen → Beschlossen/Abgelehnt → Umgesetzt`.

Beim Create kann der Request jedoch jeden Wert aus `AdvisoryStatus` direkt als
Initialstatus setzen. Ein `Umgesetzt`-Datensatz braucht weder vorherigen
Beschluss noch Recommendation-/Dokument-/Signaturanker.

Die Kundenbestätigung ist ebenfalls requestgesetzt:

- `AdvisoryLogCreate.client_signed=true` verlangt lediglich irgendeinen
  nichtleeren `client_signed_at`-String;
- ISO-Format, Serverzeit, Signaturartefakt, Portal-Principal und Dokumenthash
  fehlen;
- `AdvisoryLogUpdate` besitzt nicht einmal denselben Merged-State-Validator;
  `client_signed=true` ohne Zeit ist erlaubt;
- die neue Version übernimmt dadurch einen intern unmöglichen Zustand und
  versieht ihn trotzdem mit einem neuen Integritätshash.

Der bereits dokumentierte ContractDocument-Re-Sign-Fehler ist davon getrennt:
Hier existiert gar kein Signaturartefakt, an das der Advisory-Claim gebunden
wäre.

#### Reproduktion

```text
{'create_status': 'Umgesetzt', 'client_signed': True,
 'client_signed_at': 'not-a-date'}
```

Die Versionierung eines zuvor unsignierten Eintrags ergab:

```text
{'versioned_client_signed': 1,
 'versioned_client_signed_at': None,
 'old_superseded_by': True}
```

#### Risiko

Ein Beratungsprotokoll kann einen ausgeführten Entscheid und eine
Kundenbestätigung behaupten, ohne dass der behauptete Prozess oder eine
Kundenhandlung stattgefunden hat. Hash und Append-only-Versionierung machen den
Requestclaim nachvollziehbar, aber nicht wahr.

#### Verbindlicher Fixvertrag

1. Normale Create-Aufrufe beginnen ausschließlich in einem definierten
   Initialstatus. Migration/Import historischer Endzustände ist ein getrennter,
   operatorgebundener und auditierter Pfad.
2. Jede Transition erfolgt über einen zentralen Service mit Row-Lock oder
   atomarem CAS. Status, Recommendation, Dokument, Evidence und Auditlog liegen
   in derselben Transaktion.
3. `client_signed` ist ein abgeleiteter Zustand aus einem exakten Portal- oder
   E-Signaturartefakt samt Principal, Dokumentrevision, Content-Hash und
   serverseitigem UTC-Zeitpunkt.
4. Advisor-recorded Offline-Bestätigung erhält einen ausdrücklich anderen
   Typ, eine Evidence-Referenz und eine sichtbare Kennzeichnung. Sie darf nicht
   als kryptografische Kundensignatur erscheinen.
5. Create und Update validieren den vollständigen Post-State mit identischen
   Regeln. Kein signierter Zustand ohne Methode, Referenz und Zeitpunkt.
6. Integritätshash v2 bindet Transition, Evidence-Content-Hash und
   Publikationsfingerprint statt nur das Ergebnisflag.

### `FIDLEG-STATE-003` – Suitability besitzt widersprüchliche Wahrheiten

#### Ist-Zustand

`SuitabilityCheckCreate` akzeptiert Duty Type, Ergebnis und
Kundenbestätigungsflags direkt aus dem Advisor-Request. Die vorhandene
Validierung koppelt nur „Kunde fährt trotzdem fort“ an ein Warnflag. Sie
erzwingt nicht:

- dass `Keine Prüfung` zum Mandatstyp passt;
- dass `Geeignet` aus Knowledge-, Risk- und Recommendation-Ankern folgt;
- dass ein bestätigender Kunde oder ein Bestätigungszeitpunkt existiert;
- dass überhaupt einer der fünf Evidence-Anker gesetzt ist.

Parallel wertet `audit_mandate_suitability()` den SuitabilityCheck gar nicht
als Source of Truth. Der Service entscheidet die Konformität aus Mandatstyp und
einer lokal geladenen `RiskAssessment`-Zeile. Diese Query filtert nur
`mandate_id` und `is_current=1`; `deleted_at IS NULL` und der zentrale
Exactly-one-Resolver fehlen. Der aktuelle Target-Allocation-/Profilingpfad ist
an dieser Stelle bereits strenger, wird aber nicht wiederverwendet.

#### Reproduktion

Das Requestmodell akzeptierte für einen nicht weiter belegten Check:

```text
{'duty_type': 'Keine Prüfung', 'result': 'Geeignet',
 'client_acknowledged': True, 'ack_at': None,
 'anchors': [None, None, None, None, None]}
```

Ein aktuelles, aber soft-gelöschtes Risikoprofil wurde vom separaten
Compliance-Audit als gültige Eignungsprüfung behandelt:

```text
{'risk_assessment_id': 'ra-deleted',
 'deleted_at': '2026-08-27T09:56:43.436461Z',
 'is_compliant': True, 'logs_with_suitability': 1,
 'audit_degraded': False}
```

#### Risiko

Advisor UI, PDF und Auditstatus können gleichzeitig unterschiedliche Aussagen
tragen: ein frei behaupteter Suitability-Check, ein aus einem gelöschten Profil
abgeleiteter grüner Compliance-Status und eine separate aktuelle Strategie.
Das ist ein kundenrelevanter Hybridzustand, kein bloßer Diagnosefehler.

#### Verbindlicher Fixvertrag

1. Ein zentraler Suitability-Context löst Mandat, Clientklassifikation,
   Mandatstyp, aktuelles Knowledge/Risk, finale Recommendation und erforderliche
   Warn-/Bestätigungs-Evidence exakt auf.
2. Duty Type wird aus Service-/Mandatsart und gültigen Ausnahmen abgeleitet.
   `Keine Prüfung` ist kein frei wählbarer Shortcut.
3. Ergebnis und Einschränkungen werden aus dem Context berechnet oder gegen ihn
   vollständig validiert. Widerspruch endet 409 vor Insert/Renderer.
4. Kundenbestätigung entsteht nur aus verifizierter Portal-/Signatur-Evidence
   mit serverseitigem Zeitpunkt.
5. Alle Konsumenten verwenden den zentralen Exactly-one-RA-Resolver mit
   `deleted_at IS NULL`; soft-gelöschte, fehlende oder mehrdeutige Current-
   Zustände enden fail-closed.
6. SuitabilityCheck, Compliance-Audit, Advisory, Portal und PDFs verwenden
   denselben Context/Fingerprint und geben keine getrennten Wahrheiten aus.

## Empfohlene Umsetzungsreihenfolge

### Block A – Klassifikation zentralisieren

1. Rote API-/Service-/Raw-Row-Tests für beide Bypasspfade schreiben.
2. Direct-Update-Felder schließen und atomaren Transitionservice bauen.
3. Evidence- und Post-State-Domäne definieren.
4. Altbestand inventarisieren; widersprüchliche Kombinationen nicht still
   normalisieren.
5. DB-Versionierung/Constraints und Parallel-409 hinzufügen.

### Block B – Advisory-State und Bestätigung härten

1. Initial-/Terminalstatusvertrag festlegen.
2. Create und Update auf einen Merged-State-Validator umstellen.
3. Signatur-/Portal-Evidence und serverseitige Zeit binden.
4. Hashschema additiv versionieren.
5. Historischen Import getrennt und operatorgebunden halten.

### Block C – eine Suitability-Wahrheit herstellen

1. zentralen Context/Resolver test-first implementieren;
2. `SuitabilityCheckCreate` auf fachliche Inputs statt Ergebnisclaims umstellen;
3. Compliance-Audit auf denselben Context migrieren;
4. Advisory, Portal und PDFs auf Context/Fingerprint umstellen;
5. gelöschte/mehrdeutige/stale Anker überall auf 409 abbilden.

### Block D – Zielumgebungs- und Migrationsgate

1. Altbestandsreport für Klassifikationen, Claims und soft-gelöschte Current-RAs;
2. additive Migrationen mit Daten-Fidelity- und Downgrade-/Restore-Nachweis;
3. Paralleltests unter PostgreSQL/Nicht-Owner-/RLS-Approlle;
4. fokussierte API/PDF/Portal-Suites und vollständiger Backend-Gate auf
   demselben Fixcommit.

## Verbindlicher Testvertrag

Neue oder erweiterte Suites mindestens:

- `5eyes-backend/tests/test_client_classification_transition.py`
- `5eyes-backend/tests/test_client_opt_history_integrity.py`
- `5eyes-backend/tests/test_advisory_state_machine_integrity.py`
- `5eyes-backend/tests/test_advisory_client_confirmation_evidence.py`
- `5eyes-backend/tests/test_suitability_context_integrity.py`
- `5eyes-backend/tests/test_suitability_publication_consistency.py`
- `5eyes-backend/tests/test_fidleg_state_postgres_concurrency.py`

Pflichtfälle:

1. Allgemeiner Client-PUT kann Klassifikation/Opt-out/Qualified nicht ändern.
2. Opt-History lehnt freien Eventtyp, falsches `from`, ungültiges `to`,
   fehlende/fremde Evidence und parallelen stale Übergang ab.
3. Jeder gültige Übergang erzeugt atomar genau eine History-/Auditzeile und den
   dazu passenden Clientzustand.
4. AdvisoryCreate kann nicht in `Beschlossen`, `Umgesetzt`, `Abgelehnt` oder
   `Überarbeitung nötig` starten.
5. Create/Update mit signiertem Claim ohne exakte Evidence/Methode/Serverzeit
   endet 409/422 und speichert keine neue Version.
6. Private-/Beratungsmandat plus `Keine Prüfung` wird abgelehnt; Execution-only
   wird nur mit belegter Ausnahme akzeptiert.
7. `Geeignet` ohne oder gegen Knowledge/Risk/Recommendation endet fail-closed.
8. soft-gelöschte, fehlende, stale und doppelte Current-RA ergeben niemals
   `is_compliant=True`.
9. Advisory JSON, Kundenportal und PDFs zeigen denselben Suitability-Context;
   bei Konflikt wird kein Renderer aufgerufen.

## Definition of Done

Dieser Block ist erst geschlossen, wenn:

- [ ] allgemeine Client-Updates den Klassifikationsworkflow nicht umgehen;
- [ ] jede Klassifikationsänderung serverseitiges `from`, gültiges `to`,
      Evidence und atomare History besitzt;
- [ ] Opt-out/Qualified/Class keine unmöglichen Kombinationen bilden;
- [ ] AdvisoryCreate nur einen definierten Initialstatus erzeugt;
- [ ] alle Endzustände per CAS-Transition und belegtem Kontext entstehen;
- [ ] keine Kundenbestätigung ohne Principal, Methode, Content-Hash und
      Serverzeit existiert;
- [ ] Suitability Duty/Result aus einem verifizierten Context folgt;
- [ ] soft-gelöschte oder mehrdeutige RAs in keinem Compliance-Consumer als
      aktuell gelten;
- [ ] Advisory, Portal, PDF und Audit exakt denselben Context/Fingerprint
      publizieren;
- [ ] Altbestand und Migration ohne stilles Erfinden von Evidence behandelt
      sind;
- [ ] PostgreSQL-Parallelgate, fokussierte Suites und voller Backend-Gate auf
      demselben Fixcommit grün sind;
- [ ] Legal/Compliance, Security und fachlicher Owner den State-Vertrag
      abgenommen haben.

## Claude-Startcheckliste

1. Dieses Dokument und danach alle acht Vorgängerdokumente vollständig lesen.
2. Klassifikationsfelder nicht einzeln validieren; der gesamte Post-State samt
   Evidence ist die Invariante.
3. Einen Audit-/Integritätshash nicht als Beweis einer Kundenhandlung behandeln.
4. Initiale und historische Terminalzustände nicht über denselben öffentlichen
   Create-Pfad zulassen.
5. Advisor-recorded, Portalbestätigung und E-Signatur als getrennte Methoden
   modellieren und sichtbar ausgeben.
6. Den lokalen Suitability-Audit-Loader durch den kanonischen Exactly-one-
   Resolver ersetzen; keinen zweiten Current-Vertrag pflegen.
7. `TEN-COMP-002`, `REC-006` und `PRIV-003` bleiben eigenständige offene
   Verträge; nicht mit diesen Findings als geschlossen markieren.
8. Pro Finding roten Test, Produktfix, Migrations-/PG-Nachweis, fokussierten
   Ring und vollständigen Gate auf demselben Commit dokumentieren.

## Dokumentationsmanifest dieser Runde

Dieses Dokumentationsbatch umfasst exakt:

1. `docs/audits/2026-08-27-client-classification-and-compliance-state-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit dieses Dokuments wird nicht in den eigenen Inhalt eingebettet.
Auflösung ausschließlich extern über `document_commit_resolution`.

## Dokumentations-QA vor Commit

- Direct-Update-/Opt-History-Reproduktion: bestätigt;
- Advisory-Terminal-/Signatur-State-Reproduktionen: bestätigt;
- Suitability-Claim- und soft-deleted-RA-Reproduktionen: bestätigt;
- angrenzender Client-/Advisory-/Suitability-/Signaturring: 98 von 98 Tests
  grün;
- bereits bekannte Signatur-, Evidence- und Retentionfindings abgegrenzt;
- Finding-Register: 3 eindeutige IDs, 3 Detailsektionen;
- Produkt- und Testdateien: unverändert;
- lokale Links, Markdown-Fences, Manifest und `git diff --check`: vor Commit
  vollständig zu prüfen;
- die 53 bekannten ACL-unlesbaren `.pytest_tmp_*`-Verzeichnisse wurden weder
  gelesen noch verändert; deshalb kein globaler Clean-Claim.
