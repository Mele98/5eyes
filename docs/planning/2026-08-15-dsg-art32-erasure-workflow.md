# DSG Art. 32 — Löschungsanspruch / Erasure-Workflow

Status: Engineering-Mechanismus implementiert, **braucht juristische Freigabe vor Produktivsetzung**.
Branch: `feat/dsg-art32-erasure-workflow` (Worktree `C:\tmp\5eyes-dsg-erasure`, lokal committet, nicht gepusht).

## Auftrag und Ausgangslage

Das Schweizer Datenschutzgesetz (DSG, in Kraft seit 2023) gewährt in Art. 32 einer betroffenen
Person das Recht, die Löschung ihrer Personendaten zu verlangen. Dieser Punkt war in
`docs/planning/2026-08-03-launch-readiness-update.md` explizit als offen markiert:

> **DSG Art. 32** — Löschungs-/Erasure-Workflow | Bewusst noch nicht gebaut
> (`services/data_export.py:28`: "Konkrete Löschung folgt in einem eigenen Sprint"). Eigener
> Sprint nötig, inkl. Retention-Abwägung FIDLEG 10 Jahre vs. OR 962.

Zusätzlich hatte der Mega-Audit vom 2026-08-04 festgehalten, dass der bestehende
`DELETE /clients/{id}`-Endpoint eine Löschung **vortäuscht**, die er nicht ausführt (reiner
Soft-Delete via `deleted_at`, keinerlei Anonymisierung).

Dieser Sprint baut den fehlenden Mechanismus: `POST /clients/{client_id}/erase`.

## Die Kernspannung: Löschungsanspruch vs. Aufbewahrungspflicht vs. unveränderliches Audit-Log

Drei gesetzliche/technische Zwänge stehen sich gegenüber:

1. **DSG Art. 32** verlangt Löschung auf Verlangen der betroffenen Person.
2. **FIDLEG Art. 11/12/16/19/21, GwG Art. 7, OR Art. 962** verlangen 10 Jahre Aufbewahrung
   praktisch aller Beratungs-, Eignungsprüfungs- und Buchführungsunterlagen. Diese Fristen
   waren bereits vor diesem Sprint pro Tabelle dokumentiert in
   `services/data_export.py::RETENTION_NOTES` (Single Source of Truth, hier wiederverwendet,
   nicht dupliziert).
3. Das Audit-Log (`audit_log`, `models/review.py::AuditLog`) ist **technisch unveränderlich**:
   `database.py::ensure_audit_log_triggers()` legt harte SQLite-Trigger an
   (`trg_audit_log_no_update`, `trg_audit_log_no_delete`), die JEDES `UPDATE`/`DELETE` auf dieser
   Tabelle mit `RAISE(ABORT, 'audit_log is immutable')` verwerfen. Dieser Trigger war selbst
   Gegenstand eines kritischen Bugfixes (CEO/CFO/CIO-Audit 2026-08-07: ging bei jeder
   Neuinstallation durch eine RENAME-Migration verloren, unbemerkt seit Einführung).

**Wichtiger Rechercheergebnis, der die ursprüngliche Auftragsannahme korrigiert:** Der Auftrag
ging davon aus, Audit-Log-Zeilen könnten "anonymisiert/redigiert (nicht gelöscht)" werden, weil
speziell der Hash-Chain-*Löschung* nicht standhält. Beim Lesen von `services/audit.py` und der
Trigger-Definition zeigt sich: **auch ein reines UPDATE ist blockiert**, nicht nur DELETE. Eine
In-Place-Redaktion von `audit_log`-Zeilen ist damit *technisch unmöglich*, ohne den Trigger selbst
aufzuweichen — und genau dieser Trigger wurde erst vor einer Woche als kritische Sicherheitslücke
gefixt. Ihn für die Erasure-Funktion zu durchbrechen hätte bedeutet, exakt die Eigenschaft wieder
zu schwächen, die dort repariert wurde.

## Design-Entscheidung: Zwei-Tier-Modell

