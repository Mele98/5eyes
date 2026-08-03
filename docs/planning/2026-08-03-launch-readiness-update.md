# 5eyes WealthArchitekten — Launch-Readiness-Update

**Stand:** 3. August 2026 · Branch `develop` @ `b4201c0`
**Basis:** Update des [CTO-Standortberichts vom 18. Juli](./2026-07-18-cto-standortbericht.md). 146 Commits seither. Alle Status-Angaben unten per Code-Lektüre (Read/Grep) am aktuellen `develop`-Stand verifiziert, nicht aus dem Juli-Bericht übernommen.

---

## Kernaussage

**Der technische Abstand zum ersten Mandanten ist seit dem 18. Juli deutlich kleiner geworden — nicht grösser.** Von den 24 offenen Punkten aus dem Juni-Audit (`2026-06-24-audit-findings-backend-ops.md`) sind **17 verifiziert gefixt**, darunter beide harten Tier-2/3-Blocker AUTH-01 und AUTH-02. Der Engine-Split (ADR-014) ist abgeschlossen, die React-Migration (ADR-008) hat 6 von 7 Modulen. Der Restriktionen&Tilts-Audit von heute hat 5 weitere reale Bugs gefunden und gefixt.

**Was jetzt zwischen dem Code und einem echten ersten Mandanten steht, ist kein Feature mehr — es ist ein QA-Durchlauf, eine bewusste Entscheidung über 5 dokumentierte fachliche Korrektheits-Lücken, und eine Handvoll Themen, die ausserhalb von Code liegen** (Recht, Hosting-Vertrag, Versicherung).

---

## 01 — Seit dem 18. Juli erledigt (verifiziert, nicht aus Doku übernommen)

