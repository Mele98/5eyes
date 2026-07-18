# 5eyes — Effizienter Umsetzungsplan: „Was zu verbessern ist"

**Stand:** 18. Juli 2026 · Basis: [CTO-Standortbericht](./2026-07-18-cto-standortbericht.md) §04
**Zweck:** Die 7 Verbesserungspunkte aus §04 in der kostengünstigsten Reihenfolge abarbeiten — so, dass jeder Schritt einzeln grün testbar ist und Risiko vom Rest getrennt bleibt.

## Leitprinzipien (warum diese Reihenfolge effizient ist)

1. **Billig & risikolos zuerst.** Mechanische Hygiene (kein Fachlogik-Risiko) kostet Stunden, räumt aber das Arbeitsfeld frei und reduziert Merge-Reibung für alles danach.
2. **Isolierte Korrektheits-/Sicherheitsfixes vor Struktur-Umbau.** Ein CVE-Fix oder Fail-closed-Switch ist self-contained + mit einem Pin-Test absicherbar; er darf nicht in einem wochenlangen Monolith-Umbau untergehen.
3. **Grosse Migrationen zuletzt und inkrementell.** HTML/Engine-Split nur in kleinen PRs mit dem bestehenden Drift-Test als Sicherheitsnetz — nie „big bang".
4. **Ein PR = ein Thema = grüne Suite.** Branch-Check vor jedem Commit (Dual-Agent-Setup Claude+Codex). Kein Umbau ohne Not.
5. **Parallelisierbar markiert** — was gleichzeitig (ggf. in Worktrees) laufen kann, ohne sich in die Quere zu kommen.

---

## Welle 0 — Hygiene & Fundament (Stunden, autonom, 0 Fachlogik-Risiko)

Batchbar, kein Engine-Touch. Sofort machbar.

### 0.1 Repo-Hygiene · Schwere: Niedrig · ~1 h
- `.gitignore` um `.tmp_*` ergänzen (heute nur `tmp_*` → 3 Junk-Dateien getrackt).
- `git rm --cached .tmp_5eyes_frontend_check.js .tmp_5eyes_inline_bundle.js .tmp_pr_body.md` (520 KB raus).
- `scripts/cleanup-codex-branches-safe.ps1` einmal laufen lassen (löscht nur `ahead=0`-Branches, idempotent) → 179 Branches eindampfen.
- **Test/Nachweis:** `git status` sauber, Suite unverändert grün. **PR:** `chore/repo-hygiene`.

### 0.2 Zentrale Test-/Coverage-Konfig · Schwere: Niedrig · ~2 h
- `pyproject.toml`/`pytest.ini` anlegen: `addopts`, Marker-Registry, `testpaths`, das heute im CI-CLI verstreute Setup zentralisieren.
- Coverage-Schwelle als **Warn-Gate** einführen (nicht sofort hart, um CI nicht rot zu reissen) — Baseline messen, dann Schwelle knapp darunter setzen.
- **Test/Nachweis:** `pytest` lokal identisch zum CI-Lauf; CI grün. **PR:** `chore/pytest-central-config`.

> Nach Welle 0: sauberes Arbeitsfeld, reproduzierbare lokale Läufe, weniger Branch-Rauschen. Alles Folgende committet gegen weniger Reibung.

---

## Welle 1 — Isolierte Sicherheit & Korrektheit (Tage, hohe Wirkung, self-contained)

Jeder Punkt eigener Branch, eigener Pin-Test. **1.1 und 1.2 sind parallelisierbar** (verschiedene Dateien).

