---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-portfolio-handoff-trade-instruction-execution-evidence-integrity-followup-audit"
status_as_of: "2026-09-03"
audit_started_on: "2026-09-03"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "57da24112132ec2e16c74488f22517b63da2d91f"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md"
prior_release_audit_commit: "57da24112132ec2e16c74488f22517b63da2d91f"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md"
audit_mode: "read_only_static_router_service_orm_schema_migration_html_test_review_deterministic_runtime_reproduction_existing_focused_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "portfolio handoff creation and lifecycle, recommendation and mandate context, holdings valuation and trade arithmetic, external instruction sufficiency, delivery and execution evidence, idempotency, concurrency, tamper detection, retention, API and HTML publication contract"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_backend_service_router_schema_tests_passed: 52
focused_frontend_monolith_contract_tests_passed: 7
focused_combined_tests_passed: 59
focused_combined_tests_failed: 0
required_next_action: "replace self-attested handoff rows with an immutable idempotent execution-instruction snapshot bound to one active mandate one approved Final run one complete holdings valuation and one exact payload hash; add delivery receipts fill evidence database state invariants atomic CAS transitions retention/legal-hold rules and API/UI/PDF parity before any real handoff or execution claim"
---

# Portfolio-Handoff-/Handelsinstruktions-/Ausführungsnachweis-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die dreiundzwanzigste Read-only-
Kontrollrunde. Er wurde gegen den unveränderten Repository-Head `57da241`
durchgeführt und am 3. September 2026 konsolidiert. Produktcode und Tests
blieben unverändert.

Er ergänzt, ersetzt und schließt insbesondere nicht:

1. den unmittelbar vorherigen
   [Depot-/IST-Bestand-/Bewertungs-/SOLL-Vergleichs-Integritätsaudit](2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md),
2. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
3. den grundlegenden
   [Post-Commit-Integritätsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
4. den
   [Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit](2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md),
5. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
6. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
7. den
   [Ex-ante-Kosten-/Retrozessions-/Konfliktnachweis-Integritätsaudit](2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md),
8. sowie den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Laufzeitbelege
zuerst, danach dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu `REC-003`, `REC-005` und `REP-004`

Die Audits vom 25. August hatten bereits festgestellt:

- `REC-003`: provisorische Empfehlungen können Final/Handoff werden;
- `REC-005`: Handoff-Endzustände sind ohne CAS last-write-wins;
- `REP-004`: Handoff und andere Consumer besitzen keinen gemeinsamen
  Publikationskontext.

Diese Befunde sind **weiterhin offen**. Kontrollrunde 23 bestätigt sie auf dem
heutigen Head erneut und erweitert sie um bislang nicht vollständig
dokumentierte Verträge: Der Create-Aufruf behauptet Versand ohne Transport,
identische Requests erzeugen doppelte Instruktionen, Zielwerte können als
Bestand dienen, sichtbare SOLL-/Delta-Werte reconciliieren nicht, das HTML
verwechselt Action-Label und Action-Code, ein leerer Request behauptet
Ausführung, der Snapshot ist nicht manipulationsgeschützt und die dokumentierte
Retentionsemantik widerspricht dem tatsächlichen Foreign Key.

## Kurzurteil

**Release und reale Portfolio-Weiterleitung bleiben hart blockiert.** Das
vorhandene `PortfolioHandoff` ist kein belastbarer Nachweis, dass eine
eindeutige Handelsinstruktion an eine konkrete Ausführungsstelle übermittelt,
angenommen oder ausgeführt wurde.

Der Create-Endpoint erzeugt lediglich eine Datenbankzeile und setzt deren
Status unmittelbar auf `Gesendet`. Es gibt keinen Mail-, API-, Datei- oder
Custodian-Transport, keine Empfänger-ID, keine Message-ID, keine Quittung und
keinen Payload-Hash. `recipient_channel` ist optional. Trotzdem meldet die UI
„Handelsliste an Asset Management weitergeleitet“.

Der Endpunkt akzeptiert jeden mandateigenen RecommendationRun unabhängig von
`Draft`, `Final` oder `Superseded` und prüft nicht, ob das Mandat noch aktiv
ist. Er verlangt weder den bindenden Advisory-/Signaturstand noch Suitability-,
Kosten-, Konflikt- oder Kundenfreigabeevidenz. Bei Legacy-Runs ohne Anker kann
der Payloadpfad sogar Current-RA, Current-TA oder Current-CMA ergänzen.

Die Handelszeilen sind ebenfalls nicht ausführungsfest. In der
Laufzeitreproduktion wurden ohne eine einzige echte Holding aus
`implied_from_target` ein Verkauf von 250.000 Rappen und ein Kauf von 250.000
Rappen erzeugt. Der Handoff entfernte genau die Felder, die diese künstliche
Bewertungsbasis sichtbar gemacht hätten. Er speichert außerdem weder ISIN noch
Menge, Depotkonto, Mandatswährung, Preis-/FX-Anker, Ordertyp oder Limit.

Zwei weitere Fehler verfälschen die sichtbare Handelsliste:

- `rebalance_amount_rappen` wird gegen das heutige Live-Total berechnet,
  `target_amount_rappen` bleibt aber der alte Run-Betrag. Im Beleg ergaben
  `1.000.000 IST + (-250.000 Delta) = 750.000`, während als SOLL `500.000`
  angezeigt wurde.
- Produktion liefert `rebalance_action="Aufbauen"/"Reduzieren"` und daneben
  `rebalance_action_code="BUY"/"SELL"`. Das HTML summiert und färbt jedoch
  anhand des Label-Felds gegen `BUY`/`SELL`. Daher zeigte dieselbe Liste Kauf-
  und Verkaufsvolumen jeweils als null.

Ein identischer Create-Request erzeugte zwei verschiedene offene Handoffs.
Ein Execute-Request mit leerem Body setzte einen davon auf `Ausgeführt`.
Zwei Sessions mit bereits gelesenem Status `Gesendet` konnten anschließend
Execute und Cancel beide erfolgreich committen; gespeichert blieb
`Storniert` mit gleichzeitig gesetztem Execute- und Cancel-Zeitpunkt sowie
zwei erfolgreichen Auditzeilen.

Die behauptete Unveränderlichkeit besteht nur darin, dass kein normaler
Update-Endpoint angeboten wird. Es gibt keinen Snapshot-Hash und keine
Datenbankconstraints. Eine direkte Änderung zu `status="BROKEN"`,
`trade_list_snapshot_json="not-json"` und `position_count=999` passierte das
Response-Schema; der Auditlog blieb unverändert. Schließlich blockierte der
RecommendationRun-Cleanup bei aktivierten Foreign Keys mit `IntegrityError`,
obwohl der Model-Kommentar behauptet, der Handoff verliere dabei lediglich die
nullable Run-Referenz.

Die 59 fokussierten Tests blieben grün. Das ist kein Gegenbeweis: Die
Handoff-Tests monkeypatchen den vollständigen Enginepfad, ihre Fixture setzt
Action-Label und Action-Code fälschlich beide auf `BUY/SELL`, die sieben
Frontendtests prüfen nur Quelltextstrings, und weder Draft/Superseded,
Idempotenz, echte Delivery, Fill-Evidence, Raw-Tamper, FK-Retention noch
PostgreSQL-Concurrency werden negativ getestet.

## Stabiles Findings-Register

| ID | Prio | Status | Releasewirkung |
|---|---:|---|---|
| `HANDOFF-CONTEXT-001` | P1 | bestätigt | Draft, Superseded, alte/Legacy-Runs und nicht aktive Mandate können Handoff-Basis werden; Freigabe-/Signatur-/Suitability-/Kostenanker fehlen. |
| `HANDOFF-DELIVERY-001` | P1 | bestätigt | Ein lokaler DB-Insert wird ohne Transport, Empfängeridentität, Payload-Hash oder Empfangsquittung als `Gesendet` und „weitergeleitet“ behauptet. |
| `HANDOFF-VALUATION-001` | P1 | bestätigt | Target-implied, stale, missing oder partial Holdings-/Preis-/FX-Evidence kann Trades erzeugen; der kuratierte Snapshot entfernt Valuation-Basis und Coverage. |
| `HANDOFF-MATH-001` | P1 | bestätigt | Sichtbarer SOLL-Betrag stammt aus dem Run, Delta aus dem heutigen Live-Total; `IST + Delta = SOLL` gilt nicht und das tatsächlich verwendete Live-SOLL fehlt. |
| `HANDOFF-UI-CONTRACT-001` | P1 | bestätigt | Backend liefert lokalisierte Action-Labels plus separaten Code; HTML wertet das Label als Code aus und kann Kauf-/Verkaufsvolumen als null anzeigen. |
| `HANDOFF-INSTRUCTION-001` | P1 | bestätigt | Snapshot identifiziert weder handelbares Instrument, Menge, Konto, Mandatswährung noch Preis-/FX-/Orderbedingungen ausreichend für eindeutige externe Ausführung. |
| `HANDOFF-IDEMPOTENCY-001` | P1 | bestätigt | Create besitzt weder Idempotency-Key noch fachlichen Unique-Key; Retry/Doppelklick erzeugt mehrere offene Instruktionen. |
| `HANDOFF-EXECUTION-001` | P1 | bestätigt | Ein leerer Body genügt für `Ausgeführt`; externe Order-/Fill-/Partial-/Reject-/Settlement-Evidence und Vier-Augen-Freigabe fehlen. |
| `HANDOFF-STATE-001` | P1 | bestätigt | `REC-005` bleibt offen: Statuswechsel sind read-then-write ohne Lock/CAS; DB-State-Invarianten fehlen und widersprüchliche Endfelder sind erreichbar. |
| `HANDOFF-INTEGRITY-001` | P1 | bestätigt | Snapshot und Provenienz sind weder gehasht noch append-only oder schema-/DB-validiert; der Auditlog bindet nur eine Kurzbeschreibung, nicht den Inhalt. |
| `HANDOFF-RETENTION-001` | P1 | bestätigt | Nullable Run-FK besitzt kein `ON DELETE SET NULL`; Cleanup berücksichtigt Handoffs nicht und scheitert unter echten Foreign Keys oder hinterlässt bei schwachen SQLite-Setups Orphans. |

Keines dieser Findings hebt ältere Blocker auf. Ein P1 in Instruktionscontext,
Bewertung, Delivery, Ausführung, Statusintegrität oder Nachweisführung blockiert
reale Weiterleitung und jede Behauptung eines ausgeführten Kundentrades.

## Tatsächlicher Daten- und Zustandsfluss

```text
Berater öffnet Handelsliste
  |
  +-- strategyState.recommendation.live_rebalancing.position_drifts
  |     +-- Action ist lokalisiertes Label; Action-Code liegt separat
  |     +-- SOLL-Betrag ist persistierter Run-Betrag
  |     \-- Delta ist gegen heutiges Live-Total neu gerechnet
  |
  +-- HTML filtert > 0,5 % des Live-Totals
  |     \-- summiert/färbt Label irrtümlich als BUY/SELL-Code
  |
  \-- POST /recommendations/{beliebiger run_id}/portfolio-handoffs
        |
        +-- nur mandate_type == Vermögensverwaltung
        +-- kein Mandatsstatus-/Final-/Approval-/Signatur-Gate
        +-- Enginepayload wird mit Live-Holdings/Preisen/FX neu gebaut
        +-- Valuation-/Coverage-Felder werden aus Snapshot entfernt
        +-- kein Transport wird ausgeführt
        \-- DB-Zeile erhält sofort status = Gesendet

Gesendet
  +-- POST mark-executed {} -> Ausgeführt
  \-- POST cancel {reason} -> Storniert

Beide Endtransitionen:
  read status -> Python-Check -> ORM-Write -> AuditLog -> commit
  kein row lock / kein UPDATE ... WHERE status='Gesendet' / keine version

separat:
RecommendationRun-Cleanup
  -> löscht Positionen und Run
  -> kennt PortfolioHandoff nicht
  -> FK ohne ON DELETE SET NULL blockiert Commit
```

Es gibt keinen unveränderlichen gemeinsamen Vertrag aus
`holdings_snapshot_hash`, `instruction_payload_hash`, `delivery_receipt`,
`execution_fill_set`, `state_version` und `legal_hold`.

## Codeanker auf dem auditierten Head

| Bereich | Anker | Beobachtung |
|---|---|---|
| Run-/Handoff-Lookup | `5eyes-backend/routers/portfolio_handoff.py:47-72` | Prüft nur Mandatszugehörigkeit, keinen Run-Status oder Publikationscontext. |
| Create | `5eyes-backend/routers/portfolio_handoff.py:89-160` | Prüft nur Mandatstyp, setzt ohne Transport sofort `Gesendet`, loggt nur Anzahl und Empfängername. |
| Execute/Cancel | `5eyes-backend/routers/portfolio_handoff.py:162-243` | Read-then-write ohne Lock/CAS; Execute-Note optional. |
| Snapshotfelder | `5eyes-backend/services/portfolio_handoff.py:18-38` | Kuratierte Liste entfernt Holding-, Preis-, FX-, Coverage- und Instrumentdetails. |
| Schwelle/Snapshot | `5eyes-backend/services/portfolio_handoff.py:41-77` | Filtert nur Betragsschwelle; kein Evidence-/Publication-ready-Gate. |
| Handoff-Modell | `5eyes-backend/models/portfolio_handoff.py:12-36`, `42-81` | Behauptet Unveränderlichkeit/nullable Cleanup, besitzt aber keinen Hash, State-Version oder Constraint. |
| API-Schema | `5eyes-backend/schemas/portfolio_handoff.py:8-63` | Snapshot bleibt unvalidierter String; Status ist freier String; Execute-Body darf leer sein. |
| Alembic | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:1234-1262` | Nur Spalten/FKs/Index; keine Status-/Kohärenz-/Hash-/Idempotenzconstraints und kein `ON DELETE SET NULL`. |
| Run-Rebuild | `5eyes-backend/services/portfolio_engine.py:6167-6294` | Legacy-Fallbacks auf Current-TA/RA/CMA; Live-Bewertung wird zum Handoff-Zeitpunkt neu aufgelöst. |
| Implied Holding | `5eyes-backend/services/portfolio_engine_live_rebalancing.py:315-460` | Ohne Holding werden Units und Current Market Value aus Target/Referenzpreis abgeleitet. |
| Live-SOLL/Delta | `5eyes-backend/services/portfolio_engine_live_rebalancing.py:520-542` | Delta nutzt `live_total * target_weight`; `target_amount_rappen` im Entry wird nicht ersetzt. |
| Action-Vertrag | `5eyes-backend/services/portfolio_engine_live_rebalancing.py:220-229`, `528-541` | Liefert Code und lokalisiertes Label, setzt `rebalance_action` auf das Label. |
| Coverage | `5eyes-backend/services/portfolio_engine_live_rebalancing.py:560-675` | Kennt missing/stale/implied counts, Handoff ignoriert sie. |
| Handelslisten-HTML | `5eyes-electron/frontend/5eyes_v2.html:21166-21237` | Summiert/färbt `rebalance_action` als BUY/SELL und formatiert alle Beträge hart als CHF. |
| Handoff-HTML | `5eyes-electron/frontend/5eyes_v2.html:21239-21363` | Behauptet echten Versand, akzeptiert freien Empfänger/Kanal und führt Execute mit `{}` aus. |
| Handoff-Fixture | `5eyes-backend/tests/test_portfolio_handoff.py:117-131` | Setzt Label und Code beide auf BUY/SELL und bildet Produktionspayload nicht nach. |
| Handoff-Tests | `5eyes-backend/tests/test_portfolio_handoff.py:142-377` | Engine monkeypatched; nur sequentielle Happy-/Basic-Negativpfade. |
| Frontendtests | `5eyes-backend/tests/test_frontend_portfolio_handoff.py:20-102` | Prüfen Funktions-/Stringvorkommen, keine DOM-/Payload-/Summen-Semantik. |
| Cleanup | `5eyes-backend/services/recommendation_run_cleanup.py:119-181` | Löscht Positions und Runs, aber keine Holdings/Handoffs und nullt keine Referenzen. |
| Auditlog-Hash | `5eyes-backend/services/audit.py:8-121` | Hasht Auditzeilenfelder; Create-Log enthält den Handoff-Snapshot/Hash nicht. |
| Mandatszugriff | `5eyes-backend/services/auth.py:376-393` | Filtert soft-deleted und Zugriff, aber nicht Mandatsstatus. |

## `HANDOFF-CONTEXT-001` – Nicht freigegebene Zustände werden ausführungsnah

### Beobachtung

`create_portfolio_handoff` verlangt lediglich ein sichtbares Mandat vom Typ
`Vermögensverwaltung` und irgendeinen mandateigenen Run. Es fehlt insbesondere:

- `run.result_status == "Final"`;
- Ausschluss `Superseded`;
- `mandate.status == "Aktiv"`;
- gebundener, aktueller und nichtprovisorischer Run-/TA-/RA-/Policy-/CMA-
  Context;
- gebundene Suitability-, Advisory-, Kosten-/Konflikt- und Signaturfreigabe;
- Legal-/Compliance-Hold bei noch offenen Blockern.

`build_recommendation_payload_from_run` validiert einzelne moderne Anker, aber
nicht den Run-Status. Fehlen einem Legacy-Run TA, RA oder CMA, werden Current-
Werte ergänzt. Damit bezeichnet `recommendation_run_id` nicht zwingend den
vollständigen Entscheidungscontext der gesendeten Trades.

### Reproduktion

Ein archiviertes Vermögensverwaltungsmandat enthielt einen Draft und einen
Superseded-Run. Mit identischem serverseitigen Trade-Payload wurden beide
Create-Aufrufe akzeptiert:

```json
{
  "mandate_status": "Archiviert",
  "accepted_run_statuses": ["Draft", "Superseded"],
  "draft_handoff_created": true,
  "superseded_handoff_status": "Gesendet"
}
```

Der reproduzierte Routerpfad war derselbe wie in den vorhandenen Tests; nur
der teure Enginebuilder wurde deterministisch ersetzt. Genau an dieser Grenze
müsste der Statusvertrag serverseitig greifen, tut es aber nicht.

### Fixvertrag

1. Handoff referenziert ausschließlich den exakt wirksamen, nicht
   supersedierten Final-Run eines aktiven Mandats.
2. Run, TA, RA, Policy, CMA, Produktuniversum und Holdings-Valuation sind über
   IDs und Hashes geschlossen.
3. Provisorische, stale, missing oder driftende Evidence blockiert.
4. Suitability, Advisory-Beschluss, Kosten-/Konfliktoffenlegung und erforderte
   Signaturen werden als konkrete Evidence-IDs/Hashes geprüft.
5. Die Validierung und das Einfrieren erfolgen in einer Transaktion mit Lock
   auf Mandat/Final-Run.

## `HANDOFF-DELIVERY-001` – Datenbankeintrag wird als Versand behauptet

Der Endpoint importiert keinen Transportadapter und sendet nichts. Nach der
lokalen Snapshotberechnung wird sofort eine Zeile mit `status="Gesendet"`
angelegt. `recipient_channel` darf `None` sein. Der Auditlog hält lediglich
„N Positionen an 'Name'“ fest. Das HTML zeigt dennoch „Wird gesendet…“,
„Weitergeleitet“ und einen Success-Toast.

Damit ist nicht unterscheidbar zwischen:

- vorbereitet;
- vom Berater angeblich manuell übermittelt;
- technisch übertragen;
- von der richtigen Gegenstelle empfangen;
- von der Gegenstelle akzeptiert.

### Reproduktion

```json
{
  "recipient_name": "XY",
  "recipient_channel": null,
  "transport_invoked": false,
  "stored_status": "Gesendet"
}
```

### Fixvertrag

- Create erzeugt zunächst `Prepared`, nicht `Sent`.
- Automatischer Transport liefert Adapter, Ziel-ID, Message-/Transfer-ID,
  Payload-Hash, `sent_at`, Fehlerstatus und Empfangsquittung.
- Manueller Transport verlangt ein unveränderliches, hochgeladenes Receipt
  mit Actor, Zeitpunkt, Kanal, Empfänger und Hash des tatsächlich versendeten
  Artefakts.
- UI unterscheidet Prepared, Dispatched, Delivered/Acknowledged und Failed.
- Audittext behauptet nur den technisch oder evidenzgebunden bewiesenen State.

## `HANDOFF-VALUATION-001` – Künstliches Target-IST wird zur Handelsbasis

### Beobachtung

Die Live-Rebalancing-Pipeline setzt ohne echte Holding
`valuation_basis="implied_from_target"`. Sie rekonstruiert Units aus dem
Zielbetrag und Referenzpreis und bewertet diese angenommenen Units zum
aktuellen Preis. Preisbewegungen können deshalb BUY-/SELL-Deltas erzeugen,
obwohl nicht belegt ist, dass der Kunde die Position überhaupt hält.

Der Live-Payload kennt `holding_present`, `valuation_basis`, Holding-as-of,
Preisdatum, Price-Freshness, FX-Konversion sowie missing/stale/implied counts.
`_SNAPSHOT_TRADE_FIELDS` entfernt diese Felder. `snapshot_handoff_trades`
prüft nur, ob Drifts existieren, das Total positiv und der Betrag größer als
0,5 Prozent ist.

### Reproduktion

Zwei Zielpositionen zu je 50 Prozent und 500.000 Rappen hatten **keine**
Holdings. Für Produkt A stieg der Preis von 10.000 auf 20.000 Rappen, Produkt B
blieb bei 10.000:

```json
{
  "live_total_value_rappen": 1500000,
  "source_rows": [
    {
      "product_id": "product-a",
      "holding_present": false,
      "valuation_basis": "implied_from_target",
      "current_market_value_rappen": 1000000,
      "rebalance_action_code": "SELL",
      "rebalance_amount_rappen": -250000
    },
    {
      "product_id": "product-b",
      "holding_present": false,
      "valuation_basis": "implied_from_target",
      "current_market_value_rappen": 500000,
      "rebalance_action_code": "BUY",
      "rebalance_amount_rappen": 250000
    }
  ],
  "handoff_discloses_holding_present": false,
  "handoff_discloses_valuation_basis": false
}
```

Der Handoff würde also einen Verkauf einer nicht nachgewiesenen Position
behaupten und verschweigt, dass die gesamte Current-Basis aus dem Ziel
abgeleitet wurde.

### Fixvertrag

- Nur ein `publication_ready` HoldingsValuationSnapshot aus Runde 22 darf
  Instruktionsbasis sein.
- `implied_from_target`, missing, partial, stale, invalid oder FX-missing
  blockieren reale Trades.
- Coverage muss für Positionen, Marktwert, Preis, FX und Account exakt 100
  Prozent oder nach expliziter Policy ausreichend sein.
- Jede Instruktionszeile referenziert ihre Holding-/Valuation-Evidence.
- Handoff kann einen klar getrennten What-if-Entwurf anzeigen, aber niemals
  als gesendet oder ausführbar markieren.

## `HANDOFF-MATH-001` – SOLL und Delta verwenden verschiedene Geldbasen

`_build_live_position_drifts` berechnet das wirksame Live-Ziel als
`live_total_value_rappen * target_weight_bps`. Das Entry-Feld
`target_amount_rappen` bleibt jedoch der bei Run-Erzeugung gespeicherte Betrag.
Snapshot und HTML zeigen diesen alten Betrag als „SOLL-Wert“ neben dem neuen
Delta.

Die Reproduktion ergab:

```json
[
  {
    "side": "SELL",
    "shown_current": 1000000,
    "shown_target": 500000,
    "shown_delta": -250000,
    "current_plus_delta": 750000
  },
  {
    "side": "BUY",
    "shown_current": 500000,
    "shown_target": 500000,
    "shown_delta": 250000,
    "current_plus_delta": 750000
  }
]
```

Das tatsächlich verwendete Live-SOLL beträgt in beiden Zeilen 750.000, wird
aber nicht publiziert. Die Anzeige ist damit intern nicht reconciliert.

### Fixvertrag

- Separat benannte Felder für `target_amount_at_run_rappen` und
  `execution_target_market_value_rappen`.
- Invariante pro Zeile: `current_market_value + signed_instruction_amount ==
  execution_target_market_value`, innerhalb definierter Rundung.
- Summen-/Cash-Invariante über alle Käufe, Verkäufe, Gebühren und Reserve.
- UI und Export zeigen genau den Betrag, gegen den Delta berechnet wurde.
- Property-/Golden-Tests decken Marktbewegung, Zu-/Abfluss, FX und Rundung ab.

## `HANDOFF-UI-CONTRACT-001` – Action-Label wird als Action-Code ausgewertet

### Beobachtung

Die Produktionsengine setzt:

```text
rebalance_action_code  = BUY | SELL | HOLD | CHECK | MISSING_PRICE
rebalance_action       = Aufbauen | Reduzieren | Im Soll | Beobachten | Preis fehlt
rebalance_action_label = dasselbe lokalisierte Label
```

`openTradeList()` vergleicht hingegen `rebalance_action` mit `BUY` und `SELL`
und nutzt dasselbe Feld für die Farbe. Dadurch werden reale lokalisierte Rows
weder summiert noch korrekt gefärbt.

### Reproduktion

Mit den beiden realen Engine-Labels aus dem vorherigen Beleg:

```json
{
  "ui_total_buy_rappen": 0,
  "ui_total_sell_rappen": 0,
  "actual_by_code": {
    "buy": 250000,
    "sell": -250000
  }
}
```

Die Test-Fixture maskiert den Fehler, weil sie sowohl
`rebalance_action` als auch `rebalance_action_code` auf den Code setzt. Die
sieben Frontendtests führen die Summenlogik nicht aus.

### Fixvertrag

- Fachlogik verwendet ausschließlich `rebalance_action_code` als Enum.
- Darstellung verwendet ausschließlich `rebalance_action_label`.
- Das mehrdeutige Alt-Feld `rebalance_action` wird versioniert entfernt oder
  klar definiert.
- Type-/OpenAPI-Vertrag verwendet Literals/Discriminated Union statt freier
  Strings.
- Browser-/DOM-Test füttert echten Backendpayload und prüft Summe, Farbe,
  Label, Threshold und leere Zustände.

## `HANDOFF-INSTRUCTION-001` – Der Snapshot ist keine eindeutige Handelsinstruktion

Der Handoff speichert interne Product-ID, Namen, Anlageklasse,
Produktwährung, Market Values, Gewichte und Delta. Für eine externe
Ausführungsstelle fehlen mindestens:

- ISIN/FIGI/Ticker plus Börse oder ein anderer vereinbarter Instrument-Key;
- Depot-/Custody-Account und wirtschaftlicher Mandats-/Portfolio-Key;
- Side als kanonischer Code;
- Menge/Units und Rundungs-/Fractional-Share-Regel;
- Mandats-/Abrechnungswährung und klare Währung jedes Betrags;
- Referenz-/Limitpreis, Ordertyp, Gültigkeit und Handelsplatz;
- Preis-/FX-/Valuation-as-of und deren Quellen;
- Cash-/Gebühren-/Tax-/Lot- und Settlement-Behandlung;
- Version/Schema/Hash des eigentlichen Transportartefakts.

Besonders irreführend ist `product_currency`: Die Geldbeträge wurden zuvor in
die Mandatswährung konvertiert, aber der Snapshot speichert diese
Mandatswährung nicht. Das HTML formatiert sämtliche Beträge fest als CHF,
auch wenn das Mandat wie im Reproduktionsfall EUR führt.

### Reproduzierte fehlende Felder

```json
[
  "custody_account_number",
  "fx_rate",
  "holding_as_of_date",
  "isin",
  "latest_price_date",
  "latest_price_rappen",
  "limit_price",
  "mandate_currency",
  "order_type",
  "quantity",
  "units_milli",
  "valuation_basis"
]
```

Ein rein dokumentarischer, manueller Handoff benötigt nicht zwingend eine
Broker-API. Er benötigt aber trotzdem ein eindeutig lesbares und unveränderlich
gebundenes Artefakt, aus dem später exakt hervorgeht, **was** übermittelt wurde.

## `HANDOFF-IDEMPOTENCY-001` – Retry erzeugt doppelte offene Instruktionen

Create akzeptiert keinen Idempotency-Key und die Tabelle besitzt keinen
Unique-Key auf Mandat, Run, Valuation-/Payload-Hash und Empfänger. Zwei
identische Aufrufe erzeugten zwei verschiedene IDs:

```json
{
  "same_mandate": true,
  "same_run": true,
  "same_recipient": true,
  "same_trade_payload": true,
  "handoff_ids_distinct": true,
  "open_rows_created": 2
}
```

Ein Doppelklick, Timeout-Retry oder Proxy-Retry ist damit nicht von zwei
bewusst getrennten Instruktionen zu unterscheiden. Sobald ein echter Transport
angebunden wird, drohen doppelte Orders.

### Fixvertrag

- obligatorischer, tenant-/mandategebundener Idempotency-Key;
- Unique-Constraint und gespeicherter Request-/Instruction-Hash;
- gleicher Key + gleicher Hash liefert dieselbe Ressource;
- gleicher Key + anderer Hash liefert Konflikt;
- bewusstes Resend ist eigene Revision/Aktion mit Referenz auf den Vorgänger;
- parallele Create-Tests auf PostgreSQL.

## `HANDOFF-EXECUTION-001` – Leerer Request behauptet vollständige Ausführung

`PortfolioHandoffMarkExecuted` enthält nur die optionale
`executed_note`. Das HTML sendet `{}`. Der Server setzt daraufhin
`status="Ausgeführt"`, `executed_at` und `executed_by`.

Nicht erfasst oder geprüft werden:

- externe Order-/Batch-/Custodian-ID;
- empfangener Ack;
- Fill-Zeit, Menge, Preis, Währung und Gebühren je Instruktion;
- Partial Fill, Rejected, Expired oder Settlement Failed;
- Reconciliation gegen die ursprünglich gesendete Menge/Seite;
- Evidence-Artefakt oder Gegenstellen-Signatur;
- unabhängige Bestätigung beziehungsweise Vier-Augen-Prinzip.

Die Reproduktion bestätigte:

```json
{
  "request_body": {},
  "empty_execution_note_accepted": true,
  "stored_status": "Ausgeführt"
}
```

Ein interner Beraterklick ist damit ein Selbstattest, kein Ausführungsnachweis.

### Fixvertrag

Status `Executed` entsteht nur aus verifizierten Fills oder einer gebundenen,
unveränderlichen manuellen Ausführungsevidence. Partial/Rejected/Expired/
SettlementFailed sind eigene States. Fill-Summe, Side, Instrument, Account und
Währung müssen gegen die Instruction reconciliert werden; Abweichungen bleiben
sichtbar und genehmigungspflichtig.

## `HANDOFF-STATE-001` – Endzustände bleiben last-write-wins

### Beobachtung

Execute und Cancel laden die Zeile, prüfen in Python
`handoff.status == "Gesendet"`, ändern das ORM-Objekt und committen. Es gibt
weder `SELECT FOR UPDATE`, State-Version noch atomaren
`UPDATE ... WHERE status='Gesendet'`.

### Deterministische Stale-Read-Reproduktion

Zwei Sessions luden dieselbe Zeile im offenen Zustand. Danach wurde die
bereits geladene Instanz A über Execute und die bereits geladene Instanz B über
Cancel verarbeitet. Dies bildet exakt die kritische Interleaving-Grenze nach,
ohne Timingzufall:

```json
{
  "first_call_returned": "Ausgeführt",
  "second_call_returned": "Storniert",
  "stored_final_status": "Storniert",
  "stored_executed_at_present": true,
  "stored_cancelled_at_present": true,
  "successful_transition_audit_rows": 2
}
```

Damit ist `REC-005` unverändert bestätigt. Zusätzlich fehlen DB-Constraints,
die Status und zugehörige Zeit-/Actor-Felder kohärent halten.

### Fixvertrag

1. Zustandswechsel erfolgt als atomarer CAS mit erwarteter `state_version`.
2. Genau eine Transition gewinnt; die andere erhält 409/412.
3. Audit-/Outbox-Eintrag und Zustandswechsel liegen in derselben Transaktion.
4. DB-Checks erzwingen zulässige States und dazugehörige Pflicht-/Nullfelder.
5. PostgreSQL-Paralleltest verwendet echte Sessions/Locks, nicht SQLite.
6. Transitions sind append-only Events; der aktuelle State ist daraus
   deterministisch ableitbar.

## `HANDOFF-INTEGRITY-001` – „Immutable“ ist weder erzwungen noch prüfbar

Der Model-Kommentar nennt den Snapshot unveränderlich, weil kein Router-Update
existiert. Das schützt nicht gegen Admin-/Maintenance-SQL, Importfehler,
Migration, Restore, kompromittierte Anwendung oder versehentliche ORM-Writes.

Es fehlen:

- kanonisches JSON-Schema und Schema-Version;
- Hash des Snapshots und der Contextanker;
- Signatur/HMAC oder append-only Revision;
- DB-Trigger/Permissions gegen In-place-Update;
- Reconciliation von `position_count` und JSON-Länge;
- Status-/Zeitfeld-Constraints;
- Read-Time-Verifikation und sichtbarer Integrity-State.

Der allgemeine Auditlog ist hashverkettet, aber der Create-Eintrag hasht nur
seine eigene Kurzbeschreibung. Der Handoff-Snapshot oder dessen Hash ist nicht
Teil dieses Auditpayloads.

### Reproduktion

Eine direkte SQL-Änderung auf eine vorhandene Zeile wurde gespeichert und vom
Pydantic-Response-Schema akzeptiert:

```json
{
  "response_schema_accepts_status": "BROKEN",
  "response_schema_accepts_snapshot": "not-json",
  "response_schema_accepts_position_count": 999,
  "handoff_has_integrity_hash_column": false,
  "audit_rows_before": 1,
  "audit_rows_after": 1
}
```

Die Aussage „unverändert“ kann damit nachträglich weder bewiesen noch
falsifiziert werden.

## `HANDOFF-RETENTION-001` – Cleanup und Foreign Key widersprechen der Dokumentation

Der Model-Kommentar erklärt `recommendation_run_id` bewusst nullable: Der
90-Tage-Cleanup solle den Run löschen können; der Handoff verliere lediglich
die Provenienzreferenz. Tatsächlich besitzt der Foreign Key kein
`ON DELETE SET NULL`, und der Cleanup nullt Handoffs nicht. Er kennt außerdem
RecommendationHoldings nicht.

Mit SQLite-Foreign-Keys explizit aktiviert – also näher an der PostgreSQL-
Zielsemantik – ergab ein alter Final-Run mit genau einem Handoff:

```json
{
  "cleanup_result": "IntegrityError",
  "foreign_key_on_delete_set_null": false,
  "run_remaining_after_rollback": 1,
  "handoff_recommendation_run_id": "run-old"
}
```

Unter PostgreSQL blockiert die Default-FK-Semantik denselben Delete. In
SQLite-Setups ohne Foreign-Key-Enforcement kann dagegen ein dangling ID
zurückbleiben. Selbst ein korrektes `SET NULL` wäre fachlich nicht genug,
solange der Handoff keinen eigenen Run-/Context-Hash bewahrt.

### Fixvertrag

- Final-/gesendete/ausgeführte Runs unterliegen Legal Hold und werden nicht
  nach pauschal 90 Tagen gelöscht.
- Retentionmatrix umfasst Run, Positions, Holdings, Handoff, Delivery,
  Execution, Advisory, Signatur und Auditlog als gemeinsame Evidence-Kette.
- Soll eine technische FK gelöst werden, bleibt die vollständige immutable
  Provenienz im Handoff erhalten.
- Cleanup-Dry-Run meldet blockierende Referenzen und geplante Wirkung.
- SQLite-FK-on und echte PostgreSQL-Tests decken Restrict/Legal-Hold/
  Anonymisierung/Restore ab.

## Zielbild: `ExecutionInstructionSnapshot` plus Evidence-State-Machine

### Unveränderlicher Decision- und Valuation-Context

- `instruction_snapshot_id`, Schema-Version, kanonischer Payload-Hash
- Tenant, Client, aktives Mandat, Depot-/Custody-Account
- Final-Run-ID/-Hash, TA-/RA-/Policy-/CMA-/Product-Universe-IDs und Hashes
- `holdings_valuation_snapshot_id`/-Hash, gemeinsames `valuation_as_of`
- Preis-/FX-/Coverage-State und `publication_ready`
- Advisory-/Suitability-/Cost-/Conflict-/Signature-Evidence-IDs und Hashes
- Actor, Freigabezeit, Vier-Augen-/Berechtigungsstate

### Reconciliende Instruction-Lines

- stabiler Instrument-Key: ISIN/FIGI/Ticker+Venue und interne Product-ID
- Account, Side-Code, Quantity, Amount, Currency
- Current Market Value und **wirksamer** Execution-Target-Market-Value
- Referenz-/Limitpreis, Ordertyp, Time-in-force, Fractional-/Rundungsregel
- FX-Rate/-Pfad, Gebühren-/Tax-/Lot-/Cash-Annahmen
- Invariante `current + signed_delta = execution_target`
- line hash und deterministische Sortierung

### Delivery-Evidence

- `Prepared -> Approved -> Dispatched -> Acknowledged` getrennt
- Transportadapter oder manueller Receipt-Typ
- Ziel-/Empfänger-ID, Kanal, Message-/Transfer-ID
- Hash der wirklich übertragenen Bytes
- sent/received/ack timestamps und Fehler-/Retry-State
- Idempotency-Key, Versuchszähler und Resend-Revision

### Execution-/Fill-Evidence

- `PartiallyExecuted`, `Executed`, `Rejected`, `Expired`, `Cancelled`,
  `SettlementFailed`
- externe Order-/Batch-/Fill-IDs
- Fill-Menge, Preis, Währung, Gebühren, Trade-/Settlement-Zeit
- vollständige Reconciliation gegen jede Instruction-Line
- Abweichungsfreigabe und append-only Korrekturereignisse

### Integrität, Zugriff und Retention

- atomare CAS-State-Version
- DB-Checks und fachliche Unique-Constraints
- kein In-place-Update an Snapshot/Events
- Hash-/Signaturprüfung bei jedem Read und Export
- tenant-/mandate-/accountgebundene Autorisierung
- Legal Hold und gemeinsame Retention der ganzen Evidence-Kette
- PostgreSQL/RLS-/Backup-/Restore-Replay mit identischem Hash

## Verbindliche Testmatrix

### Context und Eligibility

1. Draft, Final, Superseded und unbekannter Status;
2. aktives, inaktives, archiviertes, geschlossenes und gelöschtes Mandat;
3. Run ohne/mit fremder/gelöschter TA, RA, CMA oder Policy;
4. provisorische CMA/Home-Bias-Daten;
5. offene/fehlende Suitability, Advisory, Costs, Conflicts oder Signaturen;
6. Final-Run wechselt während Create;
7. zwei Tenants, zwei Mandate, zwei Accounts desselben Kunden.

### Holdings, Preise, FX und Coverage

1. echte Units plus frischer Preis;
2. expliziter Zero-Bestand;
3. missing/partial/stale/invalid Holding;
4. `implied_from_target` muss blockieren;
5. missing/stale/future Preis;
6. missing/invalid/stale FX;
7. Product orphan/deleted/inactive;
8. Coverage-Nenner bleibt vollständig;
9. Snapshot-Hash bleibt beim Replay identisch.

### Handelsmathematik

1. Marktwert steigt/fällt seit Run;
2. Zu-/Abfluss ändert Live-Total;
3. Cross-Currency und FX-Rundung;
4. `current + signed_delta == execution_target` je Zeile;
5. Kauf-/Verkaufs-/Cash-/Fee-Summen reconciliieren;
6. 0,5-Prozent-Grenze knapp darunter, exakt darauf und knapp darüber;
7. keine Position verschwindet durch Rundung oder fehlende Evidence.

### Instruction- und UI-Vertrag

1. Code/Label für BUY, SELL, HOLD, CHECK, MISSING_PRICE;
2. echtes Backendpayload im Browser-/DOM-Test;
3. Kauf-/Verkaufsvolumen und Farben stimmen;
4. CHF/EUR/USD werden korrekt und eindeutig bezeichnet;
5. ISIN/Account/Quantity/Price/FX/as-of sichtbar und im Export identisch;
6. UI, API, PDF/Datei und Transportbytes besitzen denselben Hash;
7. historische Handoffs bleiben vollständig einsehbar.

### Idempotenz und State Machine

1. gleicher Idempotency-Key + gleicher Payload;
2. gleicher Key + anderer Payload;
3. paralleler Create;
4. paralleles Execute/Cancel/Reject;
5. wiederholter Delivery-Ack/Fill;
6. State-Version stale/fresh;
7. ungültige State-/Zeitfeldkombinationen werden von der DB abgewiesen;
8. Audit-/Outbox-Event und State committen atomar.

### Delivery und Execution

1. Transport success/failure/timeout/unknown outcome;
2. Retry ohne doppelte Instruktion;
3. falscher Empfänger oder Payload-Hash;
4. Ack fehlt/ist verspätet;
5. partial/full/rejected/expired/settlement failed;
6. Fill mit falschem Instrument, Account, Side, Menge, Währung oder Preis;
7. manuelles Receipt mit Signatur/Timestamp/Hash;
8. Vier-Augen-/Rollen- und Cross-Tenant-Negativfälle.

### Integrität, Retention und Zielumgebung

1. Raw-SQL-Tamper an Snapshot, State, Count und Evidence;
2. Hash-/Signaturfehler wird sichtbar und blockiert;
3. Cleanup mit Draft, Final, Handoff, Fill und Legal Hold;
4. Restore/Replay bewahrt Hash und FK-Kette;
5. SQLite mit `foreign_keys=ON` als schnelles Gate;
6. echte PostgreSQL-Parallel-/FK-/RLS-Tests als Pflicht;
7. native Electron-/Browser-/Exportprüfung der sichtbaren Nachweise.

## Empfohlene Umsetzungsreihenfolge

### Phase A – Sofortige Claim-Sperre

1. Create auf Final + aktives Mandat + vollständige Evidence begrenzen.
2. `Gesendet` und `Ausgeführt` ohne Receipt/Fill nicht mehr erzeugen.
3. Target-implied/partial/stale Valuation als nicht ausführbar blockieren.
4. Action-Code/UI-Summen und Live-SOLL-Anzeige korrigieren.
5. Reale Handoff-Funktion bis dahin sichtbar als Entwurf sperren.

### Phase B – Kanonische Instruktion

1. Runde-22-HoldingsValuationSnapshot implementieren.
2. `ExecutionInstructionSnapshot` mit vollständigen Context-/Line-Feldern
   modellieren.
3. Mathe-/Cash-/FX-/Quantity-Reconciliation implementieren.
4. Schema-Version, kanonisches JSON und Hash persistieren.
5. Idempotency-/Unique-Vertrag einführen.

### Phase C – Evidence-State-Machine

1. Prepared/Approved/Dispatched/Acknowledged trennen.
2. Transport-Outbox/Receipt atomar anbinden.
3. Fill-/Partial-/Reject-/Settlement-Modell ergänzen.
4. CAS-State-Version und DB-Constraints einführen.
5. Vier-Augen-/Rollen-/Account-Autorisierung schließen.

### Phase D – Retention und Beweis

1. gemeinsame Legal-Hold-/Retentionmatrix migrieren;
2. alte Handoffs validieren und als Legacy/Unknown kennzeichnen;
3. gesamte Testmatrix auf PostgreSQL/RLS ausführen;
4. Browser-/Electron-/Datei-/PDF-/Transport-Golden-Gates;
5. Backup-/Restore-/Tamper-Replay;
6. Fach-, Operations-, Compliance-, Security- und UX-Abnahme.

## Definition of Done

- [ ] Kein Draft, Superseded oder inaktives Mandat kann Handoff-Basis sein.
- [ ] Run, TA, RA, Policy, CMA, Product Universe und Holdings Valuation sind
      über unveränderliche IDs/Hashes geschlossen.
- [ ] Suitability, Advisory, Costs, Conflicts und Signaturen sind nach Policy
      gebundene Eligibility-Evidence.
- [ ] Target-implied, missing, partial, stale, invalid oder FX-missing erzeugt
      keine reale Handelsinstruktion.
- [ ] Jede Zeile besitzt Instrument, Account, Side, Quantity, Amount,
      Currency, Preis-/FX-/as-of und Orderbedingungen.
- [ ] `current + delta = execution_target` und alle Portfolio-/Cash-Summen
      reconciliieren.
- [ ] Backend-Code und UI-Label sind getrennt, typisiert und kanalgleich.
- [ ] CHF/EUR/USD werden ohne Hardcode korrekt publiziert.
- [ ] Create ist unter Retry und Parallelität idempotent.
- [ ] Prepared, Dispatched, Acknowledged und Executed sind getrennte,
      beweisgebundene Zustände.
- [ ] `Executed` verlangt reconciliierte externe Fill-Evidence oder einen
      gleichwertigen immutable manuellen Nachweis.
- [ ] Genau eine konkurrierende Endtransition gewinnt atomar.
- [ ] Snapshot/Events sind append-only, gehasht/signiert und bei Reads
      verifiziert.
- [ ] DB-Constraints verhindern malformed JSON, freie States, falsche Counts
      und widersprüchliche Zeit-/Actor-Felder.
- [ ] Auditlog/Outbox und State wechseln atomar und binden den Payload-Hash.
- [ ] Final-/Handoff-/Fill-Evidence unterliegt Legal Hold statt pauschalem
      90-Tage-Delete.
- [ ] SQLite-FK-on sowie echte PostgreSQL-/RLS-/Concurrency-Gates sind grün.
- [ ] Browser, Electron, API, Export/PDF und Transportartefakt zeigen denselben
      Hash, dieselben Werte und denselben Evidence-State.
- [ ] `REC-003`, `REC-005`, `REP-004` und die Runde-22-Bestandsbefunde sind
      mit Regressionen tatsächlich geschlossen, nicht nur umbenannt.

## Claude-/GPT-Startcheckliste

Vor Änderungen an RecommendationRun, Live Rebalancing, Handelsliste,
PortfolioHandoff, Delivery, Execution, Cleanup oder Auditlog:

1. Diesen Audit vollständig lesen.
2. Den Depot-/Holdings-Audit aus Runde 22 sowie `REC-003`, `REC-005` und
   `REP-004` mitlesen.
3. Zuerst Final-Run, TA, RA, Policy, CMA, Holdings-Snapshot und Account
   benennen.
4. Niemals Target-implied Daten als tatsächlichen Bestand ausführen.
5. Code und lokalisiertes Label getrennt halten.
6. SOLL/Delta je Zeile und alle Summen mathematisch reconciliieren.
7. `Prepared`, `Sent`, `Acknowledged` und `Executed` nie gleichsetzen.
8. Kein Delivery-/Execution-State ohne gebundene externe Evidence.
9. Jede Create-/Transition-Route unter Retry und Parallelität testen.
10. Snapshot und Auditlog über denselben Payload-Hash binden.
11. Retention/Legal Hold vor FK-/Cleanup-Änderungen gemeinsam modellieren.
12. ACL-unlesbare `.pytest_tmp*`-Verzeichnisse weder betreten noch bereinigen.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

- Branch: `codex/asset-allocation-stochastic-core`
- auditierter Head: `57da24112132ec2e16c74488f22517b63da2d91f`
- sichtbare tracked/untracked Änderungen: `0`
- bekannte ACL-unlesbare pytest-Tempverzeichnisse: `53`
- globale Clean-Aussage: ausdrücklich **nein**
- Produktcode verändert: **nein**
- Tests verändert: **nein**

Das temporäre Reproduktionsharness lag ausschließlich unter `C:\tmp`, wurde
nach Ausführung entfernt und gehörte nie zum Repository. Die ACL-unlesbaren
Verzeichnisse wurden nicht betreten, verändert oder bereinigt.

### Deterministische Reproduktionsblöcke

Das temporäre Harness führte drei voneinander getrennte Blöcke aus:

1. Router-/ORM-Block: archiviertes Mandat, Draft/Superseded, Duplicate Create,
   leerer Execute, zwei stale Sessions und Raw-SQL-Tamper;
2. Engine-/Snapshot-Block: zwei target-implied Positionen mit echter
   `_build_live_rebalancing_entry`-/`_build_live_position_drifts`-Logik;
3. FK-Block: RecommendationRun-Cleanup auf SQLite mit explizit aktiviertem
   `PRAGMA foreign_keys=ON`.

Alle persistierten Daten lagen in flüchtigen SQLite-Datenbanken außerhalb des
Repositories. Für den UI-Vertragscheck wurde die echte Engine-Ausgabe gegen
die unveränderte Summenlogik aus `openTradeList()` ausgewertet.

### Fokussierter Gate

Ausgeführt aus `5eyes-backend` mit externem Basetemp:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp C:\tmp\5eyes-handoff-gate-20260903 `
  tests/test_portfolio_handoff.py `
  tests/test_frontend_portfolio_handoff.py `
  tests/test_recommendation_run_cleanup.py `
  tests/test_recommendation_run_cleanup_tenant_isolation.py `
  tests/test_finalize_mandate_lock.py `
  tests/test_finalize_rejects_non_current_policy_and_cma.py `
  tests/test_live_rebalancing_fx_conversion.py `
  tests/test_contract_documents_fresh_bootstrap_schema_drift.py `
  tests/test_data_integrity_audit.py
```

Ergebnis:

```text
59 passed in 27.84s
```

Davon sind 7 reine Frontend-Monolith-Quelltexttests; die verbleibenden 52
prüfen Backend-Service-, Router-, Schema-, Finalisierungs-, Cleanup-, FX- und
Integritätspfade. Der Gate enthielt keine Browser-/DOM-Runtime und keinen
echten PostgreSQL-Concurrency-Test.

### Letzter vollständiger Backend-Gate

Der letzte dokumentierte vollständige Backend-Gate gehört weiterhin zum
Implementierungscommit `661fe73c`:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed
```

Kontrollrunde 23 hat den Vollgate nicht erneut ausgeführt.

### Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen zum Dokumentationscommit gehören:

1. `docs/audits/2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit wird reproduzierbar aufgelöst mit:

```powershell
git log -1 --format=%H -- docs/audits/2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md
```
