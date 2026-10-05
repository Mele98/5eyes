---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-product-suitability-appropriateness-recommendation-eligibility-integrity-followup-audit"
status_as_of: "2026-09-04"
audit_started_on: "2026-09-03"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "fabd8a34de23099addab45a56208042dbb96e426"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md"
prior_release_audit_commit: "fabd8a34de23099addab45a56208042dbb96e426"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-04-product-suitability-appropriateness-and-recommendation-eligibility-integrity-audit.md"
audit_mode: "read_only_static_router_service_orm_schema_migration_ui_pdf_test_review_existing_focused_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 12
documentation_manifest_paths: 5
scope: "ProductSuitability rule consumption, advisory versus discretionary eligibility, knowledge and experience semantics, appropriateness and override requirements, per-product position caps, no-rule defaults, relaxed recommendation fallback, suitability gate semantics, recommendation finalization, signed publication, portfolio handoff, schema parity, rule governance and test coverage"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
static_findings_confirmed: 10
focused_existing_tests_passed: 116
focused_existing_tests_failed: 0
isolated_runtime_harness_executed: false
isolated_runtime_harness_block_reason: "tool safety approval unavailable; no bypass attempted"
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "implement one fail-closed versioned ProductEligibilitySnapshot that derives service mode, product-rule version, semantic knowledge and experience, appropriateness and override evidence, post-aggregation position caps and finalization eligibility from one exact mandate context; remove the suitability-relaxation recommendation fallback and bind Final, signed publication and handoff to the same immutable eligibility verdict"
---

# Produkt-Suitability-/Angemessenheits-/Recommendation-Eligibility-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die fünfundzwanzigste Read-only-
Kontrollrunde. Er wurde gegen den unveränderten Repository-Head `fabd8a3`
begonnen, am 4. September 2026 konsolidiert und verändert weder Produktcode
noch Tests.

Geprüft wurde nicht, ob eine bestimmte Empfehlung rechtlich oder wirtschaftlich
geeignet ist. Geprüft wurde der technische Vertrag, mit dem 5eyes seine eigenen
Produktfreigaben, Kenntnisse-/Erfahrungsdaten, Angemessenheits- und Override-
Felder in Empfehlung, Finalisierung, Publikation und Handoff durchsetzt.

Dieser Audit ergänzt und ersetzt insbesondere nicht:

1. den unmittelbar vorherigen
   [Vertragsdokument-/E-Signatur-/signierte-Publikations-Integritätsaudit](2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md),
2. den
   [Portfolio-Handoff-/Handelsinstruktions-/Ausführungsnachweis-Integritätsaudit](2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md),
3. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
4. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
5. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
6. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
7. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
8. sowie den grundlegenden
   [Post-Commit-Integritätsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md).

Bei Widersprüchen gelten aktueller Code und nachweisbare Laufzeitbelege zuerst,
danach dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu bereits bestätigten Suitability-Befunden

Kontrollrunde 7 (`TEN-COMP-002`) hat bereits belegt, dass ein SuitabilityCheck
freie Evidence-IDs aus einem anderen Mandat übernehmen kann. Kontrollrunde 8
(`FIDLEG-STATE-003`) hat bereits belegt, dass Advisor-Request, SuitabilityCheck
und Compliance-Audit widersprüchliche Wahrheiten erzeugen können. Diese
Befunde bleiben offen und werden hier nicht unter neuen IDs dupliziert.

Kontrollrunde 25 schließt die bislang fehlende Produktperspektive: Selbst wenn
alle Referenz- und State-Probleme dieser früheren Runden behoben würden, nutzt
die Empfehlung vier fachliche `ProductSuitability`-Felder nicht, kennt den
Unterschied zwischen Anlageberatung und Vermögensverwaltung nicht, lässt
Produkte ohne Regel standardmäßig zu und übergeht eine ablehnende Regel
absichtlich über einen Fallback. Finalisierung, Signatur und Handoff prüfen
diese Entscheidung danach nicht erneut.

## Kurzurteil

Der aktuelle Stand darf **nicht** als technisch durchgesetzte Produkt-
Suitability, Angemessenheitsprüfung oder Recommendation Eligibility für reale
Beratung beziehungsweise Vermögensverwaltung freigegeben werden.

Bestätigt sind insbesondere:

1. Von den fünf fachlichen Freigabe-/Pflichtfeldern einer
   `ProductSuitability`-Regel liest der Matcher ausschließlich
   `advisory_allowed`; `discretionary_allowed`,
   `requires_appropriateness`, `requires_override` und `max_position_bps`
   beeinflussen die Entscheidung nicht.
2. Der Matcher erhält weder Mandat noch Mandatstyp oder Service Mode. Auch für
   `Vermögensverwaltung` entscheidet deshalb immer `advisory_allowed`.
3. Ein Produkt ohne Suitability-Regel wird implizit zugelassen. Manuell oder
   per Bulk-Import angelegte Produkte erhalten in diesen Pfaden keine Regel;
   das Default-Seeding ergänzt sie später nicht.
4. Findet die Engine kein zulässiges Produkt, ruft sie denselben Matcher mit
   `ignore_suitability=True` auf und erzeugt aus dem zuvor abgelehnten Produkt
   dennoch eine RecommendationPosition.
5. `max_position_bps` wird auch nach der Aggregation mehrerer Sub-Allocations
   auf dasselbe Produkt nicht geprüft. Nur separat gesetzte Benutzerlimits für
   Einzelposition und Emittent wirken.
6. Kenntnisse und Erfahrungen müssen lediglich JSON-Objekte sein. Leere oder
   inhaltlich negative Maps werden nicht gegen Produktart, Service oder
   erforderte Angemessenheit ausgewertet.
7. Das globale Suitability-Gate ist standardmäßig deaktiviert. Aktiviert prüft
   es nur die Frische eines RiskAssessment, nicht ProductSuitability,
   Kenntnisse-/Erfahrungssemantik oder das Ergebnis eines SuitabilityCheck.
8. Die Finalisierung prüft aktive Produkte, Gewichtssumme, TER und
   Marktdatenhinweise, aber weder Produktregel noch Angemessenheit, Override,
   Knowledge noch SuitabilityCheck.
9. Ein so finalisierter Run kann in die bereits separat als ungebunden
   bestätigten Signatur- und Handoff-Pfade gelangen; beide besitzen keinen
   ProductEligibility-Nachweis.
