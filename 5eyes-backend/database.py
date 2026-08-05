import sqlite3
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Generator
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

try:
    import sqlcipher3  # type: ignore
except ImportError:
    sqlcipher3 = None


SQLCIPHER_AVAILABLE = sqlcipher3 is not None


def resolve_db_file(db_path: str | Path | None = None) -> Path:
    db_file = Path(db_path or settings.db_path).expanduser().resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    return db_file


def resolve_schema_path() -> Path | None:
    pyinstaller_root = Path(getattr(sys, '_MEIPASS', '')) if getattr(sys, '_MEIPASS', None) else None
    candidates = [
        Path(__file__).parent / '5eyes_schema_v4.0_FINAL.sql',
        Path(__file__).parent.parent / '5eyes_schema_v4.0_FINAL.sql',
    ]
    if pyinstaller_root:
        candidates.insert(0, pyinstaller_root / '5eyes_schema_v4.0_FINAL.sql')
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _sqlcipher_enabled(db_key: str | None = None) -> bool:
    key = db_key or getattr(settings, 'db_key', None)
    return bool(getattr(settings, 'db_use_sqlcipher', False) and key)


def _configured_database_url(database_url: str | None = None) -> str | None:
    configured = database_url if database_url is not None else getattr(settings, "database_url", None)
    if configured and str(configured).strip():
        return str(configured).strip()
    return None


def is_sqlite_database_url(database_url: str) -> bool:
    return database_url.lower().startswith("sqlite")


def is_postgres_database_url(database_url: str) -> bool:
    return database_url.lower().startswith(("postgresql://", "postgresql+"))


def build_database_url(
    db_path: str | Path | None = None,
    db_key: str | None = None,
    database_url: str | None = None,
) -> str:
    configured = _configured_database_url(database_url)
    if configured:
        return configured
    db_file = resolve_db_file(db_path)
    if _sqlcipher_enabled(db_key=db_key):
        if not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                'DB_USE_SQLCIPHER=true ist gesetzt, aber sqlcipher3 ist nicht installiert. '
                'Installiere sqlcipher3-binary oder sqlcipher3.'
            )
        key = quote_plus((db_key or settings.db_key or ''))
        return f'sqlite+pysqlcipher://:{key}@/{db_file}'
    return f'sqlite:///{db_file}'


