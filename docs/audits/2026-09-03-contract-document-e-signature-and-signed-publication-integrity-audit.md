---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-contract-document-e-signature-signed-publication-integrity-followup-audit"
status_as_of: "2026-09-03"
audit_started_on: "2026-09-03"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "2d364de372e65aa16739a3301777b12bb2808850"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md"
prior_release_audit_commit: "2d364de372e65aa16739a3301777b12bb2808850"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md"
audit_mode: "read_only_static_router_service_orm_schema_migration_pdf_html_test_review_deterministic_runtime_reproduction_existing_focused_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "contract-document creation and status lifecycle, UI-to-PDF content mapping, signed-byte and revision binding, advisor and client signer identity, signature artifact validation, idempotency and concurrency, database invariants, contract-signoff claims, recommendation finalization eligibility, API and UI status semantics"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_existing_tests_passed: 17
focused_existing_tests_deselected: 97
focused_existing_tests_failed: 0
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "replace mutable contract rows and detached live PDFs with one immutable versioned SignedPublicationSnapshot bound to exact rendered bytes and exact final advisory context; separate authenticated signer from recording actor, validate decoded signature artifacts, use atomic state transitions and database invariants, and require evidence-backed suitability cost delivery and approval gates before any signed or final claim"
---

# Vertragsdokument-/E-Signatur-/signierte-Publikations-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die vierundzwanzigste Read-only-
Kontrollrunde. Er wurde gegen den unveränderten Repository-Head `2d364de`
durchgeführt und am 3. September 2026 konsolidiert. Produktcode und Tests
blieben unverändert.

Er ergänzt, ersetzt und schließt insbesondere nicht:

1. den unmittelbar vorherigen
   [Portfolio-Handoff-/Handelsinstruktions-/Ausführungsnachweis-Integritätsaudit](2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md),
2. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
3. den grundlegenden
   [Post-Commit-Integritätsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
4. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
5. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
6. den
   [Ex-ante-Kosten-/Retrozessions-/Konfliktnachweis-Integritätsaudit](2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md),
7. den
   [Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Integritätsaudit](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md),
8. sowie den
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Laufzeitbelege
zuerst, danach dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu `REC-006`, `REP-005`, `REC-003` und Kontrollrunde 23

Die Audits vom 25. August hatten bereits festgestellt:

- `REC-006`: Ein unterzeichnetes Dokument kann überschrieben werden;
- `REP-005`: Finaler Produktstand und Kundensignatur sind nicht gebunden;
- `REC-003`: Provisorische Empfehlungen können Final und Handoff werden.

Kontrollrunde 23 hat zusätzlich bestätigt, dass der Portfolio-Handoff weder
Signatur noch Approval, Suitability oder Kostenevidenz verlangt. Diese Befunde
sind **weiterhin offen**.

Kontrollrunde 24 bestätigt `REC-006` und `REP-005` erneut und erweitert sie um
den tatsächlichen Cross-Layer-Vertrag: Das UI speichert andere Inhaltsfelder,
als der Vertrags-PDF-Renderer liest; sein Druckbutton druckt aktuelle
Bildschirmkapitel statt des gespeicherten Dokuments; die Signatur wird nicht an
PDF-Bytes oder eine Revision gebunden; und der getrennte „Beratungsentscheid“-
PDF behauptet Finalität, Geeignetheit, Kostenaufklärung und Unterlagenübergabe,
ohne diese Nachweise als Input zu besitzen.

## Kurzurteil

Der aktuelle Stand darf **nicht** als belastbare elektronische Unterzeichnung
eines bestimmten Beratungs- oder Strategiedokuments freigegeben werden.

Bestätigt sind insbesondere:

1. `ContractDocument` besitzt keine Anker auf RecommendationRun,
   TargetAllocation, RiskAssessment, SuitabilityCheck, Kostensnapshot oder
   Publikationsfingerprint.
2. Alle fünf vom UI gespeicherten fachlichen Felder werden vom Vertrags-PDF-
   Parser ignoriert.
3. „Kapitel drucken“ übergibt nur den Dokumenttyp und druckt aktuelle UI-
   Kapitel; die gespeicherte Dokument-ID und ihr Inhalt fehlen.
4. `pdf_path`, `pdf_generated_at` und `checksum_sha256` haben im geprüften
   Produktpfad keinen Writer; Sign verlangt keines dieser Felder.
5. Ausschließlich ein Advisor-/Admin-Endpoint signiert sowohl Berater als auch
   Kunde. Der Name ist frei, und als Kunden-IP wird die IP des Advisor-Requests
   gespeichert.
6. `data:image/` als Präfix genügt. Ungültiges Base64 und ein beliebiger
   `image/*`-Subtype wurden akzeptiert.
7. Wiederholte Kundensignatur überschreibt Bild, Namen, IP und spezifischen
   Zeitpunkt in derselben Version.
8. Zwei stale Signaturreads können beide Flags setzen, aber den Status als
   `Teilweise unterzeichnet` hinterlassen.
9. ORM/Alembic/Raw-SQL-Bootstrap erzwingen unterschiedliche und unvollständige
   Invarianten; selbst der stärkere Raw-SQL-Vertrag bindet `Unterzeichnet`
   nicht an zwei Artefakte.
10. Der separate Contract-Signoff-PDF wird live neu erzeugt, enthält leere
    Unterschriftslinien, nimmt keine gespeicherten Signaturbilder entgegen und
    bezeichnet den neuesten beliebigen RecommendationRun als finale
    Empfehlung.
11. Die Recommendation-Finalisierung verlangt weder Allocation-Approval,
    Kunden-/Beratersignatur, Suitability- noch Kostennachweis und behandelt
    fehlende oder stale Preise nur als Warnung.
12. Das Frontend zählt „signiert“ je nach Kachel unterschiedlich und zählt
    selbst `Unterzeichnet` als „in Arbeit“, weil es auf den nie verwendeten
    Status `Final` prüft.

Ein grüner Bestands-Gate hebt diese Befunde nicht auf. Seine Tests prüfen die
existierenden Teilverträge, nicht die Identität der gesehenen und signierten
Bytes.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `SIGN-CONTEXT-001` | P1 | bestätigt | Das signierte Datenmodell ist nicht an Final-Run, TA, RA, Suitability, Kosten, Produkte, Holdings oder einen Publikationsfingerprint gebunden. |
| `SIGN-CONTENT-001` | P1 | bestätigt | UI und Vertrags-PDF verwenden disjunkte JSON-Feldnamen; gespeicherter Inhalt und gerenderter Inhalt weichen reproduzierbar ab. |
| `SIGN-PRINT-001` | P1 | bestätigt | Der sichtbare Druckpfad ignoriert Dokument-ID und Inhalt und druckt live zusammengesetzte UI-Kapitel. |
| `SIGN-HASH-001` | P1 | bestätigt | Signatur und Status sind nicht an kanonische Payload-/PDF-Bytes gebunden; Checksum-/PDF-Felder bleiben leer. |
| `SIGN-IDENTITY-001` | P1 | bestätigt | Ein Advisor/Admin kann die Kundenrolle mit frei gesetztem Namen behaupten; es gibt keinen kunden-authentifizierten ContractDocument-Signaturpfad. |
| `SIGN-ARTIFACT-001` | P1 | bestätigt | Signature-Image-Validierung prüft nur Präfix/Länge; ungültiges Base64 und beliebige Image-MIME werden persistiert. |
| `SIGN-IMMUTABILITY-001` | P1 | bestätigt | `REC-006` bleibt offen: Re-Sign überschreibt dasselbe Artefakt ohne neue Version oder 409. |
| `SIGN-CONCURRENCY-001` | P1 | bestätigt | Read-then-write ohne Lock/CAS kann Flags, Status und generischen Signaturzeitpunkt widersprüchlich kombinieren. |
| `SIGN-STATE-001` | P1 | bestätigt | Es fehlt ein dialektgleicher DB-Vertrag für Status, Flags, Artefakte, Hash, Version und erlaubte Übergänge. |
| `SIGN-CLAIM-001` | P1 | bestätigt | Der „finale“ Signoff-PDF behauptet Geeignetheit, Kostenaufklärung, Dokumentübergabe und Finalempfehlung ohne gebundene Evidenz. |
| `SIGN-ELIGIBILITY-001` | P1 | bestätigt | `Final` bedeutet nicht approved/signed/suitable/cost-disclosed/price-complete; diese Voraussetzungen werden nicht geprüft. |
| `SIGN-UI-STATE-001` | P2 | bestätigt | Drei UI-Berechnungen verwenden verschiedene Definitionen für signiert/in Arbeit und können DB-Inkonsistenzen verdecken. |

## Tatsächlicher Daten-, Druck- und Signaturfluss

```text
Advisor-Cockpit
  |
  | POST /mandates/{id}/documents
  | content_json = {
  |   intro, disclaimer, special, place, sign_date, client_name
  | }
  v
ContractDocument
  status=Entwurf, version=1
  pdf_path=NULL
  checksum_sha256=NULL
  kein Recommendation-/TA-/RA-/Evidence-Anker
  |
  +--> "Kapitel drucken"
  |      printDocumentTypeReport(document_type)
  |      -> printReport({pages: ...})
  |      -> aktuelle HTML-Kapitel, keine doc_id, kein content_json
  |
  +--> optionaler Server-PDF-Pfad /reports/vertrag.pdf?document_id=...
  |      liest andere Keys:
  |      praeambel, haftungsklausel, sondervereinbarungen,
  |      ort_unterzeichnung/ort, vereinbarungs_datum/datum
  |
  +--> POST /documents/{doc_id}/sign  [require_advisor]
         signed_by_advisor ODER signed_by_client
         freier signer_name + data:image/...-String
         -> Flags/Bild/Name/Zeit/IP werden in derselben Zeile überschrieben
         -> kein expected_version, kein payload_hash, keine PDF-Bytes

Separater Pfad:
GET /reports/contract-signoff.pdf
  -> aktuelle TA/RA/Policy/CMA live auflösen
  -> alle jüngsten AdvisoryLog-Zeilen lesen
  -> neuesten RecommendationRun unabhängig vom Status lesen
  -> Standard-Bestätigungen und leere Signaturlinien rendern
  -> kein ContractDocument, keine gespeicherten Signaturbilder, kein Hash
```

Damit existieren mindestens drei verschiedene Dinge:

1. gespeicherter Dokumententwurf,
2. aktuell gedruckte HTML- beziehungsweise live gerenderte PDF-Ausgabe,
3. mutable Signaturmetadaten.

Es gibt keinen Beleg, dass alle drei dieselben Bytes und denselben fachlichen
Stand repräsentieren.

## Codeanker auf dem auditierten Head

| Bereich | Pfad |
|---|---|
| ContractDocument-ORM | `5eyes-backend/models/review.py:31-69` |
| Create-/Sign-Schemas | `5eyes-backend/schemas/review.py:233-295` |
| Dokument-Create | `5eyes-backend/routers/review.py:963-995` |
| Dokument-Signatur | `5eyes-backend/routers/review.py:998-1042` |
| Recommendation-Finalisierungsgate | `5eyes-backend/routers/review.py:137-216` |
| Recommendation-Finalisierung | `5eyes-backend/routers/review.py:2290-2338` |
| Vertrags-PDF-Datenparser | `5eyes-backend/routers/pdf_reports.py:1177-1251` |
| Vertrags-PDF-Endpoint | `5eyes-backend/routers/pdf_reports.py:1253-1275` |
| Contract-Signoff-Daten | `5eyes-backend/routers/pdf_reports.py:1278-1310` |
| Contract-Signoff-Endpoint | `5eyes-backend/routers/pdf_reports.py:1336-1362` |
| Protokoll-/Recommendation-Auswahl | `5eyes-backend/routers/pdf_reports.py:1365-1482` |
| PDF-Datenklassen | `5eyes-backend/services/pdf/base.py:208-241` |
| Signoff-Claims/Unterschriftslinien | `5eyes-backend/services/pdf/documents/contract_signoff.py:28-146` |
| Standardbestätigungen | `5eyes-backend/services/pdf/documents/contract_signoff.py:274-282` |
| Frontend-Dokumentgrid/Druck | `5eyes-electron/frontend/5eyes_v2.html:24240-24284` |
| Frontend-Entwurfspayload | `5eyes-electron/frontend/5eyes_v2.html:24839-24888` |
| Frontend-E-Signatur | `5eyes-electron/frontend/5eyes_v2.html:24890-25015` |
| Frontend-Kapiteldruck | `5eyes-electron/frontend/5eyes_v2.html:8096-8106` |
| Raw-SQL-Bootstrap | `5eyes-backend/5eyes_schema_v4.0_FINAL.sql:957-994` |
| Alembic-Baseline | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:734-768` |
| additive SQLite-Signaturspalten | `5eyes-backend/database.py:630-642` |
| bestehende Signaturtests | `5eyes-backend/tests/test_runtime_contracts.py:3916-4030` |
| bestehende Signoff-PDF-Tests | `5eyes-backend/tests/pdf/test_contract_signoff.py:1-146` |

## `SIGN-CONTEXT-001` – Signatur ohne signierten Entscheidungskontext

### Beobachtung

`ContractDocument` speichert im Wesentlichen:

- Mandats-ID,
- Typ, Titel und freies `content_json`,
- optionale PDF-/Checksumfelder,
- Status und zwei Signaturflags,
- Signaturbilder/-namen/-zeiten/-IPs,
- Version und `supersedes_id`.

Es fehlen direkte, unveränderliche Anker auf:

- `recommendation_run_id`,
- `target_allocation_id`,
- `risk_assessment_id`,
- `suitability_check_id`,
- `cost_disclosure_snapshot_hash`,
- Produkt-/Holdings-/Valuation-Snapshot,
- `publication_fingerprint`,
- Renderer-/Template-/Methodikversion,
- Hash der tatsächlich gesehenen und signierten Bytes.

Das Create-Schema kennt nur Dokumenttyp, Titel, optionalen Stringinhalt und
Datenklassifikation. Der Sign-Request kennt nur Rollenflags, Bild und freien
Namen. Ein Signer kann folglich keinen erwarteten Dokumentstand mitsenden, und
der Server kann keinen Drift erkennen.

### Reproduktion

Die introspektierte Tabelle fehlte vollständig um folgende Contextspalten:

```text
missing_context_columns:
['cost_disclosure_hash',
 'publication_fingerprint',
 'recommendation_run_id',
 'risk_assessment_id',
 'signed_payload_hash',
 'suitability_check_id',
 'target_allocation_id']
```

### Fixvertrag

Die Signatur darf nicht auf eine mutable Mandatszeile oder einen freien JSON-
String zeigen. Vor der ersten Signatur ist ein kanonischer
`SignedPublicationSnapshot` zu erzeugen, der alle entscheidungswirksamen IDs,
Versionen und Hashes enthält und nach `READY_FOR_SIGNATURE` unveränderlich ist.

## `SIGN-CONTENT-001` – Gespeicherter UI-Inhalt ist nicht der PDF-Inhalt

### Beobachtung

Das Frontend speichert:

```json
{
  "intro": "...",
  "disclaimer": "...",
  "special": "...",
  "place": "...",
  "sign_date": "...",
  "client_name": "..."
}
```

`_build_vertrag_data()` liest dagegen:

```text
praeambel
haftungsklausel
sondervereinbarungen
ort_unterzeichnung oder ort
vereinbarungs_datum oder datum
```

Nur Titel und Dokumenttyp werden aus denselben Top-Level-Spalten übernommen.
Die fünf fachlichen UI-Felder fallen still auf Renderer-Defaults zurück.

### Deterministische Reproduktion

Ein Entwurf mit eindeutigen Markerwerten ergab:

```text
ui_intro_reaches_pdf: False
ui_disclaimer_reaches_pdf: False
ui_special_reaches_pdf: False
ui_place_reaches_pdf: False
ui_date_reaches_pdf: False
```

Das ist keine kosmetische Abweichung. Ein Kunde kann im UI einen spezifischen
Text sehen oder erwarten, während der Server-PDF einen anderen Standardtext,
anderen Ort und anderes Datum rendert.

### Fixvertrag

Es gibt genau ein versioniertes, strikt validiertes Content-Schema. Frontend,
API, Persistenz und Renderer verwenden dieselben Feldnamen und dieselbe
kanonische Serialisierung. Unbekannte oder fehlende Pflichtfelder schlagen vor
`READY_FOR_SIGNATURE` fail-closed fehl; stille Defaults sind im finalen Modus
unzulässig.

## `SIGN-PRINT-001` – Sichtbarer Druckpfad ignoriert das Dokument

Die Dokumentkarte besitzt zwar `data-docid`, aber ihr Druckhandler ruft nur auf:

```javascript
printDocumentTypeReport(String(doc.document_type || 'Dokument'));
```

Die Funktion übersetzt den Typ in Seitenkürzel und ruft
`printReport({pages: ...})`. Weder Dokument-ID noch Version noch `content_json`
werden übergeben.

Der separate Backendendpoint `/reports/vertrag.pdf?document_id=...` existiert,
wird von dieser Aktion aber nicht verwendet. Selbst dieser Endpoint persistiert
seine Ausgabe nicht in `pdf_path`, `pdf_generated_at` oder
`checksum_sha256`.

### Fixvertrag

Eine Dokumentkarte öffnet ausschließlich das serverseitig finalisierte Artefakt
für ihre exakte Snapshot-ID und Version. Preview und Final müssen sichtbar
getrennt sein. Der finale Download liefert dieselben Bytes, deren Hash im
Signaturereignis gebunden ist.

## `SIGN-HASH-001` – Keine Bindung an Payload- oder PDF-Bytes

### Beobachtung

Die ORM-Spalten `pdf_path`, `pdf_generated_at` und `checksum_sha256` suggerieren
einen Artefaktvertrag. Im auditierten Backend und Frontend existiert jedoch
außer der Model-/Schema-Definition kein Writer für diese Felder.

Create und Sign erzeugen keine PDF-Bytes. Sign prüft weder Checksumme noch
Version und nimmt keinen Fingerprint entgegen. Der Auditlog enthält beim Sign
nur `field_name="status"` und den neuen Status.

### Reproduktion

```text
created_checksum: None
created_pdf_path: None
checksum_after_sign: None
pdf_path_after_sign: None
audit_new_values: [None, 'Teilweise unterzeichnet', 'Teilweise unterzeichnet']
audit_binds_signature_bytes: False
vertrag_data_has_signature_fields: False
```

Der erste Auditwert `None` gehört zum Create-Ereignis. Auch beide Sign-
Ereignisse enthalten nur den Status, nicht Dokument- oder Signaturhash.

### Fixvertrag

Vor der Signatur werden kanonische Payloadbytes und finale PDF-Bytes erzeugt.
Mindestens `payload_sha256`, `pdf_sha256`, `renderer_version`,
`template_version`, Byte-Länge, MIME und Erzeugungszeitpunkt werden
unveränderlich gespeichert. Jedes Signaturereignis bindet exakt diese Hashes.

## `SIGN-IDENTITY-001` – Advisor behauptet die Kundenidentität

### Beobachtung

Der einzige ContractDocument-Signaturendpoint verwendet `require_advisor`.
Diese Dependency erlaubt `advisor` und `admin`. Derselbe Endpoint akzeptiert
wahlweise `signed_by_advisor=True` oder `signed_by_client=True`.

Ein eigener kunden-authentifizierter ContractDocument-Signaturendpoint fehlt.
Der Kundenname kommt als frei editierbarer String aus dem Advisor-Cockpit. Die
gespeicherte `signature_client_ip` ist die Quell-IP dieses Advisor-Requests.

Der vorhandene Kundenportalpfad signiert ausschließlich das aktuelle
Risikoprofil; er ist kein ContractDocument-Signaturpfad.

### Reproduktion

```text
caller_role: advisor
advisor_can_assert_client_signature: True
client_ip_is_advisor_request_ip: 10.24.0.10
client_signer_name_after_resign: Andere Behauptung
```

### Fixvertrag

`signer_subject_id` und `recorded_by_actor_id` sind getrennte Felder:

- direkte Kundensignatur: authentifizierter Kundenprincipal, Challenge/Nonce,
  Session-/Authentisierungsniveau und serverseitige Identitätsauflösung;
- Beratersignatur: authentifizierter Advisorprincipal und serverseitiger Name;
- beobachtete/offline Signatur: eigener Evidence-Typ mit Witness, Methode,
  hochgeladenem signiertem Artefakt und klarer Aussage, dass der Advisor nur
  dokumentiert, nicht als Kunde signiert.

Ein freier Name darf niemals allein die Signer-Identität bilden.

## `SIGN-ARTIFACT-001` – Präfixprüfung ersetzt keine Bildvalidierung

Das Schema prüft:

1. String beginnt mit `data:image/`;
2. Stringlänge höchstens 500.000 Zeichen;
3. Signername ist nicht leer;
4. genau ein Rollenflag ist gesetzt.

Es decodiert kein Base64, begrenzt nicht die decodierte Größe, erlaubt jeden
`image/*`-Subtype und prüft weder Dateisignatur noch Bilddimensionen.

### Reproduktion

```text
invalid_base64_accepted: True
arbitrary_image_mime_accepted: True
```

Akzeptierte Beispiele waren:

```text
data:image/png;base64,%%%NOT-BASE64%%%
data:image/anything;base64,ALSO-NOT-BASE64
```

### Fixvertrag

Der Server parst die Data-URI strikt, erlaubt eine explizite MIME-Allowlist,
decodiert mit Validierungsflag, prüft Magic Bytes, Pixelmaße und decodiertes
Bytebudget, normalisiert in ein kanonisches Format und hasht die resultierenden
Bytes. Fehler führen zu 422 ohne Teilwrite. Sensible Biometriedaten erhalten
einen expliziten Schutz-, Zugriffs- und Löschvertrag.

## `SIGN-IMMUTABILITY-001` – Re-Sign überschreibt den Nachweis

Der Endpoint prüft weder vorhandenes Rollenflag noch Status noch Version. Eine
zweite Kundensignatur schreibt Bild, Name, Einzelzeitpunkt und IP neu in dieselbe
Zeile. `version` bleibt `1`; `supersedes_id` bleibt ungenutzt.

### Reproduktion

```text
created_version: 1
signature_overwritten: True
specific_timestamp_overwritten: True
generic_signed_at_unchanged: True
```

Damit bezeichnet `signed_at` den ersten Signaturaufruf, während das sichtbare
Kundenartefakt aus einem späteren Aufruf stammt. `REC-006` ist unverändert
offen.

### Fixvertrag

Eine Partei darf pro Snapshotversion höchstens ein erfolgreiches
Signaturereignis besitzen. Derselbe idempotente Retry liefert dasselbe Ergebnis;
abweichende Wiederholung erhält 409. Jede fachlich gewollte Neusignatur setzt
die alte Version auf `VOID/SUPERSEDED` und erzeugt einen neuen Snapshot mit
neuer Zustimmung beider Parteien.

## `SIGN-CONCURRENCY-001` – Stale Reads erzeugen widersprüchlichen Status

`sign_document()` liest die Zeile, mutiert Flags und berechnet Status im
Anwendungsprozess. Es gibt weder Row-Lock noch `UPDATE ... WHERE version=?` noch
anderen atomaren Compare-and-swap.

Eine deterministische Stale-Read-Reproduktion ließ zwei Sessions denselben
Entwurf lesen. Session A setzte Berater, Session B Kunde. Beide Commits waren
erfolgreich:

```text
stored_signed_by_advisor: 1
stored_signed_by_client: 1
stored_status: Teilweise unterzeichnet
stored_generic_signed_at: 2026-09-03T10:00:01.000Z
advisor_specific_signed_at: 2026-09-03T10:00:00.000Z
client_specific_signed_at: 2026-09-03T10:00:01.000Z
```

Die UI leitet ihren grünen Status aus beiden Flags ab und kann diese DB-
Inkonsistenz verdecken.

### Fixvertrag

Signaturereignisse sind append-only und besitzen einen Unique-Key auf
`(snapshot_id, snapshot_version, signer_role)`. Der State-Übergang erfolgt
atomar mit erwarteter Version. Der abgeleitete Gesamtstatus wird entweder in
derselben Transaktion unter Lock aktualisiert oder ausschließlich aus den
unveränderlichen Events berechnet.

## `SIGN-STATE-001` – Schema- und Dialektvertrag sind nicht gleich

### Drei unterschiedliche Invariantensätze

1. SQLAlchemy `Base.metadata.create_all()` besitzt für `contract_documents`
   keine CHECK- oder Unique-Invarianten außer Primär-/Foreign Keys.
2. Die Alembic-Baseline erzeugt die Tabelle ebenfalls ohne die Raw-SQL-CHECKs.
3. `5eyes_schema_v4.0_FINAL.sql` prüft einige Domains, aber nicht die Bindung
   von `Unterzeichnet` an beide vollständigen Artefakte und nicht den
   Snapshot-/Hashvertrag.

Die Signaturspalten werden auf bestehenden SQLite-Datenbanken nur additiv per
`ensure_column()` ergänzt; dabei entstehen keine neuen Cross-Field-CHECKs.

### Reproduktion

Gegen das ORM-Schema wurde ohne Fehler gespeichert:

```text
tampered_status: Unterzeichnet
tampered_version: 999
tampered_checksum: forged
tampered_flags: 0 0
check_constraints: []
unique_constraints: []
```

Auch der Raw-SQL-CHECK koppelt `signed_at` nur an mindestens ein Flag. Der
Zustand `status='Unterzeichnet'`, `signed_at=NULL`, beide Flags `0` erfüllt den
ersten Zweig dieses CHECKs und wird nicht vom Status-CHECK verhindert.

### Fixvertrag

Alembic ist der kanonische, dialektgleiche Schemaweg. DB-Constraints erzwingen:

- erlaubte Statuswerte und Transitionen;
- `FULLY_SIGNED` genau dann, wenn beide erforderlichen append-only Events
  vorhanden und hashvalide sind;
- positive monotone Version;
- vollständige Hash-/Byte-/Contextanker ab `READY_FOR_SIGNATURE`;
- eindeutige Signerrolle je Snapshotversion;
- unveränderliche finalisierte Snapshotzeilen.

Raw-SQL-Bootstrap, SQLite-Testschema und PostgreSQL müssen denselben Vertrag
abnehmen.

## `SIGN-CLAIM-001` – Unbelegte Claims im „finalen“ Beratungsentscheid

### Beobachtung

`GET /reports/contract-signoff.pdf` nimmt keine Dokument-ID entgegen und liest
keine `ContractDocument`-Zeile. Er erzeugt live:

- aktuelle Target Allocation samt RA/Policy/CMA-Ankern,
- Protokolleinträge,
- eine vermeintlich finale Empfehlung,
- Standardbestätigungen,
- leere Unterschriftslinien.

`_build_protokoll_data()` wählt die Recommendation lediglich über
`order_by(created_at.desc()).first()`. Es filtert nicht auf `Final`, nicht auf
die aktuelle TA und nicht auf einen signierten Snapshot.

Der PDF-Text behauptet standardmäßig unter anderem:

- Geeignetheit wurde erläutert/geprüft;
- Kosten und Risiken wurden erläutert;
- relevante Produkt-, Kosten- und Vertragsunterlagen wurden erhalten oder
  seien auffindbar;
- ein Override sei bewusst bestätigt;
- die angezeigte Empfehlung sei final.

`ContractSignoffData` besitzt jedoch keine IDs/Hashes für SuitabilityCheck,
CostDisclosureSnapshot, DeliveryEvidence, ContractDocument oder Signaturen.
Die Renderer-Tests prüfen nur, dass diese Texte und leere Unterschriftslinien
vorhanden sind.

### Fixvertrag

Kein positiver Claim entsteht aus Standardtext. Jeder Claim hat einen
Evidence-Status `proven|not_applicable|missing|invalid`, eine konkrete
Evidence-ID und einen Hash. `missing/invalid` blockiert die finale Ausgabe.
Der Signoff-PDF ist eine Darstellung des `SignedPublicationSnapshot`, kein
live neu zusammengesetzter Mandatsreport.

## `SIGN-ELIGIBILITY-001` – `Final` ist keine Freigabe

### Bestehende positive Gates

Die Finalisierung prüft inzwischen sinnvoll:

- Draft-Status;
- aktuelle, mandateigene RA und TA;
- aktuelle Policy und CMA;
- TA-/Run-Policy-/CMA-Gleichheit;
- rekonstruierbaren Allocation-Context;
- vorhandene Positionen, Gewichtssumme, aktive Produkte;
- TER-/Marktpreisqualität als Warnungen.

### Fehlende Freigabegates

Nicht verlangt werden:

- `mandate.status == Aktiv`;
- ausgefüllte `TargetAllocation.approved_by/approved_at`;
- `provisional_data_warning IS NULL` beziehungsweise für Nicht-CH eine
  `committee_approved`-CMA;
- Kundensignatur des exakt referenzierten Risikoprofils;
- aktuelle passende Eignungs-/Angemessenheitsprüfung;
- gebundener Kostenausweis und Konflikt-/Retrozessionsstatus;
- Kunden-/Beratersignatur eines exakten Publikationssnapshots;
- vollständige frische Preise/FX/Holdings-Coverage.

Fehlende und stale Preise erzeugen nur Warnungen, die anschließend im Auditlog-
Text landen; der Run wird trotzdem `Final`.

### Fixvertrag

Die Statussemantik wird getrennt:

```text
DRAFT
  -> TECHNICALLY_VALIDATED
  -> ADVISOR_APPROVED
  -> READY_FOR_CLIENT_REVIEW
  -> CLIENT_ACCEPTED oder CLIENT_DECLINED
  -> READY_FOR_EXECUTION
```

`Final` darf nicht gleichzeitig technische Validierung, fachliche Freigabe,
Kundenannahme und Ausführungsbereitschaft bedeuten. Jeder Übergang besitzt
explizite, snapshotgebundene Voraussetzungen.

## `SIGN-UI-STATE-001` – Drei widersprüchliche UI-Definitionen

Das Frontend verwendet mindestens drei Definitionen:

1. Output-Strip: signiert, wenn `signed_by_advisor == 1`;
2. Review-Ausgabe: signiert, wenn Advisor **oder** Kunde gesetzt ist;
3. Dokumentkarte: vollständig unterzeichnet nur, wenn beide gesetzt sind.

Zusätzlich zählt `draftDocs` jedes Dokument als „in Arbeit“, dessen Status nicht
`Final` ist. Der Backendstatus wird aber auf `Entwurf`,
`Teilweise unterzeichnet` oder `Unterzeichnet` gesetzt, niemals `Final`.

Die UI kann daher zugleich „Unterzeichnet“, „signiert“ und „in Arbeit“ melden.

### Fixvertrag

API liefert einen kanonischen enum-basierten Status plus einzelne
Evidence-States. Alle Komponenten rendern denselben Vertrag. Keine UI leitet
einen stärkeren Zustand lokal aus Flags ab, als die serverseitige
Integritätsprüfung bestätigt.

## Zielbild: `SignedPublicationSnapshot`

### 1. Unveränderlicher fachlicher Kontext

Mindestens:

```text
snapshot_id
snapshot_version
tenant_id
client_id
mandate_id + mandate_status/version
document_type + locale
recommendation_run_id + run_status
target_allocation_id + allocation_context_hash
risk_assessment_id + risk_signature_evidence_id
suitability_check_id + suitability_hash
cost_disclosure_snapshot_id + cost_hash
conflict/retrocession evidence ids + hashes
holdings_valuation_snapshot_id + valuation_hash, falls relevant
product_snapshot_hash
publication_payload_sha256
rendered_pdf_sha256
renderer_version + template_version
created_at + ready_at
```

### 2. Kanonische Inhalte und Bytes

- Ein Pydantic-/JSON-Schema, keine freie Feldnamenübersetzung.
- Kanonische Serialisierung vor Hashbildung.
- Finaler PDF-Render genau einmal je Snapshotversion.
- Persistente oder objektgespeicherte immutable Bytes mit Inhaltshash.
- Download und Signaturreferenz lösen exakt dieselben Bytes auf.
- Jede Änderung erzeugt eine neue Version und invalidiert offene Signatur-
  Challenges.

### 3. Append-only Signaturereignis

```text
signature_event_id
snapshot_id + snapshot_version
signer_role
signer_subject_id
recorded_by_actor_id
signature_method
authentication_context
challenge_id + nonce_hash
payload_sha256 + pdf_sha256
normalized_signature_artifact_sha256
signed_at_server
source_ip + user_agent/session reference
status = accepted|revoked|superseded
```

Das Ereignis selbst wird nicht überschrieben. Korrekturen oder Widerruf sind
neue Events.

### 4. Atomare State Machine

```text
DRAFT
  -> READY_FOR_SIGNATURE
  -> PARTIALLY_SIGNED
  -> FULLY_SIGNED
  -> DELIVERED

READY_FOR_SIGNATURE | PARTIALLY_SIGNED
  -> VOID

FULLY_SIGNED | DELIVERED
  -> SUPERSEDED_BY_NEW_VERSION
```

Jeder Übergang nutzt expected version/CAS. `FULLY_SIGNED` wird nur aus zwei
hashvaliden erforderlichen Signaturereignissen desselben Snapshots abgeleitet.

### 5. Claims und Delivery

Geeignetheit, Kostenaufklärung, Unterlagenübergabe, Overridebestätigung und
Kundenannahme sind getrennte Evidence-Claims. Ein signiertes Dokument darf nur
Claims enthalten, deren Evidenz im Snapshot verankert ist. Eine Zustellung
erzeugt zusätzlich Recipient-, Channel-, Payload-Hash-, Provider-/Message-ID-,
Timestamp- und Receipt-Evidence.

## Verbindliche Testmatrix

### Content- und Rendering-Parität

- jedes UI-Feld erscheint mit eindeutigem Marker im serverseitigen PDF;
- unbekannte/falsch benannte Pflichtfelder ergeben 422, keine Defaults;
- `document_id` und `snapshot_version` bestimmen exakt ein Artefakt;
- Preview ist sichtbar markiert und nie signierbar;
- PDF-Hash vor und nach Download ist identisch;
- Änderung eines Bytes erzeugt neue Version und neuen Hash.

### Context und Eligibility

- Draft/Superseded/Legacy/provisional Run blockiert READY;
- nicht aktives/gelöschtes/fremdes Mandat blockiert Create/Ready/Sign;
- RA-, TA-, Policy-, CMA- oder Produktdrift ergibt 409;
- fehlende Approval-/Suitability-/Cost-/Conflict-/Delivery-Evidenz blockiert;
- stale/missing/partial Preis-/FX-/Holdings-Coverage blockiert relevante
  Ausführungsdokumente;
- exakt ein Final-/Approved-Context pro Snapshot.

### Signeridentität und Artefakt

- Kunde kann nur eigenes Mandat und nur aktive Challenge signieren;
- Advisor kann keinen Kundenprincipal behaupten;
- offline/witnessed wird getrennt und vollständig belegt;
- ungültiges Base64, falsche Magic Bytes, unbekannte MIME, Oversize und
  Pixelbomben ergeben 422;
- serverseitig normalisierte Bytes und Hash werden verifiziert;
- Response gibt keine unnötigen Rohartefakte an unberechtigte Rollen zurück.

### Idempotenz, Version und Concurrency

- gleicher Idempotency-Key + identische Bytes: dasselbe Event;
- gleicher Key + andere Bytes: 409;
- Re-Sign derselben Rolle ohne neue Version: 409;
- parallele Advisor-/Kundensignatur: konsistenter `FULLY_SIGNED`-Zustand;
- parallele Re-Sign-/Void-/Versionierungsoperationen: genau ein Gewinner;
- stale expected version: 409 ohne Teilwrite;
- echter PostgreSQL-Test mit mindestens zwei Verbindungen.

### DB-, Tamper- und Dialektvertrag

- ORM-, Alembic-, Raw-SQL- und PostgreSQL-Schema haben dieselben Constraints;
- `FULLY_SIGNED` ohne Events/Hashes wird DB-seitig abgewiesen;
- Flag/Status/Hash-/Byte-Tamper wird beim Read-Preflight erkannt;
- Audit-/Signaturereignisse sind append-only;
- Backup/Restore erhält Bytes, Hashes, Events und Reihenfolge;
- Retention/Legal Hold verhindert vorzeitige Löschung.

### API-/UI-/PDF-/Delivery-Parität

- alle Kanäle zeigen dieselbe Snapshot-ID, Version und Hashkurzform;
- Signiert-/Teilstatus ist überall identisch;
- PDF enthält die belegte elektronische Signaturdarstellung oder eine klare,
  prüfbare Evidence-Referenz;
- keine leere Linie wird als gespeicherte E-Signatur ausgegeben;
- Finalempfehlung ist exakt der verankerte Run;
- Claims zu Kosten, Suitability, Unterlagen und Override sind evidencegebunden.

## Empfohlene Umsetzungsreihenfolge

### Phase A – Claims sofort begrenzen

1. E-Signatur und „Unterzeichnet“-Claim nicht extern freigeben.
2. Advisor-seitige Kundenrollenbehauptung als solche kennzeichnen oder sperren.
3. „Finale Empfehlung“ nur für exakt verankerten Final-Run verwenden.
4. Nicht belegte Standardbestätigungen aus finalen PDFs entfernen.
5. Archivierte/inaktive Mandate fail-closed blockieren.

### Phase B – Kanonischer Snapshot

1. `SignedPublicationSnapshot` und striktes Contentschema einführen.
2. Alle Decision-/Evidence-Anker serverseitig auflösen.
3. Finale PDF-Bytes erzeugen und hashen.
4. Preview/Final und Dokumenttypen klar trennen.
5. UI-Druckpfad auf Snapshotartefakt umstellen.

### Phase C – Signaturereignisse und State Machine

1. Separate Principal-/Witness-Methoden implementieren.
2. Challenge, Idempotenz und expected version ergänzen.
3. Artefakte strikt decodieren, normalisieren und hashen.
4. Append-only Events und atomare CAS-Transitionen implementieren.
5. Re-Sign nur über neue Snapshotversion.

### Phase D – DB, Publikation und Betrieb

1. Alembic als kanonischen Schemaweg definieren.
2. Dialektgleiche Constraints und PostgreSQL-Concurrency-Tests ergänzen.
3. API/UI/PDF/Delivery auf einen Resolver und Hashvertrag bringen.
4. Tamper-Read-Preflight, Backup/Restore und Retention/Legal Hold abnehmen.
5. Erst danach externe oder reale Nutzung freigeben.

## Definition of Done

Kontrollrunde 24 ist erst geschlossen, wenn **alle** Punkte erfüllt sind:

- [ ] Ein versionierter `SignedPublicationSnapshot` bindet Entscheidung,
      Evidenz, Payload und PDF-Bytes.
- [ ] UI-Eingaben und Renderer verwenden dasselbe strikte Schema.
- [ ] Der sichtbare Druck-/Downloadpfad löst exakt das gespeicherte Artefakt.
- [ ] Payload-/PDF-/Signaturhashes werden serverseitig erzeugt und geprüft.
- [ ] Signerprincipal und dokumentierender Actor sind getrennt.
- [ ] Kunde und Advisor besitzen rollenrichtige Authentisierungswege.
- [ ] Signature-Image-Bytes werden strikt validiert und normalisiert.
- [ ] Signaturereignisse sind append-only und pro Rolle/Version eindeutig.
- [ ] Re-Sign überschreibt niemals einen bestehenden Nachweis.
- [ ] State-Transitionen sind atomar und stale Requests liefern 409.
- [ ] DB-Invarianten sind auf SQLite und PostgreSQL gleich.
- [ ] `FULLY_SIGNED` ohne zwei passende hashvalide Events ist unmöglich.
- [ ] Inaktive/archivierte Mandate können keine neue Signatur erhalten.
- [ ] `Final` ist in technische, fachliche und kundenseitige Zustände getrennt.
- [ ] Approval, Suitability, Kosten, Konflikte und Delivery sind gebunden.
- [ ] Contract-Signoff zeigt ausschließlich den exakt verankerten Final-Run.
- [ ] Positive PDF-Claims besitzen Evidence-ID und Hash.
- [ ] UI, API, PDF und Delivery zeigen dieselbe Version und denselben Status.
- [ ] Tamper-, Idempotency-, Race-, Backup-/Restore- und Retentiontests sind grün.
- [ ] Echte PostgreSQL- und Browser-/DOM-Abnahme ist dokumentiert.
- [ ] Frühere Blocker bleiben getrennt nachweisbar und werden nicht still
      als geschlossen markiert.

## Claude-/GPT-Startcheckliste

Vor jeder Implementierung:

1. Diesen Audit vollständig lesen.
2. Danach `REC-006`, `REP-005`, `REC-003` und Kontrollrunde 23 lesen.
3. Keine vorhandene Signaturzeile inplace „reparieren“ oder migrieren.
4. Zuerst Statussemantik, Contentschema, Snapshot- und Hashvertrag schriftlich
   festlegen.
5. Principal-Signatur und witnessed/offline Dokumentation explizit trennen.
6. Alembic-, SQLite- und PostgreSQL-Invarianten gleichzeitig entwerfen.
7. Frontend, API und Renderer gegen denselben Fixture-Hash testen.
8. Negative Tests vor Happy-Path-UI ergänzen.
9. Keine positiven Cost-/Suitability-/Delivery-/Final-Claims ohne Evidence.
10. Handoff bleibt gesperrt, bis SignedPublication- und ExecutionInstruction-
    Snapshot auf denselben freigegebenen Entscheidungskontext zeigen.
11. Keine ACL-unlesbaren `.pytest_tmp*`-Verzeichnisse betreten oder bereinigen.
12. Kein `git add -A`; nur explizite Manifestpfade stagen.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

- auditierter Head: `2d364de372e65aa16739a3301777b12bb2808850`
- sichtbare tracked/untracked Änderungen: `0`
- bekannte ACL-unlesbare pytest-Tempverzeichnisse: `53`
- globale Clean-Aussage: ausdrücklich **nein**
- Produktcode verändert: **nein**
- Tests verändert: **nein**

Das temporäre Reproduktionsharness lag ausschließlich unter `C:\tmp`, wurde
nach Ausführung entfernt und gehörte nie zum Repository. Es nutzte flüchtige
SQLite-Daten außerhalb des Repositories. Die ACL-unlesbaren Verzeichnisse
wurden nicht betreten, verändert oder bereinigt.

### Deterministische Reproduktionsblöcke

Das Harness führte aus:

1. echten `create_document()`- und `_build_vertrag_data()`-Pfad mit den vom UI
   gesendeten JSON-Feldern;
2. echten `sign_document()`-Pfad als Advisor für die Kundenrolle mit
   absichtlich ungültigen Artefakten und Re-Sign;
3. zwei getrennte stale Sessions für Advisor-/Kundensignatur;
4. Raw-SQL-Tamper der ContractDocument-Zeile;
5. Create und Sign nach Setzen des Mandatsstatus auf `Archiviert`;
6. Schema-Introspektion für Constraints und Contextspalten.

Wesentliche Ausgabe:

```text
created_status: Entwurf
created_version: 1
created_checksum: None
created_pdf_path: None
ui_intro_reaches_pdf: False
ui_disclaimer_reaches_pdf: False
ui_special_reaches_pdf: False
ui_place_reaches_pdf: False
ui_date_reaches_pdf: False
vertrag_data_has_signature_fields: False

caller_role: advisor
advisor_can_assert_client_signature: True
invalid_base64_accepted: True
arbitrary_image_mime_accepted: True
signature_overwritten: True
specific_timestamp_overwritten: True
generic_signed_at_unchanged: True
audit_binds_signature_bytes: False

stored_signed_by_advisor: 1
stored_signed_by_client: 1
stored_status: Teilweise unterzeichnet
stored_generic_signed_at: 2026-09-03T10:00:01.000Z
advisor_specific_signed_at: 2026-09-03T10:00:00.000Z
client_specific_signed_at: 2026-09-03T10:00:01.000Z

tampered_status: Unterzeichnet
tampered_version: 999
tampered_checksum: forged
tampered_flags: 0 0
archived_mandate_create_status: Entwurf
archived_mandate_sign_status: Teilweise unterzeichnet
```

### Fokussierter Bestands-Gate

Ausgeführt aus `5eyes-backend` mit externem Basetemp:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp C:\tmp\5eyes-signature-gate-20260903 `
  tests/test_contract_documents_fresh_bootstrap_schema_drift.py `
  tests/pdf/test_contract_signoff.py `
  tests/test_runtime_contracts.py `
  tests/test_asset_allocation_reference_integrity_edges.py `
  -k "contract_document or contract_signoff or sign_document or runtime_routes_expose_frontend_contracts or strategy_pdf_endpoints"
```

Ergebnis:

```text
17 passed, 97 deselected in 6.73s
```

Der Gate umfasst bestehende Signatur-Schema-/Routertests, zwei Fresh-Bootstrap-
Tests, vier Contract-Signoff-Renderer-Tests und Strategy-PDF-Endpointfälle. Er
enthält keinen echten Browser-/DOM-Ablauf, keine Bindung an tatsächlich
angezeigte Bytes, keine Re-Sign-/Tamper-/stale-read-Negativtests und keinen
echten PostgreSQL-Concurrency-Test.

### Letzter vollständiger Backend-Gate

Der letzte dokumentierte vollständige Backend-Gate gehört weiterhin zum
Implementierungscommit `661fe73c`:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed
```

Kontrollrunde 24 hat den Vollgate nicht erneut ausgeführt.

### Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen zum Dokumentationscommit gehören:

1. `docs/audits/2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit wird reproduzierbar aufgelöst mit:

```powershell
git log -1 --format=%H -- docs/audits/2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md
```
