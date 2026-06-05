# 5eyes — Glossar

Begriffsregister für Berater, Engineering und Compliance. Wenn ein Begriff
im Code oder PDF auftaucht, muss er hier definiert sein. Drift-getestet via
`5eyes-backend/tests/test_glossar_consistency.py`.

Stand: 2026-06-05

---

## A

**Aggregator** — Backend-Funktion `compute_advisory_report()` in
`5eyes-backend/services/advisory_report.py`. Liefert ein Dict mit 23
Sektionen für PDF-Rendering und Sub-App-Anzeige. Single-Source-of-Truth für
den Beratungsreport.

**Anlagephilosophie** — 5eyes betreibt **keine** aktive
Portfolio-Überwachung und **kein** Markt-Timing. Re-Balancing erfolgt
ausschließlich (a) im Rahmen der periodischen Eignungsprüfung oder (b) auf
Kunden-Initiative. Auto-Trigger sind explizit ausgeschlossen.

**Asset Allocation** — Aufteilung des Beratungsvermögens auf Asset-Klassen
(Aktien, Obligationen, Liquidität, Sachwerte, Alternative). Im PDF
Sektionen 8/9/10. Basis = SOLL, nicht IST.

**Audit-Log** — Verkettete Eintragsliste in der DB
(`AdvisoryLog`/`AuditLog`), FINMA-relevant. Read- und Write-Events werden
protokolliert. Retention via `retain_until`.

**Auth** — Bearer-JWT via `POST /auth/login`. TTL 8h default (U-59), max
24h in Production erzwungen.

## B

**Beratungsprotokoll** — FINMA-Pflichtdokumentation jedes
Beratungsgesprächs. Aggregator-Sektion 16
(`beratungsprotokoll`). Erfasst über `AdvisoryLogEditor.tsx` Drawer im
Sub-App. Auto-Log bei Suitability-Mismatch (U-FINMA-2.2).

**Beratungsvermögen** — Teilmenge des Gesamtvermögens, die unter
5eyes-Beratung steht. Basis für SAA, Torte, Portfolio-Empfehlung. **NICHT**
identisch mit Gesamtvermögen.

**Building Blocks** — Vordefinierte Anlageprodukt-Bausteine (ETFs, Fonds)
mit zugeordneten CMA-Werten. PDF-Sektion 13.

## C

**Cashflow** — Liquiditätsplanung auf Basis **Gesamtvermögen** (IST). Im
Gegensatz zur Torte, die auf Beratungsvermögen basiert.

**CHF 0/Jahr** — Kostendach für Marktdaten-Pipeline. Nur gratis Quellen
(yfinance, stooq, FRED/SNB). Keine bezahlten Vendor-Feeds.

**CMA** — Capital Market Assumptions. Renditeerwartung pro Asset-Klasse.
Konvention: bei Bandbreiten **immer den tieferen Wert** nehmen
(Ruhestandsgelder).

**Compliance-Stack** — 3-Schichten-Architektur:
1. Backend-Aggregator (`services/advisory_report.py`)
2. PDF-Renderer (`services/pdf/components/compliance_audit.py`)
3. Sub-App-Page (`frontend/reporting/src/pages/Compliance.tsx`)

**Conflict Disclosures** — Interessenskonflikte (Provisionen, Retros,
verbundene Produkte). Aggregator-Sektion 18 (`conflict_disclosures`).
FIDLEG-Pflicht.

**Customer Journey** — Schritt-Sequenz: Stammdaten → Cashflows/Ziele →
Risikoprofil → SAA → Portfolio-Optimierung. Portfolio = Ableitung der SAA,
**nicht** Bestand-vs-Empfehlung.

## D

**DSG** — Schweizer Datenschutzgesetz. Art. 25 Datenexport implementiert
(U-10). Endpoint `GET /clients/{id}/data-export`, advisor-only,
EXPORT-Audit.

**Drift-Test** — Test-Pattern: parst Quell-Datei und prüft Konsistenz
zwischen Backend, Frontend oder Doku. Verhindert dass Code wegläuft ohne
dass Tests fehlschlagen.

## E

**Eignungsprüfung** — Suitability-Check. Vergleich Kunden-Risikoprofil mit
Portfolio-Risikoprofil. Mismatch → Override-Workflow mit
Begründungspflicht (U-28/U-29).

**Editorial Design** — Sub-App-Design-System: Cormorant Garamond + Inter,
matte Status-Farben. Siehe
`5eyes-electron/frontend/reporting/DESIGN_SYSTEM.md`.

## F

**FIDLEG** — Schweizer Finanzdienstleistungsgesetz. Pflichten:
Risikoprofil, Beratungsprotokoll, Eignungsprüfung,
Konflikt-Offenlegung. Aggregator-Sektionen 16/18/19 decken dies ab.

**FINMA** — Eidgenössische Finanzmarktaufsicht. 5eyes ist
FINMA-konform-orientiert. Risikoprofil-Fragebogen folgt FINMA-Vorlagen.

