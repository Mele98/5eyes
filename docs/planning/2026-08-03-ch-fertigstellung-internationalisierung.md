# 5eyes WealthArchitekten — Schweiz-Fertigstellung + Internationalisierungs-Fahrplan

> ⚠️ **ERSETZT** durch [2026-08-04-mega-audit-standortbericht.md](./2026-08-04-mega-audit-standortbericht.md) — enthält eine deutliche Vertiefung des DACH/i18n-Abschnitts (u.a. `base_currency`-Hardcoding als funktionaler DE-Blocker, CHF-Label-Fehler in Kostenausweis/Advisory-Report, BFS-Sterbetafel ohne Jurisdiktions-Gate) sowie dieselbe RES-1/RES-2/goals-1/OPT-2-Korrektur wie im Launch-Readiness-Update.

**Stand:** 3. August 2026, Abend · Branch `develop` @ `1eedccb`
**Basis:** Update von [Launch-Readiness (heute Vormittag)](./2026-08-03-launch-readiness-update.md) + 2 seither gelandete Fixes (Restriktionen&Tilts-Audit `fa88fed`/`b4201c0`, Presentation-Mode↔mandate_type `1eedccb`) + neue Recherche zu DACH-Stand und Internationalisierungs-Infrastruktur, alles per Code-Lektüre verifiziert.

**Zielbild des Users:** Schweiz zuerst wirklich fertig/fix. Danach Länder-Erweiterung (DACH-Raum: Deutschland, Österreich). Danach Sprache (zuerst weiterhin DACH-intern deutsch, dann Englisch, dann weitere).

---

## Kernaussage

Drei fachlich unabhängige Baustellen, die im Kopf oft vermischt werden, aber unterschiedlich weit sind:

1. **Schweiz fertig** — technisch sehr nah, siehe Abschnitt 1 (unverändert zum Vormittags-Report, plus 2 neue Fixes).
2. **DACH-Erweiterung** — **Deutschland ist technisch weit fortgeschritten** (Engine, Router, Produktkatalog, CMA-Pipeline mit Governance-Konzept), aber die **komplette Compliance-Sprache im PDF/Frontend ist zu 100% Schweizer Recht** (FIDLEG, ~40 Backend-Dateien + Frontend). **Österreich ist bei 0%** — nur ein Börsen-Ticker-Suffix existiert. Das ist die grösste, bisher nicht benannte Lücke vor einem echten DE-Kunden.
3. **Internationalisierung/Sprache** — es gibt **aktuell keine i18n-Infrastruktur überhaupt**: kein Framework, `<html lang="de">` hartcodiert, jede UI-, PDF- und Engine-Reasoning-Zeichenkette ist ein deutsches Literal, direkt im Code. **Wichtig:** DACH selbst braucht dafür nichts (alle drei Länder deutschsprachig) — Englisch ist der Punkt, an dem Internationalisierung zum ersten Mal wirklich gebraucht wird, und das ist ein grösseres Unterfangen als eine reine Textübersetzung.

---

## 01 — Schweiz "fix fertig": was noch fehlt

Unverändert zum [Vormittags-Report](./2026-08-03-launch-readiness-update.md), hier kompakt mit Update:

| Kategorie | Punkt | Status |
|---|---|---|
| QA (kein Code) | A2 Visual-Smoke-Klickstrecke, A3 Pilot-Trockenlauf | Weiterhin offen — günstigster nächster Schritt |
| Fachliche Korrektheit | RES-1 (Reserve `max()` statt Running-Balance), RES-2 (Reserve ungedeckelt) | Bewusst offen, vor A3 bewerten |
| Fachliche Korrektheit (niedriger) | goals-1 (AHV im MC-Pfad), OPT-2 (Solver-Bounds), MD-01 (Preis-Batch-Currency) | Für Tier-1-Default (`house_matrix`, CHF) niedriges Risiko |
| Restriktionen & Tilts | ~~5 Bugs (Manuelle Bandbreiten vs. Risikobudget-Fallback, Tilt-Clipping, Illiquid-Cap)~~ | **✅ Heute gefixt** (`fa88fed`, `b4201c0`) |
| Presentation-Mode | ~~Consulting/Wealthmanagement-Toggle ohne sichtbare Wirkung~~ | **✅ Heute gefixt** (`1eedccb`) — steuert jetzt Review-Abschluss-Sprache |
| Sicherheit (Tier 2/3, nicht für Tier-1) | AUTH-03 (X-Forwarded-For), Postgres-Hosting-Entscheid + Pentest | Für Erstkunden self-hosted irrelevant |
| Recht (nicht Code) | DSG Art. 32 Löschungs-Workflow, AVV-Vorlage Rechtsprüfung | Eigener Sprint bzw. externe Prüfung nötig |

