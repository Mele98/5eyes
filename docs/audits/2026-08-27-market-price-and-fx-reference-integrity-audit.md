---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-market-price-and-fx-reference-integrity-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "2c2a4643a3bb8e42457a611c93b2b8e0b2872c16"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-product-master-data-and-exposure-integrity-audit.md"
prior_release_audit_commit: "2c2a4643a3bb8e42457a611c93b2b8e0b2872c16"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-market-price-and-fx-reference-integrity-audit.md"
audit_mode: "read_only_static_schema_service_and_consumer_review_isolated_http_persistence_and_determinism_reproduction_and_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "current FX write domain, FX model/report basis consistency, product-price chronology and multi-source daily backtest determinism"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 141
focused_adjacent_tests_skipped: 1
focused_adjacent_tests_failed: 0
required_next_action: "make FX quantization and current-row uniqueness atomic, validate price chronology before persistence, and bind every daily backtest date to one explicit provider snapshot"
---

# Marktpreis- und FX-Referenzintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die dreizehnte Read-only-Kontrollrunde
auf Repository-Head `2c2a4643`. Er ergänzt, ersetzt aber nicht:

1. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
2. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
3. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
4. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
5. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
6. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
7. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
8. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
9. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
10. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
11. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
12. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
13. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die dreizehn vorgenannten Dokumente in dieser
Reihenfolge. Ein sichtbarer Warntext macht einen mathematisch mehrdeutigen
Marktdatenstand nicht reproduzierbar. Ein strikter Solver-Loader ersetzt keinen
strikten Schreibvertrag.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Drei weitere P1-Verträge sind offen:

- Der FX-Endpoint akzeptiert Bool als Kurs und jeden positiven Float vor der
  Integerquantisierung. Ein echter Request mit `rate=0.00001` antwortete HTTP
  200 und persistierte `rate_x10000=0` als globalen Current-Kurs. Danach
  blockierte der strikte Modell-Loader; der ältere Reporting-Loader verwirft
  dieselbe Zeile dagegen still und verwendet Defaults.
- Produktpreise besitzen keinen kanonischen Zeitvertrag. Eine zukünftige
  Kurszeile `2099-12-31` wurde persistiert, als neueste Zeile ausgewählt und
  wegen eines negativen Alters als `fresh` mit 100 Prozent Coverage bewertet.
- Daily-Preis- und FX-Tabellen erlauben pro Datum mehrere Quellen, der
  Backtest besitzt aber weder Snapshot-ID noch Providerpriorität noch
  Konfliktfehler. Derselbe logische Zeilensatz ergab allein durch umgekehrte
  Insert-Reihenfolge eine Aktien-Tagesrendite von `10000` statt `1000` bps.

Damit sind globale FX-Modellbasis, Live-Rebalancing und kundenwirksame
Backtestzahlen nicht durchgehend atomar, chronologisch plausibel und
deterministisch belegt.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `FX-REF-001` | P1 | offen | Der globale Current-FX-Satz wird vor und nach Integerquantisierung strikt validiert, besitzt pro Währung höchstens eine Current-Zeile und wird von Modell- und Reportingpfaden identisch fail-closed konsumiert |
| `PRICE-TIME-001` | P1 | offen | Jeder Produktpreis besitzt ein geprüftes ISO-Handelsdatum innerhalb eines zulässigen Zeitfensters; zukünftige oder malformed Daten werden vor Persistenz und Bewertung verworfen |
| `MD-SOURCE-001` | P1 | offen | Für jeden Backtest-Stichtag existiert eine eindeutige, versionierte Preis-/FX-Quelle oder ein expliziter Snapshot; gleichrangige Quellenkonflikte sind Domainfehler und niemals von Insert- oder Queryreihenfolge abhängig |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| FX-Payload nutzt koerziven Float | `5eyes-backend/routers/fx_rates.py:31-39` |
| FX-Checks laufen vor Quantisierung | `5eyes-backend/routers/fx_rates.py:101-122` |
| Quantisierung kann einen geprüften Wert zu null machen | `5eyes-backend/routers/fx_rates.py:143-151` |
| FX-Tabelle ohne Current-Unique-/Range-CHECK | `5eyes-backend/models/fx_rate.py:12-34` |
| Modell-Loader blockiert null/duplicate Current-FX | `5eyes-backend/services/currency/fx_rates.py:164-236` |
| Legacy-/Reporting-Loader überspringt ungültige Zeilen und fällt auf Defaults | `5eyes-backend/services/currency/fx_rates.py:244-277` |
| PriceHistory erlaubt positive Werte ohne Datums-/Währungsprüfung | `5eyes-backend/price_updater.py:515-554` |
| Stooq-Fallback übernimmt Datum als ungeprüften String | `5eyes-backend/price_updater.py:207-228` |
| Future-Datum gilt wegen `age_days <= threshold` als frisch | `5eyes-backend/price_updater.py:643-675` |
| Live-Rebalancing verwendet dieselbe Freshness-Logik | `5eyes-backend/services/portfolio_engine_live_rebalancing.py:379-403` |
| Preis-/FX-Unique enthält bewusst `source` | `5eyes-backend/models/snapshots.py:53-104` |
| Backfill und Daily Refresh schreiben verschiedene Source-Namen | `5eyes-backend/services/market_data/asset_class_price_backfill.py:87-157`; `5eyes-backend/services/market_data_daily_refresh.py:162-245` |
| Backtest sortiert nur nach Datum und überschreibt pro Datum im Dict | `5eyes-backend/services/backtest_strategy.py:560-690` |