def build_connect_args(
    db_key: str | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    _ = db_key
    url = database_url or build_database_url(db_key=db_key)
    if not is_sqlite_database_url(url):
        return {}
    return {'check_same_thread': False, 'timeout': 30}


def attach_sqlite_pragmas(target_engine: Engine, db_key: str | None = None) -> None:
    @event.listens_for(target_engine, 'connect')
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        if _sqlcipher_enabled(db_key=db_key):
            cursor.execute('PRAGMA cipher_page_size = 4096')
            cursor.execute('PRAGMA kdf_iter = 256000')
            cursor.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA512')
            cursor.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512')
        cursor.execute('PRAGMA foreign_keys = ON')
        cursor.execute('PRAGMA journal_mode = WAL')
        cursor.execute('PRAGMA busy_timeout = 5000')
        cursor.execute('PRAGMA recursive_triggers = OFF')
        cursor.close()


def create_app_engine(
    db_path: str | Path | None = None,
    db_key: str | None = None,
    echo: bool | None = None,
) -> Engine:
    database_url = build_database_url(db_path=db_path, db_key=db_key)
    connect_args = build_connect_args(db_key=db_key, database_url=database_url)
    kwargs: dict[str, Any] = {
        'echo': settings.db_echo if echo is None else echo,
        'pool_timeout': 30,
    }
    if connect_args:
        kwargs['connect_args'] = connect_args
    if is_sqlite_database_url(database_url) and _sqlcipher_enabled(db_key=db_key):
        kwargs['module'] = sqlcipher3
    app_engine = create_engine(database_url, **kwargs)
    if app_engine.dialect.name == "sqlite":
        attach_sqlite_pragmas(app_engine, db_key=db_key)
    elif app_engine.dialect.name.startswith("postgresql"):
        from services.tenant_context import attach_tenant_context_reset
        attach_tenant_context_reset(app_engine)
    return app_engine


engine = create_app_engine(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            from services.tenant_context import reset_tenant_context
            reset_tenant_context(db)
        except Exception:
            pass
        db.close()


def new_uuid() -> str:
    return str(uuid.uuid4())


def bootstrap_sqlite_schema(
    db_path: str | Path | None = None,
    schema_path: str | Path | None = None,
    db_key: str | None = None,
) -> None:
    schema_file = Path(schema_path) if schema_path else resolve_schema_path()
    if not schema_file or not schema_file.exists():
        return

    db_file = resolve_db_file(db_path)
    sql = schema_file.read_text(encoding='utf-8')

    if _sqlcipher_enabled(db_key=db_key):
        if not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                'DB_USE_SQLCIPHER=true ist gesetzt, aber sqlcipher3 ist nicht installiert. '
                'Installiere sqlcipher3-binary oder sqlcipher3.'
            )
        with sqlcipher3.connect(str(db_file)) as conn:
            conn.execute("PRAGMA key = ?", [db_key or settings.db_key or ''])
            conn.execute('PRAGMA cipher_page_size = 4096')
            conn.execute('PRAGMA kdf_iter = 256000')
            conn.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA512')
            conn.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512')
            conn.execute('PRAGMA foreign_keys = OFF')
            conn.executescript(sql)
            conn.execute('PRAGMA foreign_keys = ON')
            conn.commit()
        return

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute('PRAGMA foreign_keys = OFF')
        conn.executescript(sql)
        conn.execute('PRAGMA foreign_keys = ON')
        conn.commit()


def database_healthcheck(db: Session) -> dict[str, str]:
    db.execute(text('SELECT 1'))
    return {'database': 'ok'}


def ensure_column(conn, table_name: str, column_name: str, sql_type: str) -> None:
    if not re.match(r'^[a-z][a-z0-9_]+$', table_name):
        raise ValueError(f"Ungueltiger Tabellenname: {table_name!r}")
    if not re.match(r'^[a-z][a-z0-9_]+$', column_name):
        raise ValueError(f"Ungueltiger Spaltenname: {column_name!r}")
    if not re.match(r'^[A-Z]+$', sql_type):
        raise ValueError(f"Ungueltiger SQL-Typ: {sql_type!r}")
    existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info({table_name})')).fetchall()}
    if column_name in existing:
        return
    conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'))


def ensure_runtime_columns() -> None:
    additive_columns: dict[str, list[tuple]] = {  # (name, TYPE) oder (name, TYPE, int_default)
        # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur.
        # Bootstrap-SQL hat das Feld noch nicht — Migration ergaenzt die
        # Column idempotent auf Live-DBs, sonst koennen Tier-2-Endpoints
        # den tenant-Scope nicht setzen und frische Installationen
        # crashen beim User-Anlegen.
        'users': [
            ('tenant_id', 'TEXT'),
            # E1 (2026-06-13): TOTP-2FA fuer externe Logins.
            ('totp_secret', 'TEXT'),
            ('totp_enabled', 'INTEGER'),
            # E1 (2026-06-14): erzwungener Passwortwechsel beim ersten Login.
            ('must_change_password', 'INTEGER'),
            # E1 (2026-06-14): Invite-Link-Onboarding (Token-Hash + Ablauf).
            ('invite_token_hash', 'TEXT'),
            ('invite_expires_at', 'TEXT'),
            # #25/#27 (2026-06-15): Self-Service Passwort-Reset + 2FA-Recovery-Codes.
            # MUSS hier (Startup-Migration) stehen, nicht nur lazy: das User-Modell
            # selektiert diese Spalten bei JEDEM Query (inkl. Login) -> auf bestehenden
            # DBs ohne die Spalten crasht sonst der Login (OperationalError).
            ('reset_token_hash', 'TEXT'),
            ('reset_token_expires_at', 'TEXT'),
            ('totp_recovery_codes', 'TEXT'),
            # AUTH-04 (2026-07-22): Token-Revocation-Timestamp fuer /auth/logout.
            ('token_revoked_before', 'TEXT'),
            # AUTH-06 (2026-07-22): letzter akzeptierter TOTP-Zeitschritt (Anti-Replay).
            ('totp_last_counter', 'TEXT'),
        ],
        'tenants': [
            ('encrypted_dek', 'TEXT'),
            ('dek_version', 'INTEGER'),
            ('dek_rotated_at', 'TEXT'),
            # 2026-07-27 (Retrozessions-Feature): Firmenweite Vorbelegung,
            # siehe models/tenant.py.
            ('default_retrocession_reimbursement', 'INTEGER', 0),
            # 2026-08-01 (Onboarding): Land der lizenznehmenden Firma, siehe
            # models/tenant.py. NULL = "CH" (kein DB-Default fuer TEXT-Spalten).
            ('home_jurisdiction', 'TEXT'),
            # 2026-08-02 (HUD-Polish): firmenweiter Default fuer die UI-
            # "Maske" (Wealthmanagement/Consulting), siehe models/tenant.py.
            # NULL = "wealthmanagement".
            ('default_presentation_mode', 'TEXT'),
        ],
        # 2026-07-27 (Retrozessions-Feature): siehe models/review.py.
        'conflict_of_interest_disclosures': [
            ('reimbursed_to_client', 'INTEGER', 0),
            ('waiver_document_id', 'TEXT'),
        ],
        # 2026-06-18 (#84): Miete-Teuerungsindexierung pro Immobilien-Position.
        # NOT NULL DEFAULT 0 -> Bestandszeilen werden auf 0 gesetzt (Response-Schema
        # erwartet int, nicht NULL).
        'wealth_positions': [
            ('property_rental_inflation_linked', 'INTEGER', 0),
        ],
        # A2-Smoke-Test-Fund (2026-07-22): 'target_allocations' hatte einen
        # DOPPELTEN Dict-Key in diesem Literal (hier + weiter unten). In Python
        # gewinnt der ZWEITE — der erste Block war dadurch tote Migration:
        # preferences_json, input_snapshot_hash, die advisory/total/reserve-
        # Rappen-Spalten, alle optimization_*-Legacy-Felder, stress_evaluations_
        # json und optimizer_reasoning_json wurden NIE auf einer per Raw-SQL-
        # Bootstrap (5eyes_schema_v4.0_FINAL.sql) frisch angelegten DB migriert
        # -> jede fabrikneue Installation crashte mit 'no such column:
        # target_allocations.preferences_json' auf /target-allocation/current/
        # payload + /recommendations/current/payload — der Blocker fuer den
        # allerersten echten Mandanten. Beide Bloecke hier zu EINEM gemergt;
        # ensure_column() ist idempotent (PRAGMA-Check), das Zusammenfuehren
        # ist ohne Risiko fuer DBs, die einzelne Spalten schon haben.
        'target_allocations': [
            ('capital_market_assumptions_id', 'TEXT'),
            # C8 audit anchors fuer Reproduzierbarkeit / Drift-Erkennung
            ('preferences_json', 'TEXT'),
            ('input_snapshot_hash', 'TEXT'),
            ('advisory_wealth_at_generation_rappen', 'INTEGER'),
            ('total_wealth_at_generation_rappen', 'INTEGER'),
            ('reserve_needed_at_generation_rappen', 'INTEGER'),
            ('external_reserve_at_generation_rappen', 'INTEGER'),
            # Optimizer-Audit-Anchor (Spec 2026-05-05). NULL fuer pre-Optimizer-
            # Allocations - bedeutet "via House-Matrix-Default berechnet".
            ('optimization_method', 'TEXT'),
            ('optimization_objective_value_milli', 'INTEGER'),
            ('optimization_iterations', 'INTEGER'),
            ('optimization_seed', 'INTEGER'),
            ('optimization_status', 'TEXT'),
            ('risky_fraction_bps_at_generation', 'INTEGER'),
            ('risk_budget_bps_at_generation', 'INTEGER'),
            ('limiting_factor', 'TEXT'),
            ('goal_achievability_json', 'TEXT'),
            # Phase 6: persistierte Stress-Auswertungen (Phase 5.2) als JSON-String.
            # NULL bei house_matrix-Modus oder Pre-Optimizer-Allocations.
            ('stress_evaluations_json', 'TEXT'),
            # Phase 6.2: persistierter Solver-Reasoning-Trace (list[str] JSON).
            # Damit /current/payload das identische Reasoning liefert wie /generate.
            ('optimizer_reasoning_json', 'TEXT'),
            # V3 Sprint 2.1 (2026-05-09 / Plan §4.1): Verknuepfung zur eigenen
            # optimizer_runs-Zeile (nur im zweiten, vormals lebenden Block).
            ('optimization_run_id', 'TEXT'),
            # Stochastic Goal Engine Stage 5: persistierter Shadow-Vergleich
            # fuer Admin-/Compliance-Auswertung.
            ('shadow_optimization_json', 'TEXT'),
            # AR-2 (2026-07-19): MC-Risiko-KPIs (bps) fuer FIDLEG-Report.
            ('mc_exp_vol_bps', 'INTEGER'),
            ('mc_exp_return_bps', 'INTEGER'),
            ('mc_max_drawdown_bps', 'INTEGER'),
            ('mc_var_95_bps', 'INTEGER'),
        ],
        'recommendation_positions': [
            ('reference_price_rappen', 'INTEGER'),
            ('reference_price_date', 'TEXT'),
            ('reference_price_source', 'TEXT'),
            ('reference_lookup_mode', 'TEXT'),
            ('reference_price_fetched_at', 'TEXT'),
            # Sprint U-P20 (2026-05-24): Echte IST-Holdings des Kunden.
            # NULL = noch nicht gepflegt (Empfehlung erstellt, Kunde hat
            # noch nichts gekauft). depot_check.py liest das Feld für den
            # IST/SOLL-Drift im Country/Sector/Currency-Vergleich.
            # HOTFIX U-P20.1 (2026-05-25): Migration war im Sprint U-P20
            # vergessen — Live-DBs hatten die Column nicht und der
            # /advisory-report-Endpoint warf 500. Mit Eintrag hier wird
            # die Column beim naechsten Backend-Start idempotent ergaenzt.
            ('current_amount_rappen', 'INTEGER'),
        ],
        'clients': [
            ('investment_horizon_start', 'TEXT'),
            ('investment_horizon_end', 'TEXT'),
            # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur.
            # Bootstrap-SQL hat das Feld noch nicht — Migration ergaenzt
            # die Column idempotent auf Live-DBs, sonst koennen Tier-2-
            # Endpoints den tenant-Scope nicht setzen.
            ('tenant_id', 'TEXT'),
        ],
        # Sprint U-37 (2026-06-03): Notes-Versionierungs-Log.
        # Append-only JSON-Array von Edit-Snapshots fuer FINMA-Audit
        # (was-stand-zu-welchem-Zeitpunkt-im-Bericht).
        'mandate_report_notes': [
            ('previous_versions_json', 'TEXT'),
        ],
        # Sprint U-P19b (2026-05-23): native Notierungswährung der Proxy-Bar
        # fuer waehrungskorrekten Daily-Backtest (NULL = wie CHF behandelt).
        # Sprint 2026-06-09 (Phase 1 Sub-Asset): sub_asset_class fuer
        # Sub-Anlageklassen-Backfill (NULL = Top-Level-Aggregat wie bisher,
        # NOT NULL = z.B. "Aktien_CH_Large" gemaess symbol_catalog.py).
        'asset_class_price_history': [
            ('currency', 'TEXT'),
            ('sub_asset_class', 'TEXT'),
        ],
        # Sprint 2026-06-09 (Phase 1 Sub-Asset): Annual-Returns auch fuer
        # Sub-Anlageklassen. NULL = Top-Level-Aggregat (Bisheriges Verhalten).
        'asset_class_annual_returns': [
            ('sub_asset_class', 'TEXT'),
        ],
        'mandates': [
            # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur.
            # Bootstrap-SQL hat das Feld noch nicht — Migration ergaenzt
            # die Column idempotent auf Live-DBs.
            ('tenant_id', 'TEXT'),
            # Sprint A3 (2026-05-06): Rentenalter + Lebenserwartung pro Mandat.
            ('retirement_year', 'INTEGER'),
            ('life_expectancy_year', 'INTEGER'),
            # Sprint B4 (2026-05-07): Anlageuniversum (Advisory-Methodik-Pattern).
            # Standard | Alternativ; Filter fuer Produkt-Auswahl.
            ('investment_universe', 'TEXT'),
            # Sprint B1 (2026-05-07): Building-Block-Wahl pro Mandat (JSON).
            ('default_building_blocks_json', 'TEXT'),
            # Sprint 4 Phase 3 (2026-05-17): BFS-Mortalitaets-Sampling
            # Wenn use_mortality_simulation=1 und client_birth_year + client_sex
            # gesetzt, sampled portfolio_engine das Sterbe-Alter aus der BFS-Tafel.
            ('client_birth_year', 'INTEGER'),
            ('client_sex', 'TEXT'),
            ('use_mortality_simulation', 'INTEGER'),
            # Sprint U-P3 (2026-05-19): Steuersitz fuer tax-aware Allocations-MC.
            # NULL = tax-naiv (Backwards-Compat). Pattern matched gegen Tax-Registry
            # ('CH', 'DE', 'CH-ZH', 'DE-BY', '*' = Generic).
            ('tax_jurisdiction', 'TEXT'),
            ('tax_overrides_json', 'TEXT'),
            # 2026-07-27 (HUD-Konfiguration): siehe models/mandates.py.
            ('hidden_report_sections', 'TEXT'),
            # 2026-07-27 (Laender-Skalierung): siehe models/mandates.py. NULL
            # (kein DB-Default möglich fuer TEXT-Spalten in dieser Migration-
            # Helper-Funktion) -- Code interpretiert NULL als "CH".
            ('jurisdiction', 'TEXT'),
        ],
        'cashflows': [
            ('gross_amount_rappen', 'INTEGER'),
            ('tax_amount_rappen', 'INTEGER'),
            ('timing_precision', 'TEXT'),
        ],
        'goals': [
            # Sprint B6 (2026-05-08): bedingte Goals — Eintrittswahrscheinlichkeit (0-100).
            # NULL bei pre-B6-Goals -> Engine interpretiert als 100 (sicher).
            ('probability_pct', 'INTEGER'),
            # Sprint B3 (2026-05-08): Vorsorge-Saeule fuer Pensionsausgabe-Goals.
            # AHV / BVG / 3a / 1e / FZG. NULL bei nicht-Pensionsausgabe oder unspezifiziert.
            ('pension_pillar', 'TEXT'),
            # Stochastic Goal Engine Stage 1 (2026-05-23): Renditeziel + Zielwahrscheinlichkeit.
            ('target_return_bps', 'INTEGER'),
            ('success_probability_min_x100', 'INTEGER'),
        ],
        'capital_market_assumptions': [
            ('correlation_matrix_json', 'TEXT'),
            ('sub_asset_class_assumptions_json', 'TEXT'),
            # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
            # siehe models/allocation.py::CapitalMarketAssumption. jurisdiction
            # NULL = "CH" (gleiches Nullable-Pattern wie mandates.jurisdiction).
            # status hat KEINEN DB-Default (bleibt NULL fuer neue Inserts von
            # aussen) -- Bestandszeilen werden weiter unten (WP1-Status-Backfill)
            # EINMALIG beim erstmaligen Anlegen dieser Spalte auf
            # 'committee_approved' zurueckgeschrieben, weil Bestandszeilen
            # bereits IC-freigegebene CH-Zahlen sind. Erlaubte Werte fuer
            # status (Validierung folgt in einem spaeteren Schema/Router-Paket):
            # "provisional" | "data_derived" | "committee_approved".
            ('jurisdiction', 'TEXT'),
            ('status', 'TEXT'),
            ('source_detail', 'TEXT'),
            ('computed_at', 'TEXT'),
            ('computed_by', 'TEXT'),
            # Generische Home-Bias-Gegenstuecke zu equity_ch_*/bonds_chf_ig_*/
            # real_estate_ch_* -- die CH-Spalten bleiben unveraendert und werden
            # weiterhin ausschliesslich vom CH-Pfad gelesen.
            ('equity_home_return_bps', 'INTEGER'),
            ('equity_home_vol_bps', 'INTEGER'),
            ('bonds_home_ig_return_bps', 'INTEGER'),
            ('bonds_home_ig_vol_bps', 'INTEGER'),
            ('real_estate_home_return_bps', 'INTEGER'),
            ('real_estate_home_vol_bps', 'INTEGER'),
            # 2026-07-31 (Tenant-Override): NULL = firmenweite CMA-Zeile
            # (Default). Gesetzt = Tenant-spezifischer Override, hat Vorrang
            # vor der firmenweiten Zeile derselben Jurisdiktion. CH-Pfad
            # ignoriert diese Spalte weiterhin komplett.
            ('tenant_id', 'TEXT'),
            # Optimizer-Phase 1: Skewness + Excess-Kurtosis pro Bucket fuer
            # Cornish-Fisher fat-tail Sampling. NULL/0 -> Normal-Verteilung
            # (backwards-compat). Werte in bps (z.B. -5000 = -0.5 skew).
            ('equities_skewness_bps', 'INTEGER'),
            ('equities_excess_kurt_bps', 'INTEGER'),
            ('bonds_skewness_bps', 'INTEGER'),
            ('bonds_excess_kurt_bps', 'INTEGER'),
            ('real_estate_skewness_bps', 'INTEGER'),
            ('real_estate_excess_kurt_bps', 'INTEGER'),
            ('alternatives_skewness_bps', 'INTEGER'),
            ('alternatives_excess_kurt_bps', 'INTEGER'),
            ('liquidity_skewness_bps', 'INTEGER'),
            ('liquidity_excess_kurt_bps', 'INTEGER'),
            # Sprint 6 Phase 2 (2026-05-17): Nelson-Siegel Yield-Curve fuer Bonds.
            ('bonds_ns_beta0_bps', 'INTEGER'),
            ('bonds_ns_beta1_bps', 'INTEGER'),
            ('bonds_ns_beta2_bps', 'INTEGER'),
            ('bonds_ns_lambda_x100', 'INTEGER'),
            # Sprint 7 (2026-05-17): KGV-Mean-Reversion fuer Equity-Returns.
            ('equity_kgv_current_x10', 'INTEGER'),
            ('equity_kgv_fair_x10', 'INTEGER'),
            ('equity_kgv_alpha_x100', 'INTEGER'),
            # Sprint 8 (2026-05-17): Risikopraemien-Modell fuer RE + Alternatives.
            ('real_estate_risk_premium_bps', 'INTEGER'),
            ('alternatives_risk_premium_bps', 'INTEGER'),
            # Roadmap #51 (2026-07-23): CMA-Werte-Pflegeprozess -- Quelle/Datum
            # dokumentieren. source (Herkunft) existierte bereits im Bootstrap-
            # SQL; source_date (ISO-Datum der Quellpublikation, kann von
            # valid_from abweichen) fehlte -- additive Migration fuer Alt-DBs.
            ('source_date', 'TEXT'),
        ],
        # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
        # siehe models/allocation.py::BuildingBlock. jurisdiction NULL = "CH"
        # (gleiches Nullable-Pattern wie mandates.jurisdiction). is_provisional
        # ist ein reiner int-Default (0 = kein IC-Vorbehalt) -- zulaessig, weil
        # INTEGER (siehe ensure_runtime_columns()-Docstring zu int_default).
        'building_blocks': [
            ('jurisdiction', 'TEXT'),
            ('is_provisional', 'INTEGER', 0),
            ('role', 'TEXT'),
        ],
        # WP1 (2026-07-30): siehe models/review.py::RecommendationRun. JSON-
        # Warnhinweis, wenn der Lauf provisorische (noch nicht IC-geprueft)
        # CMA-/Home-Bias-Daten verwendet hat -- Vorbild fee_assumptions_json
        # (gleicher Spaltentyp/-Stil, gleiche Klasse).
        'recommendation_runs': [
            ('provisional_data_warning', 'TEXT'),
        ],
        'optimizer_runs': [
            # U-9 Stage-9 Telemetry: pro Solver-Start n_paths/n_starts/Seed/
            # Status/elapsed_ms/reason auditierbar persistieren.
            ('restart_results_json', 'TEXT'),
        ],
        'products': [
            ('lookup_mode_override', 'TEXT'),
            ('lookup_symbol_override', 'TEXT'),
            ('figi', 'TEXT'),
            ('composite_figi', 'TEXT'),
            ('share_class_figi', 'TEXT'),
            ('exchange_code', 'TEXT'),
            ('market_sector', 'TEXT'),
            ('security_type', 'TEXT'),
            ('security_type2', 'TEXT'),
            ('mapping_provider', 'TEXT'),
            ('mapping_resolved_at', 'TEXT'),
            ('reference_data_provider', 'TEXT'),
            ('reference_data_refreshed_at', 'TEXT'),
            # Sprint U-P10 (2026-05-20): Depot-Check Diversifikations-Tiefe
            ('country_exposure_json', 'TEXT'),
            ('sector_exposure_json', 'TEXT'),
            ('currency_exposure_json', 'TEXT'),
            ('duration_years_x10', 'INTEGER'),
            ('credit_rating', 'TEXT'),
            ('esg_score_x10', 'INTEGER'),
            ('liquidity_tier', 'TEXT'),
            # 2026-08-01 (Laender-Skalierung, Cross-Jurisdiktions-Leck-Fix):
            # siehe models/review.py::Product.jurisdiction. NULL = "CH".
            ('jurisdiction', 'TEXT'),
        ],
    }
    inspector = inspect(engine)
    # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
    # gesetzt, wenn 'status' auf capital_market_assumptions in DIESEM Lauf
    # neu per ALTER TABLE angelegt wurde (siehe Backfill weiter unten).
    cma_status_newly_added = False
    with engine.begin() as conn:
        for table_name, columns in additive_columns.items():
            # Defensive (2026-06-08): wenn eine Tabelle (noch) nicht
            # existiert, Migration ueberspringen statt zu crashen. create_all
            # legt die fehlenden Tabellen erst nach unserem Aufruf an
            # (Bootstrap-SQL deckt nicht alle ORM-Tabellen ab).
            if not inspector.has_table(table_name):
                continue
            existing = {column['name'] for column in inspector.get_columns(table_name)}
            for spec in columns:
                # spec = (column_name, sql_type) ODER (column_name, sql_type, int_default).
                # int_default -> Spalte als NOT NULL DEFAULT <int> (Bestandszeilen erhalten
                # den Default; rohe SQL-Inserts ohne die Spalte brechen nicht).
                column_name, sql_type = spec[0], spec[1]
                default = spec[2] if len(spec) > 2 else None
                if not re.match(r'^[a-z][a-z0-9_]*$', table_name):
                    raise ValueError(f"Ungültiger Tabellenname: {table_name!r}")
                if not re.match(r'^[a-z][a-z0-9_]*$', column_name):
                    raise ValueError(f"Ungültiger Spaltenname: {column_name!r}")
                if not re.match(r'^[A-Z]+$', sql_type):
                    raise ValueError(f"Ungültiger SQL-Typ: {sql_type!r}")
                if default is not None and (not isinstance(default, int) or isinstance(default, bool)):
                    raise ValueError(f"Ungültiger Default (nur int): {default!r}")
                column_is_new = column_name not in existing
                if column_is_new:
                    ddl = f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}'
                    if default is not None:
                        ddl += f' NOT NULL DEFAULT {int(default)}'
                    conn.execute(text(ddl))
                    if table_name == 'capital_market_assumptions' and column_name == 'status':
                        cma_status_newly_added = True
                # WP-500-Fix (2026-07-01): idempotenter Backfill. Wenn die Column in
                # einer FRÜHEREN Migration OHNE Default zugefügt wurde, sind Bestands-
                # zeilen NULL geblieben — der `NOT NULL DEFAULT` oben greift nur beim
                # erstmaligen Anlegen, und ein bereits vorhandener Column-Name führte
                # bisher zu `continue` (kein Backfill). Response-Schemas erwarten aber
                # int (nicht NULL) -> ein einziges NULL liess `/wealth-positions` u.ä.
                # mit 500 (ResponseValidationError) fehlschlagen. NULL->default auf
                # jedem Start reparieren (idempotent, betrifft nur Alt-NULLs).
                if default is not None:
                    conn.execute(
                        text(f'UPDATE {table_name} SET {column_name} = :d WHERE {column_name} IS NULL'),
                        {'d': int(default)},
                    )
                existing.add(column_name)

        # WP1-Status-Backfill (2026-07-30): 'status' auf capital_market_assumptions
        # ist eine TEXT-Spalte -> kein int_default moeglich (siehe Validierung
        # oben). Bestandszeilen (heutige CH-Zeilen) sind aber bereits vom
        # Investment Committee freigegebene Zahlen -- deshalb EINMALIG beim
        # erstmaligen Anlegen dieser Spalte per Backfill auf
        # 'committee_approved' setzen (Muster wie WP-500-Fix: UPDATE ... WHERE
        # status IS NULL). BEWUSST NUR innerhalb des column_is_new-Zweigs
        # (nicht auf jedem Boot-Lauf, anders als WP-500-Fix): Constraint aus der
        # Spezifikation ist, dass status fuer NEUE Inserts von aussen (z.B.
        # provisorische Nicht-CH-CMA-Zeilen aus einem spaeteren Arbeitspaket)
        # NICHT automatisch beim naechsten Backend-Start auf
        # 'committee_approved' hochgestuft werden darf -- die Spalte bleibt
        # NULL/leer, bis ein Mensch/Prozess sie explizit setzt.
        if cma_status_newly_added:
            conn.execute(
                text(
                    "UPDATE capital_market_assumptions SET status = 'committee_approved' "
                    "WHERE status IS NULL"
                )
            )

        # RiskAssessment - Kenntnisse & Erfahrungen (Referenzmodell Eignungspruefung, 2026-04-16)
        ensure_column(conn, "risk_assessments", "knowledge_services_json", "TEXT")
        ensure_column(conn, "risk_assessments", "knowledge_instruments_json", "TEXT")
        ensure_column(conn, "risk_assessments", "income_sources_json", "TEXT")
        # FIDLEG-Signatur (2026-07-19): Kunden-Signatur des Risikoprofils. Reine
        # Dokumentation (aendert die Eignungs-Konformitaet NICHT). ensure_column ist
        # idempotent -> ergaenzt die Spalten auf bestehenden SQLite-DBs beim Start.
        ensure_column(conn, "risk_assessments", "client_signed_at", "TEXT")
        ensure_column(conn, "risk_assessments", "client_signed_method", "TEXT")
        ensure_column(conn, "risk_assessments", "client_signed_ref", "TEXT")
        # E-Signing (2026-08-05, User-Direktive): echtes Signatur-Artefakt pro
        # Unterzeichner auf ContractDocument, statt der bisherigen reinen
        # Checkbox-Flags (signed_by_advisor/client). ensure_column ist
        # idempotent -> ergaenzt die Spalten auf bestehenden SQLite-DBs beim
        # naechsten Start, ohne bestehende Vertragsdokumente zu beruehren.
        ensure_column(conn, "contract_documents", "signature_advisor_image", "TEXT")
        ensure_column(conn, "contract_documents", "signature_advisor_signer_name", "TEXT")
        ensure_column(conn, "contract_documents", "signature_advisor_signed_at", "TEXT")
        ensure_column(conn, "contract_documents", "signature_advisor_ip", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_image", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_signer_name", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_signed_at", "TEXT")
        ensure_column(conn, "contract_documents", "signature_client_ip", "TEXT")
        # Fondsuniversum (2026-08-05, User-Direktive): NULL = globaler Katalog
        # (unveraendert), gesetzt = privater Fonds eines Tenants. ensure_column
        # ist idempotent -> ergaenzt bestehende SQLite-DBs additiv.
        ensure_column(conn, "products", "tenant_id", "TEXT")


def run_advisory_log_migration(target_engine: Engine = engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table('advisory_log'):
        return

    with target_engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(advisory_log)"))
        existing = {row[1] for row in result.fetchall()}
        if "recommendation_run_id" not in existing:
            conn.execute(text(
                "ALTER TABLE advisory_log ADD COLUMN recommendation_run_id TEXT"
            ))
        if "status" not in existing:
            conn.execute(text(
                "ALTER TABLE advisory_log ADD COLUMN status TEXT NOT NULL DEFAULT 'Empfohlen'"
            ))
        conn.commit()


def run_risk_assessment_answer_migration(target_engine: Engine = engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table('risk_assessment_answers'):
        return

    with target_engine.begin() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='risk_assessment_answers'")
        ).scalar()
        ddl_text = str(ddl or '')
        ddl_upper = ddl_text.upper()
        needs_question_upgrade = 'BETWEEN 1 AND 12' not in ddl_upper
        needs_section_upgrade = 'KENNTNISSE & ERFAHRUNGEN' not in ddl_text
        if not needs_question_upgrade and not needs_section_upgrade:
            return

        conn.execute(text('PRAGMA foreign_keys = OFF'))
        conn.execute(text('ALTER TABLE risk_assessment_answers RENAME TO risk_assessment_answers__old'))
        conn.execute(text("""
            CREATE TABLE risk_assessment_answers (
                id TEXT PRIMARY KEY,
                assessment_id TEXT NOT NULL REFERENCES risk_assessments(id) ON UPDATE CASCADE,
                question_number INTEGER NOT NULL CHECK(question_number BETWEEN 1 AND 12),
                question_section TEXT NOT NULL CHECK(question_section IN ('Kenntnisse & Erfahrungen','Risikofähigkeit','Risikobereitschaft')),
                answer_label TEXT NOT NULL,
                answer_points INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(assessment_id, question_number)
            )
        """))
        conn.execute(text("""
            INSERT INTO risk_assessment_answers (
                id, assessment_id, question_number, question_section,
                answer_label, answer_points, created_at
            )
            SELECT
                id, assessment_id, question_number, question_section,
                answer_label, answer_points, created_at
            FROM risk_assessment_answers__old
        """))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_risk_answers ON risk_assessment_answers(assessment_id)'))
        conn.execute(text('DROP TABLE risk_assessment_answers__old'))
        conn.execute(text('PRAGMA foreign_keys = ON'))


def ensure_audit_log_actions(target_engine: Engine = engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table('audit_log'):
        return

    with target_engine.begin() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_log'")
        ).scalar()
        ddl_text = str(ddl or '').upper()
        has_password_reset = 'PASSWORD_RESET' in ddl_text
        has_integrity_hash = 'INTEGRITY_HASH' in ddl_text
        if has_password_reset and has_integrity_hash:
            return

        conn.execute(text('ALTER TABLE audit_log RENAME TO audit_log__old'))
        conn.execute(text("""
            CREATE TABLE audit_log (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                user_name TEXT NOT NULL,
                table_name TEXT NOT NULL,
                record_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('CREATE','UPDATE','DELETE','LOGIN','EXPORT','PASSWORD_RESET')),
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                mandate_id TEXT,
                client_id TEXT,
                integrity_hash TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO audit_log (
                id, user_id, user_name, table_name, record_id, action,
                field_name, old_value, new_value, mandate_id, client_id, integrity_hash, created_at
            )
            SELECT
                id, user_id, user_name, table_name, record_id, action,
                field_name, old_value, new_value, mandate_id, client_id,
                NULL AS integrity_hash,
                created_at
            FROM audit_log__old
        """))
        conn.execute(text('DROP TABLE audit_log__old'))


SEED_ASSET_CLASS_RETURNS = [
    # year, asset_class, return_bps  (Quelle: SPI/SBI/KGAST konservativ kalibriert)
    (2015, "Aktien",        290),   (2015, "Obligationen",   100),
    (2015, "Immobilien",    180),   (2015, "Liquiditaet",    -30),   (2015, "Alternative",     50),
    (2016, "Aktien",       -180),   (2016, "Obligationen",    20),
    (2016, "Immobilien",    640),   (2016, "Liquiditaet",    -30),   (2016, "Alternative",    380),
    (2017, "Aktien",       2010),   (2017, "Obligationen",   140),
    (2017, "Immobilien",    550),   (2017, "Liquiditaet",    -30),   (2017, "Alternative",    490),
    (2018, "Aktien",       -870),   (2018, "Obligationen",    30),
    (2018, "Immobilien",    110),   (2018, "Liquiditaet",    -10),   (2018, "Alternative",   -980),
    (2019, "Aktien",       3040),   (2019, "Obligationen",   390),
    (2019, "Immobilien",    820),   (2019, "Liquiditaet",    -30),   (2019, "Alternative",    910),
    (2020, "Aktien",        360),   (2020, "Obligationen",   180),
    (2020, "Immobilien",    250),   (2020, "Liquiditaet",    -50),   (2020, "Alternative",    420),
    (2021, "Aktien",       2320),   (2021, "Obligationen",  -120),
    (2021, "Immobilien",    710),   (2021, "Liquiditaet",    -70),   (2021, "Alternative",    630),
    (2022, "Aktien",      -1650),   (2022, "Obligationen", -1280),
    (2022, "Immobilien", -1030),    (2022, "Liquiditaet",    180),   (2022, "Alternative",   -810),
    (2023, "Aktien",       1980),   (2023, "Obligationen",   510),
    (2023, "Immobilien",    -90),   (2023, "Liquiditaet",    150),   (2023, "Alternative",    720),
    (2024, "Aktien",       1320),   (2024, "Obligationen",   310),
    (2024, "Immobilien",    420),   (2024, "Liquiditaet",    100),   (2024, "Alternative",    890),
]


def _seed_asset_class_returns(conn) -> None:
    count = conn.execute(text("SELECT COUNT(*) FROM asset_class_annual_returns")).scalar()
    if count and count > 0:
        return
    from datetime import datetime as _dt
    now = _dt.utcnow().isoformat()
    for (year, ac, ret) in SEED_ASSET_CLASS_RETURNS:
        conn.execute(text("""
            INSERT OR IGNORE INTO asset_class_annual_returns
            (id, year, asset_class, return_bps, source, created_at, updated_at)
            VALUES (:id, :year, :ac, :ret, 'seed', :now, :now)
        """), {"id": str(uuid.uuid4()), "year": year, "ac": ac, "ret": ret, "now": now})


def ensure_snapshot_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS strategy_snapshots (
                id TEXT PRIMARY KEY,
                mandate_id TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                advisory_assets_rappen INTEGER NOT NULL,
                risk_profile_score INTEGER NOT NULL,
                risk_profile_label TEXT NOT NULL,
                soll_equities_bps INTEGER NOT NULL,
                soll_bonds_bps INTEGER NOT NULL,
                soll_real_estate_bps INTEGER NOT NULL,
                soll_liquidity_bps INTEGER NOT NULL,
                soll_alternatives_bps INTEGER NOT NULL,
                band_equities_lo_bps INTEGER,
                band_equities_hi_bps INTEGER,
                band_bonds_lo_bps INTEGER,
                band_bonds_hi_bps INTEGER,
                band_real_estate_lo_bps INTEGER,
                band_real_estate_hi_bps INTEGER,
                band_liquidity_lo_bps INTEGER,
                band_liquidity_hi_bps INTEGER,
                band_alternatives_lo_bps INTEGER,
                band_alternatives_hi_bps INTEGER,
                advisor_note TEXT,
                goals_summary_json TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_strategy_snapshots_mandate
            ON strategy_snapshots(mandate_id, deleted_at, snapshot_date)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_class_annual_returns (
                id TEXT PRIMARY KEY,
                year INTEGER NOT NULL,
                asset_class TEXT NOT NULL,
                return_bps INTEGER NOT NULL,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_acr_year_class
            ON asset_class_annual_returns(year, asset_class)
        """))
        # Sprint U-P19: tägliche EOD-Serie je Asset-Klasse (Daily-Backtest)
        # U-P19b: + currency (native Notierungswährung der Proxy-Bar)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_class_price_history (
                id TEXT PRIMARY KEY,
                asset_class TEXT NOT NULL,
                price_date TEXT NOT NULL,
                close_rappen INTEGER NOT NULL,
                currency TEXT,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_acph_class_date_source
            ON asset_class_price_history(asset_class, price_date, source)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_acph_class_date
            ON asset_class_price_history(asset_class, price_date)
        """))
        # Sprint U-P19b: tägliche FX-Reihe Fremdwährung → CHF
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_class_fx_history (
                id TEXT PRIMARY KEY,
                currency TEXT NOT NULL,
                price_date TEXT NOT NULL,
                rate_to_chf_x10000 INTEGER NOT NULL,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_acfx_ccy_date_source
            ON asset_class_fx_history(currency, price_date, source)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_acfx_ccy_date
            ON asset_class_fx_history(currency, price_date)
        """))
        _seed_asset_class_returns(conn)


def ensure_audit_log_indexes(target_engine: Engine = engine) -> None:
    """Sprint U-38 (Roadmap-Punkt 38, 2026-06-01): idempotente Audit-Log-
    Indexes — inkl. neuer Composite-Index (mandate_id, table_name).

    Die Indexes werden zwar im fresh-init via Schema-SQL angelegt, aber
    ensure_audit_log_actions baut die Tabelle bei Schema-Migration neu
    auf und droppt dabei alle existierenden Indexes. Diese Funktion
    stellt sicher dass alle Indexes nach jedem Migrations-Lauf wieder
    da sind.

    Neuer Index in U-38: idx_audit_mandate_table — beschleunigt Queries
    wie "alle Audit-Eintraege fuer Mandat X auf Tabelle Y" (typisches
    Pattern in services.data_export._query_audit_log und in den FINMA-
    Compliance-Reports).
    """
    inspector = inspect(target_engine)
    if not inspector.has_table('audit_log'):
        return

    with target_engine.begin() as conn:
        # Alle Indexes idempotent — IF NOT EXISTS macht das Re-Run safe.
        # Reihenfolge nach Spezifitaet: composite zuerst, single-column danach.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_mandate_table "
            "ON audit_log(mandate_id, table_name)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_record "
            "ON audit_log(table_name, record_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_mandate "
            "ON audit_log(mandate_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_user "
            "ON audit_log(user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_audit_time "
            "ON audit_log(created_at)"
        ))


PURGE_HISTORY_COLUMNS: tuple[str, ...] = (
    "id",
    "started_at",
    "finished_at",
    "purged_rows",
    "skipped_providers_json",
    "duration_seconds",
    "errors_json",
)

PURGE_HISTORY_COLUMN_SQL_TYPES: dict[str, str] = {
    "id": "INTEGER",
    "started_at": "TEXT",
    "finished_at": "TEXT",
    "purged_rows": "INTEGER NOT NULL DEFAULT 0",
    "skipped_providers_json": "TEXT",
    "duration_seconds": "REAL",
    "errors_json": "TEXT",
}


def ensure_purge_history_table(target_engine: Engine = engine) -> None:
    """Create/upgrade market_data_purge_history idempotently."""
    with target_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_data_purge_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                purged_rows INTEGER NOT NULL DEFAULT 0,
                skipped_providers_json TEXT,
                duration_seconds REAL,
                errors_json TEXT
            )
        """))
        existing = {
            str(row[1])
            for row in conn.execute(text("PRAGMA table_info(market_data_purge_history)")).fetchall()
        }
        for column_name, sql_type in PURGE_HISTORY_COLUMN_SQL_TYPES.items():
            if column_name in existing:
                continue
            conn.execute(text(
                f"ALTER TABLE market_data_purge_history ADD COLUMN {column_name} {sql_type}"
            ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_market_data_purge_history_started "
            "ON market_data_purge_history(started_at)"
        ))


def ensure_default_tenant() -> None:
    """Sprint T1 (2026-06-08): legt den Default-Tenant 'main' an wenn nicht da.

    Tier 1 (Self-Hosted) und Tier 3 (Dedicated) nutzen genau diesen einen
    Eintrag. Tier 2 (Shared-Cloud) ueberschreibt das via T4-Admin-API.

    Idempotent: zweiter Aufruf macht nichts.

    Defensive: Bei Fehler (z.B. Schema noch nicht vollstaendig migriert)
    wird das Anlegen geloggt, der Boot aber nicht abgebrochen.
    """
    try:
        from datetime import datetime, timezone
        from models.tenant import (
            DEFAULT_TENANT_ID,
            LICENSE_STATUS_ACTIVE,
            TIER_1_SELF_HOSTED,
            Tenant,
        )

        with SessionLocal() as db:
            existing = db.query(Tenant).filter(
                Tenant.id == DEFAULT_TENANT_ID
            ).first()
            if existing is not None:
                return
            now = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3] + "Z"
            tenant = Tenant(
                id=DEFAULT_TENANT_ID,
                display_name="Default Tenant",
                slug="main",
                hosting_tier=getattr(settings, "deployment_tier", TIER_1_SELF_HOSTED),
                license_status=LICENSE_STATUS_ACTIVE,
                license_valid_until=None,
                max_users=1,
                max_mandates=None,
                storage_quota_mb=None,
                is_active=1,
                created_at=now,
                updated_at=now,
            )
            db.add(tenant)
            db.commit()
    except Exception:
        # Boot-Robustheit: Default-Tenant-Setup darf den Backend-Start
        # nicht stoppen. Logging kann der Caller verarbeiten.
        pass