**Fazit Abschnitt 1:** unverändert — der Weg zum ersten Tier-1-Kunden ist ein QA-Durchlauf + eine Entscheidung zu RES-1/RES-2, kein grösseres Feature mehr.

---

## 02 — DACH-Erweiterung: Deutschland

### Was bereits geht (Stand heute, verifiziert)

Deutschland ist seit dem 1. August (`8679c9c`, `b8884fc`, `c71124e`, `fa79d09`) end-to-end technisch nutzbar:

- **Engine-Wiring**: `_build_sub_allocations`, `ensure_runtime_reference_data`, CMA-Auflösung lesen die Jurisdiktion über `resolve_mandate_jurisdiction(mandate)` — nicht hartcodiert auf CH.
- **Jurisdiktions-generische Architektur**: Home-Bias-Defaults liegen für Nicht-CH-Länder in einer generischen DB-Tabelle (`JurisdictionHomeBiasDefault`), nicht in Python-Tupeln — eine neue Jurisdiktion hinzuzufügen ist ein **Daten-Seeding-Task, kein Architektur-Umbau**. Das zahlt sich jetzt aus.
- **CMA-Governance-Konzept**: neue CMA-Zeilen für Nicht-CH-Jurisdiktionen tragen einen `status` (`data_derived` → `pending_ic_review` → `committee_approved`); ein PDF-Warnbanner ("PROVISORISCH — NICHT IC-FREIGEGEBEN") erscheint auf der Titelseite, solange nicht freigegeben.
- **Cross-Jurisdiktions-Leck bereits gefunden und gefixt**: ein CH-Mandat hätte ohne das `Product.jurisdiction`-Feld automatisch jedes DE-Produkt im Katalog gesehen — behoben, testabgesichert.
- **Steuerregime**: `services/tax/regimes/de.py` existiert (die Plugin-Architektur zahlt sich hier aus — ein Land andocken heisst: eine neue Regime-Datei, nicht die Tax-Engine umbauen).
- **Frontend**: 2 neue Admin-Sektionen (Jurisdiktionen, Home-Bias-Defaults) + CMA-Panel mit Jurisdiktions-Filter und rollen-gateten Freigabe-Buttons.

### Was noch fehlt — das eigentliche DE-Problem

**Compliance-Text ist zu 100% Schweizer Recht, unabhängig von der Jurisdiktion des Mandats:**

| Datei/Bereich | FIDLEG-Nennungen | WpHG/MiFID-II-Nennungen |
|---|---|---|
| `services/advisory_report.py` | 27 | 0 |
| `services/cost_disclosure.py` | 4 | 0 |
| Restliche `services/` (40 Dateien insgesamt) | — | 0 |
| `5eyes_v2.html` (Frontend) | 20 | 0 |

Ein deutsches Mandat generiert heute einen "Kostenausweis" und ein Advisory-Report-PDF, die **Schweizer Gesetzesartikel (FIDLEG Art. 8/9 etc.) zitieren**, obwohl für einen deutschen Kunden das deutsche Wertpapierhandelsgesetz (WpHG) bzw. direkt MiFID II einschlägig wären. Das ist kein Stil-, sondern ein **Rechtsrisiko** — genau die Art Fehler, die bei einer echten Prüfung durch eine deutsche Aufsichtsbehörde oder einen Rechtsberater sofort auffällt. *(Ich nenne hier bewusst keine konkreten deutschen Artikelnummern — das braucht echte Rechtsprüfung durch eine Fachperson, analog zur AVV-Vorlage.)*

**Das CMA-Governance-Gate ist definiert, aber nirgends hart verdrahtet:**