10. ORM, Alembic und Raw-SQL definieren unterschiedliche Invarianten. Es fehlt
    ein versionierter, zeitlich gültiger, freigebender Regelworkflow mit
    kanalgleicher Provenienz und unveränderlichem Eligibility-Snapshot.

Der fokussierte Bestands-Gate mit 116 bestandenen Tests hebt diese Befunde nicht
auf. Er belegt die vorhandenen Positivverträge. Kein Test im Backend referenziert
die vier ungenutzten Produktregel-Felder.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `ELIG-RULE-001` | P1 | bestätigt | Der Produktmatcher ignoriert `discretionary_allowed`, `requires_appropriateness`, `requires_override` und `max_position_bps`. |
| `ELIG-MODE-001` | P1 | bestätigt | Der Service Mode fehlt im Matcher; Vermögensverwaltung wird technisch über `advisory_allowed` entschieden. |
| `ELIG-DEFAULT-001` | P1 | bestätigt | Fehlende Produktregel bedeutet erlaubt; Create, Update und Import verwalten keine Suitability-Regel. |
| `ELIG-FALLBACK-001` | P1 | bestätigt | `ignore_suitability=True` wandelt eine zuvor abgelehnte Produktwahl in eine Empfehlung mit bloßem Warntext um. |
| `ELIG-LIMIT-001` | P1 | bestätigt | Der produktspezifische Positionsdeckel wird weder bei Selektion noch nach Aggregation oder Finalisierung erzwungen. |
| `ELIG-KNOWLEDGE-001` | P1 | bestätigt | Knowledge/Experience wird auf JSON-Typ, nicht auf fachliche Abdeckung des gewählten Produkts oder Services geprüft. |
| `ELIG-GATE-001` | P1 | bestätigt | Das Default-off-Gate reduziert Suitability auf RiskAssessment-Frische und ignoriert ProductSuitability sowie SuitabilityCheck-Resultate. |
| `ELIG-FINAL-001` | P1 | bestätigt | `Final` kann ohne erneuten Eligibility-, Appropriateness-, Override- oder Knowledge-Nachweis entstehen. |
| `ELIG-PUBLISH-001` | P1 | bestätigt | Signierte Publikation und Handoff können den nicht belegten Finalzustand weitertragen und besitzen keinen Eligibility-Fingerprint. |
| `ELIG-GOVERNANCE-001` | P1 | bestätigt | Regelversion, Gültigkeitszeit, Freigabe, Autor, Tenant-/Jurisdiktionskontext, Dialektparität und unveränderliche Historie fehlen. |

## Tatsächlicher Produktentscheidungsfluss

```text
Produktquelle
  |
  +-- Default-Katalog
  |     -> ProductSuitability wird einmalig erzeugt
  |        profile_from/profile_to
  |        advisory_allowed
  |        discretionary_allowed          [gespeichert, nicht konsumiert]
  |        requires_appropriateness        [gespeichert, nicht konsumiert]
  |        requires_override               [gespeichert, nicht konsumiert]
  |        max_position_bps                [gespeichert, nicht konsumiert]
  |
  +-- Admin Create / Update / Bulk Import
        -> keine ProductSuitability-Eingabe oder -Regel
        -> leere product.suitability-Beziehung
                         |
                         v
_product_matches_constraints(product, prefs, score_bucket, jurisdiction_ctx)
  |
  +-- Regel vorhanden und ignore_suitability=False
  |     -> prüft Profilband + advisory_allowed
  |
  +-- keine Regel
  |     -> True
  |
  +-- keine zulässigen Kandidaten
        -> erneuter Aufruf mit ignore_suitability=True
        -> abgelehnte Regel vollständig übersprungen
        -> RecommendationPosition + Rationale/Warntext
                         |
                         v
Aggregation pro Produkt
  -> mehrere Sub-Allocations können zu einem Gewicht zusammenfallen
  -> prüft nur prefs.limits.singlePosition/singleIssuer
  -> ProductSuitability.max_position_bps bleibt unberücksichtigt
                         |
                         v
RecommendationRun Draft
  -> optionales globales Gate, Default false
  -> bei true: frisches RiskAssessment genügt
  -> SuitabilityCheck und Produktregeln werden nicht gelesen
                         |
                         v
Finalize
  -> aktive Produkte + ca. 100 % + Referenzanker
  -> TER/Preis nur Warnung
  -> keine ProductEligibility-Prüfung
                         |
                         v
Contract signoff / Portfolio handoff
  -> kein Eligibility-Snapshot, keine Rule-Version, kein Verdict-Hash
```

## Codeanker auf dem auditierten Head

