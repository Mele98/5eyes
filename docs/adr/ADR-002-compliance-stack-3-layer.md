# ADR-002: Compliance-Stack 3-Schichten-Trennung

- **Status:** Accepted
- **Datum:** 2026-06-02
- **Sprint:** U-66/U-71/U-73/U-74/U-FINMA-PDF/Compliance-Dashboard #165

## Kontext

FIDLEG-Pflichten (Suitability, Konflikt-Offenlegung, Methodik) müssen
auditierbar sein. Es ist nicht ausreichend wenn sie nur intern berechnet
werden — sie müssen für drei Zielgruppen sichtbar sein:

1. **Kunde** → PDF-Report bekommt fertige Compliance-Sektion 16-23
2. **Berater** → Sub-App zeigt Compliance-Dashboard zur Prüfung vor Druck
3. **Compliance/Audit** → Backend-Aggregator-Daten via API für externe
   Audits abrufbar

Naive Lösung: alles in den PDF-Renderer. Problem: Berater sieht erst beim
PDF-Klick was passiert. Mismatch-Banner würden im PDF stehen statt im
Workflow.

## Entscheidung

Compliance wird auf 3 Schichten getrennt, jede mit klarem Zweck:

| Schicht | Pfad | Verantwortung |
|---------|------|---------------|
| **1. Backend-Aggregator** | `5eyes-backend/services/advisory_report.py` | Berechnung der Compliance-Datenstruktur (Sektionen 19-23) — Single-Source |
| **2. PDF-Renderer** | `5eyes-backend/services/pdf/components/compliance_audit.py` | Layout der Compliance-Daten für Druck (Editorial-Stil) |
| **3. Sub-App-Page** | `5eyes-electron/frontend/reporting/src/pages/Compliance.tsx` | Interaktive Anzeige für Berater inkl. Drilldown |

Sub-App-Sektion 17 ist die **Aggregation** der Backend-Sektionen 19-23
(siehe PR #163 + #165).

## Konsequenzen

**Positiv:**
- Berater kann vor Druck prüfen — Mismatches/Konflikte sichtbar im Workflow
- PDF-Renderer enthält keine Geschäftslogik, nur Layout
- Audit kann direkt gegen Backend-Aggregator gehen ohne PDF zu generieren
- 3 Schichten = 3 unabhängige Test-Suiten (Aggregator-Tests, PDF-Snapshot-
  Tests, vitest-UI-Tests)

**Negativ:**
- 3 Stellen müssen synchron bleiben → gelöst via Drift-Tests (siehe ADR-006)
- Sub-App-Sektion 17 ist nicht 1:1 mit Backend-Sektion 17 (`stress_replay`)
  — verwirrend für Newcomer. Gesondert dokumentiert in Sidebar-Code-
  Kommentar und in GLOSSAR.md.

**Nicht akzeptiert (Alternativen):**
- Alles im PDF-Renderer → Berater sieht Konflikte erst nach Druck
- Sub-App rechnet selbst → Drift-Risiko zur Backend-Berechnung
- Backend rendert HTML statt Datenstruktur → Sub-App wird zum dummen
  HTML-Viewer, Drilldown nicht möglich