`services/jurisdiction/provisional_gate.py::assert_jurisdiction_ready()` — die Funktion, die eine `JurisdictionNotApprovedError` werfen SOLL, wenn Nicht-CH-CMA-Daten ohne IC-Freigabe in ein Kundendokument einfliessen — wird **an keiner einzigen Stelle im Code aufgerufen** (verifiziert: nur Definition + Re-Export, kein Call-Site). Aktiv ist ausschliesslich das schwächere Mechanismus-Paar "PDF-Titelseiten-Warnbanner" — ein Berater kann das Banner übersehen oder das PDF trotzdem an den Kunden weitergeben. Die aktuellen DE-CMA-Zeilen stehen auf `status="pending_ic_review"` — **noch nicht IC-freigegeben.**

### Was für Deutschland konkret zu tun ist

1. **Compliance-Text-Lokalisierung** (grösster Posten): eine jurisdiktionsabhängige Textquelle für Rechtszitate (FIDLEG vs. WpHG/MiFID II) — braucht zwingend echte Rechtsprüfung, nicht nur Übersetzung.
2. `assert_jurisdiction_ready()` tatsächlich in `advisory_report.py`/PDF-Pipeline verdrahten, oder bewusst entscheiden, dass das PDF-Warnbanner als alleiniger Schutz ausreicht (aktuell unklar, welche Entscheidung das war).
3. Erste DE-CMA-Zeilen durch das IC prüfen und freigeben lassen (`pending_ic_review` → `committee_approved`), bevor ein echter DE-Kunde onboarded wird.

---

## 03 — DACH-Erweiterung: Österreich

**Status: 0%.** Verifiziert per Grep über den gesamten Backend-Code — die einzigen "AT"-Treffer sind:
- Börsen-Ticker-Suffix (`.VI` für Wien) in der Marktdaten-Pipeline — reine Kursdaten-Beschaffung, keine Fachlogik.
- Ein Länder-Set in `services/tax/wegzug_ch_eu.py` (CH-Wegzugssteuer bei Auswanderung in ein EU-Land) — eine völlig andere Funktion, kein AT-Jurisdiktions-Support.

Es gibt **keine** `at.py`-Steuerregime-Datei, **keine** AT-Home-Bias-Defaults, **keine** AT-CMA-Seed-Daten, **keine** AT-spezifische Compliance-Sprache.

**Gute Nachricht:** wegen der bereits für DE gebauten generischen Architektur (Tax-Plugin-Registry, DB-getriebene Home-Bias-Defaults, jurisdiktions-generisches CMA-Schema) ist Österreich **strukturell ein Wiederholungs-Task, kein Neubau**:
1. `services/tax/regimes/at.py` (österreichisches Steuerregime — KESt/Kapitalertragsteuer, analog zu `de.py` als Vorlage).
2. AT-Home-Bias-Defaults seeden (analog `de_seed.py` → `at_seed.py`).
3. AT-CMA-Kandidaten über die bestehende Marktdaten-Pipeline berechnen lassen, IC-Freigabe-Workflow durchlaufen.
4. Gleiche Compliance-Text-Lokalisierung wie für DE, mit dem österreichischen Pendant (WAG 2018/MiFID II) — auch hier: echte Rechtsprüfung nötig, keine Artikelnummern raten.

**Aufwandseinschätzung (grob, ohne Rechtsprüfung):** deutlich kleiner als der DE-Grundaufbau, weil das Fundament (Resolver, Schema, Router, Frontend-Admin-UI) bereits für "jede Nicht-CH-Jurisdiktion" gebaut ist, nicht CH/DE-spezifisch.

---

## 04 — Sprache/Internationalisierung (nach DACH)

### IST-Zustand: keine i18n-Infrastruktur

Verifiziert: keine Treffer für ein Übersetzungs-Framework (i18n/gettext/react-intl/`useTranslation`) irgendwo im Frontend oder Backend. `<html lang="de">` ist ein hartes Literal. Jede Zeichenkette — UI-Label, Button-Text, PDF-Absatz, und vor allem **jede der hunderten Engine-Reasoning-Zeilen** ("Die Mandatsgrenze für illiquide Anlagen…", "Positiver laufender Cashflow und langfristige Wachstumsziele…") — ist deutsches Klartext-Literal direkt im Python- bzw. JavaScript-Code, nicht über einen Schlüssel/Wörterbuch-Mechanismus.

### Warum DACH das nicht braucht

Deutschland, Österreich und die Schweiz sind (für den hier relevanten Geschäftskontext) durchgängig deutschsprachig. Die DACH-Erweiterung ist ein **reines Jurisdiktions**-Thema (Recht, Steuer, Produktkatalog) — **kein Sprach**-Thema. Das deckt sich mit der User-Reihenfolge: "DACH-Raum, danach Englisch."

