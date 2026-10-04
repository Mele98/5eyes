---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-ex-ante-cost-inducement-conflict-evidence-integrity-followup-audit"
status_as_of: "2026-09-02"
audit_started_on: "2026-09-02"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend/reporting"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "0dea85fc964cfd63e994478d41ed8d3162c0084f"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md"
prior_release_audit_commit: "0dea85fc964cfd63e994478d41ed8d3162c0084f"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md"
audit_mode: "read_only_static_service_orm_schema_api_pdf_react_review_targeted_runtime_reproduction_existing_backend_and_frontend_test_gates"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "ex-ante cost recommendation context, fee and TER domains, advisory wealth basis, inducement and conflict evidence, AdvisoryLog delivery snapshot and integrity chain, API React and PDF publication parity"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_backend_tests_passed: 84
focused_backend_tests_failed: 0
focused_frontend_tests_passed: 54
focused_frontend_tests_failed: 0
required_next_action: "persist one immutable and hashed CostDisclosureSnapshot for the exact Final recommendation, allocation, fee, product and inducement evidence context; reject invalid, stale, undisclosed or unproved inputs before publication; bind delivery evidence and every API React and PDF channel to that same snapshot"
---

# Ex-ante-Kosten-/Retrozessions-/Konfliktnachweis-Integritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die einundzwanzigste Read-only-
Kontrollrunde. Er wurde gegen den unveränderten Repository-Head `0dea85fc`
durchgeführt und am 2. September 2026 als maschinen- und menschenlesbarer
Handoff konsolidiert. Er verändert weder Produktcode noch Tests.

Der Audit ergänzt, ersetzt und schließt insbesondere nicht:

