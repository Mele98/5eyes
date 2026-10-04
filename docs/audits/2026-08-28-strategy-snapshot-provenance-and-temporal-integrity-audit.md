---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-strategy-snapshot-provenance-and-temporal-integrity-followup-audit"
status_as_of: "2026-08-28"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "520baf1b8c40eb5c2f2d14a99b9da9db31692af3"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-28-historical-return-schema-and-drift-integrity-audit.md"
prior_release_audit_commit: "520baf1b8c40eb5c2f2d14a99b9da9db31692af3"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md"
audit_mode: "read_only_static_schema_router_frontend_review_isolated_http_and_temporal_reproduction_and_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "binding strategy-snapshot provenance, current decision anchors, input domains, effective-date semantics, latest selection and annual-return cutoff"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 19
focused_adjacent_tests_skipped: 0
focused_adjacent_tests_failed: 0
required_next_action: "either retire the exposed legacy strategy-snapshot workflow or make creation server-derived from one verified current allocation/risk/reference context, then enforce strict domains and effective-date-correct return periods"
---

# Strategy-Snapshot-Provenienz- und Zeitintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die fünfzehnte Read-only-
Kontrollrunde auf Repository-Head `520baf1b`. Er ergänzt, ersetzt aber nicht:

1. den
   [Historische-Renditen-/Schema-/Driftintegritätsaudit](2026-08-28-historical-return-schema-and-drift-integrity-audit.md),
2. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
3. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
4. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
5. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
6. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
7. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
8. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
9. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
10. den
    [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
11. den
    [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
12. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
13. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
14. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
15. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die fünfzehn vorgenannten Dokumente in dieser
Reihenfolge. Ein browserseitig aus dem aktuellen Strategy-State aufgebauter
Request ist kein serverseitiger Provenienznachweis. Ein Datumsstring, dessen
erste vier Zeichen als Jahr parsebar sind, ist kein fachlich korrekter
Effektivzeitpunkt.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Drei weitere P1-Verträge sind offen:

- Der aktive Ablauf „Portfolio umsetzen“ persistiert einen angeblich
  verbindlichen Strategy Snapshot vollständig aus frei übermittelten
  Clientfeldern. Der Server verlangt weder ein aktuelles Risikoprofil noch eine
  aktuelle Soll-Allokation und speichert keinerlei Assessment-, Allocation-,
  Policy-, CMA- oder Context-Hash-Anker.
- Das Create-Schema akzeptiert negative Vermögenswerte, Bool-zu-Integer,
  beliebige Risiko-Scores/-Labels, negative beziehungsweise invertierte Bänder,
  beschädigtes JSON sowie BPS-Summen von 9.950 bis 10.050. Ein gespeicherter
  9.950-bps-Stand erzeugt schon bei fünf exakt 0 %-Returns eine Phantom-Drift
  auf 10.000 bps, die vollständig grün klassifiziert wird.
- `snapshot_date` ist ein freier, clientgesetzter String und bestimmt
  lexikografisch den „latest“-Stand. Ein malformed Datum wird HTTP 201
  gespeichert und macht den Drift-GET anschließend zu HTTP 500; ein Datum im
  Jahr 9999 verdrängt den echten Stand. Außerdem erhält eine am 31.12.
  festgelegte Strategie rückwirkend die Rendite des gesamten Jahres.

Damit kann der als verbindlich bezeichnete Strategieentscheid weder aus dem
persistierten Optimizer-/Risk-Kontext hergeleitet noch zeitlich korrekt
reproduziert werden.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `SNAPSHOT-ANCHOR-001` | P1 | offen | Ein verbindlicher Strategy Snapshot wird ausschließlich serverseitig aus genau einer verifizierten aktuellen TA, RA und deren Policy-/CMA-/Context-Ankern abgeleitet oder der Legacy-Ablauf wird vollständig stillgelegt |
| `SNAPSHOT-DOMAIN-001` | P1 | offen | Vermögen, Score/Profil, BPS, Bänder, JSON und Zusatzfelder besitzen strikte, bool-sichere Fachdomänen; Raw-/Altbestände werden vor jeder Verwendung fail-closed geprüft |
| `SNAPSHOT-TIME-001` | P1 | offen | Effektivdatum, Latest-Selektion und Renditeperioden sind chronologisch valide; Future-/Malformed-Daten können weder persistiert noch einen echten Stand verdrängen, und keine Vorperiodenrendite wird rückwirkend zugerechnet |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Create-Schema mit freien/koerziven Feldern und ±50-bps-Summe | `5eyes-backend/schemas/snapshots.py:6-43` |
| Persistenzmodell ohne Entscheidungsanker, Hashes oder DB-Checks | `5eyes-backend/models/snapshots.py:6-34` |
| POST übernimmt den Request unverändert und prüft nur Mandatszugriff | `5eyes-backend/routers/snapshots.py:89-139` |
| Auditlog-Call enthält weder Ausgangskontext noch Payload-Hash | `5eyes-backend/routers/snapshots.py:130-139`; `5eyes-backend/services/audit.py:59-119` |
| Listen-/Latest-Sortierung auf clientgesetztem String | `5eyes-backend/routers/snapshots.py:143-182` |
| Vier-Zeichen-Year-Parsing und kalenderjährlicher Cutoff | `5eyes-backend/routers/snapshots.py:185-206` |
| Drift normalisiert die Snapshotgewichte erst nach vorhandenen Returns | `5eyes-backend/routers/snapshots.py:208-236` |
| Chart verwendet dasselbe volle Snapshot-Jahr | `5eyes-backend/routers/snapshots.py:238-262` |
| Bewährte exactly-one Resolver für aktuelle RA/TA existieren bereits | `5eyes-backend/services/portfolio_engine.py:380-434` |
| Strikter Risikoableitungsvertrag existiert bereits | `5eyes-backend/services/risk_assessment_semantics.py:198-270` |
| Aktive UI-Aktion „Portfolio umsetzen“ | `5eyes-electron/frontend/5eyes_v2.html:3238`; `:8868-9015`; `:25414-25446` |
| UI sendet Gewichte, Bänder und Risiko erneut als frei änderbaren Body | `5eyes-electron/frontend/5eyes_v2.html:8926-9007` |
| Data Export behandelt Rows als zehn Jahre aufzubewahrende Mandatsdaten | `5eyes-backend/services/data_export.py:61`; `:583-600` |

## `SNAPSHOT-ANCHOR-001` – „Verbindlich“ ist nicht an den Entscheid gebunden

### Aktiver Ablauf

Die Asset-Allokationsseite zeigt nach einer Berechnung die Aktion
„Portfolio umsetzen“. Der nachfolgende Dialog heißt „Strategie verbindlich
festlegen“. JavaScript liest die aktuell im Browser gehaltenen Buckets und
Risikofelder, baut daraus einen vollständigen Request und ruft anschließend
`POST /mandates/{id}/strategy-snapshots` auf.

Das Backend lädt jedoch nur das sichtbare Mandat. Es prüft nicht:

- ob genau eine aktuelle, nicht gelöschte Target Allocation existiert;
- ob diese Allocation einen modernen, vollständigen Context besitzt;
- ob das aktuelle Risikoprofil strategie-ready und fachlich hergeleitet ist;
- ob Assessment, Policy und Snapshot-CMA mit der Allocation übereinstimmen;
- ob Vermögen, Ziele und Präferenzen seit der Berechnung unverändert sind;
- ob die übersandten Gewichte und Bänder exakt der Allocation entsprechen.

Das Modell enthält auch nach dem Write keine `target_allocation_id`,
`risk_assessment_id`, `policy_id`, `capital_market_assumptions_id`,
`input_snapshot_hash`, `allocation_context_hash` oder Schema-/Engine-Version.
Der Auditlog-Eintrag bezeichnet nur Tabelle, Record, Aktion und Mandat; er
bindet weder den Request noch den Quellentscheid kryptografisch.

### Ausgeführte HTTP-Reproduktion

Auf einem Mandat ohne jede RiskAssessment- und TargetAllocation-Row wurde ein
Snapshot gesendet mit:

```text
advisory_assets_rappen = -1
risk_profile_score = 500
risk_profile_label = Kapitalschutz
soll_alternatives_bps = 950
band_equities_lo_bps = 9000
band_equities_hi_bps = -1000
goals_summary_json = {broken
```

Ergebnis:

```text
POST /strategy-snapshots => HTTP 201
persistierte RiskAssessments für Mandat => 0
persistierte TargetAllocations für Mandat => 0
Response enthält alle oben genannten Werte unverändert
```

Der Datensatz heißt damit Strategy Snapshot, obwohl keine persistierte
Strategie existiert, auf die er verweisen könnte.

### Risiko

- Ein manipulierter, veralteter oder durch einen Frontend-Bug gebauter Body
  wird zum zehn Jahre exportierten Beratungsartefakt.
- Später lässt sich nicht beweisen, welcher Optimizerlauf, welches
  Risikoprofil, welche CMA oder welche Kundeninputs „verbindlich“ waren.
- Ein korrekter TargetAllocation-/Recommendation-Publikationsvertrag schützt
  diesen separaten Legacy-Write nicht.
- Eine Browserdarstellung kann die Werte plausibel aussehen lassen, ersetzt
  aber keine serverseitige Revalidierung im Commit-Transaction.

## `SNAPSHOT-DOMAIN-001` – Persistierte Felder besitzen keine geschlossene Domain

### Ausgeführte Schema-Reproduktion

`StrategySnapshotCreate.model_validate()` akzeptierte alle folgenden Fälle:

```text
snapshot_date = "zzzz-not-a-date"
snapshot_date = "9999-12-31"
advisory_assets_rappen = -1
advisory_assets_rappen = True            -> 1
risk_profile_score = True                -> 1
risk_profile_score = 500
risk_profile_label = "Kapitalschutz"     trotz Score 500
band_equities_lo_bps = 9000
band_equities_hi_bps = -1000
goals_summary_json = "{broken"
soll_equities_bps = True                 -> 1
Summe der fünf Sollgewichte = 9950
```

Nur die fünf einzelnen Sollfelder besitzen 0..10.000-Bounds. Pydantic
koerziert Bool weiterhin zu Integer. Vermögen, Score, Profil, Bandfelder und
JSON sind unbeschränkt; die Summenprüfung erlaubt eine Abweichung von 50 bps,
obwohl BPS bereits die ganzzahlige Rundungseinheit sind.

### Ausgeführte Phantom-Drift-Reproduktion

Ein Snapshot mit fünf Gewichten `4000/3000/1000/1000/950` wurde HTTP 201
gespeichert. Für das Folgejahr existierten vollständig fünf Return-Rows mit
je exakt `0` bps.

```text
original sum = 9950
drifted sum  = 10000
delta        = +20/+15/+5/+5/+5 bps
status       = green/green/green/green/green
```

Die Berechnung normalisiert nur, weil ein Jahresdatensatz vorhanden ist. Ohne
Return-Rows bleibt die Summe 9.950. Das bloße Vorhandensein eines mathematisch
wirkungslosen 0-%-Jahres erzeugt somit eine gemeldete Allokationsänderung.

### Risiko

- Invertierte Bänder machen die Ampellogik fachlich beliebig; negative oder
  übergroße Bänder werden nicht als Datenfehler erkannt.
- Score und Profil können sich widersprechen, obwohl beide im Ergebnis
  gemeinsam angezeigt werden.
- Negative Vermögenswerte und beschädigte JSON-Strings bleiben langfristig
  persistiert und exportierbar.
- Bool-Werte werden zu scheinbar legitimen Finanzzahlen und entziehen sich
  späteren Typprüfungen, weil in der DB nur noch `0` oder `1` steht.
- Eine tolerant gespeicherte Gewichtsunterdeckung wird durch Normalisierung
  nachträglich in einen anderen, weiterhin „grünen“ Zustand verwandelt.

## `SNAPSHOT-TIME-001` – Latest und Renditebeginn sind zeitlich falsch

### Malformed und Future bestimmen „latest“

`snapshot_date` ist ein beliebiger String. Liste und Drift sortieren
lexikografisch nach diesem Wert, erst danach nach `created_at`. Der Driftcode
parst anschließend blind `int(snapshot.snapshot_date[:4])`.

Ausgeführte HTTP-Reproduktion:

```text
POST snapshot_date="zzzz-not-a-date" => HTTP 201
GET  /latest/drift                   => HTTP 500
ValueError: invalid literal for int() with base 10: 'zzzz'
```

Auf einem zweiten Mandat wurde zuerst `2025-01-01`, danach `9999-12-31`
gespeichert:

```text
beide POSTs                         => HTTP 201
erste Row in GET /strategy-snapshots => 9999-12-31
GET /latest/drift                  => HTTP 200
snapshot_date                      => 9999-12-31
has_drift_data                     => False
```

Der valide historische Stand ist damit durch einen Future-String verdeckt.
Ein fachlicher Delete-/Rollback-Endpoint für diesen Fehler existiert nicht.

### Volljahresrendite wird vor dem Effektivdatum zugerechnet

Der Reader reduziert das Datum auf das Jahr und lädt `return.year >=
snapshot_year`. Dadurch erhält jede Strategie die komplette Jahresrendite des
Snapshotjahres, unabhängig von Monat und Tag.

Ausgeführt wurden zwei ansonsten identische Mandate mit Effektivdaten
`2025-01-01` und `2025-12-31`. Für 2025 betrug die Aktienrendite 100 %, alle
anderen Buckets 0 %.

```text
01.01.-Snapshot: chart_years [2025, 2025], chart [100.0, 140.0]
31.12.-Snapshot: chart_years [2025, 2025], chart [100.0, 140.0]
beide drifted:   Aktien 5714 bps, Bonds 2143 bps, Rest je 714 bps
```

Die am letzten Tag des Jahres festgelegte Strategie bekommt somit dieselbe
volle Rendite wie die am ersten Tag. Die doppelte Jahresbeschriftung verbirgt
zusätzlich, dass Startzustand und angewandtes Renditejahr denselben Labelwert
tragen.

### Risiko

- Ein Tippfehler kann den Endpoint dauerhaft auf 500 setzen.
- Ein Future-Datum kann jeden späteren echten Snapshot bis zu diesem Datum
  unsichtbar machen.
- Die Performance zwischen Jahresbeginn und tatsächlicher Strategiefestlegung
  wird der neuen Strategie rückwirkend zugerechnet.
- Review-Ampel und Chart wirken rechnerisch konsistent, beruhen aber auf einer
  Periode, in der die Strategie noch gar nicht galt.

## Verbindlicher Fixvertrag

### Zuerst eine bewusste Produktentscheidung

1. Der Ablauf wird entweder vollständig stillgelegt oder als modernes,
   serverseitig abgeleitetes Entscheidungsartefakt neu gebaut.
2. **Stilllegung** bedeutet: aktive UI-Aktion und POST/Latest-Drift-Routen
   entfernen beziehungsweise klar `410 Gone`; historische Rows bleiben nur
   unveränderbar im Export. Ein verborgenes Frontend ohne API-Stilllegung
   genügt nicht.
3. **Beibehaltung** bedeutet: Der Request enthält höchstens Effektivdatum,
   optionale Notiz und einen erwarteten Entscheidungs-Fingerprint. Gewichte,
   Bänder, Risiko, Vermögen, Goals und Modellbasis werden nie vom Client als
   autoritative Werte übernommen.

### Server-Derivation und Provenienz

4. Im Write-Transaction exakt eine aktuelle, nicht gelöschte TA und RA über
   die bestehenden exactly-one Resolver laden und gegen Race sperren.
5. Die RA mit `validate_risk_assessment_model_input()` vollständig prüfen; die
   TA muss moderner Context sein und durch den kanonischen
   `build_target_payload_from_allocation()`-Rebuild ohne Inputdrift laufen.
6. TA-Assessment, referenzierte Policy und Snapshot-CMA müssen exakt zum
   Mandat, Client, Tenant und zur Jurisdiktion passen. Aktuelle Live-Referenzen
   ersetzen keinen Snapshotanker.
7. Persistiert werden mindestens `target_allocation_id`,
   `risk_assessment_id`, `policy_id`, `capital_market_assumptions_id`,
   `input_snapshot_hash`, `allocation_context_hash`, Engine-/Schema-Version,
   effektive Buckets/Bänder, Advisory-Wealth sowie ein kanonischer
   `strategy_snapshot_hash`.
8. Vor Commit werden Anchor-IDs und Fingerprint erneut geprüft. Ein
   zwischenzeitlicher Rollover führt zu 409, nicht zu einem hybriden Snapshot.
9. Der Auditlog bindet Snapshot-ID, Anchor-IDs und Hash; sensible Freitexte
   werden nicht unredigiert ins Log dupliziert.

### Strikte Fachdomänen

10. Pydantic-Modelle verwenden `extra='forbid'` und Before-Validatoren, die
    Bool für jedes numerische Feld ablehnen.
11. `advisory_assets_rappen` ist ein nichtnegativer exakter Integer und wird
    serverseitig aus dem verifizierten Allocation-Kontext übernommen.
12. Effektiver Risikoscore liegt exakt in 0..100 und das Profil entspricht der
    zentralen Score-Mapping-Funktion; Override-Semantik bleibt vollständig
    erhalten. Der Server leitet beides aus der verifizierten RA ab.
13. Jedes Gewicht liegt in 0..10.000 und die fünf Gewichte summieren sich exakt
    auf 10.000. Keine ±50-bps-Toleranz im persistierten Endzustand.
14. Bänder sind entweder paarweise NULL oder exakte Integer in 0..10.000 mit
    `lo <= target <= hi`. Invertierte, einseitige und fachlich unmögliche Bänder
    scheitern vor Mutation.
15. Goals werden als typisiertes, kanonisches Server-Snapshot gespeichert,
    nicht als beliebiger JSON-String. Notes besitzen Längen-/Zeichenvertrag.
16. DB-CHECKs und Foreign Keys sichern die invarianten Teile auf SQLite und
    PostgreSQL; Runtime validiert Raw-/Legacy-Rows defense-in-depth.

### Effektivzeit, Latest und Renditeperioden

17. `snapshot_date` ist ein echter ISO-`date`-Typ. Malformed, Future und ein
    Datum vor dem Quellentscheid scheitern mit 422 beziehungsweise 409.
18. Der effektive Zeitpunkt wird bevorzugt serverseitig aus dem
    Commit-/Set-at-Zeitpunkt erzeugt. Jede erlaubte fachliche Rückdatierung ist
    explizit autorisiert und auditierbar.
19. „Current“ wird durch einen genau-einen DB-Vertrag beziehungsweise den
    gebundenen Entscheidungsstand bestimmt, nicht durch lexikografisches
    Sortieren freier Strings. Reihenfolge erhält einen finalen stabilen
    Tie-Breaker.
20. Annual Returns dürfen nur für vollständig nach dem Effektivzeitpunkt
    liegende Perioden verwendet werden. Bei einem Snapshot exakt am 1. Januar
    kann dieses Kalenderjahr zulässig sein; bei jedem späteren Datum beginnt
    der erste volle Jahresbucket im Folgejahr. Alternativ ist für die
    Teilperiode der kanonische Daily-Pfad zu verwenden.
21. Chartlabels unterscheiden Effektivdatum und jeweiliges Periodenende; keine
    doppelte Jahresbeschriftung. Dataset-Version, As-of, Source und Hash werden
    gemeinsam mit dem Snapshot gebunden.

### HTTP-Vertrag

22. Malformed/außerhalb der Requestdomain: 422. Fehlende, alte oder während
    des Writes gewechselte Entscheidungsanker: 409. Unsichtbares Mandat: 404.
23. Ein fachlich ungültiger persistierter Altbestand führt beim List-/Drift-
    Reader zu sicherem Domainkonflikt; niemals zu HTTP 500 oder partieller 200.
24. Fehlgeschlagene Writes hinterlassen weder StrategySnapshot noch
    Erfolgsauditlog. Idempotency-Key beziehungsweise Fingerprint verhindert
    doppelte „verbindliche“ Entscheide durch Retry/Doppelklick.

## Verbindliche Testmatrix

### Schema, Migration und Raw-Daten

- Bool, Float, Stringzahl, negative Assets, Score außerhalb 0..100,
  Score/Profile-Mismatch, malformed/future date, beschädigtes JSON,
  unbekannte Extra-Keys und überlange Note scheitern.
- Gewichtssummen 9.950, 9.999, 10.001 und 10.050 scheitern; exakt 10.000
  roundtrippt.
- Bänder: einseitig, negativ, >10.000, invertiert und Ziel außerhalb Band
  scheitern.
- SQLite-Raw, ORM und Alembic enthalten dieselben FKs/CHECKs/Current-
  Invarianten. Raw korrupte Rows lassen Reader fail-closed enden.

### Anchor- und Race-Vertrag

- Kein aktuelles RA, kein aktuelles TA, Legacy-TA, Inputdrift, fehlende oder
  gelöschte Policy/CMA und ID-/Tenant-/Jurisdiktionsmismatch ergeben 409; keine
  Row und kein Erfolgslog.
- Clientseitig manipulierte Gewichte, Bänder, Score, Profil oder Vermögen
  werden nicht übernommen beziehungsweise bei erwartetem Fingerprint als 409
  erkannt.
- Zwei parallele Writes auf denselben Entscheid erzeugen genau einen Snapshot
  oder exakt denselben idempotenten Response; kein 500 und keine zwei Logs.
- TA-/RA-Rollover zwischen Resolve und Commit führt sicher zu 409.

### Zeit und Rendite

- Malformed Date wird beim POST 422 und kann keinen späteren GET beschädigen.
- Future Date kann einen echten Snapshot nicht verdrängen.
- Snapshot am 01.01. und 31.12. desselben Jahres verwenden nach dem expliziten
  Periodenvertrag unterschiedliche zulässige Renditezeiträume; der 31.12.-
  Snapshot erhält niemals die volle zurückliegende Jahresrendite.
- Chartlabels sind monoton, eindeutig und tragen klare As-of-/Periodenenden.
- 0-%-Returns verändern eine gültige 10.000-bps-Allokation exakt nicht.

### UI und End-to-End

- „Portfolio umsetzen“ sendet nur Note/erlaubtes Datum plus erwarteten
  Fingerprint, keine autoritativen Strategy-Felder.
- Stale Browser-State, Doppelklick und Netzretry erzeugen keinen Hybrid- oder
  Duplicate-Snapshot.
- Nach erfolgreichem Write zeigt Response/Auditblock die exakten Quellanker
  und den Snapshot-Hash; anschließender PDF-Aufruf konsumiert denselben
  verifizierten Entscheidungsstand.
- Falls der Legacy-Ablauf stillgelegt wird, existieren weder aktiver Button
  noch mutierende Route oder autoritativer Latest-Drift-Consumer.

## Empfohlene Umsetzungsreihenfolge

1. Product Owner entscheidet dokumentiert: Legacy-Feature stilllegen oder
   als modernen, gebundenen Strategy-Commit weiterführen.
2. Vor Migration Altbestand auf malformed/future dates, 10.000-Summen,
   Banddomain, Risk-Konsistenz und rekonstruierbare Anchor-Bezüge inventarisieren.
3. Additive Schema-/Migrationserweiterung und Raw-SQLite-Parität einführen;
   nicht rekonstruierbare Rows niemals still als modern markieren.
4. Zentralen serverseitigen Snapshot-Builder aus der verifizierten aktuellen
   TA/RA/Policy/CMA-Basis implementieren.
5. POST, Liste, Latest und Drift auf Domain-, Anchor- und Zeitvertrag umstellen.
6. Frontend auf minimalen Request/Fingerprint und sichere Fehlerzustände
   umstellen oder vollständig entfernen.
7. Schema-, Raw-, Parallel-, Migrations-, HTTP-, UI-, Drift- und echte
   PostgreSQL-Tests ausführen.

## Definition of Done

Die drei Findings gelten erst als geschlossen, wenn gleichzeitig:

- der Legacy-Ablauf vollständig stillgelegt oder jeder neue Snapshot aus
  genau einem verifizierten modernen Entscheidungscontext serverseitig
  abgeleitet wird;
- Assessment-, Allocation-, Policy-, CMA-, Input- und Context-Anker samt Hash
  dauerhaft nachvollziehbar sind;
- Score/Profil, Assets, Gewichte, Bänder, Goals und Notes strikte Fachdomänen
  besitzen und DB/Runtime dieselben Invarianten erzwingen;
- kein malformed/future Datum persistiert oder den Latest-Stand beeinflusst;
- keine vor dem Effektivzeitpunkt liegende Jahresrendite zugerechnet wird;
- 0-%-Daten keine Phantom-Drift erzeugen;
- API-, Raw-, Race-, Migration-, Zeit-, UI- und echte PostgreSQL-Tests grün
  sind;
- der vollständige Backend-/Frontend-Gate auf dem Fixcommit erneut grün ist;
  und
- dieser Audit mit Fixcommit, Migration, Testzahlen und Restpunkten
  aktualisiert oder durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an Strategy Snapshots, „Portfolio umsetzen“ oder Drift:

1. Diesen Audit vollständig lesen.
2. Zuerst Stilllegung versus modernes Entscheidungsartefakt klären.
3. Niemals Browser-State als Autorität oder Provenienznachweis behandeln.
4. Bestehende exactly-one-RA/TA-Resolver und den strikten Allocation-Rebuild
   wiederverwenden; keine parallele Fachlogik erfinden.
5. Kein Gewicht, Band, Score, Profil oder Vermögen ungeprüft aus dem Request
   persistieren.
6. Keine ±50-bps-Toleranz für einen verbindlichen Endzustand.
7. Datum als echten Typ und Renditeperioden relativ zum exakten Effektivdatum
   modellieren.
8. Latest nie durch freien String oder `.first()` ohne Eindeutigkeitsvertrag
   bestimmen.
9. Raw-/Legacy-Snapshots nicht still zu modernen Anchors hochstufen.
10. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline- und Audit-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Der fokussierte bestehende Snapshot-/Schema-/Permission-/Lifecycle-Ring auf
dem auditierten Head ergab:

```text
19 passed, 114 deselected in 9.87s
```

Diese grünen Positivtests widerlegen die Findings nicht. Sie prüfen BPS-
Einzelbounds, grobe Summenabweichung, Berechtigung, Auditlog-Erzeugung und den
`created_at`-Tie-Breaker. Sie enthalten weder Create ohne Strategieanker,
malformed/future date, negative/koerzierte Felder, invertierte Bänder,
9.950-bps-Phantomdrift noch den 31.12.-Volljahresrückblick.
