# Scope Split ohne Asset Allocation

Stand: 2026-05-10  
Kontext: Asset Allocation bleibt vorerst bei Claude. Codex fasst diesen Bereich nicht fachlich/visuell an, ausser um Schnittstellen stabil zu halten.

## Grundregel

Claude arbeitet oben: sichtbare Kundenreise, UX, Copy, Layout, Priorisierung, Beratungslogik.

Codex arbeitet unten: technische Stabilitaet, Handler, IDs, Datenfluss, Tests, Fehlerbehandlung, Print/Report-Mechanik.

Asset Allocation ist fuer diesen Sprint ausgeklammert:

- Claude darf dort weiterarbeiten.
- Codex aendert dort keine UX, keine Fachlogik und keine sichtbare Struktur.
- Codex prueft nur, dass bestehende Schnittstellen nicht brechen, z.B. `calculateInvestmentStrategy()`, `refreshStrategyData()`, Summary-Daten und Tests.

## 1. Stammdaten, Mandat, Haushalt

Bereich: `page-sd`, `m-nc`, `m-es`, `m-aw`

Wichtigkeit: P0

Was existiert:

- Mandats-/Kundenkontext.
- Haushalt und Stammdaten.
- Holistisches Vermoegen: Beratungsvermoegen, anderes Vermoegen, Verbindlichkeiten.
- Neues Mandat.
- Stammdaten bearbeiten.
- Vermoegensposition erfassen.

Claude oben:

- Sichtbare Struktur vereinfachen.
- Kunde soll sofort erkennen: Wer ist erfasst? Was ist Beratungsbasis? Welche Vermoegensteile gehoeren zur Beratung und welche nur zum holistischen Bild?
- Copy kundenfreundlich halten, keine technische Datenbanksprache.

Codex unten:

- `saveClientData()` pruefen.
- `saveWealthPosition()` pruefen.
- Legacy-Editoren `m-edit-depot`, `m-edit-immo`, `m-edit-hypo`, `m-edit-custom` sauber redirecten oder spaeter entfernen.
- Tests fuer Speichern/Bearbeiten/Loeschen vorbereiten.

Nicht anfassen durch Codex:

- Asset-Allocation-Ableitung aus Vermoegensdaten, solange Claude dort aktiv ist.

## 2. Risikoprofil

Bereich: `page-rp`, `m-rp-print`, `m-overr`

Wichtigkeit: P0

Was existiert:

- FINMA W305.02 Fragebogen.
- Kenntnisse/Erfahrungen.
- Risikofaehigkeit.
- Risikobereitschaft.
- Risikoprofil speichern.
- Risiko-PDF/Druck.
- Override-Modal.

Claude oben:

- Fragebogen visuell ruhiger und beratungsfreundlicher machen.
- Ergebnis fuer Kunden erklaeren: nicht nur Score, sondern warum das Profil passt.
- PDF/Druck sprachlich ehrlich formulieren.

Codex unten:

- `saveRiskProfile()` stabil halten.
- Risiko-Speichern -> dirty state -> Summary-Daten pruefen.
- `m-rp-print` auf sauberen Printflow bringen, ohne echte PDF-Engine vorzutäuschen.
- Fehler sichtbar machen, nicht nur Konsole.

Nicht anfassen durch Codex:

- Mapping Risiko -> Asset Allocation fachlich nicht veraendern.

## 3. Ziele und Cashflows

Bereich: `page-ub`, `m-acf`, `m-nz`

Wichtigkeit: P0

Was existiert:

- Cashflow erfassen.
- Ziel erfassen.
- Zufluesse/Abfluesse.
- Zielarchitektur.
- Zielerreichung als spaeterer Summary-Wert.

Claude oben:

- Ziele und Cashflows so darstellen, dass der Kunde nur bestaetigen muss: korrekt, vollstaendig, plausibel.
- Zielerreichung als klare Aussage zeigen, nicht als Rechenwand.
- Nicht zu viele Detailfelder im Hauptscreen.

Codex unten:

- Doppelte Ziel-Funktionen bereinigen:
  - `saveGoal()`
  - `openGoalEditor()`
  - `resetGoalModal()`
  - `refreshGoalsUI()`
  - `dg()`
- `saveCashflow()` testen.
- Ziel/Cashflow anlegen, bearbeiten, loeschen testen.
- Daten fuer Summary stabil bereitstellen.

Nicht anfassen durch Codex:

- Wie Ziele in Asset Allocation gewichtet werden.

## 4. Portfolio, Einzeltitel, Bestände

Bereich: `page-po`, `m-ap`, `m-ums`

Wichtigkeit: P0/P1

Was existiert:

- Portfolio & Einzeltitel.
- Bestand zu Empfehlungstitel erfassen.
- Depotbank, Konto, Stueckzahl, Marktwert, Einstand, Standdatum, Quelle.
- Umsetzung bestaetigen.

Claude oben:

- Portfolio als Beratungs-/Umsetzungsbruecke zeigen, nicht als Trading-Tool.
- Unterschied zwischen Sollbild, Empfehlung und effektivem Bestand klar machen.
- Consulting-Wording: Snapshot, Quelle, Standdatum.

Codex unten:

- `savePortfolioHolding()` pruefen.
- `deletePortfolioHolding()` pruefen.
- Fehlerboxen und Button-Zustaende verbessern.
- Marktdaten-Stubs klaeren:
  - `fetchPrice()`
  - `loadLivePrices()`

Nicht anfassen durch Codex:

- Produktauswahl-Logik der Asset Allocation.

## 5. Review, Drift, Trigger, Protokoll

Bereich: `page-rv`, `m-ed`, `m-ne`, `m-nt`, `m-ev`

Wichtigkeit: P1, teilweise P0

Was existiert:

- Review Policy.
- Drift-Entscheidung.
- Protokolleintrag.
- Trigger definieren.
- Lebens-/Portfolioereignis erfassen.
- Advisory Log.
- Dokumente.

Claude oben:

- Review als Consulting-Nachweis formulieren.
- Nicht versprechen, dass wir laufend Depotdaten ueberwachen, wenn Assets nicht bei uns liegen.
- Spaeteren Wealth-Management-Ausbau strukturell offenlassen.

Codex unten:

- `saveAdvisoryLogEntry()` testen.
- `saveReviewTrigger()` testen.
- `runtimeProtokolliereEreignis()` testen.
- `documentDecisionTemplate()` pruefen.
- Review-Prints von `window.print()` weg auf einheitlichen Printflow bringen.
- UI-Fehler statt stillem `console.warn()`.

Nicht anfassen durch Codex:

- Drift-Herleitung aus Asset Allocation, solange Claude dort arbeitet.

## 6. Zusammenfassung / POS

Bereich: `page-sr`

Wichtigkeit: P0

Was existiert:

- Kompakte Kundenfreigabe.
- Risiko bestaetigen.
- Ziele/Cashflows bestaetigen.
- Portfolio/Umsetzung bestaetigen.
- Entscheid.
- Abschluss/Dokumentation.
- Summary-Print.

Claude oben:

- Das ist der Point of Sales.
- Sichtbare Seite maximal schlank, kundenfreundlich, entscheidungsorientiert.
- Keine interne Sprache wie „Management Summary“.
- Kunde soll verstehen: Grundlagen stimmen, Umsetzung ist nachvollziehbar, Dokumentation kann erstellt werden.

Codex unten:

- `renderStrategySummary()` stabil halten.
- `printSummaryPage()` testen.
- Summary-Contract-Tests erweitern.
- Technische IDs erhalten:
  - `sr-approval-grid`
  - `sr-decision-grid`
  - `sr-allocation-compare`
  - `sr-portfolio-print`
  - `sr-goals`
  - `sr-conclusion`
- Ziel-/Cashflow-/Risiko-/Portfolio-Daten sauber in Summary spiegeln.

Nicht anfassen durch Codex:

- Asset-Allocation-Darstellung inhaltlich neu gestalten, solange Claude daran arbeitet.

## 7. Report, Druck, Dokumente