def ensure_default_ch_jurisdiction() -> None:
    """WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
    legt die JurisdictionProfile-Zeile fuer "CH" an, wenn sie fehlt.

    Analog zu ensure_default_tenant() direkt darueber: genau eine
    approved/nicht-provisorische Zeile fuer den einzigen heute existierenden
    Markt (Schweiz). Kein Mandat referenziert diese Zeile per FK -- Mandate.
    jurisdiction bleibt NULL fuer CH (siehe models/mandates.py) und wird von
    der bestehenden Engine ausschliesslich als String "CH" interpretiert,
    NICHT als Fremdschluessel auf diese Tabelle. Diese Zeile ist reine
    Stammdaten-Grundlage fuer spaetere Arbeitspakete (Router/UI), die eine
    Liste verfuegbarer/freigegebener Jurisdiktionen brauchen.

    Idempotent: zweiter Aufruf legt keine zweite CH-Zeile an (code ist
    UNIQUE).

    Defensive: Bei Fehler (z.B. Schema noch nicht vollstaendig migriert)
    wird das Anlegen geloggt, der Boot aber nicht abgebrochen.
    """
    try:
        from datetime import datetime, timezone
        from models.jurisdiction import JurisdictionProfile

        with SessionLocal() as db:
            existing = db.query(JurisdictionProfile).filter(
                JurisdictionProfile.code == "CH"
            ).first()
            if existing is not None:
                return
            now = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3] + "Z"
            profile = JurisdictionProfile(
                id=new_uuid(),
                code="CH",
                display_name="Schweiz",
                home_currency="CHF",
                is_active=1,
                is_provisional=0,
                status="approved",
                created_by=None,
                created_at=now,
                updated_at=now,
            )
            db.add(profile)
            db.commit()
    except Exception:
        # Boot-Robustheit: Default-Jurisdiktion-Setup darf den Backend-Start
        # nicht stoppen. Logging kann der Caller verarbeiten.
        pass


