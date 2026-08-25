# 5eyes — Berater-Handbuch

**Roadmap #78** · Status: v1 (Ist-Stand 2026-07-23)

Kurzanleitung durch den Beratungs-Workflow + die wichtigsten Funktionen. Methodik-Quelle:
Customer Journey **SD → CF/Ziele → RP → SAA → PO**. Kein Markt-Timing, keine aktive
Überwachung ([ADR-003](../adr/ADR-003-anlagephilosophie-no-market-timing.md)).

> **Neu (Update Juli 2026)**: Indexierungs-Schalter in der Cashflow-Projektion (§1.3),
> Signatur des Risikoprofils (§1.4), Reserve-Erklärbarkeit im Report (§2), Dark Mode (§6)
> und Eignungsprüfungs-Audit + Kostenausweis + anklickbares PDF-Inhaltsverzeichnis (§7).
> Details siehe [2026-07-changelog.md](2026-07-changelog.md).

---

## 1. Der Beratungs-Workflow (Reihenfolge zwingend)

1. **Stammdaten (Seite 1)** — Person(en), Geburtsdatum, Anrede, Wohnsitz, Haushalt.
   Geburtsdatum + Anrede steuern u. a. den **Planungshorizont** (Lebenserwartung
   = Geburtsjahr + 83 bei Männern / + 85 bei Frauen; Paare: die längere).
2. **Vermögen (Seite 2)** — Konto, Wertschriften, Vorsorge (2./3. Säule), Immobilien,
   Hypotheken. Das **Gesamtvermögen** ist die Basis; daraus wird das
   **Beratungsvermögen** abgegrenzt (das, was zielgerichtet investiert wird).
3. **Cashflows & Ziele (Seite 3)** — Ein-/Ausgaben + Lebensziele.
   - Liste ist **nach Lebensbereich gruppiert** (Erwerb · Vorsorge · Wohnen ·
     Kapital & Vermögen · Lebenshaltung) mit Zwischentotal je Gruppe.
   - **⚙ AUTO-Zeilen** sind vermögensgetriebene Cashflows (z. B. Hypothekarzins,
     Mieteinnahmen, Zinsertrag) — read-only; **Klick springt zur Vermögensposition**
     (dort bearbeiten).
   - Die **IST-Kurve** zeigt den Vermögensverzehr ohne Optimierung (Baseline).
   - **Indexierung berücksichtigen** (Schalter über der IST-Kurve): AN (Standard) =
     inflationsgekoppelte Einnahmen **und** Ausgaben werden über die Jahre gemäss
     Marktszenario (CMA-Inflationspfad) aufgezinst — die Projektion zeigt reale
     Kaufkraftentwicklung. AUS = alle Beträge bleiben nominal (heutige Kaufkraft,
     keine Aufzinsung). Der Schalter berechnet die Projektion im Backend neu, ist
     also kein rein optischer Umschalter — für Kundengespräche eignet sich AN, um
     den langfristigen Effekt der Inflation zu zeigen; AUS für den Vergleich mit
     heutigen, bekannten Beträgen.
4. **Risikoprofil (Seite 4)** — FINMA W305: Risikofähigkeit + -bereitschaft → Score.
   FZK-Cap bei 75 (= 7.5/10). Nach Vorlage aufgebaut — nicht umgestalten.
   - **Signatur des Risikoprofils**: In der Review-Zusammenfassung (Seite 7,
     Karte «Risikoprofil») kann die Eignungsprüfung als **signiert** erfasst
     werden — entweder durch den Kunden selbst im Kunden-Portal, oder durch den
     Berater über den Button **«Signatur erfassen»** (z. B. wenn die Signatur im
     Gespräch mündlich/schriftlich eingeholt wurde, aber der Kunde keinen
     Portal-Zugang nutzt). Die Karte zeigt danach **«✓ signiert am [Datum]
     (Portal)»** bzw. **«… (Berater)»** je nachdem, wer signiert hat; ohne
     Signatur erscheint **«⚠ nicht signiert»**. Bei einer neuen Profilversion
     lässt sich die Signatur jederzeit erneuern (Button wird zu «Signatur
     erneuern»). Dies dokumentiert FIDLEG-konform, dass der Kunde sein
     Risikoprofil zur Kenntnis genommen hat.
5. **Asset Allocation (Seite 5)** — hier wird die **SOLL-Strategie** hergeleitet
   (stochastisch/zielbasiert). Input: Score + Beratungsvermögen + Ziele.
6. **Portfolio (Seite 6)** — Übersetzung der SAA in konkrete Produkte (ISIN).
7. **Review & Abschluss (Seite 7)** — Entscheid, Protokoll, Freigabe.

## 2. Strategie berechnen & lesen
- Button **«Anlagestrategie berechnen»** (Seite 5) startet Engine + Monte-Carlo.
- **SOLL-Prognose**: Best Case (P90) / Hauptszenario (P50) / Worst Case (P10).
- **Kennzahlen-Tabelle (zweispaltig SOLL vs IST)**: Endwert Median, **P90/P10-Endwerte**,
  Rendite p.a., CAGR, **Rendite/Risiko (Sharpe)**, Reichweite, sowie Risiko: Volatilität,
  VaR 95%, CVaR 95%, Max Drawdown, Verlust-Wahrscheinlichkeit. Grün = SOLL besser als IST.
- **Beratungs-Mehrwert** = Differenz Median-Endwert SOLL − IST (heute brachliegendes Cash
  wird investiert).