1. den unmittelbar vorherigen
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
2. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
3. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
4. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
5. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
6. den grundlegenden
   [Post-Commit-Integritätsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
7. sowie den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Die vollständige additive Audit-Reihenfolge ist im
[`ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`](../ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md)
festgehalten. Bei Widersprüchen gelten aktueller Code und reproduzierte
Laufzeitbelege zuerst, danach dieser Audit und anschließend die vorgenannten
Dokumente in der angegebenen Reihenfolge.

### Abgrenzung zum bekannten Retrozessionsbefund

`TEN-COMP-003` aus Kontrollrunde 7 bleibt vollständig offen. Dort wurde bereits
bewiesen, dass eine behauptete Rückzahlung ohne Zahlungsnachweis die Kosten
unbegrenzt bis in den negativen Bereich reduzieren kann. Die vorliegende Runde
schließt diesen Befund nicht und zählt ihn nicht als behoben.

Kontrollrunde 21 erweitert den bekannten Befund um eigenständige Ursachen und
Publikationsgrenzen:

- Auswahl eines beliebigen jüngsten RecommendationRun statt des wirksamen
  finalen Entscheids;
- Vermischung des Runs mit Live-Policy, Live-TER, Live-Währung und späteren
  Konfliktzeilen;
- fehlende Mandatsbindung und Current-Fallback der Kostenbasis;
- ein Response-Schema, das reale Retrozessionszeilen nicht serialisieren kann;
- eine reduzierte, fail-soft erzeugte und nicht gehashte AdvisoryLog-Kopie;
- behauptete Offenlegung und dokumentierter Kundenverzicht ohne die dafür
  erforderlichen Zustands- oder Evidenzfelder;
- fail-open Konfliktaggregation;
- fehlende Kostenansicht in React und widersprüchliche PDF-Texte.

## Kurzurteil

**Release bleibt hart blockiert.** Der Kostenausweis ist derzeit kein
unveränderlicher Nachweis des dem Kunden empfohlenen Entscheids. Der Service
wählt den zeitlich jüngsten RecommendationRun eines Mandats ohne Rücksicht auf
`result_status`, aktuelle Soll-Allokation, Finalität oder Supersession. Danach
ergänzt er diesen Run mit mehreren veränderlichen Live-Quellen:

1. Gebühren aus der heutigen Policy, falls der Run keinen Snapshot enthält;
2. heutige tenant-/jurisdiktionsbezogene TER-Overrides;
3. heutige Mandatswährung;
4. sämtliche heute nicht gelöschten Konfliktzeilen mit Betrag;
5. aktuelle Soll-Allokation als Fallback, wenn dem Run die Referenz fehlt.

Der gleiche historische Run kann deshalb ohne neue Empfehlung andere Kosten,
eine andere Währung und eine andere Berechnungsbasis publizieren. Ein neuerer
`Draft` verdrängt einen älteren `Final`-Run. Eine rohe oder historische
`target_allocation_id` wird ohne Mandatsfilter geladen; fehlt sie, ändert eine
spätere Current-TA rückwirkend die Kostenbasis.

Auch die Eingabedomäne schützt die Kundenpublikation nicht. Malformed oder
negative Fee-Werte werden still zu null, extreme Basispoints besitzen keine
Obergrenze, und `is_complete` prüft im Wesentlichen nur, ob irgendein
Service-Fee-Key vorhanden und die TER-Abdeckung rechnerisch 100 Prozent ist.
Damit können ein ungültiger Gebührensatz, unbelegte Retrozessionen und sogar
negative Gesamtkosten als vollständig erscheinen.

Die reale JSON-Schnittstelle besitzt zusätzlich einen deterministischen
Schemafehler: Retrozessions-Items liefern `rate_bps: null`, während das
Response-Modell zwingend einen Integer verlangt. Derselbe Servicewert kann im
PDF erscheinen, aber die JSON-Response-Validierung scheitert.

Der AdvisoryLog ist kein belastbarer Auslieferungsnachweis. Sein Builder
ignoriert die im Log ausgewählte `recommendation_run_id`, erzeugt bei fehlender
Empfehlung einen scheinbaren Nullkosten-Snapshot, entfernt Status, Quelle,
Einzelpositionen, Warnungen und Evidenzreferenzen und nimmt diesen Snapshot
ausdrücklich nicht in den Integritätshash auf. Eine nachträgliche Änderung des
gespeicherten Kostenbetrags lässt `integrity_verified` deshalb unverändert
grün.

Die fokussierten Gates sind trotzdem grün: 84 Backend- und 54 Frontend-Tests
liefen erfolgreich. Das widerlegt die Findings nicht. Die Tests sichern
überwiegend den heutigen Einzelpfad und schreiben teilweise dessen fail-open
Semantik fest; es fehlen Cross-Run-, Cross-Mandate-, Domain-, Response-
Validation-, Evidence-, Tamper-, Delivery- und Cross-Channel-Negativtests.

## Stabiles Findings-Register

| ID | Prio | Status | Releasewirkung |
|---|---:|---|---|
| `COST-CONTEXT-001` | P1 | bestätigt | Beliebiger jüngster Run wird mit Live-Policy, Live-TER, Live-Währung und heutigen Konflikten vermischt; der historische Kostennachweis driftet. |
| `COST-BASIS-001` | P1 | bestätigt | TA-Referenz wird ohne Mandatsfilter gelesen; fehlende Referenz fällt auf die heutige Current-TA zurück und verändert denselben Run. |
| `COST-DOMAIN-001` | P1 | bestätigt | Malformed, negative, Bool- und extreme Gebühren-/TER-Werte werden nicht als ungültige Publikationsinputs zurückgewiesen. |
| `COST-COMPLETENESS-001` | P1 | bestätigt | `is_complete` kann trotz ungültiger Werte, unbelegter Konflikte, Warnungen und negativer Totale `true` sein. |
| `COST-RESPONSE-001` | P1 | bestätigt | Reale Retrozessions-Items verletzen das JSON-Response-Schema (`rate_bps: null` gegen Pflicht-Integer); PDF und API divergieren. |
| `COST-EVIDENCE-001` | P1 | bestätigt | AdvisoryLog-Kostensnapshot ignoriert den gewählten Run, reduziert Pending zu null, ist unvollständig und nicht Teil des Integritätshashs. |
| `INDUCEMENT-EVIDENCE-001` | P1 | bestätigt | Produkt behauptet dokumentierten Verzicht beziehungsweise Rückerstattung ohne Waiver-/Disclosure-/Acknowledgement-/Zahlungsnachweis. |
| `CONFLICT-STATE-001` | P1 | bestätigt | Nie offengelegte Konflikte gelten nicht als unbestätigt; Datenbankfehler werden als konfliktfreier Zustand publiziert. |
| `COST-PUBLICATION-001` | P1 | bestätigt | React zeigt Kosten nicht, Konflikte besitzen keinen sichtbaren Arbeitsablauf, PDF-Texte widersprechen Currency/Basis und Standalone-Download protokolliert keine Übergabe. |

Kein Finding aus früheren Audits wird durch diese Liste geschlossen. Ein P1 in
Kostenhöhe, Währung, Interessenkonflikt, Kundenverzicht, Auslieferungsnachweis
oder kanalübergreifender Kundendarstellung blockiert die Final-/
Kundenpublikation unabhängig vom grünen Unit-Teststand.

## Tatsächlicher Datenfluss

```text
Mandat
  |
  +-- newest RecommendationRun by created_at (beliebiger Status)
  |      |
  |      +-- fee_assumptions_json
  |      |      \-- wenn leer: heutige OptimizerPolicy.fee_model_json
  |      |
  |      +-- RecommendationPosition + heutiges Product.ter_bps
  |      |      \-- überschrieben durch heutige ProductUniverseEntry.override_ter_bps
  |      |
  |      \-- target_allocation_id ohne Mandatsfilter
  |             \-- wenn leer/fehlend: heutige Current-TA des Mandats
  |
  +-- heutige base_currency
  |
  \-- alle heutigen aktiven Konfliktzeilen mit Betrag
          |
          \-- nur amount/frequency/reimbursed/provider gelangen in Rechner

calculate_cost_disclosure
  |
  +-- API: CostDisclosureResponse (Retrozession scheitert an rate_bps=null)
  +-- PDF: direkte Dict-Nutzung, Retrozession wird gerendert
  \-- AdvisoryLog: auf 6 Betrags-/Zeitfelder reduziert, nicht gehasht
```

Dieser Datenfluss besitzt keinen gemeinsamen `snapshot_id`, keinen
`context_hash`, keine vollständige Quellenliste und keinen Preflight, der vor
einer Kundenpublikation alle Bestandteile auf denselben Entscheid bindet.

## Codeanker auf dem auditierten Head

| Bereich | Anker | Beobachtung |
|---|---|---|
| Run-Auswahl | `5eyes-backend/services/cost_disclosure.py:47-65` | `created_at.desc().first()` ohne Status-, Current-, Final- oder Superseded-Regel. |
| Besseres vorhandenes Muster | `5eyes-backend/routers/review.py:2227-2254` | Anderer Pfad filtert Current-Allocation/Superseded und bevorzugt Final; Kostenpfad nutzt diese Semantik nicht. |
| Fee-Fallback | `5eyes-backend/services/cost_disclosure.py:75-83` | Fehlt der Run-Snapshot, wird heutige Policy live gelesen. |
| TER | `5eyes-backend/services/cost_disclosure.py:84-137` | Produkte und tenant-/jurisdiktionsbezogene TER-Overrides werden live gelesen. |
| Kostenbasis | `5eyes-backend/services/cost_disclosure.py:139-162` | TA-ID ohne Mandatsfilter; bei Fehlen Fallback auf Current-TA; daraus Wealth. |
| Konfliktinput | `5eyes-backend/services/cost_disclosure.py:163-183` | Alle aktiven Zeilen mit Betrag; Disclosure, Ack, Waiver und Zahlungsbeleg werden verworfen. |
| Run-Modell | `5eyes-backend/models/review.py:355-381` | `target_allocation_id` ist ein String ohne DB-Foreign-Key. |
| Fee-Domain | `5eyes-backend/schemas/allocation.py:452-487` | `fee_model_json` ist freier String ohne fachliche Feldvalidierung. |
| TER-Domain | `5eyes-backend/schemas/review.py:461-476` | Override-TER besitzt keine fachliche Grenze; Produkt-TER ist separat begrenzt. |
| Normalisierung | `5eyes-backend/services/cost_disclosure.py:220-247`, `507-546` | Invalid/negativ wird über `_safe_int` und `max(0, ...)` zu null; keine Obergrenze. |
| Vollständigkeit | `5eyes-backend/services/cost_disclosure.py:432-465` | Nur vorhandener Service-Fee-Key plus 10000 TER-Coverage bestimmt `is_complete`. |
| Retrozession | `5eyes-backend/services/cost_disclosure.py:368-430` | Rückerstattung wird negativ verrechnet; einbehaltene Vergütung behauptet dokumentierten Verzicht. |
| Response-Schema | `5eyes-backend/schemas/cost_disclosure.py:15-25` | `CostItem.rate_bps` ist zwingender Integer; Service liefert für Retrozession `None`. |
| Konflikt-Create | `5eyes-backend/routers/review.py:1047-1099` | Create setzt Disclosure/Ack auf 0; kein Update-/Ack-Arbeitsablauf im öffentlichen Router. |
| Konfliktaggregation | `5eyes-backend/services/advisory_report.py:2860-2918` | Nur disclosed-but-unacknowledged zählt; Exception liefert leer/false. |
| Log-Snapshot | `5eyes-backend/services/advisory_log_service.py:112-198` | Builder reduziert den aktuellen Mandatsausweis und speichert ihn auch unabhängig vom ausgewählten Run. |
| Integrität | `5eyes-backend/models/review.py:130-143`; `5eyes-backend/services/advisory_log_integrity.py:35-60` | Kostensnapshot ist ausdrücklich nicht Teil des Hash-Payloads. |
| Standalone-PDF | `5eyes-backend/routers/pdf_reports.py:1966-2004` | PDF wird ausgeliefert, ohne Delivery-Event/Log/Hash zu aktualisieren. |
| PDF-Sprache | `5eyes-backend/services/pdf/components/kostenausweis.py:50-55`, `227-265` | Fixtext nennt CHF und Beratungsvermögen; nur fünf Warnungen; Finaltotal immer grün. |
| Report-Aggregator | `5eyes-backend/services/advisory_report.py:225-242`, `290-349` | Backend liefert und schützt `cost_disclosure`; React-Vertrag konsumiert ihn nicht. |
| React-Typ/Validator | `5eyes-electron/frontend/reporting/src/api/types.ts:673-721`; `src/api/client.ts:131-165` | `cost_disclosure` fehlt im Typ und in den erwarteten Keys. |
| React-Logeditor | `5eyes-electron/frontend/reporting/src/components/AdvisoryLogEditor.tsx:157-174`, `323-331` | Checkbox setzt manuell Delivery-Flag; Konflikt-IDs werden immer als leere Liste gesendet. |

## `COST-CONTEXT-001` – Kosten besitzen keinen unveränderlichen Entscheidungscontext

### Beobachtung

Der Docstring bezeichnet die neueste Empfehlung als primäre Quelle, weil sie
die verwendeten Gebührenannahmen einfriere. Der tatsächliche Service erfüllt
diesen Vertrag nur teilweise:

- Der zeitlich jüngste Run gewinnt unabhängig von `Draft`, `Final`,
  `Superseded`, Allocation-Bezug oder Ergebnisstatus.
- Fehlen `fee_assumptions_json`, wird die heutige Policy gelesen.
- TER und TER-Overrides werden heute gelesen, nicht aus dem Run-Snapshot.
- Currency stammt aus dem heutigen Mandat.
- Konflikte stammen aus dem heutigen aktiven Rowset und besitzen keinen
  `created_at <= recommendation_as_of`-Filter.

Damit ist `source_run_id` kein Nachweis dafür, dass die ausgewiesenen Kosten zu
diesem Run gehören. `as_of` trägt zwar das Run-Datum, umfasst aber Livewerte,
die nach diesem Datum geändert oder angelegt worden sein können.

### Ausgeführte Reproduktion

Ausgangslage war ein älterer freigegebener Run mit 100 bps Service Fee und 20
bps TER. Danach wurden ein neuerer Draft mit 900 bps, ein Live-TER-Override von
500 bps, eine Mandatswährungsänderung von CHF auf EUR und eine spätere
Retrozessionszeile eingebracht.

```json
{
  "approved_baseline": {
    "source_run_id": "run-approved",
    "annual_rappen": 120000
  },
  "after_newer_draft": {
    "source_run_id": "run-draft",
    "annual_rappen": 920000
  },
  "after_live_ter_override": {
    "source_run_id": "run-draft",
    "annual_rappen": 1400000,
    "ter_rate_bps": 500
  },
  "after_base_currency_change": {
    "currency": "EUR",
    "annual_rappen": 1400000
  }
}
```

Keiner dieser Schritte erzeugte einen neuen finalen Kostensnapshot für die
ursprünglich freigegebene Empfehlung.

### Releasewirkung

Ein späterer Entwurf kann eine freigegebene Empfehlung in der
Kundenkostenoffenlegung verdrängen. Umgekehrt kann ein altes PDF dieselbe
`source_run_id` und dasselbe `as_of` zeigen, obwohl Gebühren, TER, Währung oder
Interessenkonflikte aus einem späteren Zustand stammen. Ein fachlicher oder
regulatorischer Reviewer kann den Ausweis nicht deterministisch reproduzieren.

### Fixvertrag

1. Kosten dürfen nur für einen explizit übergebenen, mandateigenen und
   publikationsfähigen RecommendationRun erzeugt werden.
2. Zulässige Statuswerte und Supersession-Regeln werden zentral definiert;
   `latest by created_at` ist keine Publikationsregel.
3. Fee-Modell, Produkte, Beträge, Gewichte, TER, TER-Override, Currency und
   Konflikte werden im CostDisclosureSnapshot eingefroren.
4. `as_of` gilt für jeden Bestandteil; jede Quelle erhält ID, Version,
   Effective-Time und Hash.
5. Fehlt ein Pflichtsnapshot, lautet das Ergebnis nicht live berechnet oder
   null, sondern explizit `publication_blocked` mit stabilem Reason-Code.

## `COST-BASIS-001` – Vermögensbasis ist weder mandatgebunden noch zeitstabil

### Beobachtung

Ist `RecommendationRun.target_allocation_id` gesetzt, lädt der Service die TA
nur nach ID. Ein Mandatsfilter, Tenant-Filter und Deleted-Check fehlen. Ist die
ID leer oder zeigt sie auf keinen Datensatz, fällt der Service auf die aktuelle
TA des Mandats zurück. Deren
`advisory_wealth_at_generation_rappen` wird anschließend als Gebührenbasis
verwendet.

Die öffentliche Run-Erzeugung besitzt zwar Ownership-Prüfungen. Die
Servicegrenze selbst ist aber nicht fail-closed. Legacydaten, Migrationen,
Imports, Adminpfade oder eine manipulierte DB-Zeile können den Invariant
verletzen; gerade ein nachträglich aufrufbarer Publikationsservice muss dies
erkennen und darf die fremde Basis nicht verwenden.

### Ausgeführte Reproduktion

```json
{
  "same_legacy_run_old_current_ta": {
    "source": "run",
    "basis": 10000000,
    "annual": 100000
  },
  "same_legacy_run_new_current_ta": {
    "source": "run",
    "basis": 50000000,
    "annual": 500000
  },
  "foreign_ta_id_on_same_run": {
    "source": "run",
    "basis": 90000000,
    "annual": 900000
  }
}
```

Der gleiche Legacy-Run änderte seine Kosten beim Wechsel der Current-TA. Eine
explizite fremde TA-ID lieferte sogar deren Vermögensbasis.

### Fixvertrag

- RecommendationRun und TargetAllocation erhalten einen erzwungenen
  relationalen sowie fachlichen Zusammenhang.
- Jeder Service-Read prüft `mandate_id`, Tenant, Deleted-State, Current-/
  Final-Semantik und Snapshot-Hash erneut.
- Für historische Runs gibt es keinen Current-Fallback.
- Fehlt die gebundene Basis, blockiert der Ausweis mit
  `COST_BASIS_EVIDENCE_MISSING`.
- Betrag und fachliches Label der Basis werden gemeinsam gesnapshottet.

## `COST-DOMAIN-001` – Ungültige Kosteninputs werden als günstige Null oder Extremwert publiziert

### Beobachtung

Das Fee-Modell ist freies JSON. `_safe_int` wandelt nicht parsebare Werte zu
`0`; die Rate-Helfer klemmen negative Werte ebenfalls auf `0`. Der vorhandene
Key gilt trotzdem als konfigurierte Gebühr. Obergrenzen fehlen. Dieselbe
Liberalität gilt an weiteren Grenzen, insbesondere beim unbeschränkten
`override_ter_bps` und bei Retrozessionsbeträgen.

Das ist keine neutrale Normalisierung: Ein kaputter positiver Pflichtwert wird
zu einer kundenfreundlichen Null. Ein extremer Wert bleibt dagegen erhalten.
Bool-Werte sind in Python Integer-Untertypen und brauchen einen ausdrücklich
verbotenen Vertrag.

### Ausgeführte Reproduktion

```json
{
  "malformed_fee": {
    "service_rate_bps": 0,
    "annual_rappen": 20000,
    "is_complete": true,
    "warnings": []
  },
  "extreme_fee": {
    "annual_rappen": 25020000,
    "annual_bps": 25020,
    "is_complete": true
  }
}
```

Die malformed Service Fee wurde still null; nur andere Kosten blieben. Ein
extremer Satz von über 250 Prozent p.a. wurde vollständig und ohne Domainfehler
publiziert.

### Fixvertrag

1. Gebührenmodell erhält eine versionierte strukturierte Schema-Domain statt
   eines frei interpretierten JSON-Strings.
2. Jeder Rate-Wert ist ein echter Integer, kein Bool, in einer fachlich
   definierten Unter-/Obergrenze.
3. `null`, fehlend, malformed, negativ und außerhalb der Grenze sind fünf
   explizit getestete Zustände; keiner wird still zu null.
4. TER-Overrides besitzen dieselben oder strengere Bounds wie Produkt-TER.
5. Retrozessionsbetrag und Frequenz erhalten Bounds, Currency, Zeitraum und
   Reconciliation-Regeln.
6. Persistenz, Import, API, Service und Snapshot validieren denselben Vertrag.

## `COST-COMPLETENESS-001` – Vollständigkeit misst nur zwei technische Teilbedingungen

### Beobachtung

`is_complete` ist aktuell:

```python
service_fee_known and ter_coverage_bps == 10000
```

`service_fee_known` bedeutet nur, dass mindestens ein erwarteter Key vorhanden
war. Der dazugehörige Wert darf malformed oder negativ gewesen und zu null
geklemmt worden sein. Nicht berücksichtigt werden unter anderem:

- Result-/Finalstatus und Run-/TA-Bindung;
- Live-Drift der Fee-/TER-/Currency-/Conflict-Quellen;
- gültige Rate-Domänen;
- nichtnegative und fachlich reconciliierte Totale;
- Schätzungen und Warnungen;
- Disclosure-/Acknowledgement-/Waiver-/Payment-Evidence;
- vollständige API-Serialisierbarkeit;
- kanonische Delivery-Evidence.

Die Reproduktion mit einer unbelegten jährlichen Rückerstattung von 20 Mio.
Rappen ergab:

```json
{
  "annual_rappen": -18600000,
  "annual_bps": -18600,
  "is_complete": true,
  "has_unacknowledged": false,
  "disclosed_to_client": false
}
```

### Fixvertrag

`is_complete` darf nur ein abgeleitetes Ergebnis eines expliziten Preflights
sein. Mindestens diese maschinenlesbaren Dimensionen werden getrennt geführt:

- `context_complete`
- `domain_valid`
- `cost_components_complete`
- `inducement_evidence_complete`
- `conflict_disclosure_complete`
- `schema_valid`
- `snapshot_integrity_verified`
- `publication_ready`

Jede falsche oder unbekannte Dimension erzeugt einen stabilen Reason-Code.
Eine negative Gesamtkostenposition oder ein nicht reconciliertes Guthaben ist
kein grüner vollständiger Ausweis.

## `COST-RESPONSE-001` – Retrozession macht die JSON-Schnittstelle ungültig

### Beobachtung

Der Service erzeugt für beide Retrozessionstypen `rate_bps: None`, weil ein
absoluter Retrozessionsbetrag keine aus der Gebührenbasis berechnete Rate sein
muss. Das Pydantic-Modell `CostItem` verlangt dagegen zwingend `int`.

### Ausgeführte Reproduktion

Die erzeugten Service-Payloads wurden direkt gegen
`CostDisclosureResponse` validiert. Sowohl die rückerstattete als auch die
einbehaltene Retrozession scheiterten:

```json
{
  "validated": false,
  "errors": [
    {
      "type": "int_type",
      "loc": ["cost_items", 2, "rate_bps"],
      "msg": "Input should be a valid integer",
      "input": null
    }
  ]
}
```

Der PDF-Pfad nimmt das rohe Dict und formatiert `None` als Gedankenstrich. Die
JSON-Route nutzt das Response-Modell und kann mit demselben fachlichen
Datensatz an der Response-Validierung scheitern. „Single Source of Truth“ auf
Serviceebene reicht daher nicht für kanalgleiche Publikation.

### Fixvertrag

- Das kanonische Schema entscheidet explizit, ob eine absolute Position eine
  Rate besitzen muss. Falls nicht, ist `rate_bps` kanalgleich nullable.
- Service, Pydantic, OpenAPI, TypeScript und PDF verwenden generierte oder
  vertraglich identische Typen.
- Contract-Tests validieren das vollständige echte Payload, nicht nur
  Einzelrechner oder Top-Level-Keys.
- Reimbursed, retained, unknown frequency und no-inducement werden jeweils
  durch echte Router-Response-Tests abgedeckt.

## `COST-EVIDENCE-001` – AdvisoryLog beweist weder Inhalt noch Auslieferung

### Tatsächlicher Snapshot

`_build_cost_disclosure_snapshot` erhält nur `mandate`, nicht die im Log-Payload
ausgewählte `recommendation_run_id`. Es ruft den Live-Service auf und reduziert
das Ergebnis anschließend auf:

- `generated_at`
- `currency`
- `advisory_wealth_rappen`
- `one_time_rappen`
- `annual_rappen`
- `first_year_rappen`

Nicht gespeichert werden `data_pending`, `source_run_id`, `as_of`,
`is_complete`, TER-Coverage, Einzelpositionen, Basislabels, Warnungen,
Konflikt-/Evidenz-IDs oder ein Snapshot-Hash. Der Builder fängt Fehler ab und
gibt `None` zurück, während das manuelle `cost_disclosure_given`-Flag trotzdem
gespeichert werden kann.

Das Modell kommentiert ausdrücklich, dass
`cost_disclosure_snapshot_json` nicht Teil der Integritätskette ist. Der
Supersede-Pfad kopiert den alten Snapshot weiter, ohne dessen Inhalt zu
verifizieren.

### Ausgeführte Reproduktion

```json
{
  "pending_snapshot_without_recommendation": {
    "generated_at": "2026-09-02T21:33:20.879Z",
    "currency": "CHF",
    "advisory_wealth_rappen": 0,
    "one_time_rappen": 0,
    "annual_rappen": 0,
    "first_year_rappen": 0
  },
  "snapshot_contains_state_or_source": false,
  "integrity_before_tamper": true,
  "integrity_after_cost_snapshot_tamper": true,
  "tampered_snapshot": {
    "annual_rappen": 999999999
  }
}
```

Ein Pending-Zustand ohne Empfehlung wird somit zu einer scheinbaren
Nullkostenkopie. Die nachträgliche Manipulation auf 999.999.999 Rappen bleibt
bei der Integritätsprüfung unsichtbar.

### Fixvertrag

1. Die Kundenübergabe referenziert eine bereits persistierte immutable
   `cost_disclosure_snapshot_id` plus Hash; sie berechnet nicht live neu.
2. Der Snapshot ist vollständig genug, um exakt den ausgelieferten Inhalt zu
   reproduzieren.
3. Snapshot-ID, Hash, Run-ID, Delivery-Zeit, Kanal, Empfängerbezug und Actor
   liegen in der AdvisoryLog-Integritätskette.
4. `data_pending`, `publication_blocked` oder Servicefehler können kein
   Delivery-Flag `true` erzeugen.
5. Die im AdvisoryLog ausgewählte Run-ID muss exakt mit der Snapshot-Run-ID
   übereinstimmen.
6. Snapshotänderung ist verboten; Korrektur erzeugt neue Version und
   explizite Supersession.
7. Download allein und bestätigte Übergabe sind getrennte Events.

## `INDUCEMENT-EVIDENCE-001` – Produkttexte behaupten Evidenz, die der Rechner nie sieht

### Einbehaltene Vergütung

Bei `reimbursed_to_client=False` erzeugt der Rechner unabhängig von
`waiver_document_id`, Disclosure oder Kundenbestätigung:

```text
source: Interessenkonflikt-Offenlegung (Retrozession, Verzicht dokumentiert)
warning: ... ist offengelegt, wird gemäss dokumentiertem Kundenverzicht ...
```

Die ausgeführte Reproduktion nutzte eine aktive Konfliktzeile ohne Waiver,
ohne Disclosure und ohne Acknowledgement. Dennoch erschienen genau diese
Behauptungen. Die Serviceübergabe enthält die drei Evidenzfelder überhaupt
nicht; eine Prüfung ist damit technisch unmöglich.

### Rückerstattete Vergütung

Bei `reimbursed_to_client=True` wird ein explizit jährlicher Betrag sofort als
negative Kostenposition eingerechnet. Der Zustand unterscheidet nicht zwischen
geplant, geschuldet, angewiesen, bezahlt, reconciliiert oder storniert. Ein
Zahlungsbeleg, Currency-, Perioden-, Empfänger- oder Transaktionsbezug ist
nicht erforderlich. Genau dies ist die bereits in `TEN-COMP-003` belegte
Ursache negativer Gesamtkosten.

### Öffentlicher Workflow

Der Router stellt im geprüften Bereich List und Create bereit. Create setzt
`disclosed_to_client=0` und `client_acknowledged=0`; ein fehlender
Reimbursement-Wert fällt auf Tenant-Default oder `False`. Ein nachvollziehbarer
Transition-Pfad für Offenlegung, Bestätigung, Waiver oder Zahlung wurde nicht
gefunden. React sendet aus dem AdvisoryLogEditor immer
`conflict_disclosure_ids: []`.

### Fixvertrag

Für Konflikte und Vergütungen gilt ein expliziter Zustandsautomat:

```text
draft
  -> reviewed
  -> disclosed_to_client
  -> client_acknowledged
  -> retained_with_valid_waiver
     oder reimbursement_due
          -> payment_proved
          -> reconciled
```

- Jede Transition besitzt Actor, Zeit, Mandat, Tenant, Vorzustand, Nachzustand
  und immutable Evidence-Referenz.
- „Verzicht dokumentiert“ darf nur aus einem gültigen mandateigenen Waiver-
  Dokument abgeleitet werden.
- Eine Rückerstattung reduziert Kosten erst nach dem fachlich festgelegten
  Evidence-Zustand; bloßes Boolean genügt nicht.
- Betrag, Currency, Periode und Transaktions-/Dokumentreferenz müssen
  reconciliert sein.
- Kundenlabels werden aus validiertem State abgeleitet, nicht aus einem
  einzelnen Boolean.

## `CONFLICT-STATE-001` – Konfliktaggregation ist logisch und technisch fail-open

### Logischer Fail-open

`has_unacknowledged` wird nur gesetzt, wenn ein Konflikt bereits offengelegt,
aber noch nicht bestätigt ist. Ein nie offengelegter Konflikt führt nicht zum
Warnstatus. Der ungünstigere Zustand „Kunde kennt den Konflikt noch gar nicht“
erscheint dadurch weniger kritisch als „Kunde kennt ihn, hat aber noch nicht
bestätigt“.

Vorhandene Tests schreiben diese Semantik ausdrücklich fest. Ein grüner Test
ist daher hier ein Regressionsschutz des Ist-Verhaltens, kein fachlicher
Freigabenachweis.

### Technischer Fail-open

Schlägt die DB-Abfrage fehl, liefert der Aggregator leere Items, Counts null und
`has_unacknowledged=False`. Es gibt weder `data_pending` noch `degraded` oder
einen Fehlercode. Ein fehlender Nachweis wird damit als konfliktfreier Zustand
publiziert.

### Fixvertrag

- Status ist mindestens tri-state: `clear`, `action_required`, `unknown`.
- Undisclosed, disclosed-not-acknowledged, missing-waiver und
  reimbursement-unproved sind eigenständige Blocker.
- DB-/Schema-/Timeoutfehler führen zu `unknown` und blockieren Finalisierung.
- Counts und `has_*` werden nicht als vollständiger State-Vertrag missbraucht;
  die API liefert Reason-Codes und betroffene Evidence-IDs.
- React und PDF zeigen `unknown` sichtbar und niemals grün.

## `COST-PUBLICATION-001` – API, React, PDF und Delivery besitzen keinen gemeinsamen Vertrag

### React

Der Backend-Aggregator liefert `cost_disclosure` als geschützte Sektion. Der
TypeScript-Typ `AdvisoryReport` und `validateSchemaV2` führen diesen Key jedoch
nicht. Die App besitzt keine dedizierte Kostenseite; die Konfliktsektion ist
zwar typisiert und als Top-Level-Key erwartet, wird im geprüften Reportfluss
aber nicht als sichtbarer Arbeits-/Publikationsschritt verdrahtet.

Der AdvisoryLogEditor bietet lediglich eine manuelle Checkbox „Ex-ante Kosten
dem Kunden kommuniziert“. Er zeigt dem Benutzer weder den gebundenen Snapshot
noch Hash, Status, Betrag, Währung oder Konflikte und sendet Konflikt-IDs immer
leer. Das UI kann somit eine Übergabe behaupten, ohne den übergebenen Inhalt zu
identifizieren.

### PDF

Der PDF-Komponent formatiert Beträge inzwischen mit `data.currency`, erklärt
im Einleitungstext aber weiterhin, die Werte seien „in Schweizer Franken“.
Bei EUR oder USD widersprechen Text und Beträge einander.

Die Rechnerlogik unterscheidet `Beratungsvermögen` und als Fallback
`Empfohlenes Produktvolumen`. Die drei Totalzeilen behaupten dennoch immer
„Quote bezogen auf das Beratungsvermögen“. Das erste-Jahr-Total erhält
unabhängig von `is_complete`, Warnungen oder negativem Wert eine grüne Linie
und grünen Hintergrund. Von beliebig vielen Warnungen werden nur die ersten
fünf gerendert.

### Delivery

Die Standalone-Route beschreibt das PDF als Dokument, das dem Kunden vor
Ausführung ausgehändigt werden kann. Sie rendert und liefert es aus, erzeugt
aber kein immutable Delivery-Event und aktualisiert keinen AdvisoryLog-
Nachweis. Umgekehrt kann die UI-Checkbox ohne diesen Download gesetzt werden.

### Fixvertrag

1. Ein versioniertes CostDisclosure-Publikationsschema gilt für Service,
   Pydantic/OpenAPI, TypeScript, React, Advisory-PDF und Standalone-PDF.
2. React muss den vollständigen gebundenen Ausweis und alle Blocker vor der
   Delivery-Aktion anzeigen.
3. Konflikte müssen auswählbar, mandategebunden und im Übergabenachweis
   referenziert sein.
4. Währung und Basislabel werden ausschließlich aus Snapshotfeldern gerendert;
   es gibt keine hartcodierte CHF-/Beratungsvermögen-Sprache.
5. Farbe und Status folgen `publication_ready`; unvollständig, negativ,
   unknown oder invalid ist niemals grün.
6. Warnungen werden vollständig oder mit sichtbar ausgewiesener Anzahl und
   vollständigem Anhang publiziert.
7. Delivery ist eine serverseitige, atomare Aktion über Snapshot-ID/Hash und
   erzeugt einen unveränderlichen Nachweis.

## Zielbild: kanonischer `CostDisclosureSnapshot`

Ein implementierbarer Minimalvertrag enthält mindestens:

### Identität und Provenienz

- `snapshot_id`, `schema_version`, `created_at`, `created_by`
- `tenant_id`, `mandate_id`
- `recommendation_run_id`, Run-Status, Run-Hash und Run-`as_of`
- `target_allocation_id`, Allocation-Hash und fachlicher Current-/Final-State
- `context_hash` über alle nachfolgenden publikationsrelevanten Felder

### Basis und Currency

- `currency` als validierter ISO-4217-Code
- `basis_type`
- `basis_rappen`
- `basis_source_id`
- `basis_as_of`
- expliziter Currency-/FX-Context, falls Quellen nicht bereits dieselbe
  Währung besitzen

### Gebühren- und Produktquellen

- vollständiger validierter Fee-Snapshot samt Version und Hash
- Positionen mit Product-ID, Amount, Weight, TER, TER-Source, Override-ID und
  Effective-Time
- Transaktionskostenannahme mit Quelle und `is_estimate`
- Coverage-Nenner und Coverage-Zähler, nicht nur gerundete bps

### Konflikte und Vergütungen

- Conflict-ID und State
- Provider, Betrag, Currency, Frequenz und Periode
- Disclosure- und Acknowledgement-Evidence
- Waiver-ID/Hash für retained
- Payment-/Reconciliation-ID/Hash für reimbursed
- klare `included_in_total`-Regel mit Reason-Code

### Ergebnis und Freigabe

- vollständige Cost-Items mit jeweiliger Basis
- Totale und Reconciliation-Differenz
- Estimates und alle Warnungen
- jede Preflight-Dimension und Reason-Codes
- `publication_ready`
- Snapshot-Hash und optionale Signatur

Nach Erzeugung ist der Snapshot immutable. Jede fachliche Änderung erzeugt
eine neue Version und referenziert den Vorgänger. Kundenkanäle akzeptieren nur
die Snapshot-ID und dürfen keine Live-Kosten neu berechnen.

## Verbindliche Testmatrix

### Run- und Snapshot-Auswahl

1. älterer Final plus neuerer Draft;
2. älterer Final plus neuerer Superseded;
3. mehrere Final-Runs mit eindeutigem wirksamem Allocation-Bezug;
4. identische `created_at` mit deterministischem Tie-Break;
5. explizite Run-ID eines anderen Mandats/Tenants;
6. Run ohne gebundene TA;
7. Run mit gelöschter oder fremder TA;
8. Legacy-Run ohne Snapshotanker;
9. Policy-/TER-/Currency-/Conflict-Änderung nach Snapshot;
10. Replay liefert byte-/hash-identischen Ausweis.

### Fee-, TER- und Betragsdomain

Für jeden Rate-/Betragsinput mindestens:

- fehlend;
- `null`;
- leerer String;
- nichtnumerischer String;
- Bool;
- negativ;
- null;
- gültige Unter- und Obergrenze;
- knapp außerhalb beider Grenzen;
- extrem groß;
- Fraction/Float, falls nur Integer zulässig;
- Overflow-/Rundungsgrenze.

Die Tests prüfen nicht nur den Calculator, sondern Create/Update, Persistenz,
Snapshot, Router-Response, React-Vertrag und PDF.

### Kostenbasis und Reconciliation

1. echtes Beratungsvermögen;
2. erlaubter Produktvolumen-Fallback mit korrektem Label;
3. fehlende Basis blockiert;
4. FX-/Currency-Mismatch blockiert oder wird evidenzgebunden konvertiert;
5. Positionssumme gegen TA-/Run-Snapshot;
6. Rate mal Basis gegen Itembetrag;
7. Items gegen One-time-/Annual-/First-year-Totale;
8. negative Totale;
9. übergroße Gutschrift;
10. Rundungsdifferenz mit expliziter Toleranz.

### Konflikt- und Retrozessionsstate

1. undisclosed;
2. disclosed, nicht acknowledged;
3. acknowledged ohne Waiver;
4. retained mit fremdem/gelöschtem/abgelaufenem Waiver;
5. retained mit gültigem mandateigenem Waiver;
6. reimbursement_due ohne Zahlung;
7. Zahlung ohne Currency-/Periodenmatch;
8. gültige Zahlung und Reconciliation;
9. stornierte oder doppelt verwendete Evidence;
10. Konflikt nach Recommendation-`as_of`;
11. DB-/Schema-/Timeoutfehler;
12. Concurrent Transition/Replay.

### API- und Schemakontrakt

1. keine Retrozession;
2. retained absolute amount mit nullable Rate;
3. reimbursed absolute amount mit nullable Rate;
4. unknown frequency;
5. vollständige Router-Response-Validation;
6. OpenAPI gegen TypeScript-Vertrag;
7. unbekanntes Pflichtfeld/Schema-Version;
8. vollständige Nested-Validation statt nur Top-Level-Key-Prüfung.

### AdvisoryLog und Manipulationsschutz

1. Delivery ohne Snapshot-ID;
2. Snapshot eines anderen Runs/Mandats/Tenants;
3. Pending/blocked Snapshot plus Delivery-Flag;
4. Mutation jedes einzelnen Snapshotfelds bricht Hashprüfung;
5. Mutation von Snapshot-ID, Hash, Delivery-Time, Kanal oder Empfänger bricht
   AdvisoryLog-Integrität;
6. Supersession erhält unveränderliche Historie;
7. Download ohne bestätigte Übergabe;
8. bestätigte Übergabe ohne Download/Anzeige;
9. Concurrent Double-Delivery mit idempotentem Ergebnis;
10. Export/Restore verifiziert dieselbe Integritätskette.

### Cross-Channel-Golden-Tests

Für denselben Snapshot werden API, React-ViewModel, Advisory-PDF und
Standalone-PDF verglichen auf:

- Snapshot-/Run-ID und `as_of`;
- Currency;
- Basiswert und Basislabel;
- jedes Cost-Item;
- nullable Rate;
- Totale;
- Schätzungen und Coverage;
- vollständige Warnungen;
- Konflikt-/Retrozessionsstatus;
- `publication_ready` und Reason-Codes.

EUR, USD und CHF sowie Beratungsvermögen-/Produktvolumenbasis sind eigene
Golden-Fälle. Ein unvollständiger Fall muss in allen Kanälen gleich blockiert
und sichtbar nicht grün sein.

### Zielumgebungen

- SQLite bleibt schneller Logikgate.
- PostgreSQL ist Pflicht für Constraints, Foreign Keys, Isolation,
  Concurrency, Current-/Final-Uniqueness und RLS/Tenant-Grenzen.
- Native Electron-/Installer-Artefakte sind Pflicht für den tatsächlichen
  React-/Download-/Delivery-Workflow.
- PDF-Golden-/Text-Extraction-Tests prüfen sowohl Werte als auch erklärende
  Sprache.

## Empfohlene Umsetzungsreihenfolge

### Phase A – Publikation sofort absichern

1. Final-/Kundenpublikation blockieren, wenn Kostencontext nicht eindeutig
   und vollständig ist.
2. Negative Totale, invalid Domains und Response-Schemafehler fail-closed
   behandeln.
3. Undisclosed/unknown Konflikte als Blocker statt grün publizieren.
4. Manuelles Delivery-Flag ohne gültige Snapshot-ID serverseitig ablehnen.

### Phase B – Kanonische Datenmodelle

1. versioniertes Fee-Modell einführen;
2. CostDisclosureSnapshot und Items relational/immutable modellieren;
3. Run-/TA-/Tenant-/Mandatsbindungen mit DB-Constraints absichern;
4. Konflikt-/Waiver-/Payment-Evidence-State modellieren;
5. Migration und Legacy-Quarantäne definieren.

### Phase C – Deterministische Erzeugung

1. expliziten Final-Run statt „latest“ verlangen;
2. alle Quellen auf denselben `as_of`- und Effective-Time-Vertrag binden;
3. Domain- und Reconciliation-Preflight ausführen;
4. Snapshot einmalig erzeugen, hashen und danach nur lesen;
5. stabile Reason-Codes publizieren.

### Phase D – Delivery und Kanäle

1. API/OpenAPI/TypeScript-Vertrag angleichen;
2. React-Kosten- und Konfliktworkflow implementieren;
3. beide PDFs ausschließlich aus Snapshot rendern;
4. Currency-, Basis-, Warnungs- und Statussprache korrigieren;
5. atomaren Delivery-Endpunkt mit AdvisoryLog-Integritätskette bauen.

### Phase E – Beweise

1. gesamte Testmatrix umsetzen;
2. PostgreSQL-/RLS-/Concurrency-Gates ausführen;
3. native Electron-/PDF-Golden-Gates ausführen;
4. Migration/Restore/Reconciliation proben;
5. Security-, Compliance-, Fach- und UX-Review dokumentiert abnehmen lassen.

## Definition of Done

Kontrollrunde 21 darf erst geschlossen werden, wenn alle Punkte erfüllt sind:

- [ ] Kein Kundenkanal wählt implizit den jüngsten RecommendationRun.
- [ ] Jeder Ausweis referenziert einen expliziten mandateigenen
      publikationsfähigen Run und dessen gebundene TA.
- [ ] Fee, TER, Overrides, Currency, Basis und Konflikte sind vollständig im
      immutable Snapshot enthalten.
- [ ] Historischer Replay liefert identischen Snapshot-Hash.
- [ ] Fachdomänen lehnen malformed, Bool, negativ und extreme Werte ab.
- [ ] `is_complete` wurde durch einen nachvollziehbaren Preflightvertrag
      ersetzt oder daraus streng abgeleitet.
- [ ] Negative oder nicht reconciliierte Gesamtkosten sind nicht
      publikationsfähig.
- [ ] Retrozessions-Items validieren in echter Router-Response und allen
      Kanälen.
- [ ] Einbehalt behauptet nur mit gültiger Evidence einen dokumentierten
      Kundenverzicht.
- [ ] Rückerstattung reduziert Kosten nur mit dem festgelegten
      Zahlungs-/Reconciliation-Nachweis.
- [ ] Nie offengelegte und technisch unbekannte Konflikte blockieren sichtbar.
- [ ] AdvisoryLog bindet Snapshot-ID, Hash, Run, Delivery-Time, Kanal und Actor
      in seine Integritätskette ein.
- [ ] Mutation irgendeines ausgelieferten Kostenfelds wird erkannt.
- [ ] React zeigt den vollständigen Kostenausweis und einen bedienbaren
      Konflikt-/Delivery-Workflow.
- [ ] API, React, Advisory-PDF und Standalone-PDF sind golden-testgleich.
- [ ] PDF-Währung, Basistext, Warnungen und Farblogik stimmen mit Snapshot und
      Freigabestatus überein.
- [ ] PostgreSQL-, RLS-, Concurrency-, Electron- und PDF-Artefaktgates sind auf
      Zielumgebung grün.
- [ ] `TEN-COMP-003` und alle hier referenzierten älteren Findings wurden nicht
      nur umbenannt, sondern mit eigenem Regressionsbeleg geschlossen.
- [ ] Fachowner, Compliance, Security und UX haben die konkrete
      Kundenpublikation freigegeben.

## Claude-/GPT-Startcheckliste

Vor jeder Änderung an Kosten, Empfehlung, Produktgebühr, Retrozession,
Konflikt, AdvisoryLog, Report oder PDF:

1. Diesen Audit vollständig lesen.
2. Danach `TEN-COMP-003` im
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md)
   lesen; dort liegt der ältere Zahlungsnachweis-/Negativkostenbeleg.
