# 5eyes WealthArchitekten — Mega-Audit: Der definitive Standortbericht

**Stand:** 4. August 2026 · Branch `develop` @ `958ed86` · **Ersetzt** [CTO-Standortbericht (18.7.)](./2026-07-18-cto-standortbericht.md), [Launch-Readiness-Update (3.8.)](./2026-08-03-launch-readiness-update.md) und [CH-Fertigstellung + i18n-Fahrplan (3.8.)](./2026-08-03-ch-fertigstellung-internationalisierung.md) — diese drei Dokumente bleiben als historisches Archiv erhalten, sind aber **nicht mehr die aktuelle Wahrheitsquelle**.

**Methodik:** 9-dimensionaler Multi-Agenten-Holistik-Audit (jede Dimension unabhängig recherchiert, mit Zugriff auf Code, Git-Historie und die lokal verfügbaren 3eyes-Referenzdokumente). Jede kritische/hohe Aussage ist mit exakten `file:line`-Zitaten belegt. Die vier gravierendsten und überraschendsten Befunde habe ich **persönlich per Read/Grep/Bash unabhängig nachverifiziert** (nicht nur den Agenten-Text übernommen) — Details siehe Abschnitt „Methodik & Selbstkorrektur". Zwei automatisierte Voll-Audit-Läufe sind unterwegs am Plattform-Session-Limit gescheitert (siehe unten); die fehlenden drei Dimensionen wurden danach einzeln, gezielt nachgeholt.

---

## Kernaussage

**Die wichtigste Erkenntnis dieses Audits ist nicht fachlicher, sondern methodischer Natur:** Die eigenen Status-Berichte vom Vortag (3. August) — obwohl mit dem expliziten Anspruch „alles per Code-Lektüre verifiziert, nicht aus älteren Docs übernommen" geschrieben — enthalten mehrere nachweislich falsche „noch offen"-Behauptungen. Vier fachliche Engine-Korrektheits-Fixes (RES-1, RES-2, goals-1, OPT-2) und ein Sicherheits-Fix (AUTH-01) waren zum Zeitpunkt der Berichterstellung bereits **10 Tage zuvor** gefixt worden. Das wurde in diesem Audit von **drei unabhängigen Agenten unabhängig gefunden** und von mir persönlich per Git-Ancestry (`git merge-base --is-ancestor`) und Code-Lektüre zweifelsfrei bestätigt.

Jenseits dieser Selbstkorrektur hat der Audit eine Reihe **neuer, bisher nicht dokumentierter Befunde** von echtem Gewicht gefunden:

- **Ein reales Geld-Risiko:** Live-Rebalancing (die SOLL-IST-Ansicht für echte Depotbestände) rechnet bei Fremdwährungspositionen nie eine FX-Konvertierung — ein Beispiel-Szenario zeigt eine Verzerrung von ~15% für eine einzelne USD-Position.
- **Ein Compliance-Gate, das dreifach durchlöchert ist:** Das FIDLEG-Suitability-Gate hat mindestens drei produktive Umgehungspfade, auch wenn es aktiviert ist.
- **Ein zweiter Fall des gestrigen Bugs:** Derselbe JS-Hoisting-Namenskollisions-Fehler, der gestern `buildQT()` lahmgelegt hatte, hat auch den neuen Cashflow-Editor-Beta-Button unbrauchbar gemacht — unentdeckt vom gestrigen Cleanup, weil dieser nicht systematisch nach allen Duplikaten suchte.
- **Ein Backup-Mechanismus, der bei aktivierter Verschlüsselung wahrscheinlich nicht funktioniert:** Trotz Docstring-Behauptung „SQLCipher-aware" nutzt der Code durchgängig Standard-SQLite.
- **Ein funktionaler DE-Blocker, der schwerer wiegt als das bekannte Compliance-Text-Problem:** Der Mandats-Erstellungs-Workflow sendet `base_currency:'CHF'` als Literal — jedes über die Standard-UI angelegte DE-Mandat bleibt für immer auf CHF eingefroren.
- **Ein mathematisch bewiesener Defekt** in der Cornish-Fisher-Fat-Tails-Formel (von mir selbst numerisch nachgerechnet) — aktuell folgenlos, weil das Feature über die API gar nicht erreichbar ist, aber scharf, sobald das nachgezogen wird.

Der Weg zum ersten Schweizer Mandanten bleibt **technisch nah** — aber die Liste der davor zu klärenden Punkte ist länger und an einigen Stellen ernster als der 3.8.-Bericht suggerierte.

---

## Methodik & Selbstkorrektur — was diesem Bericht Gewicht gibt