- **Reserve-Erklärbarkeit** (im Advisory-Report, Abschnitt Compliance-Audit): Wenn die
  SOLL-Allokation eine Liquiditätsreserve ausweist, zeigt der Report **warum** — z. B.
  kurzfristiger Cashflow-Bedarf, nahe Lebensziele oder eine manuelle Vorgabe — und ob ein
  Teil davon als **externe Reserve** (ausserhalb des Beratungsmandats) empfohlen wird, weil
  der Bedarf die strategische Liquiditäts-Obergrenze der SAA übersteigt. Das ist reine
  Herleitung/Dokumentation der bereits bei der Strategie-Berechnung ermittelten Zahlen
  (keine Neuberechnung im Report) — nützlich, um dem Kunden zu erklären, weshalb nicht das
  gesamte Vermögen investiert wird. Falls sich Cashflows/Ziele seit der letzten
  Strategie-Berechnung geändert haben, weist der Report auf diese Datendrift hin und
  empfiehlt, die Strategie neu zu berechnen.

## 3. SOLL vs IST gross vergleichen
- Button **«⤢ SOLL vs. IST gross vergleichen»** öffnet das Vergleichs-Pop-up:
  beide Kurven, **gleiche Achsen + gleicher Horizont**, synchroner Hover.
- **«⤓ PNG exportieren»** speichert beide Grafiken als ein Bild fürs Kundengespräch.

## 4. Horizont der Grafiken
- Standard = Lebenserwartung (Geburt + 83/85). Über das **Anlagehorizont-Feld**
  (Jahre oder Enddatum) auf Seite 3 überschreibbar; «auto» = Ableitung aus Stammdaten.

## 5. Wichtige Prinzipien (Methodik-Disziplin)
- **Holistisch**: Gesamtvermögen inkl. Eigenheim, Vorsorge, Verbindlichkeiten.
- **Zielbasiert**: Lebensziele steuern die Allokation, nicht nur das Risikoprofil.
- **Konservativ**: bei Renditeerwartungen den tieferen Wert (Ruhestandsgelder).
- **Kein Markt-Timing / keine aktive Überwachung**: Re-Balancing nur via Eignungs-
  prüfung oder Kundenmeldung.

## 6. Externer Zugriff & Sicherheit (falls gehostet)
- **Login mit Pflicht-2FA** (Authenticator-App, TOTP). Secret-Copy/QR beim Einrichten.
- **Harte Mandantentrennung**: jede Firma sieht nur ihre eigenen Daten.
- Einladung neuer Berater/Admins via **Invite-Link** (zeitlich begrenzt, einmalig).
- **Dark Mode**: Der Mond-Button oben in der Kopfzeile schaltet zwischen heller und
  dunkler Darstellung um (inkl. Chart-Farben); die Wahl wird pro Gerät gespeichert und
  bleibt bis zur nächsten Umschaltung erhalten. Rein optisch — keine fachliche Wirkung.

## 7. Compliance-Bezug
- Eignungsprüfung (FIDLEG), Beratungsprotokoll, Ex-ante-Kostenausweis sind im Prozess
  bzw. Report abgebildet. Datenexport für Kunden (revDSG Art. 25) vorhanden.
- **Eignungsprüfungs-Audit auf Mandatsebene** (FIDLEG Art. 10/12, Abschnitt
  Compliance-Audit im Advisory-Report): Prüft pro Mandat, ob ein **aktuelles**
  Risikoprofil vorliegt — «aktuell» heisst höchstens 12 Monate alt (Branchenpraxis).
  **«Nicht konform»** bedeutet: es fehlt entweder ganz ein Risikoprofil für dieses
  Mandat, oder das vorhandene ist älter als 12 Monate. In beiden Fällen: mit dem
  Kunden die Eignungsprüfung (Risikoprofil, Seite 4) neu durchgehen und speichern —
  danach zeigt der Audit wieder konform. Ausnahme: reine Execution-only-Mandate
  (ohne Beratung) benötigen keine Eignungsprüfung und gelten automatisch als konform.
  Zeigt der Audit «Prüfung nicht möglich» (statt grün/rot), liegt ein technisches
  Problem beim Auslesen vor — das ist kein Compliance-Befund, sondern ein Hinweis,
  es später erneut zu prüfen.
- **Kostenausweis Ex-ante** (FIDLEG Art. 8/9) ist nicht mehr nur ein eigenständiger
  PDF-Abschnitt, sondern durchgängig Teil des Advisory-Reports (gleiche Zahlen in
  PDF wie in der Online-Ansicht) — Beratungs-/Verwaltungs-, Depot-/Verwahr- und
  ggf. Plattformgebühren sowie einmalige Gebühren, basierend auf der zuletzt
  berechneten Empfehlung.
- Die **PDF-Inhaltsverzeichnisse** in den Berichten sind jetzt anklickbar: ein Klick
  auf einen Eintrag springt direkt zum entsprechenden Abschnitt, zusätzlich gibt es
  ein Lesezeichen-/Outline-Menü am Bildschirmrand des PDF-Viewers — praktisch für
  längere Berichte im Kundengespräch.
- Beim Hosting: AVV / FINMA-Outsourcing / DSFA — siehe [../compliance/](../compliance/).

---
*Versionierung: bei neuen Funktionen aktualisieren. Quelle Methodik: Customer-Journey-Memory + ADR-003.*