### 1.1 python-jose → PyJWT · Schwere: HOCH · ~1 Tag
Grösstes Dependency-Risiko (CVEs im Finanz-Auth-Pfad).
1. **Zuerst verifizieren** (Vorbehalt aus Bericht): `pip show python-jose`, betroffene Version + genutzte Algorithmen prüfen (`grep -rn "jwt.encode\|jwt.decode\|from jose"` → `services/auth.py`, `services/totp.py`).
2. Adapter-dünn umstellen: `jose.jwt` → `jwt` (PyJWT), `algorithms=["HS256"]` **explizit** (schliesst Algorithm-Confusion), `options={"require":["exp"]}`.
3. `requirements.txt`: `python-jose[cryptography]` raus, `pyjwt[crypto]` gepinnt rein.
4. **Test/Nachweis:** bestehende Auth-Tests grün + neuer Pin-Test: manipuliertes `alg:none`/RS-Token wird abgelehnt; abgelaufenes Token → 401. **PR:** `fix(security)/jose-to-pyjwt`.
- *Fallback:* Falls JWE genutzt wird (PyJWT kann kein JWE), stattdessen python-jose auf gepatchte Version heben + `alg`-Whitelist erzwingen und als bewusste Entscheidung dokumentieren.

### 1.2 Fail-open → Fail-closed in Compliance-Buildern · Schwere: Mittel · ~0.5–1 Tag
`is_compliant: True` im `except` maskiert echte Verstösse.
1. In `services/advisory_report.py` alle Compliance-`_build_*` mit `except Exception`: Default-Wert von `True`/„compliant" auf `None`/„unbekannt (Prüfung fehlgeschlagen)" umstellen — Report crasht weiterhin nicht (degraded), behauptet aber nie fälschlich Konformität.
2. PDF-Renderer: „unbekannt"-Zustand sichtbar als Warnung statt grün.
3. **Test/Nachweis:** Builder mit erzwungener Exception → Sektion zeigt „unbekannt", nie `is_compliant:True`. **PR:** `fix(compliance)/fail-closed-defaults`.