## `FX-REF-001` – Der Schreibvertrag kann die globale Modellbasis ungültig machen

### Ist-Zustand

`FXRateEntry.rate` ist ein normaler Pydantic-`float`. Dadurch wird `true` zu
`1.0` koerziert. Der Router prüft anschließend nur `> 0`, `<= 1000` und für
CHF die Identität. Erst beim Erzeugen der Datenbankzeile wird mit
`round(rate * 10000)` quantisiert.

Damit kann ein vor der Quantisierung positiver Wert nach der Quantisierung null
sein. Der Request gilt dennoch als Erfolg, der globale alte Kurs wurde bereits
archiviert und die neue Nullzeile wird `is_current=1`.

Der produktive Solverpfad erkennt die Nullzeile korrekt als
`FXRateLoadError`. Das schützt vor einer falschen Allokation, erzeugt aber eine
systemweite Modellblockade durch einen zuvor mit HTTP 200 akzeptierten Wert.
Andere Consumer verwenden noch `FXRateSource.from_db()`: Dort werden ungültige
aktive Zeilen übersprungen und fehlende Währungen aus dem versionierten
Defaultset ergänzt. Derselbe DB-Stand hat somit zwei effektive FX-Wahrheiten.

Die Tabelle besitzt außerdem weder einen Range-/Bool-CHECK noch einen
Partial-Unique-Index für `(currency) WHERE is_current=1 AND valid_until IS
NULL`. `FOR UPDATE` sperrt beim ersten parallelen Insert keine nicht existente
Zeile. Die Serviceprüfung auf Duplikate ist Defense-in-depth, aber keine
atomare Current-Garantie.

### Ausgeführte HTTP-/Loader-Reproduktion

Mit isolierter SQLite-Datenbank und echtem FastAPI-Router wurden zwei Requests
ausgeführt:

```text
PUT /fx-rates  {"currency":"USD","rate":true}
=> HTTP 200, persisted USD rate_x10000=10000

PUT /fx-rates  {"currency":"JPY","rate":0.00001}
=> HTTP 200, response rate=0.0, persisted JPY rate_x10000=0

FXRateSource.from_db_for_model(...)
=> FXRateLoadError: Eine aktive FX-Rate ist ungueltig
```

Bereits die reine Schema-Probe akzeptierte `True`, `0.00001` und `NaN` als
Float. Ein zusätzlicher echter Request mit JSON-Token `NaN` erreichte die
Quantisierung und antwortete HTTP 500 (`cannot convert float NaN to integer`)
statt mit einer stabilen 422-Domainantwort.

### Risiko

- Ein erfolgreicher globaler Admin-/Advisor-Write kann sämtliche neuen
  stochastischen Allokationen blockieren.
- Legacy-Reporting kann im gleichen Zustand mit Default-JPY weiterrechnen,
  während der Solver blockiert. Modell- und Kundenerklärung driften.
- Bool- und Non-Finite-Koerzion widerspricht der fachlichen Kursdomain.
- Parallele Erstwrites können ohne DB-Eindeutigkeit zwei Current-Zeilen
  hinterlassen; anschließend ist die effektive Modellbasis mehrdeutig.

## `PRICE-TIME-001` – Zukünftige Preise gelten unbegrenzt als frisch

### Ist-Zustand

`PricePoint` ist eine ungeprüfte Dataclass. `upsert_price_history()` schützt
nur gegen nichtpositive Kurse. Es prüft weder ISO-Datum, Zukunft, maximalen
Lookback, Currency, Source noch die Chronologie zum Fetchzeitpunkt.