## G

**Gesamtvermögen** — Komplettes Kundenvermögen (IST). Basis für Cashflow.
**NICHT** identisch mit Beratungsvermögen.

**Goal-Klassifikation** — 6 Status für Ziel-Erreichbarkeit: `erreichbar`,
`knapp`, `nicht_erreichbar`, `past`, `beyond_horizon`, `unknown`. Berechnet
via Monte-Carlo-Pfade (U-11/U-12).

## H

**Hauptapp** — `5eyes-electron/frontend/5eyes_v2.html`. Monolithische
Electron-App für Berater (Kundenstamm, Mandat, SAA, Reports). Token-Quelle
für Sub-App.

**Health-Endpoints** — `/health` (root), `/health/live` (Liveness, kein
DB-Hit), `/health/ready` (Readiness, mit DB-Check). U-63.

## I

**IST** — Aktueller Bestand des Kunden (alle Konten/Depots).
Basis für Cashflow.

## L

**Liquidity Cascade** — 4-stufige Eskalations-Logik bei
Liquiditäts-Engpässen. Stages: `normal`, `hard_cap` (300bps),
`emergency` (1000bps), `unknown`. Aggregator-Sektion 23
(`liquidity_cascade`, U-21).

## M

**Mandat** — Beratungsauftrag eines Kunden bei 5eyes. Status: `Entwurf`,
`Aktiv`, `Geschlossen`. Mandate-Lock-Audit (U-22) kontrolliert
Editierbarkeit.

**Methodology Models** — Dokumentation der genutzten Risiko-/Optimierungs-
Modelle (CMA-Quellen, Optimizer-Modus). Aggregator-Sektion 20.

**Monte-Carlo-Pfade** — Stochastische Vermögensprojektion über
Anlagehorizont. Default 1000 Pfade, antithetic, Cornish-Fisher fat-tails,
deterministisch via Seed. Aggregator-Sektion 11.

## P

**Plugin-Tax** — Steuer-Architektur als Strategy-Pattern + Registry.
Jedes Land ist eigenes Plugin. Modular erweiterbar.

**Portfolio** — Konkrete Produkt-Liste als **Ableitung der SAA**. NICHT
Vergleich Bestand-vs-Empfehlung (das ist Customer-Journey-Reihenfolge).

## R

**Re-Balancing** — Manueller Prozess. Nur ausgelöst über
Eignungsprüfungs-Zyklus oder Kunden-Anfrage. Keine
Markt-Timing-Trigger.

**Recommendation Methodology** — Erklärung wie Empfehlungen
zustande kommen (Modell, Datenquellen, Annahmen).
Aggregator-Sektion 21 (`recommendation_methodology`).

**Reporting Sub-App** — `5eyes-electron/frontend/reporting/`. React/Vite,
Advisory-Report-Anzeige. Token-Handoff via URL-Fragment vom Hauptapp.

**Risikoprofil** — Kunden-Risikotragfähigkeit aus standardisiertem
Fragebogen (FINMA-Vorlage). NIE per UX-Refactor anfassen, nur
Bugfixes/Robustheit.

**Risikowährungen** — Fremdwährungs-Exposition im Portfolio. PDF-Sektion 9.

## S

**SAA** — Strategische Asset Allocation. Langfristige Sollportfolio-Struktur.
Pro Risikoprofil definiert. Quelle für Portfolio-Ableitung.

**SOLL** — Zielportfolio. Basis für Torte/SAA. Gegenstück zu IST.

**Stochastic Optimizer** — Mulvey/Ziemba-light Solver für SAA-Optimierung.
Phase 1-4 fertig, opt-in via `OPTIMIZER_MODE=stochastic`.

**Stress-Replay** — Backtest-artige Simulation historischer
Markt-Stress-Phasen (2008, 2020, 2022) gegen aktuelles Portfolio.
Aggregator-Sektion 17 (`stress_replay`).

**Sub-App** — siehe Reporting Sub-App.

**Suitability** — siehe Eignungsprüfung. Aggregator-Sektion 19
(`suitability_compliance`).

## T

**Torte** — Asset-Allocation-Pie-Chart. Basis: SOLL/Beratungsvermögen.
**NICHT** Gesamtvermögen.

**Token-Handoff** — Token-Übergabe Hauptapp → Sub-App via URL-Fragment
(`#token=<jwt>`). Sub-App räumt Fragment nach Read.

## W

**WealthArchitekten** — Produktname. 5eyes ist die Software-Plattform der
WealthArchitekten-Beratung.

---

## Begriffe die NICHT auftauchen dürfen

- Drittmarken: Swiss Life, UBS, Pictet, Julius Bär, 3eyes, PPC Metrics
- Garantie-Sprache: "garantiert", "sicher", "risikofrei"
- Markt-Timing-Sprache: "jetzt einsteigen", "Markt-Chance nutzen"