| Prüfbereich | Codeanker |
|---|---|
| Product-/Suitability-Modell | `5eyes-backend/models/review.py:262-271`, `:318-333` |
| Raw-SQL-Produktregel | `5eyes-backend/5eyes_schema_v4.0_FINAL.sql:1077-1093` |
| Alembic-Produktregel | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:421-437` |
| Product Create/Update/Response | `5eyes-backend/schemas/review.py:336-419` |
| Product Create/Import/Update | `5eyes-backend/routers/review.py:1107-1488` |
| Default-Produkte und Regeln | `5eyes-backend/services/portfolio_engine.py:1734-1830` |
| Produktmatcher | `5eyes-backend/services/portfolio_engine_payload.py:712-768` |
| Relaxed Suitability-Fallback | `5eyes-backend/services/portfolio_engine.py:6593-6654` |
| Produktaggregation | `5eyes-backend/services/portfolio_engine.py:6656-6693` |
| Konzentrationsvalidator | `5eyes-backend/services/portfolio_engine_payload.py:923-957` |
| Knowledge-/Experience-Persistenz | `5eyes-backend/models/profiling.py:84-85`; `5eyes-backend/routers/profiling.py:189-197` |
| Strategie-Readiness | `5eyes-backend/services/portfolio_engine.py:261-275`, `:367-377` |
| SuitabilityCheck-Request und Create | `5eyes-backend/schemas/profiling.py:185-210`; `5eyes-backend/routers/profiling.py:410-451` |
| Compliance-Audit | `5eyes-backend/services/suitability_audit.py:132-257` |
| Gate-Konfiguration | `5eyes-backend/config.py:289-294` |
| Gate-Aufrufer | `5eyes-backend/routers/allocation.py:235-248`, `:508-522`; `5eyes-backend/routers/review.py:2045-2058`, `:2179-2187` |
| Finalisierungsvalidator | `5eyes-backend/routers/review.py:137-234` |
| Final-Transition | `5eyes-backend/routers/review.py:2298-2322` |
| Suitability-UI-Request | `5eyes-electron/frontend/5eyes_v2.html:24191-24218` |
| Suitability-Berichtsleser | `5eyes-backend/services/advisory_report.py:2445-2527` |

## `ELIG-RULE-001` – Vier gespeicherte Produktpflichten sind wirkungslos

### Beobachtung

`ProductSuitability` modelliert fünf entscheidungsrelevante Felder:

```text
advisory_allowed
discretionary_allowed
requires_appropriateness
requires_override
max_position_bps
```

Der einzige Produktmatcher reduziert die Regel jedoch auf:

```python
profile_from <= score_bucket <= profile_to
and advisory_allowed == 1
```

Repositoryweite Suche findet die übrigen vier Feldnamen ausschließlich in
Schema, Modell, Alembic und Default-Seeding. Es gibt keinen fachlichen Reader,
der sie in Selektion, Finalisierung, Suitability-Audit oder Publikation
auswertet.

### Direkter Kontrollflussbeweis

Für eine Regel mit passendem Profilband, `advisory_allowed=1`, aber
`discretionary_allowed=0`, `requires_appropriateness=1`,
`requires_override=1` und `max_position_bps=1` hängt der Rückgabewert des
Matchers ausschließlich vom Profilband und `advisory_allowed` ab. Die vier
anderen Werte kommen im ausgeführten Ausdruck nicht vor.

Das ist kein theoretischer Altbestand: `ensure_default_products()` setzt alle
vier Felder aktiv auf konkrete Werte. Die Anwendung speichert damit einen
fachlich aussehenden Vertrag, den sie nicht vollstreckt.

### Risiko

Ein Produkt kann als zulässig selektiert werden, obwohl sein eigener Datensatz
für genau diesen Service, eine vorgängige Angemessenheitsprüfung, einen
expliziten Override oder eine kleinere Positionsgröße etwas anderes verlangt.
UI und Datenbank erwecken dabei den Eindruck, diese Regeln hätten operative
Wirkung.

### Verbindlicher Fixvertrag

1. Ein zentraler `evaluate_product_eligibility()`-Service konsumiert jedes
   fachliche Regelfeld explizit.
2. Jedes Feld besitzt eine dokumentierte Semantik, einen fail-closed Default
   und eine stabile Verdict-/Reason-ID.
3. Nicht implementierte Pflichtfelder dürfen nicht im produktiven Modell als
   scheinbar aktive Regeln verbleiben.
4. Unit-Tests parametrisieren jede boolesche Kombination und Grenzwerte von
   `max_position_bps`.
5. API, Engine, Finalisierung, PDF und Handoff lesen dasselbe Verdict statt
   eigene Teilentscheidungen zu rekonstruieren.

## `ELIG-MODE-001` – Advisory und Discretionary sind nicht unterscheidbar

### Beobachtung

Das Mandatsmodell erlaubt unter anderem `Anlageberatung` und
`Vermögensverwaltung`. Der Produktmatcher erhält aber nur Produkt,
Präferenzen, Score Bucket und Jurisdiktionskontext. Weder Mandat noch
Mandatstyp oder normalisierter Service Mode sind Argumente.

Unabhängig vom realen Mandat prüft der Matcher immer `advisory_allowed`.
`discretionary_allowed` besitzt außerhalb von Modell/Schema/Seed keinen Reader.

### Risiko

Zwei fachlich unterschiedliche Dienstleistungen können nicht unterschiedliche
Produktfreigaben erzwingen. Eine Regel kann Vermögensverwaltung ausdrücklich
sperren, ohne dass der Recommendation-Pfad dies erkennen könnte. Umgekehrt ist
auch eine nur für Discretionary gedachte Freigabe nicht ausdrückbar.

### Verbindlicher Fixvertrag

1. Mandatstyp wird einmalig in einen versionierten Service Mode normalisiert.
2. `advisory_allowed` gilt ausschließlich für Anlageberatung;
   `discretionary_allowed` ausschließlich für Vermögensverwaltung.
3. Finanzplanung, Reporting-only und mögliche Execution-only-Pfade erhalten
   ausdrücklich definierte, getestete Regeln statt impliziter Defaults.
4. Unbekannte oder historische Mandatstypen enden mit einem stabilen
   `UNKNOWN_SERVICE_MODE`-Verdict und dürfen keine Empfehlung finalisieren.
5. Ein späterer Wechsel des Mandatstyps invalidiert bestehende Drafts und
   erzeugt keine rückwirkende Umdeutung eines Snapshots.

## `ELIG-DEFAULT-001` – Keine Regel bedeutet automatisch erlaubt

### Beobachtung

Der Matcher prüft Regeln nur bei einer truthy `product.suitability`-Beziehung.
Ist die Liste leer, fällt der Code auf das abschließende `return True`.

Gleichzeitig enthalten `ProductCreate`, `ProductUpdate`, `ProductResponse`,
JSON-/CSV-Bulk-Import und die Product-Router keine Suitability-Felder oder
einen separaten Regelworkflow. Neue tenant-spezifische Produkte werden daher
ohne Regel erzeugt.

`ensure_default_products()` hilft diesem Bestand nicht:

- Es beendet sich, sobald irgendein aktives CH-Produkt existiert.
- Regeln werden nur für die in demselben Aufruf neu angelegten Default-Produkte
  erzeugt.
- Nachträglich importierte oder manuell angelegte Produkte erhalten keine
  Regel.
- Für Nicht-CH-Jurisdiktionen seedet die Funktion bewusst gar nichts.

### Risiko

Der gefährlichste oder unbekannteste Zustand – fehlende Klassifizierung – ist
zugleich der freizügigste Zustand. Ein Asset Manager kann einen neuen Fonds in
das Universum aufnehmen; die Engine behandelt dessen fehlende Eligibility-
Klassifizierung nicht als Blocker, sondern als globale Freigabe.

### Verbindlicher Fixvertrag

1. Fehlende, mehrdeutige, abgelaufene oder nicht freigegebene Regel bedeutet
   `INELIGIBLE_UNCLASSIFIED`, niemals erlaubt.
2. Product Create/Import bleibt unvollständig, bis eine gültige Rule-Version
   atomar mitgeliefert oder in einem Quarantänestatus gespeichert wurde.
3. ProductResponse zeigt Klassifikationsstatus, Rule-Version, Gültigkeit und
   Freigabeprovenienz.
4. Migration inventarisiert alle Produkte ohne exakt eine gültige Regel; keine
   stille Auto-Freigabe oder synthetische Backfill-Behauptung.
5. Nicht-CH- und tenant-spezifische Kataloge durchlaufen denselben
   Klassifikationsvertrag.

## `ELIG-FALLBACK-001` – Ablehnung wird zum Recommendation-Fallback

### Beobachtung

Findet die Engine im exakten Sub-Asset oder in derselben Assetklasse keinen
Kandidaten, baut sie `relaxed_matching` durch einen erneuten Aufruf mit
`ignore_suitability=True`.

Damit wird nicht nur das Profilband gelockert. Der komplette bisherige
Suitability-Block wird übersprungen. Ein Produkt mit explizitem
`advisory_allowed=0` oder außerhalb des Risikobands wird wieder Kandidat,
gerankt und als RecommendationPosition gespeichert.

Der Pfad setzt lediglich:

- einen Text in `RecommendationPosition.rationale`;
- einen Warnstring in der unmittelbaren Generate-Response.

Es entsteht kein bindender Override-Datensatz, keine prüfbare
Angemessenheitsentscheidung, keine Kundenwarnung und kein Blocker. Die
Warnings-Liste ist kein versioniertes Feld des RecommendationRun.

### Risiko

Eine harte Produktablehnung wird semantisch zu „Beratung/Override später
dokumentieren“ degradiert. Wird die Response nicht dauerhaft gesichert oder
ignoriert, bleibt nur ein Freitext in der Position. Die Finalisierung verlangt
weder das angekündigte Dokument noch eine entsprechende Evidence-ID.

### Verbindlicher Fixvertrag

1. Den `ignore_suitability=True`-Fallback aus produktiven Recommendations
   entfernen.
2. Kein zulässiger Kandidat endet deterministisch mit 409 und maschinenlesbaren
   Gründen pro Sub-Asset.
3. Ein echter Override ist ein separater, rollenberechtigter, append-only
   Entscheid mit Grund, Regelversion, Scope, Ablauf, Principal und Evidence.
4. `requires_appropriateness` muss vor Auswahl einen passenden, aktuellen und
   gebundenen Check verlangen.
5. Warnings dürfen harte Invarianten nie ersetzen.

## `ELIG-LIMIT-001` – Produktspezifischer Positionsdeckel wird nicht geprüft

### Beobachtung

Nach der Titelselektion aggregiert die Engine mehrere Sub-Allocations, wenn
dieselbe Produkt-ID jeweils als bester Kandidat gewählt wurde. Erst danach ruft
sie `_validate_recommendation_concentration_limits()` auf.

Dieser Validator kennt ausschließlich:

```text
prefs.limits.singlePosition
prefs.limits.singleIssuer
```

Er liest weder `product.suitability` noch `max_position_bps`. Der im Default-
Seed gesetzte produktspezifische Deckel von 2.500 bps für Aktien und 4.000 bps
für andere Produkte ist daher ohne Wirkung. Auch der Finalisierungsvalidator
prüft ihn nicht.

### Risiko

Ein allgemeines Präferenzlimit kann strenger oder lockerer als die konkrete
Produktfreigabe sein. Ohne `max_position_bps` nach Aggregation kann gerade das
Zusammenfallen mehrerer Sub-Allocations die erlaubte Produktquote überschreiten,
obwohl jede Teilentscheidung isoliert klein aussieht.

### Verbindlicher Fixvertrag

1. Produktspezifische und allgemeine Limits in einer klaren Präzedenzregel
   kombinieren; wirksam ist der strengste gültige Deckel.
2. Limit erst auf dem final aggregierten Produktgewicht bewerten.
3. Grenzwert exakt zulassen, `+1 bps` blockieren.
4. Cash, Fonds, Derivate und Look-through-Strukturen ausdrücklich definieren.
5. Finalisierung berechnet denselben Wert erneut oder prüft einen
   unveränderlichen Eligibility-Snapshot samt Positionshash.

## `ELIG-KNOWLEDGE-001` – Knowledge und Experience sind nur typisierte Anzeige

### Beobachtung

Das RiskAssessment speichert `knowledge_services_json` und
`knowledge_instruments_json`. Die Strategie-Readiness verlangt jedoch nur,
dass beide Werte als JSON-`dict` dekodierbar sind. Leere Objekte erfüllen
diesen Marker ebenso wie Maps, in denen `known=0` und `informed=0` steht.

Die tatsächlichen `known`-/`informed`-Werte werden in PDF-Komponenten
interpretiert und angezeigt. Die repositoryweite Suche findet keinen
Produktselektions- oder Finalisierungsservice, der sie gegen Produktart,
Komplexität, Service oder `requires_appropriateness` abgleicht.

Der separate Suitability-Audit betrachtet lediglich Existenz und Alter des
RiskAssessment. Ein frisches Profil wird als `is_compliant=True` markiert,
unabhängig vom Inhalt der Knowledge-Maps und unabhängig von einem negativen
SuitabilityCheck.

### Risiko

Die Anwendung kann im Bericht fehlende Kenntnisse sichtbar machen und
gleichzeitig dieselbe Empfehlung als strategie-ready beziehungsweise
Suitability-konform behandeln. Anzeige und operative Entscheidung besitzen
damit verschiedene Wahrheiten.

### Verbindlicher Fixvertrag

1. Ein versioniertes Knowledge-/Experience-Schema mit erlaubten Instrument-
   und Servicekategorien einführen.
2. Vollständigkeit von positiver Abdeckung unterscheiden; `{}` ist kein
   fachlicher Nachweis.
3. Produktklassifikation auf erforderliche Kategorien, Komplexität und
   Erfahrungsniveau abbilden.
4. Fehlende Kenntnis führt je nach verbindlichem Duty-Vertrag zu Block,
   vorgängiger Information oder Angemessenheitsworkflow – nie zu stiller
   Freigabe.
5. PDF und UI zeigen exakt das serverseitige Verdict mit denselben Reason-IDs.

## `ELIG-GATE-001` – Das Suitability-Gate schützt den Produktentscheid nicht

### Beobachtung

`require_suitability_before_recommendation` steht standardmäßig auf `False`.
Die vier geprüften Create-/Generate-Pfade rufen den Audit nur innerhalb dieses
Flags auf. Bestehende Tests sichern diesen Default ausdrücklich ab.

Selbst bei aktiviertem Flag ruft jeder Pfad `audit_mandate_suitability()` auf.
Dieser Service lädt ein aktuelles RiskAssessment, prüft dessen Alter und setzt
bei Frische `is_compliant=True`. Er fragt keinen SuitabilityCheck und keine
ProductSuitability ab; `result_issues` bleibt im betrachteten Pfad leer.

Damit würde auch ein vorhandener SuitabilityCheck mit `Nicht geeignet` den
Recommendation-Gate nicht beeinflussen. Die bereits in `FIDLEG-STATE-003`
dokumentierte widersprüchliche Source of Truth bleibt bestehen und wird durch
die Produktlücke erweitert.

### Risiko

Das Aktivieren des Flags vermittelt eine stärkere Absicherung, als technisch
existiert. Es blockiert alte oder fehlende Risikoprofile, aber nicht ein
ungeeignetes Produkt, negative Knowledge-Abdeckung, fehlende Angemessenheit,
fehlenden Override oder ein negatives Prüfergebnis.

### Verbindlicher Fixvertrag

1. Den Flag nicht als Produkt-Suitability-Control dokumentieren.
2. Einen einzigen fail-closed Eligibility-Service vor jedem Recommend-
   Schreibpfad erzwingen.
3. Default-on ist erst nach Altbestandsinventur, Migrationsplan und grüner
   Negativtestmatrix zulässig; bis dahin reale Nutzung blockieren.
4. `is_compliant=None`, fehlende Daten und Resolverfehler müssen blockieren.
5. Auditstatus, Recommendation-Gate und Publication-Gate konsumieren denselben
   Snapshot statt drei eigene Wahrheiten.

## `ELIG-FINAL-001` – Finalisierung friert keine Eligibility ein

### Beobachtung

`_validate_recommendation_for_finalization()` prüft aktuelle RA-/TA-/Policy-/
CMA-Anker, Positionen, Gewichtssumme und aktive Produkte. Fehlende TER oder
Preise werden als Warnungen behandelt.

Der Validator importiert `ProductSuitability` zwar über das Routermodul, fragt
die Tabelle aber nicht ab. Ebenso fehlen SuitabilityCheck, Knowledge-Semantik,
Appropriateness, Override und produktspezifischer Maximalanteil. Danach setzt
der Endpoint `run.result_status = "Final"`.

Zwischen Draft-Erzeugung und Finalisierung kann sich eine Produktregel außerdem
ändern, ohne dass der Run eine Rule-Version oder einen Eligibility-Hash besitzt.
Der Code kann deshalb weder den ursprünglichen noch den aktuellen Entscheid
beweisen.

### Risiko

`Final` bestätigt nur technische Teilkonsistenz, nicht die behauptete
Produktfreigabe. Ein durch den relaxed Fallback erzeugter Draft, ein Produkt
ohne Regel oder eine inzwischen gesperrte Rule kann final werden.

### Verbindlicher Fixvertrag

1. Draft-Erzeugung erzeugt einen unveränderlichen Eligibility-Snapshot pro
   Position und Gesamtportfolio.
2. Finalisierung verlangt einen vollständigen, grünen Snapshot für exakt
   denselben Run-/Positionshash.
3. Policy definiert, ob zwischenzeitliche Regeländerung zwingend neu bewertet
   oder der zeitpunktgültige Entscheid bewahrt wird; beides muss sichtbar sein.
4. Fehlende Rule-Version, Evidence oder Hash endet 409.
5. `Final` wird in technische Berechnung, fachliche Freigabe und
   kundenseitige Entscheidung getrennt.

## `ELIG-PUBLISH-001` – Unbelegter Finalzustand propagiert weiter

### Beobachtung

Kontrollrunde 24 hat belegt, dass ContractDocument und Signoff-PDF keinen
Suitability- oder Recommendation-Eligibility-Snapshot binden. Kontrollrunde 23
hat belegt, dass Portfolio-Handoff weder Suitability noch Approval oder
Signatur verlangt.

Da Runde 25 zusätzlich zeigt, dass bereits die Produktselektion und
Finalisierung keine vollständige Eligibility erzwingen, besteht eine
durchgehende Kette:

```text
Produktregel nicht/teilweise geprüft
  -> Draft
  -> Final ohne Eligibility
  -> Signoff-Claim ohne Eligibility-Evidence
  -> Handoff ohne Eligibility-Evidence
