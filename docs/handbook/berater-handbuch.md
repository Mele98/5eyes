# 5eyes — Berater-Handbuch

**Roadmap #78** · Status: v1 (Ist-Stand 2026-06-15)

Kurzanleitung durch den Beratungs-Workflow + die wichtigsten Funktionen. Methodik-Quelle:
Customer Journey **SD → CF/Ziele → RP → SAA → PO**. Kein Markt-Timing, keine aktive
Überwachung ([ADR-003](../adr/ADR-003-anlagephilosophie-no-market-timing.md)).

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
4. **Risikoprofil (Seite 4)** — FINMA W305: Risikofähigkeit + -bereitschaft → Score.
   FZK-Cap bei 75 (= 7.5/10). Nach Vorlage aufgebaut — nicht umgestalten.
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

## 7. Compliance-Bezug
- Eignungsprüfung (FIDLEG), Beratungsprotokoll, Ex-ante-Kostenausweis sind im Prozess
  bzw. Report abgebildet. Datenexport für Kunden (revDSG Art. 25) vorhanden.
- Beim Hosting: AVV / FINMA-Outsourcing / DSFA — siehe [../compliance/](../compliance/).

---
*Versionierung: bei neuen Funktionen aktualisieren. Quelle Methodik: Customer-Journey-Memory + ADR-003.*