def ensure_default_de_jurisdiction() -> None:
    """Deutschland-Anbindung (2026-07-31, Entscheid Auftraggeber): legt die
    DE-JurisdictionProfile-Zeile + Home-Bias-Default-Zeilen an (siehe
    services/jurisdiction/de_seed.py::ensure_de_jurisdiction_seed -- dort die
    volle Herleitung/Begruendung der Werte). Idempotent, defensiv wie
    ensure_default_ch_jurisdiction() direkt darueber -- beruehrt NIE eine
    CH-Zeile und blockiert den Boot nie."""
    try:
        from services.jurisdiction.de_seed import ensure_de_jurisdiction_seed

        with SessionLocal() as db:
            ensure_de_jurisdiction_seed(db)
            db.commit()
    except Exception:
        pass


def ensure_client_login_user_tenant_backfill(engine_to_use=None) -> None:
    """SEC-1 (2026-07-04): weist Bestands-Client-Login-User (role='client') mit
    tenant_id IS NULL den Tenant ihres verlinkten Clients zu.

    Hintergrund: Der Client-Login-Pfad (routers/clients.py:create_client_login)
    hat den User historisch OHNE tenant_id angelegt -> NULL-Tenant-User, die im
    Non-Strict-Modus fuer JEDEN Tenant sichtbar sind (Bruch der Mandantentrennung,
    FINMA/FIDLEG/DSG). Der generische ensure_tenant_backfill() wuerde diese Rows
    pauschal nach 'main' ziehen — FALSCH, wenn der verlinkte Client zu einer
    anderen Firma gehoert. Deshalb laeuft dieser praezise Backfill (Tenant vom
    verlinkten Client via client_logins-Linkage) ZUERST.

    Idempotent (zweiter Lauf trifft 0 Rows) und defensiv (fehlende Tabelle/Spalte
    wird uebersprungen; Boot wird nie abgebrochen).
    """
    eng = engine_to_use if engine_to_use is not None else engine
    try:
        from sqlalchemy import text as _sql_text
        with eng.begin() as conn:
            conn.execute(
                _sql_text(
                    """
                    UPDATE users
                    SET tenant_id = (
                        SELECT c.tenant_id
                        FROM client_logins cl
                        JOIN clients c ON c.id = cl.client_id
                        WHERE cl.user_id = users.id
                    )
                    WHERE role = 'client'
                      AND tenant_id IS NULL
                      AND id IN (
                          SELECT cl2.user_id
                          FROM client_logins cl2
                          JOIN clients c2 ON c2.id = cl2.client_id
                          WHERE c2.tenant_id IS NOT NULL
                      )
                    """
                )
            )
    except Exception:
        # Tabelle/Spalte (noch) nicht vorhanden -> ueberspringen (Boot-Robustheit).
        pass


