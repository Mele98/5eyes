# 5eyes WealthArchitekten — CTO-Standortbericht

> ⚠️ **ERSETZT** durch [2026-08-04-mega-audit-standortbericht.md](./2026-08-04-mega-audit-standortbericht.md) — dieses Dokument bleibt als historisches Archiv erhalten, ist aber nicht mehr die aktuelle Wahrheitsquelle. Mehrere hier genannte Status-Angaben wurden im Mega-Audit als überholt/falsch identifiziert.

**Stand:** 18. Juli 2026 · Branch `develop` @ `45d810c`
**Basis:** 668 Backend-Module, 398 Test-Dateien, 5 verifizierte Prüfstränge (Architektur, Fachengine, Compliance/Reporting, Qualität/Tests, Backlog). Alle Befunde per Code-Lektüre (Read/Grep) an `develop` belegt, ergänzt um Master-Roadmap, 3eyes-Parity-Plan und Commit-Historie (172 Commits seit dem letzten Standortaudit).
**Web-Version:** https://claude.ai/code/artifact/64106171-9612-46d2-bf12-237cfdd1c66a

---

## Kernaussage

Die **Engine-Mathematik von 5eyes ist der 3eyes-Methodik ebenbürtig bis überlegen**. Der verbleibende Abstand liegt nicht mehr in der Modell-Tiefe, sondern in **Produkt-Defaults, Beratungs-Workflow und Betriebsreife**.

Der Weg zum **ersten echten Mandanten (Tier-1, self-hosted)** ist praktisch frei: es fehlt fast kein Code, sondern zwei QA-Durchläufe. Der schwergewichtige Backlog (Postgres-Hosting, Auth-Härtung, Monolith-Migration) betrifft **Skalierung und Mehrbenutzer-Hosting**, nicht den lokalen Erstkunden.

Reifegrad gesamt: **Beta, produktionsnah**. Kernlogik gut getestet und gehärtet; die Reifelücke liegt in Frontend-Testbarkeit, Modul-Architektur und Betriebs-Härtung — Themen, die die *Wartbarkeit* stärker belasten als die *Korrektheit*.

**Kennzahlen:** Engine vs 3eyes ≥ Parität · Erster Mandant ~1 Woche (nur QA) · 398 Backend-Test-Dateien · 4 TODO / 0 FIXME / 0 HACK auf ~69k LOC · 112 Commits in 30 Tagen.

---

## 01 — Gleich oder besser als 3eyes

Gemessen am 3eyes-/iSAA-Q&A (Markowitz-Start → Simulation → Zielerreichung im schlechtesten Quartil → Constraints).

### Wo 5eyes bereits überlegen ist
- **Chance-constrained Solver mit DE/GA-Fallback** — Erfolgswahrscheinlichkeits-Schranken je Ziel (P-Ampel); garantierter House-Matrix-Fallback bei Solver-Divergenz.
- **Importance-Sampling der Tail-Szenarien** — 5–10× Varianzreduktion im Verlustbereich; präzisere VaR/CVaR bei gleicher Simulationszahl.
- **Cornish-Fisher-Fat-Tails** — Schiefe + Exzess-Kurtosis je Anlageklasse statt reiner Normalverteilung.
- **Deterministische Hash-Seeds** — jeder Lauf bit-genau reproduzierbar. Echter Audit-Vorteil für FINMA-Nachvollziehbarkeit.
- **Sequence-of-Returns / Vermögensverzehr** — Anteil erschöpfter Pfade + Median-Erschöpfungsjahr. Geht über die typische 3eyes-Darstellung hinaus.
- **Hypothek-Amortisation in der Projektion** — direkt/indirekt, Refinanzierung nach Ablauf; schlägt auf SOLL/IST-Kurven, MC und Reserve durch.
- **SOLL-vs-IST-Vergleich + Beratungs-Mehrwert-Delta** — zweispaltig mit Besser/Schlechter-Färbung, PNG-Export.
- **CHF-0-Datenstack** — yfinance + stooq + FRED/ECB/SNB mit Provider-Fallback-Chain. Keine Lizenzkosten für Marktdaten.
- **Offene Tax-Plugin-SDK** — Strategy+Registry, jedes Land andockbar (real bestückt: CH/DE).
- **Shadow-Methodenvergleich + Reasoning-Trace** — zwei Optimizer-Verfahren parallel für belegbaren Methodenvergleich.