Bereich: `m-rep`, `m-rp-print`, `m-contract-edit`, Review-Druckbuttons, Summary-Druck

Wichtigkeit: P0/P1

Was existiert:

- Report generieren.
- Risikoprofil drucken.
- Vertrag/Strategiedokument bearbeiten.
- Summary drucken.
- Review drucken.

Claude oben:

- Buttonlabels und Copy ehrlich machen.
- Kundendokumente klar benennen.
- Kein leeres PDF-Versprechen, wenn technisch nur Systemdruck vorhanden ist.

Codex unten:

- Alles auf `printReport()` / `printSummaryPage()` vereinheitlichen.
- Direkte `window.print()`-Aufrufe ersetzen.
- Dokumenttitel, Seitenwahl, CSS, Kunde, Datum konsistent halten.
- Optional spaeter echte PDF-Engine vorbereiten.

Nicht anfassen durch Codex:

- Asset-Allocation-Dokumentinhalt fachlich umstellen.

## 8. Admin, Betrieb, Marktdaten

Bereich: `m-admin`, Admin-Funktionen, Preisstatus

Wichtigkeit: P0/P2

Was existiert:

- System-Administration.
- Benutzerliste.
- Backup.
- Integrity.
- Optimierung.
- Logs.
- Support Bundle.
- Market/Price Refresh.
- Product Overrides.

Claude oben:

- Admin UI nur auf Klarheit und Bedienbarkeit pruefen.
- Nicht in Kundenreise aufblasen.

Codex unten:

- `loadAdminUserList()` Fehlerbehandlung pruefen.
- Preisstatus und Refresh sauber machen.
- Frontend-Preis-Stubs bereinigen.
- Admin-Aktionen mit sichtbarem Erfolg/Fehler versehen.

## 9. Aktuelle Codex-Prioritaet ohne Asset Allocation

1. Doppelte Ziel-Funktionen bereinigen.
2. Ziele/Cashflows Save/Edit/Delete testen.
3. Stammdaten/Vermoegen Save/Edit/Delete testen.
4. Summary-Contract-Tests erweitern.
5. Review/Trigger/Protokoll testen.
6. Print/Report vereinheitlichen.
7. Stille Fehler sichtbar machen.
8. Legacy-Modals aufraeumen.
9. Marktdaten-Stubs bereinigen.

## 10. Klare Grenze fuer diesen Sprint

Codex beruehrt Asset Allocation nur fuer:

- Tests, falls bestehende Schnittstellen brechen.
- Summary-Datenvertrag, falls Summary ohne Allocation-Daten abstuerzt.
- Sicherung kritischer Funktionsnamen/IDs.

Codex beruehrt Asset Allocation nicht fuer:

- Layout.
- Copy.
- Fachlogik.
- Optimizer-Parameter.
- Sollquoten-UX.
- Rebalancing-/Simulation-/Monte-Carlo-Darstellung.
- Produktauswahl.

Claude ist dort federfuehrend.

## 11. Codex-Fortschritt 2026-05-10

Erledigt, ohne Asset-Allocation-UX/Fachlogik anzufassen:

1. Doppelte Ziel-/Cashflow-/Admin-Handler bereinigt und per Test auf genau eine kanonische Definition gesichert.
2. Ziele/Cashflows Save/Edit/Delete-Vertraege abgesichert, inklusive Dirty-State fuer Strategie-Neuberechnung.
3. Stammdaten/Vermoegen Save/Edit/Delete-Vertraege abgesichert; Legacy-Wealth-Editoren leiten auf den kanonischen Vermoegenspositions-Editor um.
4. Review/Trigger/Protokoll/Dokumente auf Runtime-Handler und sichtbare Fehlerfuehrung abgesichert.
5. Direktes `window.print()` aus sichtbaren Buttons entfernt; Report/Risiko/Summary laufen ueber `printReport()` bzw. `printSummaryPage()`.
6. Marktdaten-Frontend-Stubs (`fetchPrice`, `loadLivePrices`) delegieren an den Backend-Preisstatus statt stille Platzhalter zu sein.
7. Risikoprofil-Speichern repariert (`surplusPoints` statt undefiniertem `incomePoints`) und Fehler/Summary-Datenfluss abgesichert.
8. Portfolio-Holding Save/Delete nutzt den aktiven Mandatskontext und hat Tests fuer API-Pfad, Validierung, Refresh und Button-Reset.
9. Admin-Benutzerfehler werden neben lokalen Feldern auch global sichtbar ausgegeben.
10. Review-Protokoll-Modal verhindert Trigger-ID-Leaks zwischen triggergebundenen und freien Protokolleintraegen.
11. Event-/Entscheidungs-/Protokoll-Modals setzen Fehlerzustand beim Oeffnen sauber zurueck.
12. Vermoegensposition-Loeschpfad faellt bei fehlendem Kundenkontext nicht mehr versehentlich in Demo-Loeschung.
13. Ziel- und Kundenladefehler sowie Summary-Print-Refresh-Fehler werden sichtbar gemeldet statt nur geloggt.
14. Cashflow- und Stammdaten-Speicherfehler werden lokal und global sichtbar ausgegeben.
15. Neues Mandat setzt Vermoegen, Cashflows, Ziele, Review und Strategie-State sauber zurueck, damit keine Alt-Daten in den neuen Kundenkontext laufen.
16. Kundenliste zeigt leere und fehlerhafte Zustaende sichtbar und escaped Sidebar-Labels.
17. Entfernte Budget-Seite ist als klarer No-op dokumentiert; keine `Stub:`-/`Platzhalter`-Marker bleiben im Frontend.
18. Anlagerezept-Print/Finalisieren stoppt bei fehlgeschlagenem Refresh, setzt Button-Zustand zurueck und zeigt Fehler sichtbar.
19. Initialer Kundenladepfad wartet auf den ersten Kunden, bevor `initApp()` weiterlaeuft.
20. Neu angelegte Kunden werden in `liveClients` synchronisiert; Sidebar-Klicks laden echte Kunden wieder ueber `loadClientById()`.
21. Demo-/Teilfehler beim Mandat-Anlegen leeren den Mandatskontext, damit kein altes Mandat in neuen Screens haengen bleibt.
22. Risikoprofil-Override ist nicht mehr nur visuell: Pflichtbegruendung, Backend-Persistenz, sichtbare Fehler und Summary-Anzeige nutzen den effektiven Override-Score.
23. Review-/Dokument-Flows fuer Protokoll, Trigger, Dokument-Entwurf und Entscheidungsvorlage melden Speicherfehler nun lokal und global sichtbar.
24. Foundation-Case, Ereignis-Erfassung, Vermoegenspositionen und Ziele nutzen bei Speicherfehlern einheitliche `parseApiError`-Meldungen plus globale App-Notices.
25. Login, Bootstrap, Admin-Audit-Log und Admin-Benutzeranlage nutzen ebenfalls sichtbare, einheitliche Fehlerfuehrung statt roher API-Meldungen.
26. Dynamische Inline-Handler fuer Admin, Vermoegen, Cashflows, Review, Dokumente und Ziele nutzen `jsAttrArg()` statt HTML-Escaping als JS-String-Ersatz.
27. Report-/Summary-Druck hat sichtbare Fallback-Meldungen, wenn Druckfenster, Seitenerzeugung oder Druckdialog nicht sauber starten.
28. Loeschpfade fuer Cashflows, Ziele und Vermoegenspositionen setzen Button-Zustaende, warten auf Refreshes und markieren Strategie/Summary konsequent als aktualisierungsbeduerftig.
29. Backdrop-Klicks auf Modals laufen ueber `cm(id)` und damit ueber denselben Cleanup-Pfad wie explizite Schliessen-Buttons.
30. Escape schliesst das oberste nicht gesperrte Modal ebenfalls ueber `cm(id)`, damit Cleanup und Reset konsistent bleiben.

Aktuelle technische Absicherung:

- `tests/test_frontend_summary_contracts.py`
- `tests/test_runtime_contracts.py`
- JS-Syntaxcheck ueber alle Inline-Skripte in `5eyes_v2.html`
