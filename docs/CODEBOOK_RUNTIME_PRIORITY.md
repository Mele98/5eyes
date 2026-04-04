# 5Eyes Runtime Codebook (WIP)

Stand: 2026-04-02
Branch-Kontext: `codex/mc-fan-chart`

## Zielbild

Das System soll als sauberer Funnel funktionieren:

1. Stammdaten und Mandat
2. Gesamtvermoegen vs. Beratungsvermoegen
3. Cashflows, Ereignisse und Ziele
4. Risikoprofil und Risikobudget
5. House Matrix und Zielallokation
6. Sub-Anlageklassen und Simulation
7. Produktempfehlung und Holdings
8. Drift, Rebalancing und Review
9. Audit, Reporting und Administration

Jede Eingabe soll genau eine fachliche Bedeutung haben.
Jede Ableitung soll nachvollziehbar sein.
Jede Ausgabe soll in Beratung und Kontrolle verwendbar sein.

## Wichtigste aktive Runtime-Dateien

- `5eyes-electron/frontend/5eyes_v2.html`
  Rolle: gesamtes Frontend, Navigation, Dialoge, Runtime-State, Charts, Admin, Review
  Risiko: sehr gross, viele Verantwortlichkeiten, hoher Regression-Hebel

- `5eyes-backend/services/portfolio_engine.py`
  Rolle: Kerntrichter fuer Allokation, Simulation, Monte Carlo, Recommendation, Drift
  Risiko: fachlich zentral, bisher zu monolithisch

- `5eyes-backend/routers/review.py`
  Rolle: Produktstamm, Recommendation, Holdings, Review-nahe Schnittstellen
  Risiko: breit, viele Seiteneffekte

- `5eyes-backend/services/cashflow_timeline.py`
  Rolle: Frequenzen, Datierung, Jahreslogik
  Risiko: kleine Datei, aber fachlich sehr sensibel

- `5eyes-backend/services/risk_scoring.py`
  Rolle: Risikofragebogen und Scoring
  Risiko: kleine Datei, aber direkt sichtbar fuer Kunde und Berater

## Hotspot-Ranking

1. `portfolio_engine.generate_target_allocation()`
   Status: bereits gekuerzt und in Hilfsfunktionen zerlegt, aber weiter Kern-Hotspot
   Warum: verbindet Risiko, Ziele, Cashflows, House Matrix und Simulation

2. `5eyes_v2.html::renderEngineRuntimePanels()`
   Status: sehr lang
   Warum: rendert viele Fachdimensionen auf einmal; gute Kandidatin fuer weitere Entflechtung

3. `5eyes_v2.html::buildRiskAssessmentPayloadFromUI()`
   Status: fachlich stabiler, aber noch dicht
   Warum: direkte Bruecke vom Fragebogen in die Engine

4. `5eyes_v2.html::bindLegacyReviewModalActions()`
   Status: funktional, aber weiterhin Legacy-Charakter
   Warum: viele UI-Bindings in einer Funktion

5. `portfolio_engine.build_live_rebalancing_payload()`
   Status: gross und wichtig
   Warum: naechster harter Kern fuer Portfolio/Review/Rezept

6. `review.py`
   Status: breit
   Warum: sammelt zu viele Verantwortlichkeiten fuer Produkte, Runs und Holdings

## Readiness nach Funktionsblock

- Stammdaten: gut
- Vermoegen / Split Gesamt vs. Beratung: gut
- Cashflows: gut, inklusive Datierung; weitere UX-Politur sinnvoll
- Ziele: gut, aber weiterhin sensibel wegen vieler Zieltypen
- Risikoprofil: deutlich besser, weiter kalibrieren gegen Fachvorlagen
- Asset Allocation: lauffaehig, aber Kernlogik weiter entflechten
- Portfolio / Drift / Rebalancing: gut, naechster Fokus auf weitere Erklaerbarkeit
- Review Policy: gut, aber UI/Flow weiter aufraeumen
- Reporting / PDF: funktional, noch nicht Endausbau
- Admin / Marktdata: gut vorbereitet; Manager-Modul fuer Kapitalmarktannahmen jetzt im Admin-Modal sichtbar, weitere Produktivhaertung offen

## Reihenfolge fuer die naechsten Optimierungsbloecke

1. Frontend-Runtime weiter beruhigen
   Ziel: Header, Navigation, Diagramme, Risikoseite und Review sauber und robust

2. `portfolio_engine.py` weiter zerlegen
   Ziel: aus dem grossen Trichter klar lesbare Stufen machen

3. Risk + Goals + Cashflow nochmals gegen Fachlogik spiegeln
   Ziel: keine versteckten konservativen Biases mehr

4. Review- und Portfolio-UI aufraeumen
   Ziel: weniger Dichte, klarere Kundenlogik

5. Marktdaten- und Forecast-Eingabe weiter haerten
   Ziel: Manager kann Annahmen bewusst setzen oder Live-Daten bewusst nutzen, ohne versteckte Defaults

## Manager-/Owner-Sicht: Wo gehoeren Kapitalmarktannahmen hin?

Der technische Pfad ist bereits da:

- `GET /capital-market-assumptions/current`
- `PUT /capital-market-assumptions`

Aktuell gibt es dafuer bereits ein Manager-Modul im Admin-Bereich:

- Assumption Set / Gueltig ab
- Rendite- und Volatilitaetsannahmen fuer Bonds, Aktien, Immobilien, Gold und Liquiditaet
- Inflation, Korrelationen, Quelle und Notizen

Der naechste sinnvolle Ausbau ist jetzt:

- risikofreier Zins explizit machen
- Sub-Anlageklassen statt nur Asset-Klassen
- Prognose-Quelle gegen Live-Marktdaten transparent spiegeln
- Gueltigkeitsdatum / Versionierung sichtbarer machen

So wird sichtbar, was live gezogen wird und was bewusst gesetzt ist.

## Leitregel fuer jede weitere Optimierung

- keine tote UI
- keine doppelte Funktion
- keine stillen Legacy-Ueberschreibungen
- keine unklaren Eingabebedeutungen
- keine Fachlogik in schwer lesbaren Monsterbloeken, wenn sie sauber extrahierbar ist