### Wo 5eyes zu 3eyes aufgeschlossen hat (ehemalige Lücken geschlossen)
- **CMA-Tiefe** — Nelson-Siegel-Zinskurve, KGV-Mean-Reversion, Sub-Asset-Klassen mit Korrelationsmatrix und Skew/Kurtosis.
- **Zielerreichung ordinal + CHF-Fehlbetrag** (PAR-3) — Median-Erreichung und pessimistischer Fehlbetrag (P25) je Ziel, SOLL und IST.
- **Gesamtvermögens-/Reinvermögens-Sicht** — Immobilie als fixes Fundament, Allokation nur auf dem Finanzteil (Etappen 1–3).
- **BFS-Mortalität, Steuer-/Dividenden-Split** — per-Pfad-Steuer in den Solver-Kontext verdrahtet.

### Wo 3eyes (noch) führt

| Parity-Lücke | Status | Bedeutung |
|---|---|---|
| Stochastik-Optimizer als Default (PAR-1) | **Offen** | Default ist `house_matrix`+Tilt; goal-based Solver nur opt-in. 3eyes optimiert *immer* auf Zielerreichung. |
| Downside-robuste Zielfunktion (PAR-2) | **Offen** | Solver optimiert Erwartungswert des Shortfalls; das schlechteste Quartil erscheint nur in der Anzeige. |
| ISIN-/Produkt-Endschritt | **Fehlt** | Kein automatischer SAA→ETF-Mapper. |
| Echtzeit-Reaktivität (Auto-Recompute) | **Fehlt** | Manueller „Strategie berechnen"-Klick. |
| Markowitz-informierter Startpunkt (PAR-5) | Offen | Multi-Start ohne MV-optimalen Startpunkt. |
| FINMA-erprobte Reife & Produktuniversum | Reife | Vertrauens-/Reife-Rückstand, kein Modell-Rückstand. |

---

## 02 — Was das System allgemein gut kann

**Vollständige Beratungs-Journey.** SD → Cashflow/Ziele → Risikoprofil → SAA → Portfolio durchgängig orchestriert. Portfolio konsequent als *Ableitung der SAA* modelliert — methodenkonform. Einzige Ausnahme: der letzte Produkt-/ISIN-Schritt.

**FIDLEG-Compliance materialisiert** — als Service-Schicht plus PDF-Sektionen, je mit Artikel-Referenz:
- Eignungs-/Angemessenheitsprüfung (Art. 11/13/16), Freshness 365 Tage.
- Kostenausweis Ex-ante (Art. 8/9) — „unbekannte Kosten nie stillschweigend null".
- Beratungsprotokoll mit Integritäts-Hash.
- Interessenkonflikt-Offenlegung (Art. 9/26).