Der standardmäßig konfigurierte Stooq-Fallback übernimmt `price_date` direkt
aus CSV als String. `latest_price_snapshot()` sortiert lexikografisch
absteigend. Die Qualitätsbewertung berechnet `today - price_date` und wertet
jeden Wert `<= stale_after_days` als frisch. Ein Future-Datum hat ein negatives
Alter und bleibt daher bis zu diesem Datum frisch.

Live-Rebalancing verwendet dieselbe Bedingung. Der Future-Kurs kann dadurch
Marktwert, IST-Gewicht, Buy-/Sell-Betrag, Preisänderung und Freshness-Ampel
beeinflussen.

### Ausgeführte Service-Reproduktion

```text
upsert_price_history(
  price_date='2099-12-31',
  price_rappen=987654,
  currency='CHF',
  source='stooq'
)
=> inserted

latest_price_snapshot => 2099-12-31 / 987654
computed_age_days      => -26789
summarize_price_quality:
  fresh_products_count=1
  stale_products_count=0
  fresh_coverage_pct=100
```

Der Fehler ist kein bloßes UI-Label: Die als Latest ausgewählte Zeile wird in
die produktive Live-Rebalancing-Berechnung weitergereicht.

## `MD-SOURCE-001` – Daily-Backtest hängt von Insert-Reihenfolge ab

### Ist-Zustand

Die Unique-Constraints der Tabellen
`asset_class_price_history` und `asset_class_fx_history` enthalten jeweils
`source`. Das ist fachlich nachvollziehbar, weil Backfill und Daily Refresh
unterschiedliche Quellen parallel speichern dürfen.

Der Reader löst diese Mehrfachquellen jedoch nicht auf:

- Preiszeilen werden nur nach `price_date` geordnet und anschließend in
  `by_class[bucket][date]` geschrieben;
- FX-Zeilen werden ebenfalls nur nach `price_date` geordnet und in
  `rate_by_date[date]` geschrieben;
- die zuletzt iterierte gleichdatierte Zeile gewinnt;
- es gibt weder Providerpriorität noch As-of-Snapshot, Quality-Status,
  ConflictError oder Hashbindung.

SQL garantiert für Zeilen mit gleichem Sortierschlüssel keine stabile
Reihenfolge. Ein Restore, Reimport, anderer Queryplan oder paralleler Provider
kann deshalb die publizierte Historie ändern, ohne dass sich der logische
Zeilensatz ändert.

### Ausgeführte Determinismus-Reproduktion

Für alle fünf Buckets wurden identische Kurse an zwei Tagen gespeichert. Nur
für `Aktien/2026-08-26` existierten zwei zulässige Quellen:

```text
provider-a: close_rappen=11000
provider-b: close_rappen=20000
```

Mit demselben logischen Datensatz, aber umgekehrter Insert-Reihenfolge ergab
`load_daily_returns_series()`:

```text
insert a, dann b => equities return_bps = 10000
insert b, dann a => equities return_bps = 1000
```

Das entspricht `+100 %` gegenüber `+10 %` für denselben Tag. Beide Läufe
meldeten vollständige Daten und keinen FX-Warnzustand.

### Risiko

- Backtestpfade, Drawdowns, CAGR, Volatilität und Vergleichsbenchmarks sind
  ohne expliziten Source-Snapshot nicht reproduzierbar.
- Eine neue Providerzeile kann historische Kundenunterlagen rückwirkend
  verändern, obwohl keine bestehende Zeile editiert wurde.
- Gleiches gilt für tägliche FX-Reihen und damit für die CHF-Umrechnung.
- Die aktuelle Warnung für ganz fehlende FX-Daten erkennt Quellenkonflikte
  nicht; ein plausibel wirkender vollständiger Datensatz kann mehrdeutig sein.

## Verbindlicher Fixvertrag

### FX-Schreib- und Current-Vertrag

1. `rate` wird vor Pydantic-Koerzion strikt geprüft: exakte Zahl, kein Bool,
   finite und in der fachlichen Range.
2. Die quantisierte Ganzzahl ist der kanonische Wert. Erst
   `rate_x10000 = round(rate * 10000)` berechnen, dann `1..10_000_000` und CHF
   exakt `10000` validieren. Response und Auditlog werden aus diesem Integer
   abgeleitet.
3. Der vollständige Batch wird vor jeder Mutation validiert; Currency-Codes
   sind kanonisch, im Request eindeutig und fachlich erlaubt. Ein Fehler lässt
   alle alten Current-Zeilen unverändert.
