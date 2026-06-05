# 5eyes — Berater-Handbuch

Praktische Anleitung fuer Berater die mit 5eyes WealthArchitekten
arbeiten. Komplementaer zum technischen Top-Level-README.md (Engineering)
und [GLOSSAR.md](GLOSSAR.md) (Begriffsdefinitionen). Hier:
**Tag-zu-Tag-Workflows** vom Login bis zum gedruckten Beratungsreport.

**Stand:** 2026-06-05

---

## Inhalt

1. [Login & Hauptapp-Start](#1-login--hauptapp-start)
2. [Neuer Kunde](#2-neuer-kunde)
3. [Risikoprofil erfassen](#3-risikoprofil-erfassen)
4. [SAA generieren](#4-saa-generieren)
5. [Portfolio-Empfehlung](#5-portfolio-empfehlung)
6. [Beratungsgespraech protokollieren](#6-beratungsgespraech-protokollieren)
7. [Beratungsreport (PDF)](#7-beratungsreport-pdf)
8. [Compliance-Drilldown](#8-compliance-drilldown)
9. [Datenpflege (CMA + FX)](#9-datenpflege-cma--fx)
10. [Audit-Log einsehen](#10-audit-log-einsehen)
11. [Wenn etwas schief laeuft](#11-wenn-etwas-schief-laeuft)

---

## 1. Login & Hauptapp-Start

5eyes startet als Electron-Desktop-App. Beim ersten Start:

1. Backend automatisch hochgefahren (`http://127.0.0.1:8000`)
2. Login mit Berater-Credentials (Bearer-JWT, TTL 8h default,
   24h max in Production)
3. Hauptapp zeigt Kunden-Stammliste links + Detail-Pane rechts

**Token-TTL:** Wenn dein Token abgelaufen ist (8h ohne Aktion),
musst du dich neu einloggen. Token bleibt in `sessionStorage` —
Browser-Tab schliessen = ausgeloggt.

**API-Doku:** `http://127.0.0.1:8000/docs` (Swagger) zeigt alle
verfuegbaren Endpoints.

## 2. Neuer Kunde

Customer-Journey-Reihenfolge:

```
Stammdaten -> Cashflows/Ziele -> Risikoprofil -> SAA -> Portfolio
```

**Stammdaten:** Name, Geburtsjahr, Steuerdomizil, Anlagehorizont.
Steuerdomizil bestimmt das Steuer-Plugin (CH/DE/CH-ZH/DE-BY ...,
Fallback '*' = Pauschal-Rate).

**Cashflows & Ziele:** wird auf **Gesamtvermoegen** gerechnet
(siehe [GLOSSAR.md#cashflow](GLOSSAR.md)). Mehrere Ziele moeglich;
jedes Ziel kategorisiert als `Primaer` / `Sekundaer` / `Opportunistisch`.

**Beratungsvermoegen** = Teilmenge des Gesamtvermoegens die unter
5eyes-Beratung steht. Wird in der SAA + Tortendarstellung +
Portfolio-Empfehlung genutzt — NICHT Gesamtvermoegen.

## 3. Risikoprofil erfassen

Standardisierter FINMA-Fragebogen, 11 Fragen aus den Kategorien:

- **Risikofaehigkeit** (Einkommen, Verpflichtungen, Spar-Quote, Vermoegen)
- **Risikobereitschaft** (Anlageziel, Praeferenz, Verhalten in Krisen)

Endergebnis: `final_profile` ∈ {Defensiv, Konservativ, Wachstumsorientiert,
Aggressiv} + `final_score_x10` (0-100).

**Override-Workflow:** Wenn du den Score manuell anpassst, MUSST du
eine Begruendung von >= 20 Zeichen + 3 sinnvollen Worten eingeben
(siehe U-28/U-29). Floskeln wie "passt zum Kunden" werden via
Phrase-Blacklist abgelehnt.

**Re-Validierung:** Risikoprofil wird automatisch ROT in der
Erkenntnisse-Sektion wenn aelter als 12 Monate
([siehe Sektion 7 in compute_advisory_report](../5eyes-backend/services/advisory_report.py)).

## 4. SAA generieren

Strategic Asset Allocation aus dem Risikoprofil + CMA:

1. Risikoprofil -> House-Matrix-Default-Allocation pro Bucket
   (Aktien/Obligationen/Real-Estate/Alternative/Liquidity)
2. Optional: Stochastic Optimizer (Mulvey/Ziemba-light) verfeinert
   die Allokation. Aktivieren via Admin: `optimizer_mode=stochastic`
3. Bands um die Targets (z.B. Aktien-Target 5000 bps, Band 4500-5500)

Wenn Optimizer Mode = `house_matrix`, kommt direkt die Default-Allokation.
Wenn `shadow_stochastic`: Optimizer rechnet aber Targets bleiben
House-Matrix (Shadow-Compare im Admin-Modal sichtbar).

Bei Aenderung der OptimizerPolicy schreibt 5eyes automatisch einen
Archive-Snapshot der vorherigen Konfiguration (U-103), damit du
spaeter rekonstruieren kannst welche Werte zu einer historischen
TA-Generierung galten.

## 5. Portfolio-Empfehlung

Portfolio = **Ableitung der SAA**, NICHT Bestand-vs-Empfehlung.
Building Blocks (vordefinierte ETF/Fonds-Bausteine) werden gemaess
SAA-Buckets ausgewaehlt + per Investment-Universum gefiltert.

**ESG/SFDR-Filter (U-95):** Im Building-Block-Selector kannst du
nach `sfdr_class` (Art. 6/8/9) oder `esg_rating` filtern wenn der
Kunde Nachhaltigkeits-Preferences hat.

**Currency-Hedge-Vorschlag (U-98):** Erkenntnisse-Sektion 7 zeigt
eine konkrete Hedge-Quote-Empfehlung basierend auf Horizont + FX-Groesse.
Heuristik:
- Horizont < 3J + grosse FX: 80% Hedge
- 3-7J: 50%
- 7-15J: 25%
- >15J: 0% (Mean-Reversion)

## 6. Beratungsgespraech protokollieren

FINMA-Pflicht: jedes Beratungsgespraech muss protokolliert werden.

Aggregator-Sektion 16 (`beratungsprotokoll`). Erfassen via:

- **Manuell:** Drawer "Beratungsprotokoll" -> Neuer Eintrag.
  Pflichtfelder: Datum, Anwesende, Themen, Empfehlungen.
- **Auto-Log:** Bei Suitability-Mismatch (Kunden-Profil ≠
  Portfolio-Profil) wird automatisch ein Eintrag mit Mismatch-Flag
  erzeugt.

Retention: Eintraege haben `retain_until` (Default 10 Jahre).
Read-Audit + Hash-Chain-Integritaet (Audit-Log) verhindert
Manipulation.

## 7. Beratungsreport (PDF)

PDF wird vom Backend gerendert + heruntergeladen. Quelle ist der
`compute_advisory_report()`-Aggregator mit **24 Sektionen**
(Stand U-94 2026-06-05) — gleicher Dict-Output fuer PDF + Sub-App.

**Aggregator-Sektionen 1-24:** siehe [README.md](../README.md#aggregator-sektionen).

**Sub-App** (`5eyes-electron/frontend/reporting/`) ist die Berater-
interne Anzeige des gleichen Dicts via Vite-Dev-Server. Token-Handoff
vom Hauptapp via URL-Fragment (`#token=<jwt>`).

PDF-Output landet als `*.pdf` im konfigurierten Output-Ordner. Berater
kann via Klick aus der Hauptapp anstoesen — Loading-Spinner zeigt
Fortschritt (U-25).

## 8. Compliance-Drilldown

Sub-App zeigt eine eigene **Compliance-Dashboard-Sektion** (Sektion 17)
die die FINMA-relevanten Backend-Sektionen 19-23 aggregiert:

- `suitability_compliance` (Eignungs-Audit)
- `methodology_models` (welche Modelle/Quellen werden genutzt)
- `recommendation_methodology` (Optimizer-Run-Metadata)
- `mandate_lock_status` (Ist Mandat editierbar?)
- `liquidity_cascade` (Liquiditaets-Stage Warning)

Plus seit U-94: `optimizer_run_history` (Audit-Trace der letzten 10
Solver-Laeufe pro Mandat).

**Vor Druck pruefen:** Compliance-Dashboard zeigt rote/gelbe Banner
wenn Mismatches/Konflikte vorhanden sind. Berater sieht das BEVOR
der Kunde den Bericht zu Gesicht bekommt.

## 9. Datenpflege (CMA + FX)

**CMA (Capital Market Assumptions):** Renditeerwartungen pro
Asset-Klasse. Konvention: bei Bandbreiten der oeffentlichen Daten
**immer den tieferen Wert** nehmen (Ruhestandsgelder-Prinzip).

Pflege-Workflow:
- Admin-Modal -> CMA-Editor -> Werte aktualisieren
- Quartalsweise empfohlen (BlackRock/JPM/Vanguard publizieren
  CMA-Updates quartalsweise)
- Per `PUT /admin/system/annual-returns/{year}/{asset_class}`
  wird ein Audit-Eintrag (UPDATE/CREATE) geschrieben (U-102)

**Nelson-Siegel CHF-Curve:** Standardmaessig auf 2024-12-31
kalibriert (U-100). Re-Kalibrieren mit aktuellen SNB-Daten:
```python
from services.rates.ns_calibration_2024 import calibrate_from_market_yields
result = calibrate_from_market_yields(
    {0.25: 50, 1.0: 35, 5.0: 50, 10.0: 65, 30.0: 85},  # bps
    calibration_date_iso="2026-03-31",
)
```

**FX-Refresh:** Im Hintergrund laeuft Daily-Cron (U-31). Wenn du nur
FX manuell aktualisieren willst (ohne den vollen Marktdaten-Sweep):
`POST /admin/system/fx-rates/refresh-now` (U-99). Audit-Log
schreibt einen `MARKET_DATA_REFRESH`-Eintrag.

## 10. Audit-Log einsehen

Alle Berater-Aktionen werden im AuditLog geloggt mit
Hash-Chain-Integritaet (kein Eintrag kann unbemerkt geaendert werden).

**Anzeige:** Admin-Modal -> Audit-Log-Tab. Filter nach:
- `action` (Whitelist: CREATE/UPDATE/DELETE/LOGIN/EXPORT/
  PASSWORD_RESET/OPTIMIZER_MODE_CHANGE/BACKFILL/BACKUP/
  SUPPORT_BUNDLE/MARKET_DATA_REFRESH/MARKET_DATA_PURGE/
  DB_OPTIMIZE/FOUNDATION_EXAMPLE)
- `q` (Volltext-Suche auf user_name + table_name)

**Bulk-Cleanup von RecommendationRuns >90 Tage (U-104):**
`POST /admin/system/recommendation-runs/cleanup` mit `dry_run=true`
zeigt erst was geloescht WUERDE, dann ohne `dry_run` echte
Loeschung. Audit-Eintrag mit Count.

**Datenexport (DSG Art. 25, U-10):** `GET /clients/{id}/data-export`
liefert alle 23 Sektionen der Mandantendaten als JSON. EXPORT-Audit
+ Legal-Basis-Notes pro Tabelle.

## 11. Wenn etwas schief laeuft

**Anzeigefehler im Beratungsbericht:** Top-Level ErrorBoundary
(U-87) faengt JS-Fehler in der Sub-App ab und zeigt eine
Berater-taugliche Fallback-UI ("Anzeigefehler im Beratungsbericht")
mit "Erneut versuchen" + "Bericht neu laden" Buttons. Tech-Details
im Entwickler-Log fuer Post-Mortem.

**Provider down (yfinance/stooq):** Provider-Health-Registry
(U-30 P5.1) trackt Failure/Recovery-Events. Admin-Modal zeigt den
aktuellen Status. Fallback-Cascade in der Pipeline sorgt dafuer dass
ein Provider-Ausfall die Beratung nicht blockiert.

**DB-Probleme:** `GET /admin/system/db/integrity` startet einen
Integritaets-Check. Backup via `POST /admin/system/db/backup` (U-102
auditiert).

**Notfall-Datenexport:** Wenn das Berater-System ausfaellt, lebt
die DB als SQLite-File. `python scripts/data_export.py
{client_id}` produziert einen vollstaendigen Export ohne dass das
Backend laeuft.

---

## Weiterfuehrendes

- [README.md](../README.md) — technische Subsystem-Uebersicht
- [GLOSSAR.md](GLOSSAR.md) — Begriffsdefinitionen
- [adr/](adr/) — Architektur-Entscheidungen (warum so gebaut)
- [data_pipeline_README.md](data_pipeline_README.md) — Marktdaten-
  Pipeline aktivieren
- [DATA_PIPELINE_STATUS.md](DATA_PIPELINE_STATUS.md) — Status der
  Pipeline-Phasen
- [RELEASE_TAGS.md](RELEASE_TAGS.md) — Versionierungs-Workflow
- [BACKUP.md](../5eyes-backend/BACKUP.md) — DB-Backup-Strategie
- `5eyes-electron/frontend/reporting/DESIGN_SYSTEM.md` —
  Tailwind-Tokens (fuer Sub-App-Customizing)