def ensure_tenant_backfill(engine_to_use=None) -> None:
    """E1 (2026-06-12, External-Access-Rollout): weist Bestands-Rows mit
    tenant_id IS NULL dem Default-Tenant 'main' zu.

    Hintergrund: tenant_id-Columns sind aus BC-Gruenden NULLABLE; die Isolation
    erlaubt heute `tenant_id == user_tid OR tenant_id IS NULL`. Vor Multi-Firma-
    Echtbetrieb muessen NULL-Rows verschwinden (sonst waeren sie fuer JEDEN Tenant
    sichtbar). Dieser Backfill ist die Vorbereitung fuer eine spaetere NOT-NULL-
    Constraint + das Entfernen der `OR IS NULL`-Klausel.

    2026-07-25 (Generalaudit): NUR in tenancy_mode == "single" (Tier 1/3 —
    strukturell IMMER genau ein Tenant, siehe models/tenant.py-Docstring)
    ist "main" fachlich garantiert korrekt. In tenancy_mode == "multi"
    (Tier 2, mehrere echte Firmen) lief dieser Backfill bisher UNCONDITIONAL
    bei JEDEM Boot und haette jede zukuenftige NULL-tenant_id-Zeile (z.B. durch
    einen noch nicht auditierten Endpoint oder Bug) STILLSCHWEIGEND der Firma
    zugewiesen, die zufaellig 'main' heisst -- eine falsche Zuordnung ist hier
    schlimmer als das (bereits bekannte, dokumentierte) NULL-bleibt-sichtbar-
    fuer-alle-Verhalten, weil sie den Datensatz faelschlich als legitimes
    Eigentum von 'main' erscheinen laesst (Bruch der Mandantentrennung durch
    die Migration selbst). Deshalb: in "multi" ueberspringen, NULL bleibt NULL.

    Idempotent (zweiter Lauf trifft 0 Rows) und defensiv (pro Tabelle isoliert;
    fehlende Tabelle/Spalte wird uebersprungen; Boot wird nie abgebrochen).
    """
    if str(getattr(settings, "tenancy_mode", "single") or "single").strip().lower() == "multi":
        return
    eng = engine_to_use if engine_to_use is not None else engine
    try:
        from models.tenant import DEFAULT_TENANT_ID
        from sqlalchemy import text as _sql_text
        for table in ("users", "clients", "mandates", "protocol_bausteine"):
            try:
                with eng.begin() as conn:
                    conn.execute(
                        _sql_text(
                            f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"
                        ),
                        {"tid": DEFAULT_TENANT_ID},
                    )
            except Exception:
                # Tabelle/Spalte (noch) nicht vorhanden -> ueberspringen.
                pass
    except Exception:
        pass


