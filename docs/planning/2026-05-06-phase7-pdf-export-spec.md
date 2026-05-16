# Phase 7 — PDF-Export der Optimization-Trace (Vor-Spec)

**Datum:** 2026-05-06
**Owner:** Emanuele
**Status:** ENTWURF — wird nach Phase-6-FE-Live aktualisiert.

## Ziel

FINMA RS 2017/2 verlangt nachvollziehbare Allocation-Entscheidungen. Aktuell ist
der Optimizer-Trace nur in der Web-UI sichtbar. Bei einer Audit-Anfrage
(Referenzmodell Compliance, Revisor) muss eine **PDF-Druckversion** existieren, die
die ganze Optimization-Entscheidung dokumentiert.

## Quellen

- Methodik-Schulung 2024-04-09 Slide 17 (House-View-Trace-Beispiel)
- FINMA RS 2017/2, Sec 3.4 (Dokumentationspflicht der Anlage-Entscheide)
- ASIP §3.2 (PK-Mandate, Audit-Trail)

## Inhalt der PDF (eine Seite + ggf. 2. Seite mit Stress-Anhang)

```
+-----------------------------------------------------------+
| 5eyes Wealth Architects                  [Mandat-Nummer]  |
| Strategie-Allocation Optimizer-Trace      [Datum/Version] |
+-----------------------------------------------------------+
| Mandant:   [Name]                                         |
| Berater:   [Name + ID]                                    |
| Score:     [X/10] · Profil: [Wachstumsorientiert]         |
| House-Mx:  [Profile-Name]                                 |
+-----------------------------------------------------------+
| OPTIMIZER STATUS                                          |
|   Method:        stochastic                               |
|   Status:        converged                                |
|   Seed:          4252227462396896290                      |
|   Iterations:    47 (4 Multi-Starts, SLSQP)               |
|   L(w*):         1.250e+10                                |
+-----------------------------------------------------------+
| ALLOCATION (Soll)                                         |
|   Aktien:           60% (Band 50-70)                      |
|   Obligationen:     25% (Band 20-35)                      |
|   Real Estate:      10% (Band  5-15)                      |
|   Alternativen:      3% (Band  0-10)                      |
|   Liquidity:         2% (Band  2-10)                      |
+-----------------------------------------------------------+
| STRESS-TESTS (historisch)                                 |
|   1929 Depression:  End 6.75M | Min 3.10M | DD -58.0%     |
|   2008 Finanzkrise: End 8.50M | Min 5.20M | DD -38.0%     |
|   2020-22 Covid:    End 9.20M | Min 7.80M | DD -23.0%     |
+-----------------------------------------------------------+
| REASONING-TRACE                                           |
|   - Stochastic Solver (SLSQP): 47 iter, 4 multi-starts.   |
|   - Best objective L(w*) = 1.250e+10                      |
|   - Goal "Pension Hart": Funded Ratio P50 = 92%           |
|   - Goal "Vermoegen": Funded Ratio P50 = 78%              |
|   - Risiko-Cap eingehalten: 75% von 75% max.              |
|   - Stress 1929: -58% Drawdown akzeptabel fuer Hart-Goal  |
+-----------------------------------------------------------+
| SIGNATUR                                                  |
|   Berater: ____________   Datum: ___________              |
|   Mandant: ____________   Datum: ___________              |
+-----------------------------------------------------------+
```

## Backend (neuer Endpoint)

```
GET /mandates/{mandate_id}/target-allocation/current/pdf-trace
Response: application/pdf, Disposition: attachment;
          filename="optimizer-trace-{mandate_number}-{version}-{date}.pdf"
```

Auth: `require_advisor`. Mandate-Ownership-Check.

Implementierung:
- ReportLab oder WeasyPrint (evaluieren — ReportLab ist im Python-Ecosystem
  stabil und ohne native deps).
- Datenquelle: `build_target_payload_from_allocation()` — alle Felder schon da
  dank Phase 6.1+6.2 Persistenz. Kein erneuter Solver-Lauf noetig.
- Template: einfache PDF mit fixem Layout, keine HTML-Engine noetig.

## Frontend

Einzelner Button im `#al-optimizer-panel`:
```html
<button class="btn-p" onclick="downloadOptimizerTracePdf()">PDF-Trace herunterladen</button>
```

JS:
```js
function downloadOptimizerTracePdf(){
  var mid=getActiveMandateId();
  if(!mid)return;
  window.open('/mandates/'+encodeURIComponent(mid)+'/target-allocation/current/pdf-trace','_blank');
}
```

## OWNER-DECISIONS (offen)

- **OD-PDF-1**: ReportLab vs WeasyPrint vs FPDF? Vorschlag: ReportLab (bewaehrt, keine deps).
- **OD-PDF-2**: PDF einsprachig DE oder mehrsprachig? Vorschlag: DE-only fuer Phase 7.
- **OD-PDF-3**: Signaturzeile mandatory oder optional? Vorschlag: optional (manche Mandanten signieren digital extern).
- **OD-PDF-4**: Stress-Anhang als 2. Seite oder zusammen mit Trace? Vorschlag: zusammen (eine Seite).

## Akzeptanzkriterien

1. PDF wird in <2s generiert auch fuer Mandanten mit 10+ Goals.
2. PDF ist text-selectable (keine Bitmap-Konvertierung).
3. PDF-Datei <500 KB bei realistischen Daten.
4. Alle Optimizer-Audit-Felder (method/status/seed/iter/L(w*)) sind drin.
5. Reasoning-Trace komplett (nicht trunkiert).
6. Bei `optimization_method=null` → 409 "Kein stochastischer Trace vorhanden".

## Tests

- Unit: PDF-Builder-Funktion mit Test-Allocation-Dict → assert content-type, size, contains expected strings.
- Integration: Endpoint-Call → 200 + binary PDF, header check.
- E2E (manuell): Browser-Click → PDF-Download → optisch pruefen.

## Was NICHT in Phase 7 ist

- Multi-Mandanten-Batch-PDF.
- PDF-Versionierung (separate Bibliothek noetig).
- Digitale Signaturen (eigene Spec).
- Multilanguage.

## Aufwand-Schaetzung

- Backend: ~6h (ReportLab-Setup, Template, Endpoint, Tests).
- Frontend: ~1h (Button + Download-Trigger).
- Manuelle QA: ~2h.
- **Gesamt: ~9h.**