```

### Risiko

Ein später signiertes oder operativ übergebenes Artefakt kann die fachliche
Freigabe nicht aus seinem eigenen Kontext rekonstruieren. Nach einer
Regeländerung ist auch retrospektiv nicht beweisbar, welche Rule-Version für
welche Position geprüft wurde.

### Verbindlicher Fixvertrag

1. SignedPublicationSnapshot und ExecutionInstructionSnapshot referenzieren
   dieselbe immutable `product_eligibility_snapshot_id` und deren Hash.
2. Positive Claims enthalten Rule-Version, Bewertungszeitpunkt und Verdict-
   Reason-IDs oder verweisen darauf.
3. Änderung von Positionen, Gewichten, Mandatstyp, RA, Knowledge, Rule oder
   Override invalidiert nachgelagerte Freigaben deterministisch.
4. Delivery-/Handoff-Gates prüfen Hash und Freigabestatus serverseitig.
5. Alte Runs ohne Snapshot bleiben sichtbar als Legacy, sind aber nicht neu
   signier- oder ausführbar.

## `ELIG-GOVERNANCE-001` – Kein belastbarer Regel- und Schemavertrag

### Beobachtung

`ProductSuitability` besitzt Produkt-ID, Profilband, fünf Regelwerte, Notes und
Zeitstempel. Es fehlen insbesondere:

- Rule-Version und Supersedes-Beziehung;
- Valid-from/valid-to und Currentness;
- Approvalstatus, Approver und fachlicher Änderungsgrund;
- Jurisdiktions-/Service-Policy-Version;
- deleted-/retired-Semantik;
- Content-Hash und immutable Historie.

Die öffentliche Product-API kann Regeln weder erstellen noch lesen oder
versionieren. Praktisch entstehen Regeln nur beim einmaligen CH-Default-Seed.

Der Raw-SQL-Bootstrap definiert Bounds, Bool-Checks, Profilreihenfolge und eine
Unique-Regel auf `(product_id, profile_from, profile_to)`. ORM und Alembic-
Baseline definieren diese Check-/Unique-Invarianten nicht vollständig. Damit
hängt die zulässige Datenmenge vom Erstellungsweg der Datenbank ab.

### Risiko

Regeln können nicht kontrolliert ausgerollt, historisch rekonstruiert oder
über Dialekte gleich abgesichert werden. Eine In-place-Änderung verändert die
gegenwärtige Interpretation alter Recommendations, ohne deren Bytes oder
Status zu ändern.

### Verbindlicher Fixvertrag

1. Alembic als kanonischen, dialektgeprüften Schemaweg festlegen.
2. Append-only Rule-Versionen mit exakter Gültigkeit und Approval einführen.
3. Überschneidende gültige Profil-/Service-Regeln verhindern.
4. Integer-Bools, Profilbereiche, Maximalanteil und Status auf SQLite und
   PostgreSQL gleich erzwingen.
5. Regeländerung als auditierbares Ereignis mit Actor, Reason und Hash führen.
6. Reads lösen exakt eine zeitpunktgültige freigegebene Rule-Version auf;
   zero-or-many endet fail-closed.

## Zielbild: `ProductEligibilitySnapshot`

### 1. Kanonischer Eingangskontext

Ein Eligibility-Entscheid bindet mindestens:

```text
snapshot_id
mandate_id + client_id + tenant_id + jurisdiction
service_mode + mandate_type_version
recommendation_run_id + recommendation_positions_hash
risk_assessment_id + risk_assessment_hash
knowledge_experience_schema_version + content_hash
target_allocation_id + target_allocation_hash
product_universe_version + as_of
policy_id + cma_id
evaluated_at + evaluator_version
```

### 2. Verdict pro Produktposition

Jede Position enthält unveränderlich:

```text
product_id + product_master_version
product_rule_version_id + rule_hash
target_weight_bps
profile_band_verdict
service_mode_verdict
knowledge_verdict
appropriateness_required + appropriateness_evidence_id/hash
override_required + override_evidence_id/hash
max_position_bps + limit_verdict
overall_verdict
reason_ids[]
```

### 3. Fail-closed Resolver

Die verbindliche Reihenfolge lautet:

1. aktives Mandat, Client, Tenant, Jurisdiktion und Service Mode auflösen;
2. exakt ein aktuelles, nicht gelöschtes RA samt Knowledge-Schema auflösen;
3. exakte Universe- und Product-Versionen bestimmen;
4. je Produkt exakt eine zeitpunktgültige freigegebene Rule-Version auflösen;
5. Profil, Service Mode, Knowledge, Appropriateness und Override bewerten;
6. erst zulässige Kandidaten ranken – niemals nach Ablehnung entspannen;
7. gleiche Produkt-IDs aggregieren;
8. strengstes allgemeines und produktspezifisches Limit prüfen;
9. Positions- und Gesamtverdict hashen und append-only speichern;
10. Finalisierung, Signatur und Handoff gegen denselben Snapshot prüfen.

### 4. State Machine

```text
UNCLASSIFIED
  -> DRAFT_RULE
  -> APPROVED_RULE_VERSION
  -> SUPERSEDED / RETIRED