_LEGACY_HOUSE_MATRIX_REAL_ESTATE_MAX = {
    "Kapitalschutz": 1000,
    "Defensiv": 1500,
    "Ausgewogen": 1500,
    "Wachstumsorientiert": 1200,
    # Bestehende Datenbanken koennen noch den historischen Kurznamen tragen.
    "Wachstum": 1200,
    "Dynamisch": 1000,
    "Aktien": 800,
}


def migrate_house_matrix_real_estate_cap_20(engine_to_use=None) -> int:
    """Hebt nur unveraenderte Legacy-Defaults auf die neue 20%-Obergrenze.

    Bewusst kein pauschales UPDATE: individuell konfigurierte House-Matrix-
    Zeilen bleiben erhalten. Die Zielquote wird nicht veraendert.
    """
    eng = engine_to_use if engine_to_use is not None else engine
    updated = 0
    try:
        with eng.begin() as conn:
            for profile_name, legacy_max_bps in _LEGACY_HOUSE_MATRIX_REAL_ESTATE_MAX.items():
                result = conn.execute(
                    text(
                        """
                        UPDATE house_matrix
                        SET real_estate_max_bps = 2000,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE is_active = 1
                          AND profile_name = :profile_name
                          AND real_estate_max_bps = :legacy_max_bps
                          AND policy_id IN (
                              SELECT id
                              FROM optimizer_policies
                              WHERE is_current = 1
                                AND max_real_estate_bps >= 2000
                          )
                        """
                    ),
                    {
                        "profile_name": profile_name,
                        "legacy_max_bps": legacy_max_bps,
                    },
                )
                if result.rowcount and result.rowcount > 0:
                    updated += int(result.rowcount)
    except Exception:
        # Boot-Robustheit: eine alte/partielle DB darf den Start nicht stoppen.
        return 0
    return updated