Anstatt "alles hart löschen" oder "nur Soft-Delete vortäuschen" implementiert
`services/client_erasure.py` ein Zwei-Tier-Modell:

### Tier A — sofortige, irreversible Anonymisierung (bei jedem Aufruf)

Direkt identifizierende Felder werden auf einen fixen Marker (`[ERASED-DSG-ART-32]`) bzw. `NULL`
gesetzt: Name, Geburtsdatum, Partnerdaten, Zivilstand, Beruf/Arbeitgeber, freie Notizfelder,
Adressen, Bank-/Depotkontonummern, Vertragssignatur-Artefakte (Bild, Name, IP), sowie das
eigene Kundenportal-Login (E-Mail, Name, 2FA-Secret, Refresh-Tokens revoziert). Betroffene
Tabellen: `clients`, `client_opt_history`, `mandates` (redundante PII-Kopien), `wealth_positions`,
`cashflows`, `wealth_inflows`, `goals`, `planning_assumptions`, `contract_documents`, `users`
(Client-Rolle), `client_logins`, `refresh_tokens`.

Begründung: Diese Felder sind selbst **nicht** der gesetzlich vorgeschriebene Beleg — der Beleg
ist die Beratungsleistung, der Entscheid, der Betrag, das Datum. Sie sind Metadaten *über* die
Person. Nach dieser Stufe ist die Person aus den verbleibenden Datensätzen praktisch nicht mehr
identifizierbar, obwohl die Datensätze selbst für die Aufbewahrungsfrist bestehen bleiben
(Pseudonymisierung statt Löschung, vergleichbar mit der GDPR-Praxis bei Art.-17(3)-Ausnahmen).

### Tier B — bewusst unverändert belassen

