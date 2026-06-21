# Spec-Sprint 2026-06-21 — Master-Index (13 implementierungsfertige Specs)

Autonomer Multi-Agent-Sprint: 13 Specs für die schwersten offenen Master-Roadmap-Cluster, jede gegen den echten Code verifiziert (file:line), jede mit fertigem Codex-Prompt. **Nächster Schritt = nur noch Umsetzung.**

> Erstellt während Codex auf `codex/postgres-rls-tenant-crypto` arbeitet (uncommittete Änderungen, #8–11 Postgres/RLS). **Diese Specs haben NUR neue Dateien angelegt** — keine bestehende Datei editiert, kein Commit, kein Branch-Wechsel. Vor Umsetzung jeweils `git branch --show-current` prüfen.

## Übersicht

| Spec-Datei | Roadmap | Kern-Erkenntnis |
|---|---|---|
| `spec-05-httponly-cookie-auth.md` | #5 | 3-Phasen-Cookie-Migration ohne Bruch; Electron braucht SameSite=None+Secure (127.0.0.1 trustworthy) |
| `spec-33-goal-scope-gesamtvermoegen.md` | #33 | **Engine bereits fertig** — nur Test-Lock + Doku offen |
| `spec-39-46-tax-aware-engine.md` | #39 #46 #40 | **Bug:** toter `TaxConfig`-Pfad → Solver läuft IMMER tax-naiv |
| `spec-45-47-optimizer-subclass-currency.md` | #45 #47 | Block-Diagonal-Sub-Klassen-Draws + FX-Faktor, beide opt-in, Output-Shape unverändert |
| `spec-41-44-engine-hardening-p2-p5.md` | #41–44 | CTO-Plan längst gemerged → echte Rest: #3 Inflations-Offset + #5 brutto-Renditeziel + Guards |
| `spec-52-59-61-verzehr-reserve.md` | #52 #59 #61 | **Verdeckter Double-Count in der Reserve** (Cashflow+Goal); MC selbst sauber |
| `spec-71-72-57-pdf-twopass-sollist.md` | #71 #72 #57 | Two-Pass+Seitenzahlen da → nur Bookmarks/Hyperlinks + Page-Ranges + SOLL/IST-Sektion |
| `spec-76-admin-menue-redesign.md` | #76 | Audit: **0 Placeholder** (12 WORKS / 5 PARTIAL) → reine UX-Regruppierung 17→~10 |
| `spec-24-54-55-quota-inflows-phasen.md` | #24 #54 #55 | 70-80 % gebaut → Soft-Limit + Inflow-FE-Maske + Phasen-Assistent offen |
| `spec-28-20-21-14-sec-ops-hardening.md` | #28 #20 #21 #14 | Refresh-Token + globales Rate-Limit + Audit-Log-tenant_id + Metrics/Alerts |
| `spec-34-48-51-data-engine-konsistenz.md` | #34 #48–51 | **#49 Audit: kein Market-Timing** (ADR-003 ok) → Anti-Trigger-Regressionstest |
| `spec-63-69-fe-react-migration-adr008.md` | #63–69 | Strangler-Fig #63→64→67→68→65→66→69; Monolith real ~24'700 Zeilen |
| `spec-79-86-qa-e2e-ci-hardening.md` | #79–86 | Playwright (`e2e.yml`!), Perf-Budget, Mutation, Concurrency, Lint-Gate |

## Empfohlene Codex-Reihenfolge (Aufwand vs. Wert)

**Sofort / billig (Quick Wins, viel ist schon gebaut):**
1. #33 — Test-Lock + Doku (kein Engine-Code).
2. #39/46 — `TaxConfig`-Bug fixen (Solver tax-aware machen), Tax-Cashflow opt-in.
3. #49 — Anti-Market-Timing-Regressionstest + Audit-Doc.
4. #85/#83/#86 — CI-Gates (Lint/Perf/Mutation) als kleine Parallel-Branches.

**Mittel:**
5. #71/72/57 — PDF-Bookmarks + Page-Ranges + SOLL/IST-Sektion.
6. #24/54/55 — Quota-Soft-Limit + Inflow-FE + Phasen-Assistent.
7. #52/59/61 — Reserve-Dedup (Double-Count!) + Verzehr-Sockel + Reserve-Narrativ.
8. #76 — Admin-Menü-Regruppierung.

**Groß / eigener Sprint (OWNER-DECISION zuerst):**
9. #5 — HttpOnly-Cookie (Breaking-Change, 3 Phasen).
10. #28/20/21/14 — Token-Refresh + Rate-Limit + Audit-Streaming + Monitoring.
11. #45/47 — Optimizer Sub-Klassen + Currency.
12. #41-44 — Engine-Hardening (#3 braucht OWNER-DECISION Inflations-Konvention).
13. #63-69 — FE-React-Migration (mehrjähriger Track, je Track ein PR).

## Offene OWNER-DECISIONs (blockieren Umsetzung)
- **#3** Inflations-Konvention (Cashflow Beginn- vs. End-of-Year) — Empfehlung End-of-Year.
- **#5** SameSite-Wert, Refresh-Token jetzt/später, Reporting-Token-Handoff.
- **#33** externe-Assets-Wachstum real 0 % (konservativ, im Code bestätigt) — nur festschreiben.
- **#52** Drawdown-Rendite 100 bps, sockelIndexBps 100 bps.
- **#28** TTL-Werte, **#20** Rate-Limit-Schwellen, **#21** Retention (≥10J FINMA).

> Jede Spec enthält ihren eigenen kopierbaren Codex-Prompt-Block am Ende.
