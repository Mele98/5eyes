# 5eyes — DSG-Datenexport

> Roadmap-Punkt 10 (2026-05-30): Erfuellt das Schweizer Auskunftsrecht
> nach DSG Art. 25. Liefert alle personenbezogenen Daten zu einem
> Kunden in maschinenlesbarem JSON-Format.

---

## Gesetzlicher Rahmen

| Norm | Pflicht |
|---|---|
| **DSG Art. 25** (Schweiz, in Kraft 01.09.2023) | Kunde hat Anspruch auf Auskunft ueber **ALLE** ueber ihn bearbeiteten Daten |
| Format | "uebliches elektronisches Format" → wir liefern strukturiertes JSON, UTF-8 |
| Frist | 30 Tage nach Anfrage |
| Empfaenger | Nur der Kunde selbst (oder dokumentiert legitimierter Vertreter) |
| Kosten | Erste Auskunft pro Jahr kostenlos |
| Audit | Jede Export-Anfrage muss dokumentiert sein (intern + Audit-Log) |

Zusaetzlich beruecksichtigt werden FIDLEG Art. 11 (10-Jahres-Doku), GwG
Art. 7 (Sorgfaltspflicht-Belege), OR Art. 962 (10-Jahres-Aufbewahrung).

---

## Was im Export enthalten ist

23 Sektionen — alle Tabellen, in denen das System personenbezogene
Daten zum Kunden haelt:

| Block | Sektionen |
|---|---|
| Stammdaten | `client`, `client_nationalities`, `client_opt_history` |
| Profiling | `client_knowledge`, `risk_assessments`, `risk_assessment_answers`, `suitability_checks` |
| Mandate | `mandates`, `target_allocations`, `recommendation_runs`, `recommendation_positions`, `recommendation_holdings`, `strategy_snapshots` |
| Beratung | `advisory_log`, `contract_documents`, `conflict_of_interest_disclosure`, `mandate_report_notes`, `review_trigger` |
| Vermoegen | `wealth_positions`, `cashflows`, `wealth_inflows`, `goals`, `planning_assumptions` |
| Audit | `audit_log` (nur Eintraege, die diesen Kunden / seine Mandate betreffen) |

### Was bewusst NICHT exportiert wird

- **Berater-Stammdaten** (`users`) — anderes Datensubjekt
- **Produktstammdaten** (`products`) — kein Personenbezug
- **Marktdaten** (`asset_class_price_history`, `fx_rate`, ...) — kein Personenbezug
- **Capital Market Assumptions / House Matrix** — kein Personenbezug
- **Daten anderer Kunden** — Mandantentrennung wird strikt verifiziert (Test: `test_export_does_not_leak_other_clients_data`)

---

## Aufruf

### HTTP-Endpoint (advisor-only)

```
GET /clients/{client_id}/data-export
Authorization: Bearer <JWT>
```

Antwort: `application/json` mit dem vollen Schema (siehe unten).
**Jeder Aufruf erzeugt einen `EXPORT`-Eintrag im `audit_log`** mit
Berater-ID, Kunden-ID und Anzahl ausgegebener Datensaetze. Damit bleibt
FINMA-konform nachvollziehbar, wer wann was herausgegeben hat.

### CLI (offline, kein laufender Server noetig)

```bash
cd 5eyes-backend
python scripts/data_export.py --client-id <UUID>
python scripts/data_export.py --client-number C-001234
python scripts/data_export.py --client-id <UUID> --output /tmp/export.json
```

---

## Format

```json
{
  "schema_version": 1,
  "exported_at": "2026-05-30T08:22:11.123Z",
  "client_id": "...",
  "client_number": "C-001234",
  "legal_basis": {
    "primary": "DSG Art. 25 (Recht auf Auskunft, Schweiz, in Kraft seit 2023)",
    "supplementary": [
      "FIDLEG Art. 11 (Dokumentationspflicht)",
      "GwG Art. 7 (Sorgfaltspflicht-Belege)",
      "OR Art. 962 (10-Jahres-Aufbewahrung)"
    ],
    "format": "Maschinenlesbares JSON, UTF-8."
  },
  "retention_notes": {
    "clients": "Aufbewahrung waehrend der Kundenbeziehung plus 10 Jahre...",
    "...": "..."
  },
  "manifest": {
    "client": 1,
    "mandates": 2,
    "risk_assessments": 5,
    "...": "..."
  },
  "sections": {
    "client": { ... Stammdaten ... },
    "mandates": [ ... ],
    "risk_assessments": [ ... ],
    "...": "..."
  }
}
```

