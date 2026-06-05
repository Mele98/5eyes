# 5eyes — Onboarding fuer neue Berater

Erst-Setup-Anleitung fuer Berater die zum ersten Mal mit 5eyes
arbeiten. Komplementaer zu
[BERATER_README.md](BERATER_README.md) (Tag-zu-Tag-Workflows) und
[GLOSSAR.md](GLOSSAR.md) (Begriffe). Hier:
**Tag 1 bis Woche 2** — wie du startklar wirst.

**Stand:** 2026-06-05
**Ziel:** Vom Erstkontakt bis zum ersten signierten Beratungsreport
in <= 2 Wochen.

---

## Inhalt

1. [Voraussetzungen](#1-voraussetzungen)
2. [Account-Setup (Tag 1)](#2-account-setup-tag-1)
3. [System-Tour (Tag 1-2)](#3-system-tour-tag-1-2)
4. [Test-Mandat erstellen (Tag 3)](#4-test-mandat-erstellen-tag-3)
5. [Erster Test-Report (Tag 4-5)](#5-erster-test-report-tag-4-5)
6. [Compliance-Grundlagen (Woche 2)](#6-compliance-grundlagen-woche-2)
7. [Erstes echtes Mandat (Ende Woche 2)](#7-erstes-echtes-mandat-ende-woche-2)
8. [Selbst-Check Checkliste](#8-selbst-check-checkliste)

---

## 1. Voraussetzungen

**Was du mitbringen solltest:**
- FINMA-Zulassung als Anlageberater oder Vermoegensverwalter
- Grundverstaendnis der FIDLEG-Pflichten (Risikoprofil, Eignungs-
  pruefung, Beratungsprotokoll, Konflikt-Offenlegung)
- Grundverstaendnis Asset Allocation, Risiko/Rendite-Trade-off,
  Anlagehorizont-Konzept

**Was du NICHT brauchst:**
- Programmier-Kenntnisse (Backend laeuft im Hintergrund)
- Marktdaten-Abo (5eyes nutzt gratis Quellen, siehe
  [ADR-005](adr/ADR-005-free-data-pipeline.md))

**Hardware:**
- Windows-PC mit Windows 11
- Mindestens 8 GB RAM
- 5 GB Speicherplatz (DB waechst mit Kunden-Stand)

## 2. Account-Setup (Tag 1)

**Schritt 1: Installation**

Berater-Installation kommt als Electron-Paket. Bei Erst-Start:
- 5eyes-Backend startet automatisch auf `http://127.0.0.1:8000`
- DB wird angelegt unter `%APPDATA%/5eyes/5eyes.db` (SQLCipher-
  verschluesselt)
- Initialer Admin-User wird beim ersten Login erstellt

**Schritt 2: Erst-Login**

- Username + Passwort gemaess Setup-Anweisung
- Beim ersten Login: Passwort aendern (PASSWORD_RESET wird auditiert)
- Token-TTL ist 8h default. Nach 8h Inaktivitaet musst du dich
  erneut anmelden.

**Schritt 3: Master-Daten pruefen**

Im Admin-Modal pruefen:
- **Optimizer-Mode** (Default `house_matrix`. `stochastic` ist
  opt-in fuer Berater die das brauchen)
- **CMA-Snapshot** ist aktuell (Quartals-Pflege empfohlen, siehe
  Workflow 9 in BERATER_README)
- **Nelson-Siegel-Curve** ist auf 2024 kalibriert (U-100)
- **FX-Reihen** sind aktuell (Daily-Cron laeuft, U-31)

## 3. System-Tour (Tag 1-2)

Lies in dieser Reihenfolge:

1. **[BERATER_README.md](BERATER_README.md)** — Tag-zu-Tag-Workflow
   (1-2h Lesezeit)
2. **[GLOSSAR.md](GLOSSAR.md)** — Begriffsdefinitionen
   (30-45 min, wichtig: Gesamt-vs-Beratungsvermoegen, IST vs SOLL,
   SAA vs Portfolio)
3. **[adr/README.md](adr/README.md)** — Architektur-Entscheidungen
   (30 min, wichtig: ADR-003 Anlagephilosophie ohne Markt-Timing)

**Aktiv ausprobieren:**

- Klicke dich durch die Hauptapp (Kundenstamm-Liste, Mandat-Detail,
  SAA-Editor)
- Oeffne die Reporting Sub-App (Klick auf "Bericht" oeffnet
  Vite-Dev :5173 mit Token-Handoff via URL-Fragment)
- Schau die API-Doku unter `http://127.0.0.1:8000/docs` an
  (Swagger UI listet alle Endpoints)

## 4. Test-Mandat erstellen (Tag 3)

**Foundation-Example:** Im Admin-Modal kannst du via
`POST /admin/system/foundation-example` ein vollstaendiges Test-
Mandat anlegen (Stammdaten + Cashflows + Ziele + Risikoprofil +
SAA). Spielt durch ohne dass du echte Kunden-Daten brauchst.

**Eigenes Test-Mandat:**

1. **Stammdaten:** Fiktiver Kunde, dein eigenes Geburtsjahr +/- 5J,
   Steuerdomizil = dein Kanton
2. **Cashflows + Ziele:**
   - Pension ab 60 mit CHF 60'000/Jahr (Primaer)
   - Hauskauf in 5J mit CHF 200'000 (Sekundaer)
3. **Risikoprofil:** durch den 11-Fragen-Workflow gehen, beobachten
   wie sich der Score aendert
4. **SAA generieren:** House-Matrix-Default
5. **Portfolio:** mit Building Blocks aus dem Default-Universum

**Was du dabei lernst:**
- Die Customer-Journey-Reihenfolge ist verbindlich
  (Stammdaten -> Cashflows -> Risikoprofil -> SAA -> Portfolio)
- Erkenntnisse-Sektion 7 zeigt 10 Pruefpunkte mit Ampel-Bewertung
- ESG/SFDR-Filter (U-95) hilft Building-Blocks zu finden

## 5. Erster Test-Report (Tag 4-5)

**PDF generieren:**

In der Hauptapp -> "Bericht generieren". Backend rendert via
`compute_advisory_report()` (24 Sektionen Stand U-94) und liefert
PDF zurueck.

**Sub-App anschauen:** Klick "Bericht ansehen" oeffnet Sub-App
mit gleicher Datenstruktur. Klick durch die Sidebar
(17 Sub-App-Sektionen, inklusive Compliance-Aggregator-Sektion 17).

**Was du pruefen sollst:**
- [ ] Risikoprofil ist GRUEN in Erkenntnisse (frisch erfasst)
- [ ] Waehrungsstruktur-Item zeigt sinnvolle Bewertung
- [ ] Waehrungsabsicherung (U-98) zeigt konkrete Hedge-Quote
- [ ] Aggregator-Sektion 16 (Beratungsprotokoll) ist leer wenn
      noch kein Gespraech protokolliert
- [ ] Compliance-Dashboard (Sub-App-Sektion 17) zeigt
      Mandate-Lock-Status, Liquidity-Cascade, Suitability-Compliance
- [ ] Optimizer-Run-History (U-94) zeigt leere Liste bei
      house_matrix-Modus (kein Solver-Lauf erwartet)

**ErrorBoundary (U-87):** Wenn die Sub-App einen Render-Fehler hat
(sollte nicht passieren, aber...), siehst du keine weisse Seite
sondern eine berater-taugliche Fallback-UI mit "Erneut versuchen"
und "Bericht neu laden" Buttons.

## 6. Compliance-Grundlagen (Woche 2)

**FIDLEG-Pflichten** die 5eyes durchsetzt:

| Pflicht | Aggregator-Sektion | Sprint |
|---------|---------------------|--------|
| Risikoprofil dokumentieren | 12 (`risikoprofilierung`) | U-P21 |
| Eignungspruefung | 19 (`suitability_compliance`) | U-66 |
| Beratungsprotokoll | 16 (`beratungsprotokoll`) | U-FINMA-2.2 |
| Konflikt-Offenlegung | 18 (`conflict_disclosures`) | U-68 |
| Methodik-Audit | 20 (`methodology_models`) | U-73+U-74 |
| Empfehlungs-Audit | 21 (`recommendation_methodology`) | U-69 |
| Solver-Run-Trace | 24 (`optimizer_run_history`) | U-94 |

**DSG Art. 25 (Datenexport):** Wenn ein Kunde alle seine Daten
verlangt: `GET /clients/{id}/data-export` liefert vollstaendiges
JSON. EXPORT-Audit-Log + Legal-Basis-Notes.

**Override-Workflow (U-28/U-29):** Wenn du den Risikoprofil-Score
manuell anpassst, brauchst du eine Begruendung mit:
- **>= 20 Zeichen**
- **>= 3 sinnvolle Worte** (Floskeln wie "passt zum Kunden" werden
  abgelehnt via Phrase-Blacklist)

**Audit-Log:** Alle deine Aktionen werden auditiert mit Hash-Chain-
Integritaet. Admin-Modal -> Audit-Log zeigt die Verlaeufe. Bei
FINMA-Audit kannst du dort jeden Schritt rekonstruieren.

## 7. Erstes echtes Mandat (Ende Woche 2)

Wenn du die Compliance-Workflows verstanden hast:

1. **Stammdaten:** echter Kunde, alle Pflichtfelder
2. **Cashflows + Ziele:** mit Kunde besprechen, dokumentieren
3. **Risikoprofil:** mit Kunde durchgehen, Override nur mit
   wasserdichter Begruendung
4. **SAA:** generieren, mit Kunde besprechen, signieren lassen
5. **Beratungsprotokoll erfassen** (PFLICHT vor PDF-Druck!)
6. **PDF generieren + Kunde uebergeben** (gedruckt oder
   verschluesselt elektronisch)

**Wichtig:** PDF darf erst gedruckt werden wenn die
Compliance-Dashboard-Sektion 17 (Sub-App) keine roten Banner zeigt.
Mismatches oder fehlende Pflichtfelder schlagen dort auf.

## 8. Selbst-Check Checkliste

Nach Woche 2 solltest du:

- [ ] Token-Login + TTL verstehen
- [ ] Customer-Journey-Reihenfolge auswendig kennen
- [ ] Unterschied Gesamt- vs Beratungsvermoegen
  erklaeren koennen
- [ ] Unterschied IST vs SOLL kennen
- [ ] Risikoprofil-Override mit gueltiger Begruendung machen
  koennen
- [ ] Beratungsprotokoll-Eintrag erstellen (manuell oder Auto-Log)
- [ ] Erkenntnisse-Sektion 7 lesen + Handlungsempfehlungen
  weitergeben koennen
- [ ] Currency-Hedge-Vorschlag (U-98) interpretieren koennen
- [ ] Compliance-Dashboard (Sub-App-Sektion 17) lesen koennen
- [ ] CMA-Werte pflegen (Quartals-Update)
- [ ] FX-Recovery anstossen koennen (U-99)
- [ ] Optimizer-Run-History (U-94) als Audit-Trace nutzen
- [ ] Audit-Log einsehen + filtern (action-Whitelist U-102)
- [ ] DSG-Datenexport anstoesen (U-10)
- [ ] Backup-Status pruefen (U-102 BACKUP-Audit)
- [ ] PDF-Generierung + Sub-App-Anzeige beherrschen

Wenn alle Punkte abgehakt: Du bist startklar.

---

## Bei Fragen

- **System-Probleme:** [BERATER_README.md Sektion 11](BERATER_README.md#11-wenn-etwas-schief-laeuft)
- **Begriffe unklar:** [GLOSSAR.md](GLOSSAR.md)
- **"Warum ist das so gebaut?"**: [adr/](adr/) Architektur-Entscheidungen
- **Technische Details:** [README.md](../README.md) + Swagger-UI
- **Codex-Kollaboration:** [CODEX_WIP.md](CODEX_WIP.md) (fuer
  Engineer/CTO-Sicht)

## Naechste Schritte nach Onboarding

- 1x pro Quartal: CMA-Update + Nelson-Siegel-Re-Kalibrierung
  (U-100 mit aktuellen SNB-Daten)
- 1x pro Monat: Audit-Log-Review (auf ungewoehnliche Patterns
  achten)
- 1x pro Woche: Backup-Status pruefen (U-102)
- Bei Marktstress: proaktiv mit Kunden Kontakt aufnehmen
  ([ADR-003](adr/ADR-003-anlagephilosophie-no-market-timing.md):
  Software ist NICHT der Trigger, du bist es)