**Reporting & Strategietreue.**
- 27-Sektionen-PDF-Aggregator, jede Sektion gekapselt (try/except → „degraded" statt Crash).
- Strategietreue test-verankert — „kein Markt-Timing" über AST-/Invarianz-Tests durchgesetzt.
- revDSG — Register Privacy-by-Default, DSG-Art.-25-Datenexport.

**Technische Substanz.**
- Echte Postgres Row-Level-Security (`FORCE ROW LEVEL SECURITY` + Tenant-Policy), adversariale Isolations-Tests, eigener Postgres-CI-Job.
- Reife CI — Security-Gate *vor* der Vollsuite, Coverage-Messung, Frontend-Vitest, Postgres-RLS-Container.
- Saubere Marker-Hygiene (4 TODO, 0 FIXME/HACK), defensiver Stil (519 try/except, 48 Pydantic-Validatoren).
- Saubere Schichtung + Plugin-Architektur, 10 ADRs, Drift-Test-Disziplin.

---

## 03 — Was noch offen ist

> **Weichenstellung:** Für den ersten Kunden gilt `deployment_tier = tier1` (self-hosted, Einzelberater). Der komplette Hosting-, Multi-Tenant- und Auth-Härtungs-Cluster ist **für den Erststart irrelevant** — er wird erst mit Shared-Cloud (Tier 2/3) zum Blocker.

### Vor dem ersten Mandanten (Tier-1)

| Punkt | Status | Aufwand |
|---|---|---|
| A1 — Crash-Wurzelfix „Maximum call stack" | **Vermutlich behoben** (Root-Fix in #362) | Nur im A2-Smoke bestätigen |
| A2 — End-to-End-Visual-Smoke (11-Schritt-Klickstrecke) | Offen (QA) | ~1–2 Tage |
| A3 — Pilot-Trockenlauf mit 1 Kunden | Offen (QA) | ~1 Tag + Fixes |
| CF-1/CF-2 — Cashflow-Projektion divergiert von Engine | **Vor A3 bewerten** | Vertrauensrisiko im FIDLEG-Report |

### Für Hosting / Mehrbenutzer-Betrieb (Tier 2/3)
- **AUTH-01** — org-weites 2FA nicht serverseitig erzwungen (verifiziert offen). Für extern erreichbaren Betrieb kritisch.
- **AUTH-02** — Passwort-Zwangswechsel nur Frontend (verifiziert offen).
- **rls-1** — strict_tenant_isolation nicht aus Tier abgeleitet (verifiziert offen).
- **Postgres-Hosting-Cluster** — CH-Provider-Entscheid, Adapter-Verifikation, tenant_id NOT NULL, Per-Tenant-Encryption, externer Pentest.
- **DSG Art. 32** — Löschungs-/Erasure-Workflow fehlt (Retention-Abwägung FIDLEG 10J / OR 962).

### Engine-/Report-Korrektheit (vor breiterem Roll-out)
- **OPT-1/MC-1** — `chance_constraint_penalty` ohne Gewichte → verzerrte Erfolgswahrscheinlichkeit.
- **RES-1/RES-2** — Reserve nutzt max() statt additiv, ignoriert Verzehr ab Jahr 5+ → mögliche Unterreservierung.
- **AR-1/AR-2** — Report-Kennzahlen teils Stub (None), Hardness-Key-Mismatch.
- **Kostenausweis Ex-ante nicht im 27-Sektionen-Aggregator** — aktuell nur DepotCheck-PDF + Standalone.

---

## 04 — Was zu verbessern ist

| Thema | Schwere | Befund & Richtung |
|---|---|---|
| **Frontend-Monolith** `5eyes_v2.html` (25'593 Zeilen) | **Hoch** | Grösstes Artefakt, funktional ungetestet (nur Struktur-Snapshot). Split-Plan (ADR-008) existiert seit 6 Wochen, unbegonnen. Schrittweise React-Migration. |
| **Engine-God-Module** `portfolio_engine.py` (8'227 Zeilen) | Mittel | ~15% der Service-LOC in einer Datei, *kein* Split-Plan. Gut getestet (16 Engine-Test-Dateien). Eigenes Backend-Tech-Debt-Item. |
| **python-jose 3.3.0** (JWT-Auth-Pfad) | **Hoch** | Bekannte CVEs (Algorithm-Confusion, JWE-DoS). Migration zu `pyjwt` prüfen. *(Aus Versionskenntnis, nicht per Scanner verifiziert.)* |
| **Fail-open Compliance-Defaults** (`is_compliant: True` bei Exception) | Mittel | Report-Builder maskieren im Fehlerfall einen Verstoss als „compliant". Auf Fail-closed umstellen. |
| **Suitability-Check nicht blockierend** | Mittel | Pflichtverletzung wird angezeigt, nicht verhindert. Optionales Hard-Gate erwägen. |
| **Keine zentrale Test-/Coverage-Konfig** | Niedrig | Coverage gemessen, nicht erzwungen. Zentrale Konfig + Schwelle einführen. |
| **Repo-Hygiene** (179 Branches, 3 getrackte `.tmp_*`-Dateien) | Niedrig | Dual-Agent-Wildwuchs (77 codex/*). `.gitignore` um `.tmp_*` ergänzen, Junk (520 KB) entfernen. |

---

## 05 — Empfohlene Reihenfolge

**A · Blocker für den ersten Mandanten (überwiegend QA)**
1. A2 Visual-Smoke — 11-Schritt-Klickstrecke mit Testkunden (bestätigt A1).
2. A3 Pilot-Trockenlauf — fachliche Gegenprüfung mit echtem Kunden.
3. CF-1/CF-2 — Cashflow-Projektion mit der Engine in Einklang bringen (oder Divergenz dokumentieren) vor A3.

**B · Methodik-Parität & Empfehlungsqualität**
- PAR-1 + PAR-2 — Optimizer scharfschalten (mit Shadow-Validierung), Zielfunktion auf schlechtestes Quartil.
- Engine-Korrektheit — OPT-1/MC-1, RES-1/RES-2, AR-1/AR-2 re-verifizieren und fixen.
- Kostenausweis + KPIs ins Advisory-PDF (PAR-10).
- ISIN-Endschritt + Auto-Recompute.

**C · Skalierung, Hosting & Wartbarkeit**
- Auth-Härtung — AUTH-01/02, rls-1 serverseitig erzwingen.
- Postgres-Cluster + Pentest — CH-Provider, Encryption, externer Sicherheitstest.
- python-jose ablösen.
- Monolith-Migration — HTML→React in kleinen PRs; portfolio_engine.py-Split als eigenes Item.
- Methodik-Whitepaper + Engine-Backtest.

---

## Methodik & Vorbehalte

*Nicht abschliessend verifiziert:* CVE-Zuordnung python-jose (kein Scanner-Lauf); Detailstatus einzelner Audit-Findings (AUTH-04/05/06, RT-2, SEC-2) aus dem Audit-Doc übernommen; Soft- vs. Hard-Delete-Semantik von `delete_client`; „über 3400 Tests" ist ein CI-Kommentar (Datei-Zahl 398 ist verifiziert).
