# Doku-Manifest

Dieses Manifest legt fest, welche Dokumentation zum aktuellen Produkt gehoert.
Kriterium: Braucht ein Betreiber, Entwickler oder Berater die Datei fuer das
aktuelle Produkt?

- `KEEP`: Produktdoku. Sie geht in den Clean-Room-Export.
- `ARCHIVE`: historisches Material (Planung, Audits, Agenten-Briefings,
  Entwurfsfotos, Bug-Screenshots). Es bleibt in diesem Repository als Archiv
  und wird beim Clean-Room-Export weggelassen.

Erfasst sind jede Datei unter `docs/` und jede `*.md` ausserhalb von `docs/`.
Dateien ausserhalb dieses Umfangs gelten als `KEEP`, sofern sie hier nicht
ausdruecklich als `ARCHIVE` gefuehrt sind.

Vorrang: Ein Eintrag in der Dateitabelle geht einer Regel vor. Regeln erfassen
ausserdem Dateien, die in der Dateitabelle nicht einzeln stehen. Das betrifft
derzeit 3 Dateien, deren Pfad einen frueheren Produktnamen enthaelt.

## Regeln

| Muster | Status | Begruendung |
|---|---|---|
| `docs/planning/` | ARCHIVE | Sprint-Specs, Roadmaps, Standortberichte und Kalibrier-Rohdaten; historisch |
| `docs/audits/` | ARCHIVE | Audit- und Zertifizierungsberichte; historisch |
| `docs/codex_briefs_archive/` | ARCHIVE | Agenten-Briefings |
| `docs/gpt_stage_notes_archive/` | ARCHIVE | Agenten-Notizen |
| `docs/design/` | ARCHIVE | Fotos von Fremdsoftware als Entwurfsvorlage; kein Produktbestandteil |
| `docs/bugs/` | ARCHIVE | Bug-Screenshots aus Einzelfaellen |
| `docs/*.docx` | ARCHIVE | Fachlogik-Basis als Word-Datei, Stand Maerz 2026; abgeloest durch Engine-Spec und Methodik-Doku |

## Dateien

