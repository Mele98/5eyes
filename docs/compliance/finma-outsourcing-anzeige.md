# FINMA-Outsourcing — Trigger, Prozess & Anzeige-Vorlage

**Roadmap #17** · Status: Vorlage (rechtlich/aufsichtsrechtlich prüfen)
**Stand:** 2026-06-15

> ⚠️ **Kein Aufsichtsrechts-Rat.** Bezug: FINMA-Rundschreiben **2018/3 «Outsourcing –
> Banken und Versicherer»** (sinngemäss auch für beaufsichtigte Vermögensverwalter/
> Wertpapierhäuser relevant; massgebend ist der konkrete Bewilligungstyp der nutzenden
> Firma). Diese Vorlage ist vor Einsatz mit der Compliance-Funktion / dem Rechtsdienst
> der **beaufsichtigten Firma** abzustimmen.

---

## 1. Wann ist 5eyes überhaupt ein meldepflichtiges Outsourcing?

Entscheidend ist, ob eine **wesentliche Funktion** der beaufsichtigten Firma ausgelagert
wird und ob dabei **Kundendaten** beim Betreiber verarbeitet werden.

| Konstellation | Outsourcing-relevant? |
|---|---|
| **T1 Self-Hosted** (Firma betreibt 5eyes selbst, Daten bleiben bei der Firma) | **In der Regel nein** — reiner Software-Bezug, keine Datenauslagerung |
| **T2 Shared-Cloud (CH)** — Betreiber hostet, Kundendaten beim Betreiber | **Ja, prüfen** — Auslagerung von Datenverarbeitung/IT-Betrieb |
| **T3 Dedicated** — Betreiber hostet dedizierte Instanz | **Ja, prüfen** — wie T2 |

**Wesentlichkeit** ist firmenspezifisch zu beurteilen (Bedeutung der Funktion, Datenmenge,
Substituierbarkeit). Die Beurteilung obliegt der **beaufsichtigten Firma**, nicht dem Betreiber.

## 2. Trigger (ab wann handeln)
- **Auslöser:** Erster produktiver Echt-Tenant in **T2/T3** (≠ Demo/Testdaten).
  Die Daten-Klassifizierungs-Sperre (`allow_real_client_data`, Roadmap #29/#91) ist das
  technische Gate vor diesem Schritt.
- **Vorlauf:** Beurteilung + ggf. Anzeige **vor** Aufnahme der produktiven Verarbeitung.

## 3. Prozess (Checkliste)
1. [ ] Wesentlichkeitsbeurteilung der ausgelagerten Funktion dokumentieren.
2. [ ] AVV mit dem Betreiber abgeschlossen ([avv-template.md](avv-template.md)).
3. [ ] Risikoanalyse (inkl. Datenstandort CH, Mandantentrennung, Exit-Fähigkeit).
4. [ ] Sicherstellung von **Prüf-/Zugangsrechten** (Firma, Revision, FINMA).
5. [ ] **Weiterauslagerungen** (Hosting-Provider) erfasst und genehmigt.
6. [ ] **Geschäftskontinuität/Exit-Strategie** (Datenexport, Rückgabe, Provider-Wechsel).
7. [ ] Eintrag im **Outsourcing-Inventar** der Firma.
8. [ ] Soweit erforderlich: Anzeige/Information an die FINMA (siehe Vorlage unten).

## 4. Anzeige-/Inventar-Vorlage (auszufüllen durch die beaufsichtigte Firma)

| Feld | Inhalt |
|---|---|
| Beaufsichtigte Firma / Bewilligungstyp | _…_ |
| Ausgelagerte Funktion | Digitale Vermögensberatung / Datenverarbeitung (5eyes) |
| Dienstleister (Betreiber) | _…_ |
| Hosting-Tier | T2 / T3 |
| Datenstandort | Schweiz |
| Weiterauslagerungen | _CH-Hosting-Provider, …_ |
| Wesentlich? (Begründung) | _…_ |
| Risikobeurteilung (Verweis) | _Dokument/Datum_ |
| Prüf-/Zugangsrechte gesichert | Ja (AVV §6, Audit-Logs) |
| Exit-Strategie | Datenexport (revDSG Art. 25), Rückgabe/Löschung nach Vertragsende |
| Datum Aufnahme produktiv | _…_ |

## 5. Was der Betreiber bereitstellt (zur Unterstützung der Firma)
- AVV + TOM-Anhang.
- Nachweis CH-Datenstandort + Liste Unterauftragsverarbeiter.
- Audit-Logs (mandanten-partitioniert, Roadmap #21), Health-/Readiness-Endpoints.
- Datenexport-/Lösch-Funktion (revDSG Art. 25 bereits umgesetzt).
- Dieses Dokument + DSFA-Vorlage ([dsfa-datenschutz-folgenabschaetzung.md](dsfa-datenschutz-folgenabschaetzung.md)).