4. Additiver Partial-Unique-Index und DB-CHECKs sichern Current-Eindeutigkeit,
   `is_current` 0/1, positive Range und die CHF-Identität in SQLite und
   PostgreSQL. Altbestände werden vor Migration inventarisiert; Duplikate oder
   Nullkurse werden nicht willkürlich ausgewählt.
5. Rollover behandelt den leeren Slot und Konkurrenz atomar. Ein
   Unique-/CAS-Verlierer erhält 409 oder einen kontrollierten Retry, niemals
   500 oder zwei Current-Zeilen.
6. Alle kunden- und modellwirksamen Consumer verwenden einen gemeinsamen
   strikten Loader. Defaults sind nur bei nachweislich leerem, versioniertem
   Bootstrapzustand zulässig, nicht als Ersatz für vorhandene ungültige Daten.

### Produktpreis-Zeitvertrag

7. Ein zentraler `PricePoint`-Validator prüft Preis, ISO-Currency, Source,
   ISO-Kalenderdatum und `price_date <= authoritative_as_of_date`. Eine kleine
   explizite Markt-/Timezone-Toleranz darf dokumentiert werden; `2099` niemals.
8. Provideradapter validieren ihren `get_eod`-Vertrag, und
   `upsert_price_history()` wiederholt die Prüfung als letzte
   Persistenzgrenze. Raw-/Legacyzeilen werden beim Lesen ebenfalls geprüft.
9. Malformed oder zukünftige Zeilen sind keine Latest-Kandidaten und dürfen
   weder `fresh` noch `priced` zählen. Kundenwirksames Rebalancing blockiert
   bei einer ungültigen tatsächlich benötigten Preiszeile fail-closed.
10. DB-CHECKs sichern mindestens positiven Preis und kanonische 0/1-Felder;
    komplexe Datums-/Source-Semantik bleibt im gemeinsamen Servicevalidator.

### Provider-Snapshot und Backtest

11. Für einen Backtestlauf wird vor Berechnung genau ein versionierter
    Preis-/FX-Snapshot beziehungsweise eine explizite Providerpriorität mit
    Stichtag aufgelöst. Der Lauf persistiert Snapshot-ID, Source-Set, As-of und
    Hash in seiner Modellbasis.
12. Mehrere gleichrangige Zeilen für denselben logischen
    `(asset_class, sub_asset_class, date)`- beziehungsweise
    `(currency, date)`-Key lösen einen Domainkonflikt aus. Insert-Reihenfolge
    und lexikografische ID dürfen keine Semantik tragen.
13. Ein Source-Fallback wird beim Write oder Snapshot-Build entschieden, nicht
    implizit beim Dict-Overwrite. Gewählte und verworfene Quelle sowie
    Quality-Reason werden auditierbar gespeichert.
14. Kunden-PDF/-Portal verwendet nur den an die Recommendation-/Publication-
    Basis gebundenen Backtest. Ein späterer Market-Data-Refresh verändert ein
    finalisiertes Dokument nicht still.

## Verbindliche Testmatrix

### FX API, Loader und Datenbank

- Bool, Stringzahl, NaN, Infinity, null, null/negative/sub-quantum und
  overrange werden mit 422 abgelehnt; alte Current-Zeile und Auditlog bleiben
  unverändert.
- Randwerte werden nach Integerquantisierung getestet; CHF ist exakt 10000.
- Duplicate Currency im Batch und duplicate Raw-Current-Zeilen scheitern
  deterministisch.
- Zwei parallele Erstwrites und zwei parallele Rollover liefern genau eine
  Current-Zeile; der Verlierer erhält einen stabilen 409/Retry-Vertrag.
- Modell, Advisory, Cashflow, Live-Rebalancing und PDF sehen dieselbe
  `basis_id` und dieselben effektiven Kurse oder denselben Domainfehler.
- SQLite- und echte PostgreSQL-Migration prüfen CHECKs, Partial-Unique,
  Upgrade, Altbestandskonflikt und Rollbackstrategie.

### Preiszeit und Freshness

- Malformed Datum, Future-Datum, falscher Currency-Code, Bool-/Non-Integer-
  Preis, null/negativer Preis und leere Source scheitern im Provideradapter,
  Persistenzhelper und Raw-Reader.
- `today`, letzter Handelstag und dokumentierte Timezone-Grenzen werden als
  gültig getestet; `today + tolerance + 1` wird abgelehnt.