RECOMMENDATION_DRAFT
  -> ELIGIBILITY_EVALUATED
  -> APPROVED_FOR_ADVICE
  -> CLIENT_DECIDED
  -> SIGNED_PUBLICATION
  -> HANDOFF_READY
```

Kein später Zustand darf ohne seine unmittelbare Vorbedingung entstehen.
Replays sind idempotent; stale Versions- oder Hashwerte liefern 409.

## Verbindliche Testmatrix

### Produktregel und Service Mode

- Advisory erlaubt / Discretionary gesperrt in beiden Mandatstypen testen.
- Advisory gesperrt / Discretionary erlaubt spiegelbildlich testen.
- unbekannter Mandatstyp blockiert.
- fehlende, doppelte, abgelaufene und nicht freigegebene Regel blockiert.
- Profiluntergrenze/-obergrenze sowie jeweils `-1/+1` testen.
- jedes Regel-Bool einzeln und in Kombination testen.

### Knowledge, Appropriateness und Override

- `{}`, malformed JSON und unbekannte Kategorien blockieren.
- `known=0/informed=0`, `known=0/informed=1` und `known=1` gemäß festgelegter
  Policy testen.
- Instrumentkategorie passt nicht zum Produkt.
- Appropriateness fehlt, ist stale, fremd, negativ oder nach Recommendation
  erstellt.
- Override fehlt, ist fremd, abgelaufen, scope-falsch oder nachträglich
  verändert.
- Advisor-Claim ohne verifizierbare Evidence blockiert.

### Selektion, Aggregation und Limits

- kein zulässiger Kandidat liefert 409 statt relaxed Product.
- explizites `advisory_allowed=0` kann durch keinen Fallback zurückkehren.
- gleiche Produkt-ID aus mehreren Sub-Assets wird vor Limitprüfung aggregiert.
- `max_position_bps` exakt erreicht ist zulässig; `+1 bps` blockiert.
- allgemeines und produktspezifisches Limit: strengstes gewinnt.
- Recommendation enthält Rule-/Verdict-/Positionshash.

### Finalisierung, Publikation und Handoff

- Finalisierung ohne Snapshot blockiert.
- Positions-, Gewichts-, RA-, Knowledge-, Service- oder Rule-Tamper blockiert.
- negativer SuitabilityCheck kann nicht parallel als compliant/final erscheinen.
- Regeländerung zwischen Draft und Final gemäß Policy deterministisch behandeln.
- SignedPublication und Handoff verlangen exakt denselben Snapshot-Hash.
- Legacy-Run ohne Snapshot bleibt lesbar, aber nicht neu signier-/ausführbar.

### API, UI und PDF

- Product API zeigt Klassifikationsstatus und Rule-Version.
- UI kann einen unklassifizierten Fonds nicht als freigegeben darstellen.
- Reason-IDs und Verdict sind in Advisor-UI, JSON, PDF und Portal identisch.
- Warnung ist kein Ersatz für blockierende Regel.
- Deep Links und Refresh rekonstruieren denselben Snapshot.

### Schema, Migration und Concurrency

- SQLite- und PostgreSQL-Constraints mit identischer Negativmatrix testen.
- überlappende aktuelle Rule-Versionen verhindern.
- parallele Rule-Approvals beziehungsweise Finalisierungen serialisieren.
- direkte SQL-Tamper-Versuche für Bool, Band, Max, Version und Hash blockieren
  oder beim Read fail-closed erkennen.
- Backfill-Inventar trennt classified, unclassified und ambiguous ohne
  erfundene Freigabe.

Empfohlene neue Testmodule:

```text
tests/test_product_eligibility_rule_semantics.py
tests/test_product_eligibility_service_mode.py
tests/test_product_eligibility_knowledge_appropriateness.py
tests/test_product_eligibility_selection_fail_closed.py
tests/test_product_eligibility_position_limits.py
tests/test_product_eligibility_finalization.py
tests/test_product_eligibility_publication_handoff.py
tests/test_product_eligibility_schema_parity.py
tests/test_product_eligibility_concurrency.py
```

## Empfohlene Umsetzungsreihenfolge

### Phase A – Falsche Freigabe sofort begrenzen

1. `ignore_suitability=True` aus dem produktiven Auswahlpfad entfernen.
2. Produkte ohne gültige Regel als unklassifiziert blockieren.
3. Positive Suitability-/Eligibility-Claims in UI/PDF bis zur Evidencebindung
   neutral formulieren.
4. Reale Finalisierung, Signatur und Handoff bei fehlendem Snapshot sperren.

### Phase B – Fachlichen Regelvertrag festlegen

1. Service-Mode-Mapping verbindlich dokumentieren.
2. Semantik aller fünf ProductSuitability-Felder und ihrer Kombinationen
   definieren.
3. Knowledge-/Experience-Taxonomie und Product-Mapping versionieren.
4. Appropriateness- und Override-Evidence samt Rollen und Zeitlogik definieren.
5. Präzedenz allgemeiner und produktspezifischer Limits festlegen.

### Phase C – Versionierte Datenmodelle und Resolver

1. Rule-Versionen und Approvalworkflow per Alembic einführen.
2. Altbestand read-only inventarisieren.
3. Exactly-one-Rule-Resolver und stabile Reason-IDs implementieren.
4. ProductEligibilitySnapshot samt Positionshash append-only speichern.
5. Dialektgleiche Constraints und Tamper-Checks ergänzen.

### Phase D – Alle Schreib- und Publikationspfade anbinden

1. Create/Import/Update des Produktkatalogs anbinden.
2. Recommendation Generate und Direct Create anbinden.
3. Aggregation und Limits anbinden.
4. Finalisierung mit CAS-/Hash-Precondition anbinden.
5. SignedPublication und Handoff an denselben Snapshot binden.

### Phase E – Abnahme

1. Rote Negativtests vor Happy-Path-UI schreiben.
2. Focused Gate und vollständigen Backend-Gate ausführen.
3. Echte PostgreSQL-Migrations-/Concurrency-Abnahme durchführen.
4. Browser-/DOM-/PDF-Parität prüfen.
5. Legacy-Migration, Backup/Restore, Retention und Audit-Export abnehmen.

## Definition of Done

Kontrollrunde 25 ist erst geschlossen, wenn **alle** Punkte erfüllt sind:

- [ ] Alle fünf ProductSuitability-Felder besitzen operative, getestete
      Semantik.
- [ ] Anlageberatung und Vermögensverwaltung verwenden das richtige Allow-
      Feld.
- [ ] Unbekannte Service Modes blockieren fail-closed.
- [ ] Kein Produkt ohne exakt eine gültige freigegebene Rule-Version ist
      empfehlbar.
- [ ] Product Create/Import/Update und Response zeigen den
      Klassifikationszustand.
- [ ] Der relaxed Suitability-Fallback ist entfernt.
- [ ] Fehlende geeignete Produktabdeckung endet mit einem stabilen 409.
- [ ] Knowledge-/Experience-Daten werden semantisch, nicht nur als JSON-Typ
      geprüft.
- [ ] Appropriateness-Evidence ist bei Pflicht vorhanden, aktuell und exakt
      gebunden.
- [ ] Override-Evidence ist rollenrichtig, scopegebunden, zeitlich gültig und
      append-only.
- [ ] Produktspezifische Limits werden nach Aggregation erzwungen.
- [ ] Der strengste allgemeine/produktspezifische Deckel gewinnt.
- [ ] Jede Position bindet Product-, Rule- und Verdict-Version/Hash.
- [ ] Ein Gesamt-ProductEligibilitySnapshot bindet Run und Positionshash.
- [ ] Finalisierung ohne grünen exakten Snapshot ist unmöglich.
- [ ] Regel-/Kontextänderungen invalidieren oder versionieren deterministisch.
- [ ] Suitability-Audit und Recommendation-Gate verwenden dieselbe Wahrheit.
- [ ] Negative SuitabilityCheck-Resultate können nicht als compliant/final
      erscheinen.
- [ ] SignedPublication und Handoff binden denselben Eligibility-Snapshot.
- [ ] UI, API, PDF und Portal zeigen identische Verdicts und Reason-IDs.
- [ ] Alembic, ORM, SQLite und PostgreSQL besitzen denselben Invariantensatz.
- [ ] Rule-Historie und Eligibility-Snapshots sind unveränderlich auditierbar.
- [ ] Legacy-Bestand wird nicht still als geeignet backgefüllt.
- [ ] Negative API-/Tamper-/Race-/Migrationstests sind grün.
- [ ] Echte PostgreSQL- und Browser-/PDF-Abnahme ist dokumentiert.
- [ ] Frühere Suitability-, Signatur-, Handoff- und Tenant-Blocker bleiben
      getrennt geschlossen nachweisbar.

## Claude-/GPT-Startcheckliste

Vor jeder Implementierung:

1. Diesen Audit vollständig lesen.
2. Danach `FIDLEG-STATE-003`, `TEN-COMP-002` sowie Kontrollrunde 23 und 24
   vollständig lesen.
3. Keine bestehende ProductSuitability-Zeile inplace als neue Wahrheit
   umdeuten.
4. Zuerst Service Mode, Rule-Version, Knowledge-Semantik, Appropriateness,
   Override und Limitpräzedenz schriftlich festlegen.
5. Rote Tests für `discretionary_allowed=0`, fehlende Rule,
   `ignore_suitability`, `max_position_bps+1` und negatives SuitabilityCheck-
   Resultat schreiben.
6. Den relaxed Fallback nicht durch einen anders benannten Warnpfad ersetzen.
7. Einen zentralen Resolver bauen; keine weitere lokale Teilprüfung.
8. Finalisierung, Signatur und Handoff in derselben Änderung auf den Snapshot
   umstellen oder bis dahin blockieren.
9. Alembic-, SQLite- und PostgreSQL-Invarianten gemeinsam entwerfen.
10. Altbestand inventarisieren; keine Freigabe erfinden.
11. Keine ACL-unlesbaren `.pytest_tmp*`-Verzeichnisse betreten oder bereinigen.
12. Kein `git add -A`; nur explizite Manifestpfade stagen.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

- auditierter Head: `fabd8a34de23099addab45a56208042dbb96e426`
- sichtbare tracked/untracked Änderungen: `0`
- beim Statusaufruf ausgegebene ACL-Warnzeilen zu unlesbaren pytest-
  Tempverzeichnissen: `12`
- globale Clean-Aussage: ausdrücklich **nein**
- Produktcode verändert: **nein**
- Tests verändert: **nein**

Die ACL-unlesbaren Verzeichnisse wurden nicht betreten, verändert oder
bereinigt.

### Statische Negativ- und Kontrollflussbelege

Repositoryweite Suchläufe ergaben:

| Suchziel | Ergebnis |
|---|---|
| `discretionary_allowed` | Raw SQL, ORM, Alembic, Default-Seed; kein fachlicher Reader |
| `requires_appropriateness` | Raw SQL, ORM, Alembic, Default-Seed; kein fachlicher Reader |
| `requires_override` | Raw SQL, ORM, Alembic, Default-Seed; kein fachlicher Reader |
| `max_position_bps` | Raw SQL, ORM, Alembic, Default-Seed; kein Selektions-/Aggregations-/Finalisierungsreader |
| `ProductSuitability` in Tests | keine Treffer |
| `ignore_suitability=True` | produktiver Recommendation-Fallback in `portfolio_engine.py:6615` |
| Product Create/Update/Import | keine Rule-Felder und kein atomarer Rule-Write |
| Finalisierungsvalidator | keine Query auf ProductSuitability oder SuitabilityCheck |

Direkte Kontrollflüsse schließen folgende Fälle ohne Interpretation:

1. `product.suitability == []` erreicht `return True`.
2. `ignore_suitability=True` überspringt den gesamten Regelblock.
3. Eine vorhandene Regel wird nur nach Profilband und `advisory_allowed`
   gefiltert.
4. Aggregation summiert Gewichte vor einem Validator, der nur User-Limits
   kennt.
5. Ein frisches RiskAssessment setzt den Suitability-Audit auf compliant, ohne
   SuitabilityCheck-Query.
6. Finalisierung setzt nach ihren Teilprüfungen `result_status="Final"`, ohne
   Eligibility-Resolver.

### Nicht ausgeführter isolierter Runtime-Harness

Ein ausschließlich für `C:\tmp` geplanter isolierter Reproduktionsharness
erhielt keine Tool-Sicherheitsfreigabe. Die Aktion wurde nicht umgangen und es
wurde keine temporäre Datei erzeugt. Deshalb beansprucht dieser Audit für Runde
25 **keine** isolierte Laufzeitreproduktion dieser neuen Negativfälle.

Die P1-Einstufung stützt sich auf direkte Produktionskontrollflüsse,
repositoryweite Negativsuche, Schemavergleich und die bereits separat
reproduzierten angrenzenden Suitability-/Final-/Signatur-/Handoff-Befunde.

### Fokussierter Bestands-Gate

Ausgeführt aus `5eyes-backend` mit externem Basetemp:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp C:\tmp\5eyes-round25-gate-20260904 `
  tests/test_suitability_optin_gate.py `
  tests/test_suitability_gate_all_paths.py `
  tests/test_suitability_fidleg_audit.py `
  tests/test_risk_assessment_suitability_persistence.py `
  tests/test_portfolio_engine_regressions.py `
  tests/test_products_fund_universe.py `
  tests/test_product_universe_filter.py `
  tests/test_product_universe_entries.py `
  tests/test_finalize_mandate_lock.py `
  tests/test_portfolio_handoff.py
```