### Warum Englisch grösser ist als "Text übersetzen"

Vier Ebenen, die alle betroffen sind, nicht nur die UI:

1. **UI-Strings** (die "klassische" i18n-Aufgabe) — im aktuellen 26'910-Zeilen-Monolithen wären das tausende Einzelstellen.
2. **Engine-Reasoning-Text** — die Erklärsätze, die die Engine für den Berater generiert, sind fachlich präzise formulierter deutscher Text, keine simplen UI-Labels. Eine Übersetzung braucht denselben fachlichen Blick wie das Schreiben selbst.
3. **PDF-/Compliance-Text** — hier gilt dasselbe Rechtsprüfungs-Problem wie bei DE/AT: eine englische Fassung für einen FIDLEG-Kontext (z.B. ein Schweizer Kunde, der auf Englisch bedient werden will) braucht korrekte Fachterminologie, keine wörtliche Übersetzung.
4. **Formate**: Datum/Zahlen laufen heute grösstenteils über `toLocaleString('de-CH', …)`-Aufrufe mit hartcodiertem Locale-String — auch das müsste parametrisiert werden.

### Empfehlung: i18n NICHT auf den Alt-Monolithen aufsetzen

Die React-Migration (ADR-008) läuft bereits und hat 6 von 7 Tracks fertig (Profiling, Goal-Wizard, Mandate, CRM, Asset-Allocation, Cashflow). **Jedes neu migrierte React-Modul sollte von Anfang an mit einer i18n-Bibliothek (z.B. react-i18next) aufgebaut werden** — dort ist der Mehraufwand pro Modul klein, weil die Struktur ohnehin neu entsteht. Eine nachträgliche i18n-Einführung im 26'910-Zeilen-Monolithen wäre doppelte Arbeit für Code, der mittelfristig ohnehin ersetzt wird. Die Engine-Reasoning-Strings (Backend) sind davon unabhängig und brauchen einen eigenen Ansatz (z.B. Message-Keys statt Klartext-Return-Werte) — das ist der grössere, noch nicht angefangene Teil.

---

## 05 — Empfohlene Gesamt-Reihenfolge

**Phase 0 — Schweiz fix fertig** (Tage): A2/A3-QA, RES-1/RES-2-Entscheid. Siehe Abschnitt 1.

**Phase 1 — DACH** (kein i18n nötig, reines Jurisdiktions-Thema):
1. DE: Compliance-Text-Lokalisierung (WpHG/MiFID II) mit Rechtsprüfung — grösster Posten.
2. DE: `assert_jurisdiction_ready()` verdrahten oder Entscheid dokumentieren, dass das PDF-Banner ausreicht.
3. DE: erste CMA-Zeilen IC-freigeben.
4. AT: `at.py`-Steuerregime + Home-Bias-Seed + CMA-Pipeline (strukturell ein Wiederholungs-Task).
5. AT: gleiche Compliance-Text-Lokalisierung wie DE (WAG 2018/MiFID II).

**Phase 2 — Internationalisierung + Englisch:**
1. i18n-Framework für alle NEUEN React-Module ab jetzt einführen (nicht auf den Monolithen).
2. Engine-Reasoning-Strings auf Message-Keys umstellen (grösster Backend-Posten).
3. Compliance-Text-Übersetzung mit Rechtsprüfung (nicht wörtlich, fachlich).
4. Verbleibenden Monolith-Rest (nur noch App-Shell laut ADR-008-Plan) zuletzt.

**Phase 3 — weitere Länder/Sprachen:** je nach Bedarf, Architektur ist jetzt jurisdiktions- und (nach Phase 2) sprachgenerisch.

---

## Methodik & Vorbehalte

Alle Code-Status-Angaben per Read/Grep am aktuellen `develop`-Stand (`1eedccb`) verifiziert. Rechtliche Aussagen zu DE/AT (WpHG, MiFID II, WAG 2018) sind bewusst nur als *Rahmen* genannt, nicht mit konkreten Artikelnummern — das erfordert echte Rechtsprüfung durch eine Fachperson, analog zur bereits bekannten AVV-Vorlage-Einschränkung. Aufwandsschätzung für Österreich ist grob (relativ zu DE), nicht auf Basis einer detaillierten Task-Zerlegung.