| Pfad | Status | Begruendung |
|---|---|---|
| `README.md` | KEEP | Einstieg ins Repo: Subsysteme, API-Doku-Links, Tests, CI |
| `ares-backend/BACKUP.md` | KEEP | Betreiber: Backup- und Restore-Ablauf des Backends |
| `ares-backend/DSG_EXPORT.md` | KEEP | Betreiber/Berater: DSG-Datenexport (Auskunftsrecht) |
| `ares-backend/README_price_updater.md` | KEEP | Entwickler/Betreiber: Kursaktualisierung |
| `ares-desktop/PACKAGING.md` | KEEP | Entwickler: Packaging der Desktop-App |
| `ares-desktop/README.md` | KEEP | Entwickler: Start und Aufbau der Desktop-Shell |
| `ares-desktop/WINDOWS_RELEASE.md` | KEEP | Entwickler: Windows-Release-Ablauf |
| `ares-desktop/frontend/reporting/DESIGN_SYSTEM.md` | KEEP | Entwickler: Design-System der Reporting-App (von Test gelesen) |
| `ares-desktop/frontend/reporting/README.md` | KEEP | Entwickler: Aufbau und Token-Handoff der Reporting-App |
| `docs/AUTO_UPDATE.md` | KEEP | Betreiber: Auto-Update der Desktop-App (von Test gelesen) |
| `docs/BERATER_ONBOARDING.md` | KEEP | Berater: Erst-Setup (von Test gelesen) |
| `docs/BERATER_README.md` | KEEP | Berater: Handbuch zur Bedienung (von Test gelesen) |
| `docs/CHANGELOG_TEMPLATE.md` | KEEP | Entwickler: Changelog-Vorlage (von Test gelesen) |
| `docs/CLAUDE_CODEX_SCOPE_SPLIT_NO_ASSET_ALLOCATION.md` | ARCHIVE | Agenten-Aufgabenteilung |
| `docs/CLAUDE_HANDOFF.md` | ARCHIVE | Agenten-Handoff |
| `docs/CLIENT_DATA_STORAGE_AND_PROCESSING.md` | KEEP | Betreiber/Datenschutz: wo Kundendaten gespeichert und verarbeitet werden |
| `docs/CODEBOOK_RUNTIME_PRIORITY.md` | ARCHIVE | Agenten-Arbeitsnotiz |
| `docs/CODEX_WIP.md` | ARCHIVE | Agenten-Koordination (Datei-Trennung, Race-Recovery) |
| `docs/CODE_SIGNING.md` | KEEP | Entwickler: Code-Signing (von Test gelesen) |
| `docs/DAILY_MARKET_DATA.md` | KEEP | Betreiber: taeglicher Marktdaten-Refresh (von Test gelesen) |
| `docs/DATA_PIPELINE_STATUS.md` | KEEP | Entwickler/Betreiber: Stand und Diagnose der Datenpipeline (von Test gelesen) |
| `docs/DOCS_MANIFEST.md` | KEEP | Dieses Manifest; steuert den Clean-Room-Export |
| `docs/E2E_TESTING.md` | KEEP | Entwickler: End-to-End-Tests (von Test gelesen) |
| `docs/GLOSSAR.md` | KEEP | Alle: Fachbegriffe und verbotene Begriffe (von Test gelesen) |
| `docs/GPT_STAGE3_NOTES.md` | ARCHIVE | Agenten-Notizen |
| `docs/GPT_STAGE4_NOTES.md` | ARCHIVE | Agenten-Notizen |
| `docs/GPT_STAGE5_NOTES.md` | ARCHIVE | Agenten-Notizen |
| `docs/GPT_STAGE7_NOTES.md` | ARCHIVE | Agenten-Notizen |
| `docs/GPT_STAGE8_NOTES.md` | ARCHIVE | Agenten-Notizen |
| `docs/I18N.md` | KEEP | Entwickler: Internationalisierung (von Test gelesen) |
| `docs/MARKET_DATA_PROVIDER_STRATEGY.md` | KEEP | Entwickler/Betreiber: Rollen der Marktdaten-Provider |
| `docs/MULTI_PLATFORM_BUILD.md` | KEEP | Entwickler: Builds fuer Windows, macOS, Linux (von Test gelesen) |
| `docs/MUTATION_TESTING.md` | KEEP | Entwickler: Mutation-Testing (von Test gelesen) |
| `docs/OFFLINE_MODE.md` | KEEP | Entwickler: Offline-Modus der Reporting-App (von Test gelesen) |
| `docs/PENTEST_PREPARATION.md` | KEEP | Betreiber: Vorbereitung externer Pentest (von Test gelesen) |
| `docs/PROPERTY_BASED_TESTING.md` | KEEP | Entwickler: Property-Based-Testing (von Test gelesen) |
| `docs/RELEASE_TAGS.md` | KEEP | Entwickler: Release-Tag-Strategie (von Test gelesen) |
| `docs/REPO_HYGIENE_2026-06-04.md` | ARCHIVE | Bestandsaufnahme Stashes/Branches vom 2026-06-04 |
| `docs/RISK_QUESTIONNAIRE_SOURCE_NOTES.md` | KEEP | Entwickler/Compliance: Quellenabgleich des Risikofragebogens |
| `docs/SCHEMA_MIGRATIONS.md` | KEEP | Entwickler: Alembic-Migrationen (von Test gelesen) |
| `docs/SQLCIPHER_PREP.md` | KEEP | Betreiber: SQLCipher-Verschluesselung |
| `docs/STORYBOOK.md` | KEEP | Entwickler: Storybook (von Test gelesen) |
| `docs/adr/ADR-001-aggregator-pattern.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-002-compliance-stack-3-layer.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-003-anlagephilosophie-no-market-timing.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-004-editorial-no-recharts.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-005-free-data-pipeline.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-006-drift-tests.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-007-multi-tenancy-strategy.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-008-html-monolith-migration.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-009-3-tier-hosting-architecture.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-010-provider-discovery-pattern.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-011-engine-methodik-2026-06.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-012-postgres-rls-tenant-isolation.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-013-tax-plugin-architecture.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/ADR-014-engine-module-split-plan.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/adr/README.md` | KEEP | Architekturentscheid (Ordner wird von Test gelesen) |
| `docs/architecture/tax-plugin-sdk.md` | KEEP | Entwickler: Schnittstelle fuer Steuer-Plugins |
| `docs/audits/2026-05-25-advisory-report-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-05-25-final-audit-after-briefings.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-05-25-owner-handover.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-02-monolith-inventory.json` | KEEP | Generierter Inventar-Snapshot des Monolithen; Soll-Wert fuer test_monolith_inventory_stable und audit_html_monolith.py |
| `docs/audits/2026-06-07-b1-sub-allocation-aware-implementation.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-07-b2-per-path-tax-implementation.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-07-b3-multi-currency-implementation.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-07-cashflow-in-mc-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-07-strategic-pdf-design-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-08-option-c-renditeziel-tilt.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-10-admin-menu-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-06-11-engine-validation-findings.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-25-asset-allocation-post-commit-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-25-auth-execution-operations-followup-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-26-data-lifecycle-crypto-browser-followup-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-26-electron-runtime-release-security-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-advisory-workflow-and-temporal-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-client-classification-and-compliance-state-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-market-price-and-fx-reference-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-product-master-data-and-exposure-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-recovery-link-mail-transport-security-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-reference-data-read-authorization-and-model-basis-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-request-ingestion-and-resource-governance-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-review-trigger-and-reassessment-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-27-tenant-and-compliance-reference-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-28-historical-return-schema-and-drift-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-08-31-performance-attribution-context-and-model-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-04-product-suitability-appropriateness-and-recommendation-eligibility-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-05-tax-model-regime-parameter-and-after-tax-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-07-mortality-longevity-retirement-and-decumulation-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-14-direct-property-mortgage-amortization-and-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-16-liquidity-instrument-availability-yield-and-funding-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-21-alternative-custom-asset-valuation-tradability-and-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-22-stochastic-estimator-correlation-cache-and-stress-reproducibility-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-23-solver-goal-maximization-and-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-equity-valuation-kgv-calibration-horizon-and-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-goal-sensitivity-common-baseline-and-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-manual-target-band-and-publication-semantics-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-04-target-allocation-editor-context-and-release-lifecycle-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-b2b-accessibility-golden-path-and-pdf-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-b2b-claims-dark-patterns-commercial-surfaces-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-b2b-iam-lifecycle-privileged-access-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-b2b-incident-response-and-resilience-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-b2b-privacy-governance-reconciliation-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-b2b-vendor-data-egress-license-sbom-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-parity-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-core-coverage-benchmark-governance-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-core-coverage-depotcheck-end-to-end-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-core-coverage-portfolio-construction-recommendation-reconciliation-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-publication-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/audits/2026-10-05-sub-asset-risk-aggregation-cache-and-replay-integrity-audit.md` | ARCHIVE | Audit-Bericht, historisch |
| `docs/bugs/Gesamtvermoegen_Depot_komische_Zeichen.png` | ARCHIVE | Bug-Screenshot |
| `docs/bugs/Neues_Mandat_Anlegen_Button_verbessern.png` | ARCHIVE | Bug-Screenshot |
| `docs/cma_import_workflow.md` | KEEP | Betreiber/CIO: Quartals-Update der Kapitalmarktannahmen |
| `docs/codex_briefs_archive/CODEX_BRIEF_RP_ETF.md` | ARCHIVE | Agenten-Material |
| `docs/codex_briefs_archive/CODEX_DEBUG_GUIDE.md` | ARCHIVE | Agenten-Material |
| `docs/codex_briefs_archive/CODEX_GUIDE.md` | ARCHIVE | Agenten-Material |
| `docs/codex_briefs_archive/CODEX_SESSION_BRIEF.md` | ARCHIVE | Agenten-Material |
| `docs/codex_briefs_archive/CODEX_TASKS.md` | ARCHIVE | Agenten-Material |
| `docs/codex_briefs_archive/README.md` | ARCHIVE | Agenten-Material |
| `docs/compliance/2026-10-05-trust-compliance-accessibility-readiness-plan.md` | ARCHIVE | Readiness-Plan, historisch |
| `docs/compliance/avv-template.md` | KEEP | Betreiber: Vorlage Auftragsverarbeitungsvertrag |
| `docs/compliance/dsfa-datenschutz-folgenabschaetzung.md` | KEEP | Betreiber: Vorlage Datenschutz-Folgenabschaetzung |
| `docs/compliance/finma-outsourcing-anzeige.md` | KEEP | Betreiber: FINMA-Outsourcing-Pruefung und Anzeige-Vorlage |
| `docs/compliance/shadow-vergleich-2026-08-05-gesamt.md` | ARCHIVE | Einmaliger Shadow-Report vom 2026-08-05 |
| `docs/compliance/shadow-vergleich-template.md` | KEEP | Berater/Compliance: Vorlage Shadow-Vergleichs-Report |
| `docs/compliance/stage8-berater-runbook.md` | KEEP | Berater: Runbook zum Default-Mode-Wechsel |
| `docs/data_pipeline_README.md` | KEEP | Entwickler/Betreiber: Index der Datenpipeline (von Test gelesen) |
| `docs/data_pipeline_activation.md` | KEEP | Betreiber: Aktivierung der Datenpipeline |
| `docs/decisions/SHADOW_STOCHASTIC_DEFAULT.md` | KEEP | Entscheid zum Default-Optimizer-Modus (von Test gelesen) |
| `docs/deploy/.env.staging.example` | KEEP | Betreiber: Beispiel-Env fuer Staging (von Test gelesen) |
| `docs/deploy/Caddyfile` | KEEP | Betreiber: Reverse-Proxy-Konfiguration (von Test gelesen) |
| `docs/deploy/README.md` | KEEP | Betreiber: Deployment fuer externen Zugriff |
| `docs/deploy/ares.service` | KEEP | Betreiber: systemd-Unit (von Test gelesen) |
| `docs/deploy/disaster-recovery-plan.md` | KEEP | Betreiber: Disaster-Recovery-Plan |
| `docs/deploy/postgres-migrations.md` | KEEP | Betreiber: Postgres-Schema-Migrationen |
| `docs/deploy/promote_operator.py` | KEEP | Betreiber: Werkzeug zur Operator-Freischaltung (von Test gelesen) |
| `docs/deploy/provisioning-runbook.md` | KEEP | Betreiber: Provisioning- und Onboarding-Runbook |
| `docs/deploy/start-external-staging.ps1` | KEEP | Betreiber: Startskript externer Test mit Staging-DB (von Test gelesen) |
| `docs/deploy/start-external.ps1` | KEEP | Betreiber: Startskript externer Zugriff (von Test gelesen) |
| `docs/deployment/README.md` | KEEP | Betreiber: Hosting-Rezept je Tier |
| `docs/deployment/phase1-cloudflare-tunnel.md` | KEEP | Betreiber: Hosting-Rezept je Tier |
| `docs/deployment/tier1-self-hosted.md` | KEEP | Betreiber: Hosting-Rezept je Tier |
| `docs/deployment/tier2-shared-cloud.md` | KEEP | Betreiber: Hosting-Rezept je Tier |
| `docs/deployment/tier3-dedicated.md` | KEEP | Betreiber: Hosting-Rezept je Tier |
| `docs/design/08f319d0-a9ec-4983-adbb-79888a9c80dc.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/1aaa5ed7-edb2-4329-9a9a-5c399f3f4a09.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/1f819227-d08e-4929-b5a4-481c3ee99343.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/22a9c56c-bd24-4a4b-bb48-1caaf37b5c70.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/27475fa8-a04e-4ce4-a332-1fc36a0eb988.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/2e7822a9-7bd6-4c4f-bc5b-166451f9f0ce.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/36bc2ed5-b98d-450e-8d96-3f8f95430f82.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/3b393bb3-d7b9-47a1-bb0e-383a48a8c47b.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/43d4b5a6-4914-4ae8-a40e-5b949568e748.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/45b9d497-222c-4411-844a-08cba84525f2.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/566a24f3-46f7-4143-bf0d-161dedcf5c02.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/5f10ecb3-e794-4698-bc9b-b0a9b7e7344f.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/6126e78b-2501-4c00-b5c7-2a5c95402b4f.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/65e3e9bb-c413-42dd-ae79-8933756c3705.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/6754b52c-1ed6-4bef-b754-d7e96cdaa63e.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/82ffe680-df4e-4f08-9d7a-70c84e626924.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/8344ffea-c0aa-42a4-bdd8-5fc921a55bcd.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/d02f646d-4eb0-479e-a00a-4145e9b8cbb1.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/d8b18346-f3fa-4bc7-88ff-df9aed93cc79.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/df362f11-9730-410a-a7c0-b7232237b7d0.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/df874157-6b09-4746-b412-9783f99944c0.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/e5d96df7-8f42-4e49-b716-e68e425265f0.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/design/ec746e46-ae0c-4e21-bf0b-4357d28eb504.jpg` | ARCHIVE | Foto einer Fremdsoftware |
| `docs/engine-spec.md` | KEEP | Entwickler/Methodik: mathematische Grundlage der Engine |
| `docs/gpt_stage_notes_archive/GPT_STAGE4_NOTES.md` | ARCHIVE | Agenten-Material |
| `docs/gpt_stage_notes_archive/GPT_STAGE5_NOTES.md` | ARCHIVE | Agenten-Material |
| `docs/gpt_stage_notes_archive/README.md` | ARCHIVE | Agenten-Material |
| `docs/handbook/2026-07-changelog.md` | KEEP | Berater: Aenderungsprotokoll zum Handbuch |
| `docs/handbook/berater-handbuch.md` | KEEP | Berater: Handbuch |
| `docs/methodology/2026-06-19-tax-plugin-integration-interface.md` | KEEP | Methodik: Schnittstelle Steuer-Plugin zur Engine |
| `docs/methodology/2026-07-19-methodik-whitepaper.md` | KEEP | Methodik: Whitepaper fuer Aufsicht, Compliance und Berater |
| `docs/methodology/engine-whitepaper.md` | KEEP | Methodik: Beschreibung der Anlagestrategie-Engine |
| `docs/planning/2026-04-01-audit-log-viewer.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-01-decision-template-modal.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-01-product-market-override.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-01-user-management.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-02-cashflow-projection.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-02-monte-carlo-fan-chart.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-02-rebalancing-trade-sheet.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-15-portfolio-umsetzen-review.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-16-portfolio-etf-phase1.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-16-risikoprofil-ueberarbeitung.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-17-cma-korrekturen.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-17-goal-architecture-pk-aligned.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-17-high1-willingness-profile.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-17-krit2-portfolio-engine-fixes.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-17-krit3-override-warning.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-17-scoring-parameter-editor.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-04-18-goal-architecture-pk-aligned.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-05-fe-optimizer-panel-spec.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-05-stochastic-optimizer-spec.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-06-integration-branch-spec.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-06-merge-plan-three-branches.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-06-phase6-fe-implementation-patch.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-06-phase7-pdf-export-spec.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-06-risk-free-rate-spec.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-06-sprint-a-fe-patch.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-06-status-und-naechste-schritte.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-11-pdf-replikation.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-3-tax-plugin-system.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-4-bfs-mortality.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-5-pdf-engine.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-6-nelson-siegel.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-7-kgv-mean-reversion.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-8-risk-premium.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-sprint-9-multi-currency.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-17-standortanalyse-v2.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-18-sprint-14-pdf-vollausbau.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-22-sprint-u-p19-daily-backtest.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-23-stochastic-goal-engine-spec.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-23-stochastic-shadow-comparison-methodology.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-23-stochastic-ux-and-messages-spec.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-24-foundation-smoketest-finding.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-24-sprint-u-p20-depot-check-soll-drift.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-24-sprint-u-p21-advisory-report-backend.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-24-sprint-u-p22-1-reporting-react-scaffold.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-24-stochastic-stage9-spec-solver-robustifizierung.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p23-advisory-frontend-phase1.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p24-advisory-frontend-phase2-charts.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p25-advisory-frontend-phase3-final.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p26-advisory-report-pdf.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p27-electron-window-integration.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p28-mandate-report-notes.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p29-state-of-art-extensions.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-codex-sprint-u-p30-ausgangslage-derived-fields.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-05-25-sprint-u-p22-6-mainapp-handoff.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-06-02-sprint-u-35-modul-split-plan.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-06-12-external-access-rollout-plan.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-06-14-roadmap-master.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-06-18-roadmap-200-detailliert.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-06-24-audit-findings-backend-ops.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-07-03-top10-implementation-specs.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-07-09-first-client-readiness-specs.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-07-18-cto-standortbericht.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-07-18-umsetzungsplan-verbesserungen.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-07-23-independent-security-audit.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-08-03-ch-fertigstellung-internationalisierung.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-08-03-launch-readiness-update.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-08-04-mega-audit-standortbericht.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-08-15-dsg-art32-erasure-workflow.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-08-15-stochastic-optimizer-pr-description.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-08-17-consolidated-pr-description.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-04-goal-engine-time-lifecycle-scheduler-validation-unification.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-14-saa-stability-resampling.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-18-house-prior-kappa-calibration.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/holdout/holdout_A_ausg_spar.jsonl` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/holdout/holdout_B_kons_entn.jsonl` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/holdout/holdout_C_wachs_entn.jsonl` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/holdout/holdout_D_wachs_spar.jsonl` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/holdout/holdout_E_ausg_entn.jsonl` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/holdout/holdout_summary.json` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/results_kappa_misspec.txt` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/results_main.txt` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_manifest.json` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/kappa_A_ausg_spar.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/kappa_B_kons_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/kappa_C_wachs_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/kappa_D_wachs_spar.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/kappa_E_ausg_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_A_ausg_spar_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_A_ausg_spar_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_A_ausg_spar_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_B_kons_entn_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_B_kons_entn_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_B_kons_entn_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_C_wachs_entn_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_C_wachs_entn_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_C_wachs_entn_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_D_wachs_spar_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_D_wachs_spar_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_D_wachs_spar_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_E_ausg_entn_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_E_ausg_entn_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/mis300_E_ausg_entn_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_A_ausg_spar_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_A_ausg_spar_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_A_ausg_spar_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_B_kons_entn_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_B_kons_entn_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_B_kons_entn_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_C_wachs_entn_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_C_wachs_entn_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_C_wachs_entn_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_D_wachs_spar_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_D_wachs_spar_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_D_wachs_spar_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_E_ausg_entn_0.90.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_E_ausg_entn_1.00.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/misspec_E_ausg_entn_1.10.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/seeds_A_ausg_spar.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/seeds_B_kons_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/seeds_C_wachs_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/seeds_D_wachs_spar.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/seeds_E_ausg_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_A_ausg_spar.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_A_ausg_spar_fixed.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_B_kons_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_B_kons_entn_fixed.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_C_wachs_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_C_wachs_entn_fixed.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_D_wachs_spar.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_D_wachs_spar_fixed.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_E_ausg_entn.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-kappa-calibration/tuning_raw/sweep_E_ausg_entn_fixed.jsonl.gz` | ARCHIVE | Kalibrier-Rohdaten eines abgeschlossenen Laufs |
| `docs/planning/2026-10-18-house-prior-v6.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-18-importance-sampling-ess.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-18-maximize-goal-and-hardness.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-18-objective-normalization.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-18-resampling-statistics-contracts-v7.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-18-vorsorge-benefit-reconciliation.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-19-reserve-funding-ledger.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/2026-10-22-analytic-gradients.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/CLAUDE_SPEC_TEMPLATE.md` | ARCHIVE | Agenten-Vorlage |
| `docs/planning/CODEX_IMPLEMENTATION_TEMPLATE.md` | ARCHIVE | Agenten-Vorlage |
| `docs/planning/README.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/REVIEW_CHECKLIST.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/planning/codex-task-2026-06-18-postgres-rls.md` | ARCHIVE | Planung/Spec, historisch |
| `docs/status_snapshot_2026-05-14.md` | ARCHIVE | Statusbericht, historisch |
| `docs/status_snapshot_2026-05-17.md` | ARCHIVE | Statusbericht, historisch |
| `docs/status_snapshot_2026-05-23.md` | ARCHIVE | Statusbericht, historisch |
| `docs/wip_cleanup_2026-05-13.md` | ARCHIVE | Aufraeumprotokoll, historisch |

Summe: 79 KEEP, 273 ARCHIVE (3 davon nur ueber Regeln erfasst).