- Ein Future-/malformed Raw-Row kann weder Latest noch Freshness-Coverage noch
  Buy-/Sell-Betrag beeinflussen; bei benötigter Zeile endet der
  kundenwirksame Pfad mit 409 vor Renderer.
- Provider liefert Fehler nach bestehendem validen Preis: der valide Preis
  bleibt erhalten, Error-/Freshnessstatus ist sichtbar und auditierbar.

### Source-Determinismus und Publikation

- Derselbe logische Preis-/FX-Zeilensatz in jeder Insert-Reihenfolge erzeugt
  bitgenau denselben Snapshot, Hash und Backtest.
- Zwei gleichrangige Quellen mit abweichendem Wert scheitern vor Berechnung;
  eine explizit priorisierte Quelle gewinnt unabhängig von ID/Insert-Reihenfolge.
- Preis- und FX-Quelle werden gemeinsam gebunden; fehlende FX für eine
  tatsächlich fremdwährungsnotierte Serie folgt dem expliziten
  Preview-/Final-Vertrag und wird nicht still als CHF gerechnet.
- Änderung oder Nachlieferung historischer Marktdaten nach Finalisierung
  erzeugt einen neuen Snapshot beziehungsweise sichtbare Drift; bestehende
  Publikation bleibt unverändert.
- Advisor-Preview, Kundenportal und PDF zeigen Source, As-of, Datenqualität und
  Snapshot-Hash konsistent.

## Empfohlene Umsetzungsreihenfolge

1. FX-Quantisierung als kanonische Domain definieren und Batch-Prevalidation
   vor den ersten Write ziehen.
2. FX-CHECKs, Current-Unique und konfliktfesten Rollover additiv migrieren.
3. Strict-Loader für alle Modell-/Reportingconsumer vereinheitlichen.
4. Produktpreis-Zeit-/Currency-/Source-Validator in Adapter, Persistenz und
   Runtime einführen.
5. Versionierten Market-Data-Snapshot mit expliziter Source-Priorität bauen
   und Daily-Backtest daran binden.
6. Publikationskontext um Backtest-/Marktdatenbasis erweitern; Altbestände
   inventarisieren.
7. API-, Raw-, Parallel-, Determinismus-, SQLite-, echte PostgreSQL- und
   Kundenpublikationstests ausführen.

## Definition of Done

Die drei Findings gelten erst als geschlossen, wenn gleichzeitig:

- kein akzeptierter FX-Payload nach Quantisierung ungültig werden kann;
- pro Währung atomar höchstens eine Current-FX-Zeile existiert;
- alle Consumer dieselbe strikte FX-Basis verwenden;
- zukünftige oder malformed Preise weder persistiert noch als Latest/Fresh
  verwendet werden;
- jeder Backtest exakt einen versionierten Preis-/FX-Snapshot bindet;
- gleichrangige Quellenkonflikte fail-closed statt per Reihenfolge enden;
- finalisierte Kundenstände durch spätere Marktdaten nicht still umgeschrieben
  werden;
- API-, Raw-, Parallel-, Determinismus-, Consumer- und echte PostgreSQL-Tests
  grün sind;
- der vollständige Backend-/Frontend-Gate auf dem Fixcommit erneut grün ist;
  und
- dieser Audit mit Fixcommit, Migration, Testzahlen und Restpunkten
  aktualisiert oder durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an FX, Preisen, Backtest, Live-Rebalancing oder Marktdaten:

1. Diesen Audit vollständig lesen.
2. `FX-REF-001`, `PRICE-TIME-001`, `MD-SOURCE-001` sowie den zentralen
   Advisory-Publikationskontext gemeinsam behandeln.
3. Validierung immer auf dem quantisierten FX-Integer wiederholen.
4. Vor Batchmutation den gesamten Payload prüfen.
5. Vorhandene ungültige Daten nie als fehlend oder Default umdeuten.
6. Future-Daten nie über negatives Alter als frisch klassifizieren.
7. Source-Priorität oder Snapshot explizit machen; nie Dict-Overwrite als
   Resolver verwenden.
8. Keine kundenwirksame Backtestzahl ohne gebundene Source-/As-of-Evidence.
9. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline- und Audit-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Der fokussierte bestehende FX-/Preis-/Backtestring auf dem auditierten Head
ergab:

```text
141 passed, 1 skipped, 61 warnings in 44.92s
```

Diese grünen Positivtests widerlegen die Findings nicht. Sie enthalten weder
den erfolgreichen sub-quantum-FX-Write noch den Future-Price-Freshness-Fall
noch den Backtest mit demselben Multi-Source-Zeilensatz in umgekehrter
Insert-Reihenfolge.
