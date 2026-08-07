from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from database import Base


class ReviewTrigger(Base):
    __tablename__ = "review_triggers"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    trigger_type = Column(String, nullable=False)
    trigger_name = Column(String, nullable=False)
    threshold_bps = Column(Integer)
    frequency = Column(String)
    status = Column(String, nullable=False, default="Aktiv")
    next_due_at = Column(String)
    last_triggered_at = Column(String)
    triggered_value = Column(String)
    triggered_at = Column(String)
    triggered_notes = Column(String)
    calendar_exported = Column(Integer, nullable=False, default=0)
    calendar_exported_at = Column(String)
    is_system = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="review_triggers")


class ContractDocument(Base):
    __tablename__ = "contract_documents"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    document_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content_json = Column(String)
    pdf_path = Column(String)
    checksum_sha256 = Column(String)
    pdf_generated_at = Column(String)
    status = Column(String, nullable=False, default="Entwurf")
    signed_by_advisor = Column(Integer, nullable=False, default=0)
    signed_by_client = Column(Integer, nullable=False, default=0)
    signed_at = Column(String)
    # 2026-08-05 (User-Direktive, E-Signing): signed_by_advisor/client waren
    # reine Checkbox-Flags ohne jede tatsaechliche Signatur -- jeder
    # authentifizierte Advisor-User konnte sie fuer jeden setzen, ohne dass
    # je eine Unterschrift erfasst wurde. Jetzt zusaetzlich ein echtes
    # Signatur-Artefakt pro Unterzeichner (Canvas-gezeichnetes PNG als
    # data:-URI, analog zum bestehenden QR-Code-data:-URI-Muster in
    # routers/auth.py::twofa_setup).
    signature_advisor_image = Column(String)
    signature_advisor_signer_name = Column(String)
    signature_advisor_signed_at = Column(String)
    signature_advisor_ip = Column(String)
    signature_client_image = Column(String)
    signature_client_signer_name = Column(String)
    signature_client_signed_at = Column(String)
    signature_client_ip = Column(String)
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="contract_documents")
    creator = relationship("User")


class AdvisoryLog(Base):
    """Beratungsprotokoll-Eintrag (FINMA / FIDLEG Art. 16+17).

    Pro Mandanten-Termin **ein Eintrag** mit allen pflichtgemäßen Angaben:
    Zeitpunkt + Dauer, Kommunikationskanal, Anwesende, besprochene Themen,
    erteilte Risiko-/Kostenhinweise, Eignungsprüfungs-Bezug, Entscheid, Hash.

    Versions-Geschichte: Updates erstellen *neue* Zeile mit höherer `version`
    und `supersedes_id` zeigt auf den Vorgänger. Der jüngste Eintrag einer
    Kette ist `superseded_by_id IS NULL`. Damit keine Daten je verloren gehen
    (FINMA-Pflicht: Aufbewahrung 10 Jahre, Integritäts-Audit).
    """

    __tablename__ = "advisory_log"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    entry_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String)
    decision = Column(String)
    trigger_id = Column(String)
    recommendation_run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=True)
    status = Column(String, nullable=False, default="Empfohlen")
    advisor_id = Column(String, ForeignKey("users.id"), nullable=False)
    client_signed = Column(Integer, nullable=False, default=0)
    client_signed_at = Column(String)
    document_id = Column(String)
    entry_date = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    # --- FINMA-Erweiterung (Sprint U-FINMA-2.1, 2026-05-28) ---
    # Zeitpunkt + Dauer (FIDLEG Art. 16)
    entry_datetime = Column(String)  # ISO Y-m-dTH:M:S.fZ — präziser als entry_date
    duration_minutes = Column(Integer)

    # Kommunikationsmedium (entscheidet über Hinweispflichten)
    # Erlaubt: 'persoenlich' | 'video' | 'telefon' | 'schriftlich' | 'hybrid'
    communication_channel = Column(String)

    # Beratungs-Sprache + Ort (für Remote-vs-in-person-Audit)
    language = Column(String)  # 'de' | 'fr' | 'it' | 'en'
    location = Column(String)

    # Anwesende neben Berater (JSON-Array: [{"role": "client", "name": "..."}, ...])
    participants_json = Column(String)

    # Strukturierte Themen-Liste (JSON-Array of strings)
    topics_json = Column(String)

    # Erteilte Risiko-Hinweise (JSON-Array of strings)
    risk_warnings_given_json = Column(String)

    # Wurden Ex-ante Kosten kommuniziert? (FIDLEG Pflicht)
    cost_disclosure_given = Column(Integer, nullable=False, default=0)

    # Offengelegte Interessenkonflikte (JSON-Array of conflict_of_interest_disclosures.id)
    conflict_disclosure_ids_json = Column(String)

    # Bezug zur Eignungsprüfung zum Zeitpunkt der Beratung
    suitability_check_id = Column(String, ForeignKey("suitability_checks.id"), nullable=True)

    # Integritäts-Hash über Eintragsinhalt (FINMA-Audit-Trail)
    integrity_hash = Column(String(64))

    # Aufbewahrungs-Pflicht (= entry_datetime + 10 Jahre, ISO-Date)
    retain_until = Column(String)

    # Versions-Geschichte
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String, ForeignKey("advisory_log.id"), nullable=True)
    superseded_by_id = Column(String, ForeignKey("advisory_log.id"), nullable=True)

    # Read-Audit (FINMA verlangt Access-Tracking bei sensiblen Daten)
    last_read_at = Column(String)
    last_read_by = Column(String, ForeignKey("users.id"), nullable=True)

    mandate = relationship("Mandate", back_populates="advisory_log")
    advisor = relationship("User", foreign_keys=[advisor_id])
    recommendation_run = relationship("RecommendationRun")