Zwei vollautomatisierte 29-Agenten-Workflow-Läufe sind am Plattform-Session-Limit gescheitert (25 von 29 bzw. 25 von 29 Agenten-Aufrufe schlugen mit „hit your session limit" fehl, jeweils nach ~13–17 Minuten und ~1,5–1,6 Mio. Subagenten-Tokens). Ich habe daraufhin die 6 in beiden Läufen kombiniert erfolgreichen Dimensionen zusammengeführt und die 3 fehlenden (Engine-Methodik, Architektur, Test-Reife) einzeln als gezielte Einzel-Agenten nachgeholt, statt blind einen dritten Vollversuch zu starten. Das ist im Bericht selbst transparent gemacht, nicht verschwiegen.

**Von mir persönlich (nicht nur vom Agenten) verifiziert, mit Ergebnis:**

| # | Behauptung | Meine Verifikationsmethode | Ergebnis |
|---|---|---|---|
| 1 | RES-1/RES-2/goals-1/OPT-2 waren am 24.7. bereits gefixt, entgegen den 3.8.-Berichten | `git log`, `git merge-base --is-ancestor 0af8f2f HEAD` | **Bestätigt** — echter Vorfahre, 47–48 Commits vor den 3.8.-Doku-Commits |
| 2 | Cornish-Fisher-Transform ist auch im „typischen" Bereich nicht-monoton | Eigene numerische Berechnung (`numpy`, 2000 Stützstellen) | **Bestätigt, sogar schärfer** — auch bei skew=-1/kurt=10 (laut Docstring „sicher") nicht-monoton |
| 3 | `openCashflowEditor`-Namenskollision macht den Cashflow-Beta-Button tot | `grep` auf beide Definitionen + Button-Onclick + Funktionskörper gelesen | **Bestätigt** — identisches Muster zum gestrigen `buildQT()`-Bug |
| 4 | Suitability-Gate wird in `routers/review.py` nirgends geprüft | `grep 'require_suitability_before_recommendation\|audit_mandate_suitability'` in beiden Router-Dateien | **Bestätigt** — 0 Treffer in `review.py`, nur `allocation.py` hat das Gate |
| 5 | AUTH-01 (2FA-Pflicht) ist entgegen dem 3.8.-Bericht nicht serverseitig erzwungen | `grep 'require_2fa'` im gesamten Backend | **Bestätigt** — nur 2 Fundstellen (Deklaration + Status-Anzeige), keine Durchsetzung |

Alle fünf Stichproben bestätigten den Agenten-Befund exakt oder sogar schärfer als berichtet — ein starkes Signal für die Verlässlichkeit der restlichen, nicht einzeln von mir nachgeprüften Befunde, die aber jeweils mit vollständigen `file:line`-Zitaten belegt sind und bei Bedarf genauso nachvollzogen werden können.

---

## 01 — Engine-Fachlogik, Statistik & 3eyes-Methodik-Vergleich

**Gesamtbild:** Die Kernbausteine (Nelson-Siegel-Zinskurve, Korrelationsmatrix, Importance-Sampling-Formel, Zwei-Phasen-Zielfunktion, Goal-Score-Gewichtung) sind nachweislich korrekt und teils literaturtreu implementiert. Die vier gravierendsten neuen Funde:

### Kritisch/Hoch

**Cornish-Fisher-Clamp verhindert Nicht-Monotonie NICHT — numerisch bewiesen, auch im „typischen" Bereich.** Der 24.7.-Fix begrenzt Skew auf [-3,3] und Exzess-Kurtosis auf [-2,30] mit der Begründung, das decke „jeden plausiblen Marktwert weit übersteigend" ab. Eigene numerische Verifikation (2000 Stützstellen, `z∈[-4,4]`): bei skew=3.0/kurt=0.0 ist die Transform nicht-monoton (min. Differenz -0.103) — UND selbst bei skew=-1.0/kurt=10.0, dem laut Docstring „typischen Aktien-Bereich", bleibt eine kleine Nicht-Monotonie bestehen (-0.00055). *(`services/portfolio_engine_cma.py:114-144`)* **Aktuelles Produktionsrisiko: gering**, weil die zugrundeliegenden Skew/Kurt-CMA-Felder über kein Schema/Router erreichbar sind (siehe unten) — das Feature ist für echte Mandate ein No-op. Wird aber sofort scharf, sobald jemand diese Lücke schliesst.

**Skew/Kurtosis-CMA-Felder sind für echte Mandate faktisch tot.** 10 DB-Spalten existieren (`models/allocation.py:242-252`), die MC-Engine liest und wendet sie an (`portfolio_engine_mc_simulation.py:951-958,1087-1092`) — aber `schemas/allocation.py::CapitalMarketAssumptionCreate` hat kein einziges Feld dafür. Jedes über die normale Applikation angelegte CMA bleibt bei skew=0/kurt=0, die Transform ist dann laut eigenem Code ein No-op. Die MC-Simulation degeneriert damit immer auf reine Normalverteilung — exakt das, was 3eyes/SLAM als Schwäche des klassischen Markowitz-Ansatzes benennt und was 5eyes eigentlich vermeiden wollte.

**KGV-Mean-Reversion ist ein permanenter Drag statt eines transienten Signals.** Der Horizont ist hartcodiert auf 10 Jahre (`_KGV_DEFAULT_HORIZON_YEARS`, `scenario_engine.py:733,755`) — unabhängig vom tatsächlichen Mandats-Horizont, und die Anpassung fliesst als KONSTANTER Jahres-Drag über die gesamte Projektion ein, nicht als abklingendes Signal. 3eyes/SLAM projiziert dagegen explizit eine zeitabhängige Konvergenz über ~50-60 Quartale. Für einen jungen Kunden mit überbewertetem Startmarkt zeigt Jahr 35 noch dieselbe Korrektur wie Jahr 1.

**PAR-1 ist struktureller, nicht nur ein Default-Wert.** 3eyes kennt laut Referenzmaterial nur zwei Pfade: „Standard approach" (vordefinierte SAA, keine Optimierung) und den eigentlichen 3rd-eyes-Pfad (immer stochastisch, zweistufig). Es gibt dort **keinen** dritten, gemischten Pfad wie 5eyes' `house_matrix`+Tilt. 5eyes' eigener Solver-Pfad (`combined_objective_two_phase`) implementiert die 3eyes-Logik fachlich korrekt — aber der Produktions-Default entspricht strukturell dem von 3eyes selbst als unterlegen bezeichneten „Standard approach".