FIDLEG-Pflichtdokumentationen mit eigenem Integritäts-/Versionsvertrag bleiben unangetastet:
`advisory_log` (Beratungsprotokoll, eigener `integrity_hash` + `retain_until`, Docstring:
"damit keine Daten je verloren gehen"), `portfolio_handoffs` (laut Docstring "UNVERÄNDERLICHER
Snapshot", OR Art. 400 Rechenschaftsablegung), `risk_assessments`, `risk_assessment_answers`,
`suitability_checks`, `conflict_of_interest_disclosures`, `recommendation_runs`/`_positions`/
`_holdings`, `target_allocations`, `strategy_snapshots`, `mandate_report_notes`,
`mandate_baustein_selections`. Laut `RETENTION_NOTES` sind das ausnahmslos 10-Jahre-pflichtige
Tabellen mit primär strukturierten Compliance-Entscheiden (Scores, Ja/Nein-Flags, Daten), nicht
primär Identitätsmerkmalen — die Person bleibt darin nur über die (jetzt anonymisierte)
`client_id`/`mandate_id`-Verkettung referenziert.

**Bekannter Restrisikopunkt, explizit zur juristischen Prüfung:** Einzelne Freitextfelder in
Tier-B-Tabellen (z. B. `AdvisoryLog.description`/`participants_json`,
`ConflictOfInterestDisclosure.description`) können Klarnamen enthalten. Eine feldweise Redaktion
dieser Tabellen würde ihre eigenen Integritäts-/Versionsverträge brechen (bei `advisory_log`
sogar einen dokumentierten "festen Hash-Vertrag", siehe `models/review.py` Kommentar bei
`cost_disclosure_snapshot_json`). Ob das im Einzelfall zumutbar/nötig ist, ist eine
Abwägungsfrage zwischen Löschungsanspruch und Dokumentationspflicht — **keine rein technische
Entscheidung**, wurde hier bewusst nicht autonom getroffen.

### `audit_log` — unverändert, aus rechtlichem UND technischem Grund

`audit_log` wird komplett unangetastet gelassen. Nicht nur, weil die Aufbewahrung als interne
Compliance-/Beweissicherung gerechtfertigt ist (`RETENTION_NOTES["audit_log"]`: "10 Jahre nach
Eintrag"), sondern weil eine In-Place-Anonymisierung technisch nicht ohne Aufweichung des
Immutability-Triggers möglich ist (siehe oben). Die Erasure-Aktion selbst wird stattdessen als
ganz normaler, neuer, hash-verketteter Audit-Log-Eintrag geschrieben
(`action='CLIENT_ERASE'`, `routers/clients.py::erase_client`) — das erfüllt die
Nachvollziehbarkeitspflicht ("wer hat wann wen aus welchem Grund gelöscht"), statt sie zu
untergraben.

## Implementierung

| Datei | Änderung |
|---|---|
| `models/clients.py` | `Client.erased_at`, `Client.erasure_reason` (unterscheidet DSG-Erasure von gewöhnlichem Soft-Delete) |
| `database.py` | additive Spalten-Migration für `erased_at`/`erasure_reason`; `'CLIENT_ERASE'` zur `audit_log.action`-CHECK-Liste + neuer Migrations-Marker `has_erasure_action` (sonst würde die Aktion auf bereits migrierten Bestands-DBs mit IntegrityError crashen — identische Bugklasse wie der 2026-08-07-Fund) |
| `5eyes_schema_v4.0_FINAL.sql` | `'CLIENT_ERASE'` zur rohen CHECK-Liste (Fresh-Bootstrap-Pfad) |
| `services/client_erasure.py` | Kern-Cascade-Logik (`erase_client_personal_data`), ausführlich dokumentierter Modul-Docstring mit der vollständigen Begründung |
| `schemas/clients.py` | `ClientErasureRequest` (Pflichtbegründung, wiederverwendet `services/override_reason_quality.py` — dieselbe Qualitätsprüfung wie bei Risikoprofil-Overrides), `ClientErasureResponse` |
| `routers/clients.py` | `POST /clients/{client_id}/erase`, admin-only (`require_admin`), tenant-gescoped, 404/409-Guards, schreibt Audit-Log-Eintrag |
| `tests/test_client_erasure.py` | 9 Tests (siehe unten) |

Der Endpoint ist bewusst **idempotent-sicher** (409 bei zweitem Aufruf) statt idempotent-still,
damit ein Doppelaufruf (Bug im Client, Doppelklick) auffällt statt unbemerkt still zu bleiben.
Er funktioniert auch für bereits (soft-)gelöschte Kunden (`_get_client_for_erasure_or_404`
filtert bewusst NICHT auf `deleted_at`, im Unterschied zu `get_client_for_user_or_404`) — eine
Löschungsanfrage trifft in der Praxis häufig gerade einen Kunden, der zuvor schon per
gewöhnlichem `DELETE` "gelöscht" wurde, dessen Personendaten aber unverändert in der DB liegen.

## Tests

`tests/test_client_erasure.py`, 9 Tests, alle grün:

- `test_erase_client_redacts_all_tier_a_pii_and_returns_summary` — voller Cascade-Test über alle
  Tier-A-Tabellen inkl. Freitextsuche ("Hans"/"Muster"/"Bahnhofstrasse" darf in keiner Tier-A-Spalte
  mehr vorkommen).
- `test_erase_client_leaves_tier_b_fideleg_records_untouched` — Beratungsprotokoll, Risikoprofil,
  Eignungsprüfung bleiben wortgleich erhalten.
- `test_erase_client_writes_auditable_clientase_event` — die Löschung selbst ist im Audit-Log
  nachvollziehbar (wer/wann/wen/warum).
- `test_erase_client_does_not_delete_or_mutate_pre_existing_audit_rows` — ein vorbestehender
  Audit-Eintrag mit Klarnamen bleibt byte-identisch (Hash unverändert) erhalten; ein direkter
  `UPDATE`-Versuch auf `audit_log` wird weiterhin vom DB-Trigger verworfen (Beweis: die
  Immutability-Garantie wurde durch dieses Feature NICHT aufgeweicht).
- `test_erase_client_rejects_non_admin` — 403 für Advisor-Rolle, keine Datenänderung.
- `test_erase_client_requires_meaningful_reason` — 422 bei zu kurzer/generischer Begründung.
- `test_erase_client_is_idempotent_guarded_with_409` — zweiter Aufruf liefert 409.
- `test_erase_client_404_for_unknown_client`.
- `test_erase_client_works_on_already_soft_deleted_client`.

Zusätzlich verifiziert:

```
python -m pytest tests/ -q -x --timeout=0 -k "erase or deletion or dsg"   → 12 passed, 1 skipped (hypothesis fehlt, unabhängig)
python -m pytest tests/test_client_erasure.py -q --timeout=0              → 9 passed
```

sowie ein breiter Sanity-Lauf über `client`-, `mandate`-, `wealth`-, `audit`- und
`foundation_purge`-Tests (inkl. `test_audit_log_action_check_constraint_drift.py`, um zu
bestätigen, dass die erweiterte `action`-CHECK-Liste die 32 zuvor funktionierenden Actions nicht
regressiert) — Ergebnis siehe Commit-Historie / CI.

## Was noch juristische Prüfung braucht, bevor dies live geht

1. **Die Tier-A/Tier-B-Grenze selbst.** Diese Implementierung trifft eine vertretbare
   *technische* Abwägung (Identitätsmerkmale vs. Compliance-Beleg), ist aber keine Rechtsberatung.
   Ein Jurist muss bestätigen, dass die gewählte Grenze DSG Art. 32 tatsächlich genügt, insbesondere
   ob strukturierte Felder wie `Cashflow.label` (können Klarnamen enthalten, z. B. "Lohn Hans
   Muster") oder `MandateBausteinSelection.custom_override_md` ("Klienten-spezifische
   Erläuterung") zusätzlich redigiert werden müssen.
2. **Freitextfelder in Tier-B-Tabellen** (`advisory_log.description`/`participants_json`,
   `conflict_of_interest_disclosures.description`) — siehe Restrisikopunkt oben. Falls diese
   redigiert werden müssen, braucht das einen eigenen, mit dem jeweiligen Integritätsvertrag
   abgestimmten Entwurf (nicht Teil dieses Sprints).
3. **Retention-Ablauf-Purge.** Dieser Service löscht nichts hart. Ein künftiger, separater Job,
   der Tier-B-Zeilen NACH Ablauf der 10-Jahres-Frist tatsächlich hart entfernt (inkl. der Frage,
   ob/wie `audit_log`-Zeilen nach Fristablauf behandelt werden — z. B. per Archivierung + erneuter
   Trigger-Deaktivierung unter kontrollierten Bedingungen), ist bewusst **out of scope** und
   müsste separat spezifiziert werden.
4. **DE-Mandate / DSGVO.** Der Mega-Audit vom 2026-08-04 hat festgehalten: "Null Erwähnungen von
   GDPR/DSGVO im gesamten Backend, obwohl DE-Mandate (EU-Datensubjekte) technisch produktiv sind."
   Dieser Erasure-Mechanismus wurde ausschliesslich gegen DSG Art. 32 entworfen; ob er auch
   Art. 17 DSGVO genügt (z. B. abweichende Fristen/Ausnahmetatbestände), ist ungeprüft.
5. **Downstream-Verarbeitung.** Backups, Support-Bundles und Exporte (`services/data_export.py`)
   wurden hier nicht angepasst — ein VOR der Erasure gezogener Export oder ein Backup enthält die
   Klardaten weiterhin. Das ist ausserhalb des DB-Mechanismus und braucht eine operative
   Richtlinie (siehe bereits offener Punkt in `docs/CLIENT_DATA_STORAGE_AND_PROCESSING.md` §7:
   "Define operational retention/deletion rules for backups and support bundles").

**Zusammenfassung für die Freigabe:** Dies ist der Engineering-Mechanismus (technisch korrekt,
getestet, mit der Immutability-Garantie des Audit-Logs vereinbar). Die *rechtliche* Korrektheit
der genauen Retention-/Anonymisierungs-Grenze braucht eine menschliche juristische Prüfung, bevor
dies für echte Mandanten produktiv geschaltet wird.