class ConflictOfInterestDisclosure(Base):
    __tablename__ = "conflict_of_interest_disclosures"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    conflict_type = Column(String, nullable=False)
    description = Column(String, nullable=False)
    inducement_provider = Column(String)
    inducement_amount_rappen = Column(Integer)
    inducement_frequency = Column(String)
    disclosed_to_client = Column(Integer, nullable=False, default=0)
    disclosed_at = Column(String)
    client_acknowledged = Column(Integer, nullable=False, default=0)
    client_acknowledged_at = Column(String)
    mitigation_action = Column(String)
    document_id = Column(String)
    # 2026-07-27 (Retrozessions-Feature): FIDLEG/BGE 132 III 460 verlangt
    # Herausgabe von Retrozessionen an den Kunden, AUSSER er hat vorgaengig,
    # in Kenntnis der ungefaehren Groessenordnung, gueltig darauf verzichtet.
    # reimbursed_to_client=1 -> Retrozession wird tatsaechlich zurueckerstattet
    # (mindert den ausgewiesenen Kostenausweis). =0 -> Verzicht dokumentiert,
    # Berater behaelt sie (bleibt aber offenlegungspflichtig, siehe
    # services/cost_disclosure.py). waiver_document_id referenziert das
    # unterschriebene Verzichts-Dokument fuer Beweiszwecke.
    reimbursed_to_client = Column(Integer, nullable=False, default=0)
    waiver_document_id = Column(String)
    disclosed_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="conflict_disclosures")
    discloser = relationship("User")


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True)
    isin = Column(String)
    symbol = Column(String)
    lookup_mode_override = Column(String)
    lookup_symbol_override = Column(String)
    figi = Column(String)
    composite_figi = Column(String)
    share_class_figi = Column(String)
    exchange_code = Column(String)
    market_sector = Column(String)
    security_type = Column(String)
    security_type2 = Column(String)
    mapping_provider = Column(String)
    mapping_resolved_at = Column(String)
    reference_data_provider = Column(String)
    reference_data_refreshed_at = Column(String)
    product_name = Column(String, nullable=False)
    provider = Column(String)
    product_type = Column(String, nullable=False)
    asset_class = Column(String, nullable=False)
    sub_asset_class = Column(String)
    currency = Column(String, nullable=False, default="CHF")
    ter_bps = Column(Integer)
    sfdr_class = Column(String)
    esg_rating = Column(String)
    # Sprint U-P10 (2026-05-20): Depot-Check / Diversifikations-Tiefe.
    # JSON-Strings mit {ISO-Code/Sektor: bps}. Σ jeder JSON-Map = 10000 bps (100%).
    # Wenn NULL: Engine nutzt Default-Proxy aus sub_asset_class (siehe
    # services/product_exposures.py).
    country_exposure_json = Column(String)   # {"CH": 4500, "US": 3500, "EU": 2000}
    sector_exposure_json = Column(String)    # GICS: {"Tech": 2500, "Financial": 1500, ...}
    currency_exposure_json = Column(String)  # {"CHF": 5000, "USD": 3000, "EUR": 2000}
    duration_years_x10 = Column(Integer)     # Bonds: 50 = 5.0 Jahre Duration
    credit_rating = Column(String)           # 'AAA','AA','A','BBB','BB','B','CCC','NR'
    esg_score_x10 = Column(Integer)          # 0-1000 = 0.0-100.0 (numerischer Score)
    liquidity_tier = Column(String)          # 'daily','weekly','monthly','illiquid'
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)
    # 2026-08-01 (Laender-Skalierung, Cross-Jurisdiktions-Leck-Fix): Land, fuer
    # das dieses Produkt kuratiert wurde (z.B. "CH", "DE"). NULL = "CH"
    # (Backwards-Compat, gleiches Nullable-Pattern wie Mandate.jurisdiction).
    # ZWECK: _filter_products_by_universe() in services/portfolio_engine.py
    # nutzt dieses Feld als FALLBACK-Filter, wenn fuer ein Mandat KEINE
    # ProductUniverseEntry-Zeilen existieren (der Normalfall) -- ohne dieses
    # Feld wuerde ein CH-Mandat ohne eigene Kuratierung automatisch JEDES
    # in der Installation angelegte Nicht-CH-Produkt sehen (echtes, per
    # Integrationstest gefundenes Datenleck: tests/test_de_onboarding_
    # integration.py::test_ch_mandate_unaffected_by_coexisting_de_fixtures_
    # in_same_db). Aendert NICHTS am CH-Verhalten, solange kein Produkt
    # explizit mit jurisdiction != "CH"/NULL angelegt wird (Golden-Snapshot-
    # Test bleibt gruen, da das Bestandskatalog komplett NULL ist).
    jurisdiction = Column(String)
    # 2026-08-05 (User-Direktive, Fondsuniversum): "jedes Assetmanagement
    # seine eigenen Fonds der Software fuettern". NULL = globaler/geteilter
    # Katalog (Marktdaten-Pipeline-Seed, Default-Produktliste in
    # services/portfolio_engine.py -- UNVERAENDERT, diese Funktion setzt nie
    # tenant_id). Gesetzt = privat fuer genau diesen Tenant, ueber
    # routers/review.py::create_product serverseitig aus current_user
    # abgeleitet (NIE vom Client-Payload uebernommen -- sonst Tenant-Spoofing
    # moeglich). Gleiches additives, rueckwaerts-kompatibles Nullable-Muster
    # wie jurisdiction oben.
    tenant_id = Column(String, ForeignKey("tenants.id"))

    suitability = relationship("ProductSuitability", back_populates="product")
    price_history = relationship("PriceHistory", back_populates="product")