| Punkt (Juli-Bericht) | Status heute | Fundstelle |
|---|---|---|
| AUTH-01 — 2FA nicht serverseitig erzwungen | ✅ gefixt (Re-Verifikation 23.7.) | `docs/planning/2026-06-24-audit-findings-backend-ops.md` |
| AUTH-02 — Passwort-Zwangswechsel nur Frontend | ✅ gefixt 19.7. | `services/auth.py:181-211` (`must_change_password` serverseitig gegated) |
| rls-1/rls-2/rls-3 — Tenant-Isolation-Lücken | ✅ gefixt (rls-2 über unabhängigen Deep-Audit F3, vollständiger) | `services/auth.py:267-321`, `routers/protocol_bausteine.py` |
| SEC-1/SEC-2 — Tenant-lose Admin-Sichtbarkeit | ✅ gefixt | `routers/auth.py` (`_assert_user_visible_to`) |
| CF-1/CF-2 — Cashflow-Projektion divergierte von Engine | ✅ beide gefixt | `tests/test_cf2_cashflow_summary_fx.py` |
| AR-1/AR-2/AR-3 — Report-Kennzahlen Stub/Mismatch | ✅ alle gefixt (MC-KPIs jetzt aus `ta.mc_exp_vol_bps` etc. verdrahtet) | `services/advisory_report.py:763-766` |
| OPT-1/MC-1/MC-2 — Chance-Constraint-Gewichte | ✅ gefixt | s.o. |
| python-jose → PyJWT | ✅ gefixt 18.7. | `requirements.txt:11` (`PyJWT[crypto]==2.10.1`) |
| Fail-open → Fail-closed Compliance-Defaults | ✅ gefixt | `is_compliant=None` + `audit_degraded` |
| Kostenausweis Ex-ante nicht im 27-Sektionen-Aggregator | ✅ gefixt | `services/advisory_report.py:342` |
| Suitability Hard-Gate (2.1, User-Entscheid) | ✅ als Opt-in-Flag umgesetzt (Default aus) | `routers/allocation.py:436` (`require_suitability_before_recommendation`) |
| Engine-God-Module `portfolio_engine.py` (8'227 Zeilen) | ✅ **abgeschlossen heute** (ADR-014, 8 Extraktionsschritte) | 3'771 Zeilen Kern + 8 Cluster-Module, Golden-Snapshot byte-identisch |
| Frontend-Monolith-Migration (ADR-008) | 🟡 **6 von 7 Tracks fertig** (Profiling #63, Goal-Wizard #64, Mandate #65, CRM #66, Asset-Allocation #67, Cashflow #68 + Wiring-Brücken) | nur App-Shell (#69, laut Plan bewusst zuletzt) offen |
| **Restriktionen & Tilts (heutiger Audit)** | ✅ 5 Bugs gefixt, 35 neue Tests, gemergt (`fa88fed`, `b4201c0`) | Kernfund: Risikobudget-Fallback verwarf manuelle Bandbreiten-Restriktionen |

**17 von 24 Juni-Audit-Findings sind zu.** Das ist der grösste Teil der Substanz hinter "was noch offen ist" aus dem Juli-Bericht.

---

## 02 — Was noch offen ist, neu geordnet nach Launch-Relevanz

### A. Vor dem ersten Mandanten (Tier-1, self-hosted) — reine QA, kein Code

| Punkt | Status |
|---|---|
| A2 — End-to-End-Visual-Smoke (11-Schritt-Klickstrecke) | **Weiterhin offen** — kein neuer QA-Report seit Juli gefunden |
| A3 — Pilot-Trockenlauf mit 1 echten/Test-Kunden | **Weiterhin offen** |

Die 146 Commits seit dem 18. Juli waren fast ausschliesslich Engineering-Hardening (Engine-Split, DE-Jurisdiktion, dieser Audit) — **kein dokumentierter Klickstrecken-Test mit einem Testkunden hat seither stattgefunden.** Das ist der greifbarste, günstigste nächste Schritt: ~1-2 Tage, kein Risiko, deckt vermutlich weitere kleine UI-Lücken auf (wie den `buildQT()`-Desync-Bug von heute, der genau durch einen Klicktest gefunden wurde).

### B. Bewusst offene fachliche Korrektheits-Lücken — reale Zahlen-Risiken, brauchen eine Scoping-Entscheidung

Diese wurden am 23./24. Juli **bewusst nicht gefixt**, weil sie reale Empfehlungszahlen ändern und ausserhalb eines "sicher additiven" Scopes lagen — nicht weil sie übersehen wurden:

| Finding | Risiko | Warum noch offen |
|---|---|---|
| **RES-1** | Reserve-Berechnung nutzt `max()` statt jahresweiser kumulativer Running-Balance — mögliche **Unterreservierung** bei mehrjährigen Entnahme-Szenarien | Ändert `reserve_needed_rappen`, Kern der SAA-Empfehlung |
| **RES-2** | `external_reserve_rappen`/`reserve_needed_rappen` ungedeckelt gegen `advisory_wealth_rappen` | Ändert `investable_advisory_wealth_rappen` |
| **goals-1** | AHV-Goals werden im Monte-Carlo-Pfad NICHT als "bereits finanziert" erkannt (im Gegensatz zum deterministischen Pfad) | Verzerrt Goal-Achievability-Scores im Bericht |
| **OPT-2** | Solver-Bounds nutzen das schwächere `equity_min_bps` statt `equity_minimum_bps` — Divergenz Solver vs. deterministischer Pfad | Ändert die Lösungsmenge im `stochastic`/`shadow_stochastic`-Modus (Default ist `house_matrix` — **kein Blocker für Tier-1-Standardbetrieb**) |
| **MD-01** | Preis-Batch-Pfad trägt keine Provider-Currency; Single-Pfad schon — Inkonsistenz | Reales Korrektheitsrisiko bei Fremdwährungs-Positionen, mehrstelliger Tuple-Refactor über 4 Provider-Funktionen |
| RT-2 | Negative Steuer-Overrides erzeugen negative "Steuer" | Explizit out-of-scope laut Auftrag (Tax-Formeln tabu) |

**Empfehlung:** RES-1/RES-2 vor A3 (Pilot-Trockenlauf) bewerten — genau wie der Juli-Bericht das für CF-1/CF-2 schon empfahl (die inzwischen gefixt sind). goals-1/OPT-2/MD-01 sind für den Tier-1-Erstkunden im Default-Modus (`house_matrix`, keine MC-Pension-Goals, CHF-only) niedrigeres Risiko, aber vor breiterem Roll-out zu adressieren.

### C. Sicherheit für Mehrbenutzer-Hosting (Tier 2/3) — für Tier-1-Erstkunden irrelevant

| Punkt | Status |
|---|---|
| **AUTH-03** | X-Forwarded-For wird unbedingt vertraut (spoofbar, Rate-Limit-Bypass) — ein Fix wurde versucht und **bewusst verworfen**, weil er einen bestehenden Test brach, der explizit XFF-basierte Isolation verlangt. Braucht eine echte Deployment-Topologie-Entscheidung (Reverse-Proxy ja/nein, `trusted_proxy_count`) bevor das sauber gefixt werden kann. |
| Postgres-Hosting-Cluster | CH-Provider-Entscheid, `tenant_id NOT NULL`, Per-Tenant-Encryption, externer Pentest — weiterhin offen, ADR-009 ist der Plan, keine Umsetzung |
| MD-05 (Rest) | Inter-Symbol-Throttle im Stooq-Batch-Loop bleibt offen (Retry-Backoff selbst ist gefixt) |

### D. Regulatorisch/rechtlich — ausserhalb Code, aber launch-relevant

| Punkt | Status |
|---|---|
| **DSG Art. 32** — Löschungs-/Erasure-Workflow | Bewusst noch nicht gebaut (`services/data_export.py:28`: "Konkrete Löschung folgt in einem eigenen [Sprint]"). Eigener Sprint nötig, inkl. Retention-Abwägung FIDLEG 10 Jahre vs. OR 962. |
| **AVV-Vorlage** (Auftragsverarbeitungsvertrag) | Existiert (`docs/compliance/avv-template.md`), aber explizit als **"kein Rechtsrat, vor produktivem Einsatz durch Datenschutz-/Rechtsfachperson zu prüfen"** markiert — braucht echte juristische Prüfung vor dem ersten Mandanten mit Fremd-Hosting. |
| Global konfigurierbare Hauptwährung | Separates, grösseres Vorhaben (nicht code-verifiziert in dieser Runde, siehe Projekt-Memory) |

### E. Struktur/Wartbarkeit — nicht launch-blockierend

- **Frontend-Monolith**: von 25'593 auf 26'910 Zeilen gewachsen (netto, trotz Migration — neue Features kamen schneller hinzu als React-Extraktion sie abbaute), aber 6 von 7 ADR-008-Tracks sind fertig. Nur die App-Shell fehlt (bewusst zuletzt laut Plan).
- **Engine-God-Module**: **erledigt** (ADR-014 heute abgeschlossen, 3'771 statt 8'227 Zeilen im Kern).

### F. Business/Go-to-Market — ausserhalb meiner Code-Verifikation, aber für "Launch" typischerweise nötig

Diese kann ich nicht aus dem Code beantworten — nur benennen, damit sie nicht vergessen werden:
- Berufshaftpflichtversicherung für Software-Fehler mit Vermögensschaden-Folge
- Endgültiges Preis-/Lizenzmodell + Rechnungsstellung (Tenant-Lizenz-Enforcement ist technisch gebaut, siehe Memory, aber Preismodell selbst ist eine Geschäftsentscheidung)
- Support-/Incident-Response-Prozess für den ersten Kunden (wer nimmt Anrufe entgegen, SLA?)
- Onboarding-Dokumentation/Schulung für den ersten Berater
- Ggf. FINMA-/SRO-Registrierungsstatus der nutzenden Beratungsfirma selbst (nicht von 5eyes, aber Voraussetzung, dass der Kunde die Software überhaupt regulatorisch einsetzen darf)

---

## 03 — Empfohlene Reihenfolge zum Launch

**Schritt 1 (jetzt möglich, ~2-3 Tage, kein Risiko):**
1. A2 Visual-Smoke — 11-Schritt-Klickstrecke, diesmal inkl. des heute gefixten Restriktionen&Tilts-Bereichs.
2. RES-1/RES-2 bewerten und entscheiden: fixen vor A3, oder bewusst als bekanntes Risiko für den Piloten dokumentieren (konservativ: eher fixen, da "Unterreservierung" direkt Kundenvertrauen betrifft).
3. A3 Pilot-Trockenlauf mit Testkunde.

**Schritt 2 (parallel möglich, juristisch/organisatorisch):**
4. AVV-Vorlage durch Rechtsfachperson prüfen lassen.
5. Berufshaftpflicht, Support-Prozess, Preismodell klären (Geschäftsentscheidungen, nicht technisch).

**Schritt 3 (erst wenn Tier 2/3 = Mehrbenutzer-Hosting anstehen):**
6. AUTH-03 — Deployment-Topologie-Entscheidung treffen, dann fixen.
7. Postgres-CH-Provider wählen, Pentest beauftragen.
8. DSG Art. 32 Löschungs-Workflow als eigener Sprint.

**Nicht blockierend, kontinuierlich weiterlaufen lassen:**
9. goals-1, OPT-2, MD-01 vor breiterem Roll-out (mehr als Pilot-Kunde) fixen.
10. App-Shell-React-Migration (ADR-008 letzter Track).

---

## Methodik & Vorbehalte

Alle Status-Angaben oben per Read/Grep am aktuellen `develop`-Stand (`b4201c0`) verifiziert, nicht aus dem Juli-Bericht oder Audit-Docs unkritisch übernommen — mit Ausnahme der Business/Go-to-Market-Punkte (Abschnitt F), die ausserhalb von Code-Verifikation liegen und als solche markiert sind. QA-Status (A2/A3) basiert auf "kein dokumentierter Report gefunden", nicht auf Bestätigung, dass es nicht informell passiert ist.