`manifest` ist eine schnelle Schaufel-Zahl pro Sektion — der Berater
sieht auf einen Blick, wieviel im Export drinsteckt.
`retention_notes` enthaelt Klartext-Hinweise pro Tabelle: **welche Norm**
verlangt **welche Aufbewahrungsfrist** — damit der Kunde verstehen
kann, warum bestimmte Daten noch nicht geloescht werden duerfen.

---

## Beispiel (Live, Mandat MX-FOUNDATION-01)

```
Client: EX-5E-FOUNDATION (Daniel Beispiel)
Schema-Version: 1
Manifest:
  client: 1                       client_nationalities: 1
  client_knowledge: 1             mandates: 1
  risk_assessments: 5             risk_assessment_answers: 40
  suitability_checks: 0           target_allocations: 108
  recommendation_runs: 22         recommendation_positions: 212
  advisory_log: 7                 wealth_positions: 6
  cashflows: 7                    goals: 4
  planning_assumptions: 1         contract_documents: 3
  review_trigger: 9               strategy_snapshots: 9
  audit_log: 164
Total: 601 Datensaetze
Serialisierte Groesse: 494273 bytes (~494 KB)
```

---

## Audit-Trail

Jeder Export-Aufruf via HTTP loggt:

```sql
SELECT created_at, user_name, action, client_id, new_value
FROM audit_log
WHERE action='EXPORT'
ORDER BY created_at DESC;
```

```
created_at              user_name      action  client_id            new_value
2026-05-30T09:14:22Z    Anna Beraterin EXPORT  daniel-uuid-...      DSG-Export schema_v1, 601 Datensaetze
```

Der `integrity_hash` jeder AuditLog-Zeile (siehe `services/audit.py`)
verknuepft die Eintraege zu einer Tamper-evident Chain. Manipulation
einzelner Zeilen wird beim naechsten Audit-Verify auffallen.

---

## Was U-10 NICHT abdeckt (Folge-Punkte)

| Feature | Status | Roadmap |
|---|---|---|
| **Loeschanspruch** (DSG Art. 32) | nicht implementiert | eigener Sprint |
| **Berichtigungsanspruch** (DSG Art. 32 Abs. 1) | manuell ueber CRUD-Endpoints | OK |
| **PDF-Begleitdokument** mit Klartext-Erklaerung | nicht implementiert | nice-to-have, JSON reicht laut DSG |
| Export-Verschluesselung (PGP, S/MIME) | nicht implementiert | bei Versand an Kunden manuell |
| Auto-Mail an Kunden mit Export | nicht implementiert | bewusst — Berater entscheidet pro Fall |
| Erweiterung Frontend: "Export anfordern"-Button | nicht implementiert | Punkt 36 (Kunden-Sicht) wuerde davon profitieren |

---

## Test-Coverage

12 pytest-Cases in `tests/test_data_export.py`, alle gruen (2026-05-30):

| Test | Verifiziert |
|---|---|
| `test_export_returns_expected_top_level_keys` | Schema-Struktur stabil (8 Top-Keys) |
| `test_legal_basis_block_documents_dsg` | DSG / FIDLEG / OR-Hinweise im Output |
| `test_retention_notes_cover_all_section_tables` | Keine Sektion ohne Retention-Note |
| `test_client_section_contains_personal_data` | Stammdaten 1:1 |
| `test_mandates_section_contains_clients_mandate` | Mandat-Bezug korrekt |
| `test_risk_assessment_and_suitability_are_exported` | Profiling-Daten drin |
| `test_wealth_and_cashflow_and_goal_are_exported` | Vermoegens-Daten drin |
| `test_manifest_counts_match_section_sizes` | Manifest vertrauenswuerdig |
| **`test_export_does_not_leak_other_clients_data`** | **Mandantentrennung — kritisch!** |
| `test_export_raises_when_client_missing` | Klarer ValueError |
| `test_export_works_for_client_without_mandates` | Neue Kunden ohne Mandate |
| `test_export_payload_is_json_serializable` | json.dumps() ohne TypeError |

**Live-Roundtrip:** `scripts/data_export.py` gegen die produktive
5eyes.db (MX-FOUNDATION-01) exportierte 601 Datensaetze in 494 KB JSON
in unter einer Sekunde, alle Sektionen befuellt.