class ProductUniverseEntry(Base):
    """2026-07-27 (Laender-Skalierung, Fonds-Kuratierung): kuratierte
    Positivliste "welche Fonds sind fuer Tenant X in Jurisdiktion Y zulaessig"
    -- ersetzt fuer den Optimizer den kompletten globalen Produktkatalog
    durch eine engere Auswahl, SOBALD mindestens ein Eintrag fuer ein
    (tenant_id, jurisdiction)-Paar existiert. Deckt zwei Anwendungsfaelle ab:
    (1) eine Verwaltung will fuer ein bestimmtes Land NUR dort zulaessige/
    vertriebene Fonds als Kandidaten haben, (2) eine Verwaltung hat eigene
    Fonds oder ausgehandelte, tiefere Gebuehren-Konditionen fuer ein Produkt
    (override_ter_bps ersetzt product.ter_bps fuer die Kostenberechnung
    dieses Tenants -- siehe services/cost_disclosure.py).

    Rueckwaerts-kompatibel: existiert fuer ein (tenant_id, jurisdiction)-Paar
    KEIN Eintrag (der Normalfall fuer alle Bestandsmandate/CH), bleibt der
    volle globale Katalog unveraendert nutzbar -- diese Tabelle greift nur,
    wenn ein Admin explizit mindestens einen Eintrag anlegt.
    """
    __tablename__ = "product_universe_entries"
    __table_args__ = (
        Index(
            "ix_product_universe_tenant_jurisdiction",
            "tenant_id", "jurisdiction",
        ),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    jurisdiction = Column(String, nullable=False)  # z.B. "CH", "DE"
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    # NULL = nutze product.ter_bps unveraendert. Gesetzt = diese Verwaltung
    # hat fuer dieses Produkt eine eigene, ausgehandelte Gebuehr -- ersetzt
    # product.ter_bps AUSSCHLIESSLICH fuer diesen Tenant in der Kosten-
    # berechnung (services/cost_disclosure.py), das globale Produkt selbst
    # bleibt unveraendert (kein Cross-Tenant-Seiteneffekt).
    override_ter_bps = Column(Integer)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    product = relationship("Product")


class ProductSuitability(Base):
    __tablename__ = "product_suitability"

    id = Column(String, primary_key=True)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    profile_from = Column(Integer, nullable=False)
    profile_to = Column(Integer, nullable=False)
    advisory_allowed = Column(Integer, nullable=False, default=1)
    discretionary_allowed = Column(Integer, nullable=False, default=1)
    requires_appropriateness = Column(Integer, nullable=False, default=0)
    requires_override = Column(Integer, nullable=False, default=0)
    max_position_bps = Column(Integer)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    product = relationship("Product", back_populates="suitability")


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("product_id", "price_date", "source", name="uq_price_history_product_date_source"),
        Index("ix_price_history_product_date", "product_id", "price_date"),
    )

    id = Column(String, primary_key=True)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    price_date = Column(String, nullable=False)
    price_rappen = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="CHF")
    source = Column(String, nullable=False, default="yfinance")
    fetched_at = Column(String, nullable=False)

    product = relationship("Product", back_populates="price_history")


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    assessment_id = Column(String)
    target_allocation_id = Column(String)
    policy_id = Column(String, ForeignKey("optimizer_policies.id"), nullable=False)
    capital_market_assumptions_id = Column(String)
    run_type = Column(String, nullable=False)
    objective_summary = Column(String)
    optimizer_version = Column(String)
    weighting_regime = Column(String)
    fee_assumptions_json = Column(String)
    # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30): JSON-
    # Warnhinweis, wenn dieser Lauf provisorische (noch nicht IC-geprueft,
    # siehe CapitalMarketAssumption.status) CMA- oder Home-Bias-Daten
    # verwendet hat. NULL = keine provisorischen Daten beteiligt (Backwards-
    # Compat -- alle Bestandslaeufe sind CH und damit committee_approved).
    # Befuellung ist NICHT Teil dieses Arbeitspakets (spaeteres WP).
    provisional_data_warning = Column(String)
    other_assets_included = Column(Integer, nullable=False, default=0)
    result_status = Column(String, nullable=False, default="Draft")
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    mandate = relationship("Mandate", back_populates="recommendation_runs")
    positions = relationship("RecommendationPosition", back_populates="run")