**Importance-Sampling wirkt nur im opt-in Solver-Pfad**, nicht in der Default-Reporting-Engine, die die im PDF gezeigten VaR/CVaR-Zahlen erzeugt (0 Treffer für den Import in `portfolio_engine_mc_simulation.py`). Der CTO-Bericht-Claim ist korrekt, aber im Scope zu breit formuliert.

**5eyes nutzt P25 für den Zielerreichungs-Fehlbetrag, 3eyes definiert methodisch P5** (`drei augen.pdf`, Kapitel 4.6: „entspricht dem 5. Perzentil"). 5eyes ist an dieser Stelle weniger konservativ als das eigene Vorbild.

**Tilt-Interferenz (Kapitalerhalt vs. Renditeziel) ist durch Code-Reihenfolge, nicht durch eine bewusste Priorität entschieden.** Der 3.8.-Fix macht die Interferenz nur sichtbar (Netto-Effekt-Reasoning), löst sie nicht. Im Solver-Pfad (eine gemeinsame Zielfunktion über alle Ziele) kann dieses Muster gar nicht auftreten — ein struktureller, nicht nur Implementierungs-Unterschied zu 3eyes.

### Positiv bestätigt (info)

Dokumentations-Drift RES-1/RES-2/goals-1 (siehe Kernaussage) · Nelson-Siegel korrekt & textbuchtreu · Korrelationsmatrix positiv-definit (eigene Eigenwert-Prüfung) · OPT-1/OPT-2/MC-1/MC-2 vollständig und korrekt gefixt · Deterministischer Seed audit-taugliche implementiert (SHA-256 über alle Inputs, lokale RNG-Instanz) · Goal-Score-Alpha-Gewichtung literaturbasiert (Brunel 2003, Das/Markowitz/Scheid/Statman 2010).

---

## 02 — Regulatorische Compliance (FIDLEG, DSG, Cross-Jurisdiction)

**Gesamtbild:** Das Compliance-Geflecht ist dicht instrumentiert (>90 FIDLEG-Fundstellen in `services/`, >20 im Frontend) — aber zu 100% Schweizer Recht, unabhängig von der Mandats-Jurisdiktion.

### Kritisch

**`assert_jurisdiction_ready()` ist bestätigt toter Code — der Produktionspfad rechnet aktiv mit nicht-freigegebenen CMA-Daten, nicht nur für eine Vorschau.** Der Produktionspfad ruft `resolve_cma_for_jurisdiction(..., require_committee_approved=False)` explizit auf (`portfolio_engine.py:1059-1061`). Der einzige Schutz ist ein PDF-Titelseiten-Banner (`services/pdf/provisional_notice.py`) — eine komplett separate, nicht mit dem Gate verbundene Implementierung.

**Das Provisorik-Warnbanner erreicht nur 1 von 3 Konsum-Pfaden.** Es ist ausschliesslich im PDF-Renderer verdrahtet. Der JSON-Aggregator (`services/advisory_report.py`, 0 Treffer für „jurisdiction") versorgt sowohl die Berater-React-Ansicht (`routers/allocation.py::get_advisory_report`) als auch das **Kunden-Self-Service-Portal** (`routers/client_portal.py::client_portal_mandate_report`) — beide zeigen einen vollständigen Report mit provisorischen CMA-Daten ohne jede Warnung. Der Kunde selbst sieht in seinem eigenen Portal weniger Warnung als der Berater beim PDF-Export.

**Suitability-Gate hat mindestens drei produktive Umgehungspfade** — bestätigt durch zwei unabhängige Agenten UND von mir persönlich verifiziert (siehe Methodik-Abschnitt). `routers/review.py::create_recommendation_run` und `::generate_recommendation_run_endpoint` erzeugen vollständige Empfehlungsläufe ohne jeden Bezug zu `require_suitability_before_recommendation`/`audit_mandate_suitability`. Selbst der direkte `create_target_allocation`-Endpoint prüft nur Vollständigkeit, nicht die 365-Tage-Freshness.

**Compliance-Zitate sind über mindestens 26 Backend-Dateien jurisdiktionsblind** (20 in `services/`, 6 in `routers/`), nicht nur die 2 ursprünglich bekannten. Besonders: `'fidleg_basis'` ist ein hartcodierter **API-Response-Key-Name** (48 Vorkommen in 19 Dateien) — kein reines Text-, sondern ein Schema-/Vertrags-Problem. `routers/profiling.py:315` gibt „…FIDLEG)." sogar direkt als HTTP-Fehlermeldung an den Client zurück.

### Hoch

DSG Art. 32: der DELETE-Endpoint täuscht eine Löschung vor, die er nicht ausführt (reines Soft-Delete, auch ohne kollidierende Aufbewahrungspflicht) · Beratungsprotokoll-Integritäts-Hash wird geschrieben, aber nirgends verifiziert (`verify_integrity_hash()` nur in Tests aufgerufen) · „Fail-open→Fail-closed"-Fix deckte nur `advisory_report.py` ab — `recommendation_audit.py`, `liquidity_cascade_audit.py`, `mandate_lock_audit.py` haben denselben Anti-Pattern weiterhin · Manuelle `RecommendationRun`-Erstellung wählt die CMA ohne Jurisdiktions-Filter · **Null Erwähnungen von GDPR/DSGVO im gesamten Backend**, obwohl DE-Mandate (EU-Datensubjekte) technisch produktiv sind — ein bisher in keinem Bericht benannter blinder Fleck, braucht echte Rechtsprüfung.

### Mittel/Niedrig (kompakt)

| Befund | Kern |
|---|---|
| Retrozessions-Kostenausweis | leerer Frequenz-Wert wird als „jährlich" gewertet → mindert Kosten-Total zugunsten des Beraters, entgegen dem eigenen „nie stillschweigend Null"-Prinzip |
| Produkt-Suitability-Override | automatischer Fallback ohne erzwungenes Reason-Feld (anders als beim Risikoprofil-Override) |
| Integritäts-Hash | unkeyed SHA256 ohne Chaining — schützt nur gegen App-Bugs, nicht gegen DB-Zugriff |
| `cost_disclosure_given` | reines Selbst-Attest-Flag, kein Snapshot der tatsächlich gezeigten Zahlen |
| Retrozessions-Vollständigkeit | abhängig von manueller Advisor-Erfassung, keine Gegenprüfung |
| `cost_disclosure.py` | `'currency':'CHF'` hartcodiert, unabhängig von `mandate.base_currency` |
| Risk-Scoring-Matrix | 100% FINMA/CH-spezifisch, keine WAG/MiFID-II-Variante |
| Österreich | 0% bestätigt (nur Ticker-Suffix `.VI`) |

### Positiv bestätigt

Kostenausweis Ex-ante bei unbekannten Kosten: „nie stillschweigend Null" hält der Tiefenprüfung stand.

---

## 03 — Security, Authentifizierung, Multi-Tenant-Isolation

**Gesamtbild:** Substanziell gewachsen seit dem letzten Audit (Token-Revocation, TOTP-Replay-Schutz, PyJWT-Hardening, DB-persistenter Login-Guard, saubere Postgres-RLS) — aber ein zentraler Fund widerspricht der eigenen Dokumentation direkt.

### Kritisch

**AUTH-01 (2FA-Pflicht) ist entgegen dem 3.8.-Bericht weiterhin NICHT serverseitig erzwungen** — persönlich verifiziert (siehe Methodik). `settings.require_2fa` wird ausschliesslich für die Status-Anzeige gelesen. Ein User ohne aktives 2FA kann sich mit `require_2fa=True` normal einloggen und erhält ein voll funktionsfähiges Token.

### Hoch

**AUTH-03 (X-Forwarded-For) — Tiefenanalyse mit konkretem Fix-Vorschlag:** Risiko ist rein deployment-topologie-abhängig (Tier-1 ohne Reverse-Proxy: irrelevant; Tier-2/3 hinter Proxy: sofortiger Rate-Limit-Bypass). Der saubere Fix ist ein `trusted_proxy_count`-Pattern mit Rightmost-Hop-Parsing (Default 0 = XFF ignorieren), nicht das verworfene „immer `request.client.host`", das den bestehenden Per-Source-Test zu Recht brach.

### Mittel/Niedrig (kompakt)

| Befund | Kern |
|---|---|
| TOTP-Secrets | Klartext (Base32) in der DB — kein Encryption-at-Rest, obwohl `tenant_crypto.py`-Infrastruktur dafür existiert |
| Tenant-DEK-Envelope-Encryption | vollständig gebaut, aber komplett ungenutzt — UND `rotate_tenant_dek` würde bei Live-Einsatz ohne Vorwarnung Altdaten zerstören |
| `get_current_tenant_id` | ungenutzt, aber würde Token-Revocation umgehen, falls je als Dependency eingesetzt |
| AUTH-05 | Rate-Limiting gefixt, TOCTOU-Race für „genau 1 Bootstrap-Admin" bleibt |
| SQLite/Tier-1 | kein DB-seitiger Isolation-Backstop (anders als Postgres-RLS) — App-Layer-Filter sind einzige Verteidigungslinie, historisch mehrfach vergessen (SEC-1/2, rls-2/3) |
| Login-Guard | bewusst fail-open bei DB-Ausfall (dokumentierter Trade-off) |
| Mandate-Nummer | global statt tenant-scoped eindeutig — minimaler Cross-Tenant-Seitenkanal |

### Positiv bestätigt

PyJWT-Migration vollständig verifiziert (harte alg-Allowlist, `alg=none`- und Algorithm-Confusion-Tests grün) · Token-Revocation (AUTH-04) korrekt an 5 Stellen verdrahtet · Secrets-Handling sauber (keine Klartext-Secrets im Repo) · AUTH-06 TOTP-Replay-Schutz korrekt implementiert.

---

## 04 — Marktdaten-/Preispipeline

**Gesamtbild:** Zwei parallele Welten — eine moderne, robuste Provider-Schicht und eine ältere, direkt in `price_updater.py` duplizierte Logik, die per Default aktiv ist und die Vorteile der modernen Schicht nicht nutzt.

### Kritisch

**Währungsblindheit geht tiefer als das bekannte MD-01: Live-Rebalancing rechnet nie FX.** `services/portfolio_engine_live_rebalancing.py` enthält 0 Treffer für „currency". **Konkretes Beispiel:** 200 Stück eines USD-ETF (XLE), Kurs USD 88.00 → das System zeigt CHF 17'600.00 als Marktwert, obwohl der reale CHF-Gegenwert bei ~CHF 15'312 liegt (**+14.9% Überzeichnung**) — weil das Currency-Feld nie konsultiert wird. Dieser Fehlbetrag fliesst direkt in die BUY/SELL/HOLD-Entscheidung. Ein reines MD-01-Fix (Provider-Currency ins Batch-Tupel) würde das NICHT beheben, weil der Konsument das Feld nie liest.

### Hoch

MD-01-Ursachenkette vollständig verifiziert — für den `aggregator`-Modus ist der Fix trivial (Vorlage existiert bereits im selben Repo), für die drei Legacy-Pfade weiterhin aufwändig · **Zwei tägliche Refresh-Jobs feuern per Werkseinstellung zur exakt selben Uhrzeit (06:00:00)** gegen dieselben unauthentifizierten Provider — verdoppelt die Last genau im Risiko-Zeitfenster · Der MD-05-Retry-Fix betrifft nur den kaum genutzten Einzel-Fetch-Pfad — der produktive Batch-Pfad (beide täglichen Jobs) hat auf keinem der vier Provider-Zweige irgendeinen Retry.

### Mittel/Niedrig (kompakt)

| Befund | Kern |
|---|---|
| Stooq-Throttle | ungebremste Serie von HTTP-GETs, am stärksten genau dann, wenn Yahoo bereits ausfällt |
| Werks-Default | `yfinance`/`stooq` (nicht `aggregator`) umgeht die selbst gebaute Health/Circuit-Breaker-Infrastruktur komplett |
| `coverage_pct` | rein informativ — 0%-Preisabdeckung blockiert keine Empfehlung/PDF-Export |
| Fallback-Kette | real nur 2-stufig (yfinance→stooq), EODHD ist kein Preis-Provider, Twelve Data ohne API-Key inaktiv |
| `eodhd_client.py`/`twelvedata_client.py` (Legacy) | keine Rate-Limit-Erkennung, im Gegensatz zu ihren modernen Pendants |
| Totalausfall <5 Tage | für den Berater von einem gesunden Refresh nicht unterscheidbar (nur Admin-Panel zeigt es) |

### Positiv bestätigt

MD-02 (0-Kurs-Schutz), MD-03 (Stale-Redundant-Erkennung), MD-04 (`<=on_date`-Vertrag), MD-06 (Business-Day) — alle robust umgesetzt, keine Regression.

---

## 05 — Architektur & Wartbarkeit

**Gesamtbild:** ADR-014 (Engine-Split) ist tatsächlich sauber — null Zirkularimporte in 210 Modulen, konsequente Lazy-Import-Disziplin. ADR-008 (React-Migration) ist der Ort der gravierendsten neuen Funde.

### Kritisch

**Zweiter Fall des gestrigen Bugs: `openCashflowEditor`-Namenskollision macht den Cashflow-Beta-Button tot** — persönlich verifiziert (siehe Methodik). Zwei Top-Level-Funktionen desselben Namens (`5eyes_v2.html:12294` ohne Argument, `:22211` mit `cashflowId`); die spätere gewinnt. Der Button ruft ohne Argument auf → `cashflowId===undefined` → kein Treffer → stiller No-op. Eingeführt am 2. August, vom dedizierten „tote Duplikate entfernt"-Commit am 3. August **nicht** gefangen, weil dieser nur 3 spezifische Namen traf, nicht systematisch scannte. Zwei weitere Duplikate im selben Muster gefunden: `dg()` (Ziel löschen — die BESSERE Version mit Risk-Context-Update ist die tote), `dcf()` (Cashflow löschen, hier zufällig folgenlos) und `isAllocationTimelineCashflow` (Duplikat seit Mai, von einem damaligen Cleanup übersehen, das direkt daneben stand).

### Hoch

Wiring-Contract-Tests sind reine Text/Regex-Prüfungen — führen NIE JavaScript aus, sind daher gegen genau diese Bugklasse blind und bleiben grün, obwohl der Button nicht funktioniert · Kein CI/Lint-Guard gegen doppelte Top-Level-Funktionsnamen · ADR-008 „6 von 7 Tracks fertig": Alt-Code wurde bei KEINEM migrierten Track entfernt — der neue React-Editor ist nur über einen sekundären „(Beta)"-Button erreichbar, kein produktiver Pfad wurde umgestellt.

### Mittel/Niedrig/Info (kompakt)

| Befund | Kern |
|---|---|
| ADR-008-Dokument | veraltet gegenüber dem Codestand (Stand 23.7., Wiring-Bridges existieren seit 2.8.) |
| Monolith-Zeilenzahl | wächst trotz Migration weiter (25'593 → 26'929) |
| App-Shell (Track 3) | 0% begonnen, konkreter Umfang identifiziert (Login/Bootstrap, Router `go()`, Sidebar) |
| ADR-014-Zirkularimport-Freiheit | positiv bestätigt (0 Zyklen in 210 Modulen, AST-Analyse) |
| ADR-014 vs. Code | ein von ADR-014 selbst behaupteter Abhängigkeits-Fakt ist laut eigenem Code-Kommentar falsch |
| Zeilenzahl-Angaben | uneinheitlich über 3 Dokumente (8'227 vs. 8'820 vs. 3'771) |
| TODO/FIXME/HACK | exakt 4/0/0 bestätigt (unverändert seit Juli) |
| 90 Testdateien | direkter Import-Zähler für Engine-Tests unabhängig reproduziert |

---

## 06 — Test-/QA-Reife

**Gesamtbild:** Quantitativ stark (5074 Tests, 5065 bestanden/0 fehlgeschlagen, echte 87% Coverage) und methodisch reif — die gravierendsten Lücken liegen nicht in der Menge, sondern in drei spezifischen Bereichen.

### Hoch

A2/A3 (Klickstrecke, Pilot) weiterhin ohne jede Spur — `docs/E2E_TESTING.md` sagt explizit „E2E-Tests existieren nicht", ein Guard-Test stellt sogar aktiv sicher, dass Playwright NICHT installiert wird · **63 Backend-Testdateien (410 Testfunktionen, ~8% der Suite) verifizieren Frontend-Verhalten ausschliesslich per Text-/Regex-Scan — keine Ausführung, kein DOM** · **Baseline-Dokumente selbst unzuverlässig:** unabhängig dieselbe RES-1/RES-2/goals-1/OPT-2-Diskrepanz gefunden (dritte unabhängige Bestätigung) · Der einzige im Arbeitsbaum liegende `coverage.xml` ist 2+ Monate alt, git-ignoriert, und zeigt irreführende 0%-Werte (z.B. `optimizer/solver.py`: Datei zeigt 0%, live gemessen 91%).

### Mittel/Niedrig (kompakt)

| Befund | Kern |
|---|---|
| Kein Coverage-Floor | bewusst so dokumentiert in `pyproject.toml`, aber 2 andere Docs behaupten fälschlich einen „82%-Floor" |
| `routers/pdf_reports.py` | nur 18% Coverage — die HTTP-Endpunkt-Schicht des zentralen FIDLEG-Deliverables ist praktisch ungetestet |
| Postgres-RLS-Job | misst gar keine Coverage — künstlich niedrige 59%/70% für die sicherheitskritischsten Module |
| `security_gate.py` | listet einen Test, der im Security-Gate-Job selbst immer geskippt wird (echter Schutz kommt aus einem anderen Job) |
| Hypothesis-Property-Tests | 4 Tests permanent inaktiv (Package bewusst nicht installiert) |
| Mutation-Testing | konfiguriert, installiert, nie tatsächlich ausgeführt |
| Zeit-Flakiness | mehrere echte `time.sleep()`-Aufrufe (1.1-1.2s) statt Zeit-Mocking — kein `freezegun` im Repo |
| ADR-014-Cluster | fast keine direkten Tests, Absicherung läuft nur transitiv über den Re-Export-Shim |
| Vitest-Suite | keine Coverage-Messung konfiguriert |
| CI-Kommentar | veraltet (2026-06-08, „3400 Tests" — heute 5074, +49%) |

### Positiv bestätigt

Voller lokaler Lauf heute: 5065 passed, 0 failed, 17m32s — `develop` ist tatsächlich stabil.

---

## 07 — DACH-Erweiterung & Internationalisierung (Vertiefung)

**Gesamtbild:** Die gestrige Analyse hat die Grössenordnung richtig benannt, aber nicht die volle Tiefe ausgelotet.

### Kritisch

**Mandat-Erstellung hardcodet `base_currency:'CHF'` — kein UI-Pfad, um je eine andere Währung zu setzen.** Das ist der schärfste Einzelbefund dieser Vertiefung: **jedes über die Standard-UI angelegte DE-Mandat bleibt für immer auf CHF eingefroren**, obwohl das Mandate-Settings-Panel Jurisdiktion (CH/DE) und Steuerregime bereits auswählen lässt. Das Backend-Schema unterstützt `base_currency` als patchbares Feld — es gibt nur keinen Frontend-Pfad, der es je befüllt.

**`'CHF'`-Formatierung ist NICHT durchgängig hartcodiert — aber ausgerechnet in den zwei FIDLEG-kritischsten Dokumenten schon.** `asset_allocation.py` parametrisiert korrekt nach `ctx.base_currency`. **`kostenausweis.py` und `advisory_report.py`** (das Kostenausweis- und das Haupt-Advisory-Dokument!) nutzen durchgängig `format_chf_rappen()` — eine Funktion ohne Currency-Parameter, die `"CHF "` fest einbaut. In derselben Tabelle steht die dynamisch korrekte „Referenzwährung" direkt neben Beträgen, die immer mit „CHF" beschriftet sind — ein direkter, im selben PDF-Block sichtbarer Widerspruch für ein EUR-Mandat. Das ist kein Kosmetikfehler, sondern eine Falschangabe der Währungseinheit in einem gesetzlich vorgeschriebenen Dokument.

### Hoch

**BFS-Schweizer-Sterbetafel wird in der Monte-Carlo-Engine ohne Jurisdiktions-Gate verwendet.** Für ein DE/AT-Mandat mit aktivierter Mortalitätssimulation würde die (sehr hohe) Schweizer Lebenserwartung verwendet — das führt zu einer **fachlich falschen, systematisch zu niedrigen** Einschätzung des Sequence-of-Returns-/Verzehr-Risikos, nicht nur zu einem Text-Problem · `'fidleg_basis'` ist ein API-Response-**Key-Name** in 19 Dateien, kein reiner Text — eine Lokalisierung muss das Schema, nicht nur Strings, anfassen · `country_of_residence:'CH'` beim Klienten-Anlegen hardcodiert, kein Länder-Select im Formular, kein Nachbesserungspfad · FIDLEG-Referenzen auch in `routers/` (6 Dateien, 14 Stellen) — u.a. eine direkt an den API-Client zurückgegebene Fehlermeldung.

### Mittel/Niedrig/Info (kompakt)

| Befund | Kern |
|---|---|
| Vorsorge-Säulen-Enum | hartes CH-only Literal (AHV/BVG/3a/1e/FZG), kein DE-Äquivalent |
| `PDFContext.locale` | vollständig dead code — Feld existiert, wird nirgends gelesen |
| `FIDLEG_DISCLAIMER`-Footer | hat bereits einen Override-Parameter, der nie benutzt wird — identisches Muster zu `assert_jurisdiction_ready()` |
| React-Module (bereits migriert) | wiederholen exakt das CHF/de-CH-Antipattern, das die i18n-Empfehlung „für neue Module" vermeiden wollte — kommt für 4+ Stellen bereits zu spät |
| `toLocaleString('de-CH')` | exakt 57 Aufrufe, über 6 redundante lokale Formatierungs-Closures verteilt |
| Compliance-Text-Registry | konkrete Code-Skizze entworfen, analog zur bestehenden Tax-Plugin-Registry — Rechtsinhalte selbst dürfen nicht ohne Rechtsprüfung befüllt werden |
| Schweizer Feiertagslogik | Nicht-Befund — es gibt keine, das ist symmetrisch für alle Jurisdiktionen gleich |

---

## 08 — Business-/Betriebsreife

**Gesamtbild:** Ungewöhnlich viel Betriebs-/Compliance-Dokumentation bereits vorhanden — aber das durchgängige Muster ist: **der Prozess/die Vorlage existiert, die tatsächliche Durchführung fehlt.**

### Kritisch

**Backup-Engine hat keine SQLCipher-Unterstützung, obwohl Produktiv-SQLite SQLCipher zwingend voraussetzt.** `services/backup.py` behauptet „SQLCipher-aware" im Docstring, importiert aber durchgängig Standard-`sqlite3` — kein `sqlcipher3`, kein `PRAGMA key`. `config.py` erzwingt SQLCipher für jede Produktiv-SQLite-Installation. Ein `sqlite3.connect()` auf eine SQLCipher-Datei schlägt mit „file is not a database" fehl. **Der Backup-Scheduler fängt das mit `except Exception: logger.exception(...)` ab, ohne den Berater zu alarmieren** — er glaubt an tägliche Backups, hat aber möglicherweise seit Aktivierung der Verschlüsselung keinen einzigen erfolgreichen Lauf. **Der Juni-Audit-Trackingdoc behauptet explizit, dieser Punkt (AB-1) sei bereits gefixt — das ist falsch, dieselbe Fehlerklasse wie beim Engine-Cluster.**

### Hoch

Disaster-Recovery-Plan verlangt „PFLICHT"-quartalsweise Restore-Drills — Protokoll-Tabelle ist leer, nie durchgeführt · Kein Restore-Endpoint, kein Restore-CLI — nur ein interner Python-Funktionsaufruf, ein Berater ohne Programmierkenntnisse kann im Ernstfall nicht selbst wiederherstellen · Produktions-Sicherheits-Guards (Secret-Key, Verschlüsselungspflicht) greifen nur bei `app_env=production` — wird beim Electron-Standardstart nicht gesetzt und in der Berater-Onboarding-Doku nirgends verlangt · `license_valid_until` wird nirgends automatisch geprüft — reines Anzeigefeld, ein Admin muss manuell auf „expired" umstellen.

### Mittel/Niedrig/Info (kompakt)

| Befund | Kern |
|---|---|
| `storage_quota_mb` | reine Kosmetik, keine technische Durchsetzung, obwohl Teil der Preisskizze |
| Stage-8-Runbook | (Optimizer-Default-Wechsel) vollständig spezifiziert, 0 von 4 ausgefüllten Shadow-Reports |
| Kein Incident-Response-Plan/SLA-Dokument | trotz ADR-009-Pflichtliste für Tier 2/3 |
| Code-Signing | seit 7+ Wochen nicht beschafft — blockiert Auto-Update zusätzlich, Update-Server-Domain ist ein Platzhalter |
| Externer Pentest | weiterhin nicht beauftragt, nur Vorbereitungsdokument |
| Berater-Onboarding-Doku | ~2 Monate / 150+ Commits veraltet, deckt Presentation-Mode/DE-Jurisdiktion nicht ab |
| Compliance-Vorlagen (AVV/DSFA/FINMA) | seit 15.6. unverändert, explizit ungeprüft, 100% CH-fokussiert, keine DE/AT-Entsprechung |
| `avv_signed_at`/`finma_outsourcing_notified_at` | reine Metadatenfelder, kein technisches Gate zu `allow_real_client_data` (bewusst so, Prozessdisziplin statt Code) |

### Positiv bestätigt

Lizenz-/Quota-Enforcement für Users/Mandates ist tatsächlich hart (403/409, an Login UND jedem Request) · Business-/Go-to-Market-Themen sind ausserhalb des Repos bestätigt (keine versteckten Festlegungen).

---

## 09 — Roadmap-Konsolidierung (Cross-Dokument-Check)

Alle `docs/planning/*.md` + `docs/adr/*.md` gelesen und gegen den aktuellen Code verifiziert. Kernbefund bereits in der Kernaussage behandelt (RES-1/RES-2/goals-1/OPT-2-Fehlerkette). Zusätzlich:

- **RES-1 ist nur TEILWEISE gefixt** — der 24.7.-Fix behebt die Monotonie-Lücke (Running-Min statt Endsumme), NICHT die `max()`-statt-additiv-Kombination zwischen Cashflow-Shortfall und Goal-Reserve, die dieselbe Finding-ID ursprünglich auch beschrieb. Sollte im Backlog als „teilweise", nicht „offen" oder „erledigt" geführt werden.
- ADR-008 fehlt der Status-Refresh, den ADR-007/009/014 bereits erhalten haben.
- ADR-007 widerspricht sich im eigenen Dokument (Kopf „deferred", Body „aktiv").
- Der Sprint-U-35-Modul-Split-Plan wurde durch ADR-008 lautlos abgelöst, ohne als obsolet markiert zu werden.
- Der referenzierte „Engine-Hardening 3-Phasen-Plan" existiert als Dokument nirgends im Repo — 4 Roadmap-Punkte verweisen ins Leere.
- Ein stale Code-Docstring (`services/jurisdiction/resolve.py`) behauptet, ein Modul werde „nirgends aus der Engine aufgerufen" — tatsächlich seit 1. August an 5+ Stellen aktiv verdrahtet.
- **Positive Kontrollprobe:** die Tenant-Isolation-Historie (SEC-1/2, rls-1/2/3) ist die best-dokumentierte, mehrfach re-verifizierte Baustelle im ganzen Projekt — dort hat wiederholte Prüfung mit Tests als Beleg tatsächlich funktioniert, im Gegensatz zum Engine-Cluster.

---

## 10 — Konsolidierte Prioritätenliste

**Sofort, unabhängig von allem anderen (Doku-Korrektheit, kein Code-Risiko):**
1. Die 3.8.-Berichte korrigieren: RES-1 (teilweise statt offen), RES-2/goals-1/OPT-2 (erledigt statt offen), AUTH-01 (offen statt erledigt) — siehe Abschnitt „Was seit heute Vormittag korrigiert wurde" *(dieses Dokument selbst)*.

**Vor dem ersten Tier-1-Kunden (real, unabhängig vom DACH-Thema):**
2. `openCashflowEditor`/`dg()`-Namenskollisionen fixen (schnell, gleiches Muster wie gestern) + einen systematischen Duplikat-Namen-Scan als CI-Guard einführen.
3. AUTH-01 tatsächlich serverseitig erzwingen (nicht nur Status-Anzeige).
4. Live-Rebalancing-FX-Konvertierung nachziehen (echtes Geld-Risiko bei Fremdwährungspositionen).
5. Backup/SQLCipher-Kompatibilität herstellen UND einen echten Restore-Drill durchführen, bevor ein Berater sich darauf verlässt.
6. Suitability-Gate auf alle drei Erzeugungspfade ausweiten (oder bewusst dokumentieren, warum nicht).
7. A2/A3 (Klickstrecke, Pilot) endlich durchführen.

**Vor dem ersten DE-Kunden (zusätzlich zu allem oben):**
8. `base_currency`-Feld im Mandats-Erstellungs-Workflow ergänzen (funktionaler Blocker, nicht nur Text).
9. `format_chf_rappen()` in Kostenausweis/Advisory-Report auf dynamische Währung umstellen.
10. `assert_jurisdiction_ready()` verdrahten ODER bewusst entscheiden, dass das Banner ausreicht — und diese Entscheidung dokumentieren.
11. BFS-Sterbetafel jurisdiktionsabhängig machen (fachlich falsche Zahl, nicht nur Text).
12. Compliance-Text-Registry bauen (Skizze in Abschnitt 07) — Rechtsinhalte selbst brauchen echte Rechtsprüfung.

**Nicht blockierend, aber im Auge behalten:**
13. Zwei tägliche Preis-Jobs zeitlich entzerren (5-Minuten-Fix, senkt Rate-Limit-Risiko).
14. `PRICE_REFRESH_PRIMARY_PROVIDER=aggregator` als Default erwägen (nutzt bereits vorhandene Robustheit).
15. Skew/Kurtosis-CMA-Felder ins Schema nachziehen, WENN das Feature genutzt werden soll — sonst bleibt der Cornish-Fisher-Fund folgenlos.

---

## Anhang: Was seit dem Vortag korrigiert wurde

| Punkt | 3.8.-Bericht sagte | Tatsächlicher Stand (heute verifiziert) |
|---|---|---|
| RES-1 | „bewusst offen" | **Teilweise gefixt** (24.7., Commit `0af8f2f`) — Monotonie-Lücke behoben, additiv-vs-max()-Problem bleibt |
| RES-2 | „bewusst offen" | **Vollständig gefixt** (24.7., Commit `0af8f2f`) |
| goals-1 | „bewusst offen" | **Vollständig gefixt** (24.7., Commit `0af8f2f`) |
| OPT-2 | „bewusst offen" | **Vollständig gefixt** (24.7., Commit `1dcfd93`) |
| AUTH-01 | „✅ gefixt" | **Weiterhin offen** — keine serverseitige Durchsetzung |
| MD-01 | „offen" | **Bestätigt weiterhin offen** — der einzige der ursprünglichen 6 Punkte, bei dem der 3.8.-Bericht recht hatte |

---

## Methodik & Vorbehalte

Alle Code-Status-Angaben per Read/Grep/Bash am aktuellen `develop`-Stand verifiziert. Rechtliche Aussagen zu DE/AT (WpHG, MiFID II, WAG 2018, GDPR/DSGVO) sind bewusst nur als Rahmen genannt, nie mit konkreten Artikelnummern — das erfordert echte Rechtsprüfung durch eine Fachperson. Der 3eyes-Methodik-Vergleich basiert auf den lokal verfügbaren Referenzdokumenten (`drei augen.pdf`, `erklärung drei augen.pdf`, Schulungsunterlagen) — direkte Seitenzitate sind im Text vermerkt. Die drei nachgeholten Einzel-Dimensionen (Engine-Methodik, Architektur, Test-Reife) liefen als gezielte Einzel-Agenten nach zwei gescheiterten Vollversuchen, nicht als Teil derselben adversarialen Verify-Pipeline wie die anderen 6 — ihre Befunde wurden dafür an den kritischsten Stellen von mir persönlich per Read/Grep nachverifiziert (siehe Methodik-Tabelle oben).