3. Keine ältere grüne Testsuite als Schließungsnachweis verwenden.
4. Zuerst explizit notieren, welcher RecommendationRun und welche TA der
   Kostensnapshot belegt.
5. Keine Live-Quelle in historische Kundenpublikation einbauen.
6. Keine ungültigen Kostenwerte still auf null klemmen.
7. Keine Begriffe wie „offengelegt“, „bestätigt“, „Verzicht dokumentiert“ oder
   „zurückerstattet“ aus einem einzelnen Boolean ableiten.
8. Kein Delivery-Flag ohne immutable Snapshot-ID und Hash akzeptieren.
9. API-Response vollständig gegen Pydantic/OpenAPI validieren.
10. React und beide PDFs mit demselben Golden-Snapshot vergleichen.
11. Neue Migrationen und Constraints auf PostgreSQL samt RLS prüfen.
12. Nur die tatsächlich bearbeiteten Pfade stagen; ACL-unlesbare
    `.pytest_tmp*`-Verzeichnisse weder bereinigen noch als global clean
    bezeichnen.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

- Branch: `codex/asset-allocation-stochastic-core`
- auditierter Head: `0dea85fc964cfd63e994478d41ed8d3162c0084f`
- sichtbare tracked/untracked Änderungen: `0`
- bekannte ACL-unlesbare pytest-Temp-Verzeichnisse in `git status`: `53`
- globale Clean-Aussage: ausdrücklich **nein**
- Produktcode während Kontrollrunde 21 verändert: **nein**
- Tests während Kontrollrunde 21 verändert: **nein**