### 1.3 Engine-/Report-Korrektheit re-verifizieren + fixen · Schwere: Mittel · ~1–2 Tage
Am **gemergten** Code prüfen (nach #299/#305 umgeschrieben — Findings evtl. veraltet). Subagent-Verifikation mit Read-Tool vor jedem Fix.
- **OPT-1/MC-1** — `chance_constraint_penalty(..., weights=...)` korrekt durchreichen in `optimizer/objective.py`. Pin-Test: P(success) invariant gegen Bucket-Reihenfolge.
- **RES-1/RES-2** — Reserve additiv statt `max()`, Verzehr-Fenster über Jahr 5+ ausdehnen, Input-Validierung (negative minReserve, Ceiling-Cap). Pin-Test: Unterreservierungs-Szenario.
- **AR-1/AR-2** — Hardness-Key-Mismatch (`primär/primaer`) + Stub-`None`-Kennzahlen in `advisory_report.py` schliessen.
- **PR:** je Finding ein Commit, gebündelt in `fix(engine)/audit-correctness` — **erst nachdem** die Erstkunden-QA (A2/A3) nicht blockiert wird.

> Regel bei allen Engine-Fixes: konservativer Wert im Zweifel, volle Regression, Determinismus-Check über zwei Läufe.

---

## Welle 2 — Compliance-Entscheid (braucht User-Input, klein umzusetzen)

### 2.1 Suitability-Check optional blockierend · Schwere: Mittel · ~0.5 Tag Code + Entscheid
**User-Entscheid nötig:** soll fehlende Eignungsprüfung eine Empfehlung *verhindern* (Hard-Gate) oder weiter nur *anzeigen*?
- Umsetzung als **opt-in Flag** (`require_suitability_before_recommendation`, Default = heutiges Verhalten), damit kein Bruch für bestehende Nutzung.
- Gate in `advisory_log_service.create_entry` bzw. dem Recommendation-Run.
- **Test/Nachweis:** Flag an → Run ohne aktuelle Prüfung wird mit klarer FIDLEG-Meldung blockiert; Flag aus → unverändert. **PR:** `feat(compliance)/optional-suitability-gate`.

---

## Welle 3 — Struktur-Migration (Wochen, inkrementell, Sicherheitsnetz Pflicht)

Erst starten, wenn Welle 0–1 durch ist. **Nie big-bang.**

### 3.1 Frontend-Monolith `5eyes_v2.html` → React · Schwere: HOCH · Wochen
Split-Plan existiert (ADR-008 + `2026-06-02-sprint-u-35-modul-split-plan.md`) — abarbeiten, nicht neu planen.
1. **Sicherheitsnetz aktiv halten:** vor/nach jeder Änderung `python scripts/audit_html_monolith.py` → Drift-Test grün.
2. Reihenfolge nach ADR-008 (Roadmap #63–69): Profiling → Goal-Wizard → Mandate-Edit → CRM → Asset-Allocation → Cashflow → App-Shell **zuletzt**.
3. Muster je Modul: Schema-First → React-Page in bestehende Reporting-Subapp → Vitest → Wiring → Drift-Test. **Ein Modul = ein PR, einzeln grün.**
4. Erster Schnitt **ohne Fachlogik-Änderung** (reines Extrahieren), um das Muster zu validieren.

### 3.2 Engine-God-Module `portfolio_engine.py` splitten · Schwere: Mittel · Wochen
Kein Plan vorhanden → **Vorarbeit: Split-Plan schreiben** (analog ADR-008), dann umsetzen.
- Kandidaten-Schnitte: MC-Simulation, House-Matrix/Tilt, CMA-Verarbeitung, Reserve, Gesamtvermögen, Payload-Bau → je eigenes Modul mit stabilem Import-Alias in `portfolio_engine.py` (Rückwärtskompatibilität).
- Absicherung: 16 vorhandene Engine-Test-Dateien laufen unverändert grün → Refactoring ist verhaltensneutral beweisbar.
- **Ein Extraktionsschritt = ein PR.** Reihenfolge: die am wenigsten verflochtenen Blöcke zuerst.

---

## Reihenfolge-Übersicht (Effizienz-Sicht)

| # | Punkt | Welle | Schwere | Aufwand | Parallel? | Risiko |
|---|---|---|---|---|---|---|
| 0.1 | Repo-Hygiene | 0 | Niedrig | ~1 h | – | keins |
| 0.2 | Zentrale Test-/Coverage-Konfig | 0 | Niedrig | ~2 h | mit 0.1 | keins |
| 1.1 | python-jose → PyJWT | 1 | **Hoch** | ~1 Tag | mit 1.2 | mittel (Auth) |
| 1.2 | Fail-open → Fail-closed | 1 | Mittel | ~1 Tag | mit 1.1 | niedrig |
| 1.3 | Engine-/Report-Korrektheit | 1 | Mittel | ~1–2 Tage | nach QA | mittel (Empfehlung) |
| 2.1 | Suitability Hard-Gate (opt-in) | 2 | Mittel | ~0.5 Tag | – | niedrig (Entscheid) |
| 3.1 | HTML→React-Migration | 3 | **Hoch** | Wochen | modulweise | hoch (inkrementell zähmen) |
| 3.2 | Engine-Modul-Split | 3 | Mittel | Wochen | nach 3.1-Muster | mittel |

**Gesamt bis „strukturell sauber": Welle 0–2 in ~4–6 Arbeitstagen autonom machbar; Welle 3 als eigene, dauerhafte Sprint-Spur.**

## Sofort-Start (autonom, ohne Rückfrage)
Welle 0 (0.1 + 0.2) + Welle 1.1/1.2 kann ich direkt in Angriff nehmen — alles self-contained, testabgesichert, kein User-Entscheid nötig. **Rückfrage nur bei 2.1** (Suitability blockierend ja/nein).

## Offene User-Entscheide
- **2.1:** Eignungsprüfung blockierend erzwingen oder nur anzeigen?
- **1.1 Fallback:** falls JWE genutzt wird — PyJWT-Wechsel oder gepatchtes python-jose behalten?
