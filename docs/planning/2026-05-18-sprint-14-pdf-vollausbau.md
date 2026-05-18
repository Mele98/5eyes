# Sprint 14 — PDF-Vollausbau nach Swiss-Life-Wealth-Vorlage (19 Seiten)

**Datum:** 2026-05-18
**Status:** Aktiv / massiver Refactor
**User-Direktive:** "Gehe nochmals sauber drueber, sieh was alles noch
fehlt und integriere bausteine wie ich dir sie gegeben habe" — exakte
19-seitige Anlagestrategie-Vorlage von Swiss Life Wealth Managers.

## 0. Gap-Analyse

Aktuelles Server-PDF: 4 Seiten, ~10kB. Soll: 19 Seiten, vollumfaenglich
mit allen Sektionen, statischen Erklaerungstexten, FIDLEG-Disclaimer.

## 1. Sektionen-Plan (19 Seiten, in Reihenfolge)

| Seite | Sektion | Inhalt |
|---|---|---|
| 1 | Cover | Titel + Kontakt-Berater + Persoenliche-Daten-Klient + Tagline + Datum |
| 2 | Eignungspruefung: Kenntnisse | Frage-Antwort-Tabelle (3 Bereiche) |
| 3 | Eignungspruefung: Risikoprofil | Profil-Text "Basierend auf Antworten max 80% Aktien" |
| 4 | Praeferenzen | 4-Spalten-Checkbox-Tabelle + Erklaerungen |
| 5-6 | Vermoegensstruktur Beratungsvermoegen | 2 Donuts (IST + Empfehlung) + Tabellen |
| 7 | Investitionsansatz | Static Text (zielbasiertes Investieren, iSAA, etc.) |
| 8 | Anlageuniversum | Static Text (aktiv/passiv-Fonds, ETFs, Derivate, etc.) |
| 9 | Zusammenfassung | Static Text + Bestaetigung mit Unterschrift |
| 10 | Trenn-Cover | "Ihre persoenliche Ausgangslage" mit Logo |
| 11 | Vermoegensuebersicht | Beratungsvermoegen + Anderes Vermoegen (Tabellen) |
| 12 | Kapitalzufluesse + Ziele | Cashflows + Goals Tabellen |
| 13-14 | Vermoegensstruktur Gesamtvermoegen | 2 Donuts + hierarchische Tabellen |
| 15 | Unsere Empfehlung | 2 Charts + Kennzahlen + Zielerreichung |
| 16-17 | Kennzahlen-Erlaeuterungen | Definitionen (Max DD, Median CAGR, VaR, etc.) |
| 18 | Fonds-Uebersicht | ISIN-Tabelle gruppiert nach Anlageklasse |
| 19 | Disclaimer | Langer rechtlicher Text |

## 2. Phasen-Aufteilung

### Phase 1 (jetzt, ~2h) — Statische Geruest-Seiten + Cover
- Cover-Seite (Seite 1)
- Trenn-Cover "Ausgangslage" (Seite 10)
- Investitionsansatz (Seite 7) — static text
- Anlageuniversum (Seite 8) — static text
- Zusammenfassung + Bestaetigung (Seite 9) — static text
- Kennzahlen-Erlaeuterungen (Seite 16-17) — static text
- Disclaimer (Seite 19) — static text wortgetreu

### Phase 2 (~2h) — Daten-Sektionen Beratungsvermoegen
- Eignungspruefung Frage-Antwort statt Bool (Seite 2)
- Risikoprofil-Text mit max-Anteil (Seite 3)
- Praeferenzen-Tabelle 4-Spalten (Seite 4)
- Vermoegensstruktur Beratungsvermoegen Donuts (Seite 5-6)

### Phase 3 (~2h) — Daten-Sektionen Gesamtvermoegen + Empfehlung
- Vermoegensuebersicht hierarchisch (Seite 11)
- Kapitalzufluesse + Ziele (Seite 12)
- Vermoegensstruktur Gesamtvermoegen Donuts (Seite 13-14)
- Empfehlung mit Vermoegensverlauf + Kennzahlen (Seite 15)
- Fonds-Uebersicht gruppiert (Seite 18)

## 3. Wording-Quellen

Alle statischen Texte WOERTLICH aus User-Vorlage uebernehmen:
- Investitionsansatz: 3 Absaetze ueber zielbasiertes Investieren
- Anlageuniversum: Aufzaehlung Fonds-Typen + Derivate
- Zusammenfassung: 3 Absaetze ueber Empfehlungsgrundlagen
- Kennzahlen-Definitionen: 7 Definitionen
- Disclaimer: vollstaendiger rechtlicher Text mit Swiss-Life-Wealth-Adresse

## 4. Daten-Loader-Erweiterungen

Aktuell fehlende DB-Loads:
- Client-Adresse (Strasse, PLZ, Ort, Tel) — fuer Cover
- Berater-Kontakt (Org, Strasse, Tel, Email, Webseite) — aus User/Config
- RiskAssessmentAnswer mit Frage-Text (statt nur Bool) — aus RA-Answers-Tabelle
- Praeferenzen (preferences_json aus TargetAllocation oder Mandate)
- Cashflows + Goals fuer Seite 12 — aus existierenden Models
- IST + Empfehlung Donut-Daten — aktuelle + target weights pro Bucket
- Vermoegensverlauf-Series (P10/P50/P90) fuer Diagramme
- Zielerreichung pro Goal mit Fehlbetrag

## 5. Out-of-Scope (Phase 4+, on-demand)

- Echte Diagramme (Vermoegensverlauf-Linien) — erstmal als Tabelle
- Logo-Image-Embedding (Swiss Life Wealth Managers Logo)
- Multi-Lingual (FR/IT/EN)
- Versions-Branching (mehrere Empfehlungen vergleichen)