Die ACL-unlesbaren Verzeichnisse wurden nicht betreten, nicht verändert und
nicht bereinigt. Sie verhindern weiterhin eine globale Clean-Aussage, obwohl
keine sichtbare Änderung vor der Dokumentation vorlag.

### Fokussierter Backend-Gate

Ausgeführt aus `5eyes-backend` mit externem Basetemp:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp C:\tmp\5eyes-cost-conflict-audit-20260902 `
  tests/test_cost_disclosure_endpoint.py `
  tests/pdf/test_kostenausweis.py `
  tests/test_cost_disclosure_retrocessions.py `
  tests/test_cost_disclosure_aggregator_section.py `
  tests/test_advisory_log_cost_disclosure_snapshot.py `
  tests/test_conflict_disclosures_aggregator.py `
  tests/test_retrocession_reimbursement_default.py `
  tests/test_cost_fee_basis_label.py `
  tests/test_cost_disclosure_pdf.py `
  tests/test_cost_disclosure_frontend.py `
  tests/pdf/test_protokoll_conflict_hinweis.py `
  tests/test_advisory_log_integrity.py
```

Ergebnis:

```text
84 passed in 17.37s
```

### Fokussierter Frontend-Gate

Ausgeführt aus `5eyes-electron/frontend/reporting`:

```powershell
npm.cmd test -- --run src/api/client.test.ts src/pages/sections.test.tsx
```

Ergebnis:

```text
Test Files  2 passed (2)
Tests       54 passed (54)
Duration    1.57s
```

Es erschienen nur die bereits bekannten Vite-Hinweise zur
esbuild-/oxc-Konfiguration. Sie erklären oder schließen keines der Findings.

### Letzter vollständiger Backend-Gate

Der letzte dokumentierte vollständige Backend-Gate gehört zum unveränderten
Implementierungscommit `661fe73c`:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed
```

Kontrollrunde 21 hat diesen Vollgate nicht erneut ausgeführt und behauptet
keinen neueren vollständigen Freigabenachweis.

### Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen zum Dokumentationscommit von Kontrollrunde 21
gehören:

1. `docs/audits/2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit dieses Dokuments ist absichtlich nicht selbst hartcodiert. Er wird
reproduzierbar aufgelöst mit:

```powershell
git log -1 --format=%H -- docs/audits/2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md
```