def init_db() -> None:
    active_url = build_database_url(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))
    if settings.db_bootstrap_schema_on_startup and is_sqlite_database_url(active_url):
        bootstrap_sqlite_schema(db_path=settings.db_path, db_key=getattr(settings, 'db_key', None))

    # Import von Tenant-Model VOR create_all, damit das Table angelegt wird.
    import models.tenant  # noqa: F401
    # WP1 (2026-07-30): dito fuer die neuen Jurisdiktions-Tabellen.
    import models.jurisdiction  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns()
    migrate_house_matrix_real_estate_cap_20()
    ensure_snapshot_tables()
    from services.market_data.provider_health_registry import ensure_provider_health_table
    ensure_provider_health_table(engine)
    ensure_purge_history_table(engine)
    run_risk_assessment_answer_migration(engine)
    run_advisory_log_migration(engine)
    ensure_audit_log_actions()
    # U-38: Indexes nach ensure_audit_log_actions, weil das die Tabelle
    # ggf. komplett neu baut (Index-Drift-Risk).
    ensure_audit_log_indexes()
    # Sprint T1 (2026-06-08): Default-Tenant 'main' anlegen wenn nicht da.
    # Backwards-Compat: tenant_id-Columns sind NULLABLE, aber die Existenz
    # der 'main'-Row erlaubt T2-Sprint die Auth-Layer-Migration.
    ensure_default_tenant()
    # WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
    # Default-Jurisdiktion 'CH' anlegen wenn nicht da (analog zu
    # ensure_default_tenant() direkt darueber).
    ensure_default_ch_jurisdiction()
    # Deutschland-Anbindung (2026-07-31): zweite Jurisdiktion, analog CH.
    ensure_default_de_jurisdiction()
    # SEC-1 (2026-07-04): Client-Login-User mit NULL-Tenant praezise auf den
    # Tenant ihres verlinkten Clients ziehen — MUSS vor dem generischen
    # ensure_tenant_backfill() laufen, das sonst pauschal nach 'main' zieht.
    ensure_client_login_user_tenant_backfill()
    # E1 (2026-06-12): Bestands-Rows ohne tenant_id dem 'main'-Tenant zuweisen.
    ensure_tenant_backfill()
    # Postgres/RLS: SQLite bleibt unveraendert; PostgreSQL erzwingt die
    # Tenant-Isolation zusaetzlich auf Datenbankebene.
    from services.postgres_rls import ensure_postgres_rls_policies, ensure_postgres_tenant_not_null
    ensure_postgres_tenant_not_null(engine)
    ensure_postgres_rls_policies(engine)