Ergebnis:

```text
116 passed in 75.92s (0:01:15)
```

Der Gate bestätigt bestehende Regressionen. Er enthält keine Negativfälle für
die vier ungenutzten ProductSuitability-Felder, keine No-Rule-Fail-closed-
Prüfung und keine Eligibility-Bindung von Finalisierung/Publikation/Handoff.

### Letzter vollständiger Backend-Gate

Der letzte vollständig dokumentierte Backend-Gate gehört weiterhin zum
Implementierungscommit `661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4`:

```text
6074 bestanden
0 fehlgeschlagen
10 übersprungen
1 erwartetes XFail
```

Er wurde in dieser Read-only-Runde nicht erneut ausgeführt und ist kein Ersatz
für die fehlende neue Negativtestmatrix oder eine echte PostgreSQL-/Browser-
Abnahme.

### Dokumentationsmanifest dieser Runde

Es dürfen ausschließlich diese fünf Dateien geändert werden:

```text
docs/audits/2026-09-04-product-suitability-appropriateness-and-recommendation-eligibility-integrity-audit.md
docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md
docs/CLAUDE_HANDOFF.md
docs/deploy/README.md
docs/deploy/provisioning-runbook.md
```

Produktcode, Tests, Migrationen und generierte Artefakte gehören ausdrücklich
nicht zum Manifest.

## Schlussentscheidung

Kontrollrunde 25 bestätigt neue release-blockierende P1. 5eyes besitzt
`ProductSuitability` als Datenmodell, aber noch keinen durchgängigen
Product-Eligibility-Vertrag. Vier gespeicherte Pflichtfelder sind operativ
wirkungslos; fehlende Regeln erlauben; eine abgelehnte Regel kann über den
produktiven Fallback wieder zur Empfehlung werden; Knowledge, Finalisierung,
Signatur und Handoff schließen die Lücke nicht.

Die sichere nächste Einheit ist deshalb kein weiterer Warntext und kein
isolierter UI-Fix. Erforderlich ist ein zentraler, versionierter, fail-closed
`ProductEligibilitySnapshot`, der Auswahl, aggregierte Limits, Finalisierung,
signierte Publikation und Handoff an dieselbe nachweisbare Entscheidung bindet.
