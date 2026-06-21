# Spec #33 — goal_scope="Gesamtvermögen" engine-seitig

**Status:** Engine **bereits implementiert** (intern Label #83) und per untracked Test verifiziert (6 passed). Restarbeit = Regressions-Lock + Doku + optional PDF-Surfacing.
**Erstellt:** 2026-06-21 (autonomer Spec-Sprint). Alle file:line per Read am echten Code verifiziert.
**Branch-Vorschlag:** `codex/u33-goal-scope-gesamtvermoegen`

---

## 1. Ziel
Ziele mit `goal_scope='Gesamtvermögen'` werden gegen das **Gesamtvermögen** (total_wealth) statt nur gegen das Beratungsvermögen (advisory) bewertet. Externe (nicht-beratene) Assets gehen **konservativ** ein: real 0 %, nur Teuerung, keine Volatilität.

## 2. Verifizierter IST-Zustand (NICHT ändern)
- `_goal_uses_total_scope` — `services/portfolio_engine.py:2663`: substring "gesamt", case-insensitive.
- `_external_assets_inflation_value` — `:2669`: externe Assets = real 0 %, nur Teuerung, keine Vola; Fallback 150 bps; base≤0 → 0.
- Deterministischer Pfad `_build_goal_analysis` — `:2689`, Zweig Kapitalerhalt/Vermögensziel `:2757-2760`: bei Total-Scope `external_wealth=max(0,total-advisory)` inflationiert → zu `projected` addiert.
- Monte-Carlo `_monte_carlo_goal_summary` — `:2958`, Zweig `:3042-3052`: derselbe **konstante** Betrag auf jeden Pfad → kein MC-Drift.
- Call-Sites geben `total_wealth_rappen`: `:6247`, `:7012`, `:3408`, `:3422`. total_wealth berechnet `:4354/:6839/:6003`.
- Modell/Schema: `models/wealth.py:132` · `schemas/wealth.py:420` (Create, bereits Literal-gehärtet) / `:459` (Update, NICHT gehärtet).
- Test (untracked, grün, 6 passed): `tests/test_goal_scope_gesamtvermoegen.py`.
- Advisory-PDF zeigt goal_scope heute **nicht** an (`services/pdf/documents/advisory_report.py:543` zeigt nur die Wealth-Overview-Zeile); goal_scope steht aber bereits im `goal_analysis`-Dict (`portfolio_engine.py:2808`).

## 3. Restarbeit (SOLL)
1. **Test-Lock:** `tests/test_goal_scope_gesamtvermoegen.py` unverändert ins Repo committen.
2. **Ergänzungstests:** total==advisory (kein Effekt) · total<advisory (kein Abzug, max(0,…)) · gemischte Ziel-Liste (nur Gesamtvermögen-Ziel bekommt Summanden) · Renditeziel/Pensionsausgabe mit Total-Scope → **kein** externer Summand (bewusst locken).
3. **Doku/ADR + Glossar:** "Gesamtvermögen-Scope": externe Assets real 0 % (User-Entscheid); **Risiko-Hinweis** — Buchwert heute, keine Illiquiditäts-/Verkaufskosten/Wertänderung modelliert → Zielerreichung evtl. zu optimistisch.
4. **OPTIONAL (Owner bestätigt):** Advisory-PDF Gesamtvermögen-Ziele in Goal-Tabelle kennzeichnen + Risiko-Fussnote.
5. **OPTIONAL:** `schemas/wealth.py:459` Update-Schema `goal_scope` auf `Literal["Beratungsvermögen","Gesamtvermögen"]` härten (parity zu `:420`).

## 4. OWNER-DECISIONS
- Wachstumsrate externer Assets: **real 0 % (konservativ)** — bestätigt durch Code, in Doku festschreiben.
- PDF-Surfacing von goal_scope: ja/nein.

## 5. Definition of Done
- `pytest tests/test_goal_scope_gesamtvermoegen.py -q` → 6+ passed
- Voller Backend-Lauf grün (v.a. test_audit_b4_goal_base_consistency, test_audit_f23_mc_total_paths, test_advisory_report*, test_glossar_consistency)
- VOR jedem Commit: `git branch --show-current` prüfen.