class RecommendationPosition(Base):
    __tablename__ = "recommendation_positions"

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    target_weight_bps = Column(Integer, nullable=False)
    target_amount_rappen = Column(Integer)
    # Sprint U-P20 (2026-05-24): Echte IST-Holdings des Kunden. NULL =
    # noch nicht gepflegt (Berater hat Empfehlung erstellt, Kunde hat noch
    # nichts gekauft). depot_check.py liest dieses Feld als IST-Amount
    # statt auf target_amount zurueckzufallen (= echter IST/SOLL-Drift).
    current_amount_rappen = Column(Integer)
    reference_price_rappen = Column(Integer)
    reference_price_date = Column(String)
    reference_price_source = Column(String)
    reference_lookup_mode = Column(String)
    reference_price_fetched_at = Column(String)
    rationale = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    run = relationship("RecommendationRun", back_populates="positions")
    product = relationship("Product")


class RecommendationHolding(Base):
    __tablename__ = "recommendation_holdings"
    __table_args__ = (
        Index("ix_recommendation_holdings_run_position", "run_id", "recommendation_position_id"),
    )

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=False)
    recommendation_position_id = Column(String, ForeignKey("recommendation_positions.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    depot_bank = Column(String)
    custody_account_number = Column(String)
    as_of_date = Column(String)
    units_milli = Column(Integer)
    market_value_rappen = Column(Integer)
    avg_cost_price_rappen = Column(Integer)
    source = Column(String, nullable=False, default="manual")
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    run = relationship("RecommendationRun")
    position = relationship("RecommendationPosition")
    product = relationship("Product")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    user_name = Column(String, nullable=False)
    table_name = Column(String, nullable=False)
    record_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    field_name = Column(String)
    old_value = Column(String)
    new_value = Column(String)
    mandate_id = Column(String)
    client_id = Column(String)
    integrity_hash = Column(String(64))
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit, DSG Art. 32): Quell-IP fuer
    # sensible Aktionen (Login, Passwort-Reset, Export, Loeschung) -- vorher
    # nur im App-Log, nicht im auditierbaren, hash-verketteten Audit-Trail.
    ip_address = Column(String)
    created_at = Column(String, nullable=False)


class MandateReportNotes(Base):
    """Berater-individuelle Texte für den Advisory-Report (Sprint U-P28).

    Eine Zeile pro Mandat (UNIQUE auf mandate_id). Wird durch den Aggregator
    `services.advisory_report` konsumiert; jedes leere Feld fällt auf den
    Auto-Default-Text der jeweiligen Sektion zurück. Das PDF (U-P26) und die
    React-Sub-App lesen denselben Aggregator — Single Source of Truth.

    Auditierbar über `last_edited_by` + `last_edited_at`.
    """

    __tablename__ = "mandate_report_notes"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False, unique=True)

    # Sektion „Asset Allocation": überschreibt den Drift-Auto-Text
    aa_anmerkungen = Column(String)

    # Sektion „Risikowährungen": überschreibt den CHF-Anteil-Auto-Text
    waehrungen_erklaerung = Column(String)

    # Sektion „Branchen": überschreibt die Sektor-Drift-Auto-Analyse
    branchen_analyse = Column(String)

    # Sektion „Weiteres Vorgehen": Berater-Texte + strukturierte Listen
    vorgehen_block_optimierungen = Column(String)
    vorgehen_block_zielstrategie = Column(String)
    vorgehen_offene_fragen_json = Column(String)  # JSON-Array["frage1","frage2"]
    vorgehen_naechster_termin = Column(String)    # ISO-Datum oder freier Text
    vorgehen_todos_json = Column(String)          # JSON-Array["todo1",...]
    vorgehen_dokumente_json = Column(String)      # JSON-Array["Dok 1",...]

    # Audit-Anchor (FINMA-relevant)
    last_edited_by = Column(String, ForeignKey("users.id"), nullable=False)
    last_edited_at = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    # Sprint U-37 (2026-06-03): Append-only Versionierungs-Log.
    # JSON-Array von Snapshots: [{edited_at, edited_by, changes: {field:
    # {old, new}}}, ...]. FINMA-Audit-Anforderung "was stand wann im
    # Bericht". NULL bei Pre-U-37-Notes.
    previous_versions_json = Column(String)

    mandate = relationship("Mandate", back_populates="report_notes")
    editor = relationship("User")
