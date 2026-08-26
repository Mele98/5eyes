from pathlib import Path
import sys

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET_KEY = "CHANGE_ME_IN_PRODUCTION_USE_STRONG_RANDOM_KEY"


def resolve_env_file() -> str:
    env_override = Path.cwd() / '.env'
    candidates = []
    if getattr(sys, '_MEIPASS', None):
        candidates.extend([
            Path(sys.executable).resolve().parent / '.env',
            Path(getattr(sys, '_MEIPASS')).resolve() / '.env',
        ])
    module_dir = Path(__file__).resolve().parent
    candidates.extend([
        env_override,
        module_dir / '.env',
        module_dir.parent / '.env',
    ])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return '.env'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=resolve_env_file(),
        env_file_encoding='utf-8',
        extra='ignore',
    )

    app_name: str = '5Eyes WealthArchitekten API'
    app_version: str = '1.3.0'
    app_env: str = 'development'
    app_host: str = '127.0.0.1'
    app_port: int = 8000
    log_level: str = 'INFO'
    log_max_bytes: int = 2_000_000
    log_backup_count: int = 5

    # Database
    database_url: str | None = None
    db_path: str = str(Path.home() / '5eyes' / '5eyes.db')
    db_echo: bool = False
    db_key: str | None = None
    db_use_sqlcipher: bool = False
    db_bootstrap_schema_on_startup: bool = True

    # U-43 (Roadmap-Punkt 43, 2026-06-01): Log-Verzeichnis explizit
    # konfigurierbar. Vorher: gekoppelt an db_path.parent — sub-optimal
    # in packaged Electron (DB sollte ggf. in Backup-Volume liegen,
    # Logs aber in app.getPath('userData')/logs).
    # Leer = Fallback auf Path(db_path).parent (backwards-compat).
    log_dir: str = ''

    # Auth
    secret_key: str = DEFAULT_SECRET_KEY
    algorithm: str = 'HS256'
    access_token_expire_minutes: int = 480
    # Roadmap #28 (Standpunkt 2026-08-07): Refresh-Token-Rotation. Deutlich
    # laenger als access_token_expire_minutes -- der Sinn eines Refresh-Tokens
    # ist gerade, ein KURZES Access-Token (kleines Leck-Zeitfenster) mit einem
    # LANGEN, aber rotierenden (Reuse-Detection) Refresh-Token zu kombinieren,
    # statt ein einzelnes langlebiges Access-Token zu haben.
    refresh_token_expire_days: int = 30
    login_rate_limit_enabled: bool = True
    login_max_attempts: int = 5
    login_window_seconds: int = 60
    login_lockout_seconds: int = 600
    # AUTH-03 (Mega-Audit 2026-08-04): X-Forwarded-For wurde bisher IMMER als
    # Klartext-Wahrheit fuer den Rate-Limit-Guard-Key genommen -- ohne einen
    # tatsaechlich davorstehenden Reverse-Proxy kann JEDER Client den Header
    # selbst setzen und bekommt pro Request einen frischen Guard-Key (voller
    # Rate-Limit-Bypass auf Login/Bootstrap-Admin/Password-Reset/Invite).
    # trusted_proxy_count = Anzahl der Reverse-Proxy-Hops, denen VOR dieser
    # Instanz vertraut wird. 0 (Default, Tier-1 ohne Proxy) = XFF komplett
    # ignorieren, echte TCP-Peer-Adresse (request.client.host) verwenden.
    # >0 (Tier-2/3 hinter N Reverse-Proxies): Rightmost-Hop-Parsing -- der
    # N-te Eintrag von RECHTS ist der echte Client, alles rechts davon sind
    # die eigenen (vertrauenswuerdigen) Proxy-Hops.
    trusted_proxy_count: int = 0

    # CORS / Electron
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            'null',
            'http://localhost:3000',
            'http://localhost:5173',
            'http://127.0.0.1:3000',
            'http://127.0.0.1:5173',
            'app://.',
        ]
    )
    cors_allow_origin_regex: str | None = r'^null$'
    # 2026-07-25 (Generalaudit): Passwort-Reset-/Invite-Links wurden bisher aus
    # dem (Client-kontrollierten!) Host/X-Forwarded-Host-Header konstruiert --
    # Host-Header-Injection auf dem OEFFENTLICHEN, unauthentifizierten
    # /auth/password-reset/request-Endpoint erlaubte einen gueltigen Reset-
    # Link auf eine Phishing-Domain fuer die HINTERLEGTE (echte) E-Mail-Adresse
    # des Opfers zu versenden (klassisches "Password-Reset-Poisoning"). Ist
    # public_base_url gesetzt, wird IMMER dieser vertrauenswuerdige Wert
    # genutzt (Header ignoriert). Fuer jede extern erreichbare Installation
    # (Tier 2/3, Browser-Hosting) MUSS dies konfiguriert werden. Bleibt NULL
    # (Tier-1-Desktop-Default, kein externer Zugriff), bleibt das bisherige
    # Header-Fallback-Verhalten unveraendert.
    public_base_url: str | None = None

    # Price refresh
    price_scheduler_enabled: bool = True
    price_scheduler_timezone: str = 'Europe/Zurich'
    price_scheduler_hour: int = 6
    price_scheduler_minute: int = 0
    price_refresh_max_attempts: int = 2
    price_refresh_retry_delay_seconds: float = 1.0
    # Mega-Audit (2026-08-04): der Stooq-Fallback-Batch-Loop
    # (price_updater._fetch_stooq_symbol_points) feuerte bisher eine
    # ungebremste Serie von HTTP-GETs ab -- am staerksten genau dann, wenn
    # der PRIMARY-Provider (yfinance) bereits ausfaellt und ALLE Symbole auf
    # Stooq zurueckfallen. Kleine feste Pause zwischen Requests, Default
    # konservativ (nicht gemessen, siehe PR-Kommentar).
    stooq_batch_throttle_seconds: float = 0.3

    # Market data provider strategy
    price_refresh_primary_provider: str = 'yfinance'
    price_refresh_fallback_provider: str = 'stooq'
    reference_data_active_provider: str = 'local_catalog'
    id_mapping_active_provider: str = 'product_symbol_or_isin'
    macro_assumptions_active_provider: str = 'manual_cma'
    target_market_price_provider: str = 'twelvedata'
    target_reference_data_provider: str = 'eodhd'
    target_id_mapping_provider: str = 'openfigi'
    target_macro_core_provider: str = 'fred'
    target_macro_euro_provider: str = 'ecb'
    target_macro_swiss_provider: str = 'snb'
    target_enterprise_reference_provider: str = 'six'
    twelvedata_api_key: str | None = None
    eodhd_api_key: str | None = None
    openfigi_api_key: str | None = None
    fred_api_key: str | None = None
    six_api_key: str | None = None
    alphavantage_api_key: str | None = None

    # V3 Sprint 2026-05 (Multi-Source Data Aggregator).
    # Komma-separierte Reihenfolge der Provider; erste = Primary.
    # Gueltige Werte: yfinance, stooq, alphavantage, twelvedata
    # Default: yfinance,stooq,alphavantage (gratis-only, Tier 1)
    market_data_providers: str = 'yfinance,stooq,alphavantage'
    market_data_unhealthy_ttl_seconds: int = 300

    # P15 — Scheduler-Hooks fuer Cache-Purge und Cross-Validation.
    # daily_cache_purge laeuft taeglich 03:00 lokal (purgt expired Cache-Eintraege).
    # weekly_validation laeuft sonntags 04:00 lokal (Median-Vergleich Provider).
    market_data_cache_purge_enabled: bool = True
    market_data_cache_purge_hour: int = 3
    market_data_cache_purge_minute: int = 0
    market_data_validation_enabled: bool = False
    market_data_validation_hour: int = 4
    market_data_validation_minute: int = 0
    market_data_validation_day_of_week: str = 'sun'
    market_data_validation_symbols: str = ''  # kommaseparierte Liste
    market_data_validation_threshold_bps: int = 300
    market_data_daily_refresh_enabled: bool = True
    # Mega-Audit (2026-08-04): lag per Werkseinstellung exakt auf derselben
    # Uhrzeit wie price_scheduler_hour/minute (06:00:00) -- beide Jobs feuerten
    # zeitgleich gegen dieselben unauthentifizierten Provider (yfinance/stooq)
    # und verdoppelten die Last genau im Risiko-Zeitfenster. 20 Min. Versatz
    # entzerrt das, ohne die Jobs inhaltlich zu aendern.
    market_data_daily_refresh_hour: int = 6
    market_data_daily_refresh_minute: int = 20
    market_data_daily_refresh_max_symbols: int = 500

    # P22 — Webhook-Notifier fuer Validation-Alerts. Default leer = no-op.
    market_data_alert_webhook_url: str = ''
    market_data_alert_webhook_timeout_seconds: float = 5.0

    # System / diagnostics
    recent_log_lines_default: int = 120
    recent_log_lines_max: int = 500

    # Sprint U-7 (2026-06-04): Content-Security-Policy + Permissions-Policy.
    csp_enabled: bool = True
    csp_policy: str = ''
    permissions_policy_enabled: bool = True
    hsts_enabled: bool = False

    # Sprint U-64 (2026-06-04): Telemetrie-Adapter (opt-in).
    telemetry_enabled: bool = False
    telemetry_dsn: str = ''
    telemetry_environment: str = ''
    telemetry_sample_rate: float = 1.0

    # U-8 — DB-Backup-Strategie (PR #106).
    backup_enabled: bool = True
    backup_dir: str = str(Path.home() / '5eyes' / 'backups')
    backup_retain_days: int = 30
    backup_keep_minimum: int = 3
    backup_scheduler_enabled: bool = True
    backup_scheduler_timezone: str = 'Europe/Zurich'
    backup_scheduler_hour: int = 3
    backup_scheduler_minute: int = 0

    # Roadmap #15 (Off-Site-Backup-Replikation, 2026-08-07): das lokale,
    # verschluesselte SQLCipher-Backup (siehe backup_dir oben) schuetzt nicht
    # gegen einen Ausfall des Standorts selbst (Hardware/RZ-Ausfall). Opt-in
    # Kopie via rsync-ueber-SSH an einen zweiten CH-Standort. Default AUS --
    # erfordert einen bereits eingerichteten SSH-Zugang zum Ziel-Host.
    backup_offsite_enabled: bool = False
    # rsync-Zielangabe, z.B. "5eyes-offsite@backup-host.ch:/srv/5eyes-offsite/"
    backup_offsite_target: str = ''
    backup_offsite_ssh_key_path: str = ''
    backup_offsite_ssh_port: int = 22
    # Sekunden, nach denen ein haengender rsync-Versuch abgebrochen wird --
    # ein Netzwerk-Hang darf den Backup-Scheduler nie blockieren.
    backup_offsite_timeout_seconds: int = 120

    # U-19 — Aggregator-Cache (Roadmap-Punkt 19). compute_advisory_report
    # macht 17 Sektionen mit je mehreren DB-Queries; der Sub-App-User klickt
    # durch Sektionen und triggert pro Sektionsanzeige einen vollen Recompute.
    # In-Memory-TTL+LRU-Cache zwischen HTTP-Endpoint und Aggregator.
    aggregator_cache_enabled: bool = True
    aggregator_cache_ttl_seconds: int = 60
    aggregator_cache_max_size: int = 256

    # Optimizer (siehe docs/planning/2026-05-05-stochastic-optimizer-spec.md
    # und claude-bericht-Advisory-Methodik-assetallocation-optimierung-v3-codeplan.md).
    # Gueltige Werte:
    # - 'house_matrix': expliziter Legacy-/Notbetrieb; Solver wird nicht ausgefuehrt.
    # - 'iterative': reservierter Legacy-/Experimentmodus, faellt auf house_matrix.
    # - 'shadow_stochastic': Solver laeuft parallel; House-Matrix bleibt aktive
    #   Zielallokation. Solver-Ergebnis wird nur als Methodenvergleich geliefert
    #   und NICHT auf der TargetAllocation als optimization_* persistiert.
    # - 'stochastic' (default): finales Produktionsmodell. House Matrix liefert
    #   Initialisierung/Policy-Bounds und bleibt auditierter technischer Fallback.
    optimizer_mode: str = 'stochastic'

    # Mean-Shift Importance Sampling fuer Tail-Risk im stochastic Optimizer
    # (Phase 5 der Stochastic-Optimizer-Spec). Default OFF, opt-in via
    # MC_IMPORTANCE_SAMPLING_ENABLED=true. Bringt 5-10x Varianz-Reduktion
    # bei Tail-Statistiken (P(Drawdown > X)) ohne Bias. Siehe
    # services/optimizer/importance_sampling.py.
    mc_importance_sampling_enabled: bool = False
    # Shift-Magnitude in Standard-Deviationen (typisch 0.3-1.0). Hoeher =
    # mehr Tail-Konzentration aber hoeherer Bias-Variance-Tradeoff.
    mc_importance_sampling_strength: float = 0.5
    # P1 (2026-06-06): Auto-Decision — IS wird automatisch aktiviert wenn der
    # Mandate-Context Tail-Schutz erfordert (konservatives Risikoprofil,
    # Decumulation, mindestens ein hart-Ziel). Default TRUE — das ist die
    # Verbesserung gegenueber dem urspruenglichen Phase-5 opt-in-Konzept.
    # Wenn mc_importance_sampling_enabled=True ueberschreibt das die
    # Auto-Decision (legacy force-on). Wenn beide False: nie IS.
    mc_importance_sampling_auto_enable: bool = True
    # Sprint C2-Wiring (2026-06-08): Default Tax-Modus fuer simulate_wealth_paths.
    # 'median' (Default) = Backwards-Compat. HNW-Mandate koennen via Admin auf
    # 'binned' setzen fuer per-Pfad-progressive-Tax-Berechnung. 'per_path' nur
    # fuer Audit-Strict-Modus (langsam).
    mc_default_tax_mode: str = "median"

    # ----- Sprint T1 (2026-06-08): 3-Tier-Hosting-Architektur -----
    # Bestimmt Deployment-Charakteristik des Backends.
    # 'tier1' (Default): Self-Hosted, single-tenant ('main'), kein Tenant-UI
    # 'tier2': Shared-Cloud, multi-tenant via RLS / JWT-claim
    # 'tier3': Dedicated-VPS, single-tenant per Instance, voll-Multi-User
    # Siehe docs/adr/ADR-009-3-tier-hosting-architecture.md
    deployment_tier: str = "tier1"
    # Tenancy-Modus — fuer Tier 1 + 3 = 'single', fuer Tier 2 = 'multi'.
    # Wird typischerweise vom Tier abgeleitet, kann aber manuell ueberschrieben
    # werden (z.B. Tier 1 Multi-User-Test-Setup).
    tenancy_mode: str = "single"
    # Tenant-Admin-UI fuer Super-Admin. Tier 2 = True, sonst False.
    tenant_admin_ui_enabled: bool = False
    # E1 (2026-06-14): Strikte Mandanten-Trennung. Default False = BC (Rows mit
    # tenant_id IS NULL gelten als zum eigenen Tenant gehoerig). True (Multi-Firma/
    # Staging) = NUR exakter Tenant-Match, NULL-Rows sind unsichtbar. Voraussetzung:
    # Backfill gelaufen + alle Creates setzen tenant_id (Client/Mandate/User/Baustein).
    strict_tenant_isolation: bool = False
    # E1 (2026-06-14): Pflicht-2FA. True (Staging/extern) = Nutzer ohne aktives
    # 2FA muessen es nach dem Login zwingend einrichten, bevor sie weiterarbeiten.
    require_2fa: bool = False

    # Welle 2.1 (2026-07): Opt-in FIDLEG-Hard-Gate fuer die Eignungspruefung.
    # Default FALSE = heutiges Verhalten unveraendert — der Suitability-Check
    # bleibt ein reiner Sichtbarkeits-/Audit-Layer (services/suitability_audit.py),
    # ein Empfehlungs-Run wird NICHT blockiert. Wenn TRUE, blockiert der
    # Router-Endpoint einen Empfehlungs-/Strategie-Run mit HTTP 409, sobald
    # audit_mandate_suitability() eine fehlende/nicht-konforme Eignungspruefung
    # meldet (is_compliant=False, FIDLEG Art. 11-13). NON-BREAKING: nur explizit
    # per Config aktivierbar (z.B. compliance-strenge Deployments).
    require_suitability_before_recommendation: bool = False

    # E1 (2026-06-14): SMTP fuer Einladungs-E-Mails (Onboarding). Default AUS —
    # ist es aus/unkonfiguriert, faellt der Invite-Flow auf Link-Copy zurueck
    # (kein harter Fehler). Stdlib-smtplib, keine neue Dependency.
    smtp_enabled: bool = False
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from: str = '5eyes <no-reply@5eyes.local>'
    smtp_use_tls: bool = True        # STARTTLS auf smtp_port
    smtp_timeout_seconds: int = 10

    # Phase-0 safety gate for external access. Staging sets this to False so
    # writes explicitly classified as real client data are rejected.
    allow_real_client_data: bool = True
    # Tenant-DEK envelope encryption. Production/Tier-2 should supply this via
    # env/vault (TENANT_MASTER_KEK); development can pass an explicit KEK in tests.
    tenant_master_kek: str = ''

    # Browser-Hosting (2026-06-10): Haupt-App (5eyes_v2.html) ueber das Backend
    # ausliefern, damit ein einzelner Host/Tunnel die komplette App im Browser
    # bereitstellt (Remote-Demo/Tier-2). Default AUS — Tier-1/Electron laedt die
    # HTML weiterhin lokal via file://. Nur fuer Browser-/Tunnel-Demos einschalten.
    serve_main_frontend: bool = False

    # Sprint U-P8 Fix M1 (2026-05-20): Block-Diagonal Sub-Asset-Class
    # Korrelation innerhalb eines Buckets. Default 1.0 = perfekt korreliert
    # (Backwards-Compat zur Bucket-Skalar-Vola). Werte < 1.0 aktivieren
    # echte Intra-Bucket-Diversifikation (z.B. CH-Equity ↔ EM-Equity ρ=0.7-0.8).
    # Inter-Bucket-Korrelationen bleiben aus _DEFAULT_CORRELATION_MATRIX
    # (siehe portfolio_engine._DEFAULT_CORRELATION_MATRIX).
    sub_class_intra_correlation: float = 1.0

    @field_validator('app_env')
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {'development', 'test', 'staging', 'production'}
        if normalized not in allowed:
            raise ValueError(f"app_env must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator('optimizer_mode')
    @classmethod
    def validate_optimizer_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {'house_matrix', 'shadow_stochastic', 'stochastic'}
        if normalized not in allowed:
            raise ValueError(f"optimizer_mode must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator('sub_class_intra_correlation')
    @classmethod
    def validate_sub_class_intra_correlation(cls, value: float) -> float:
        v = float(value)
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"sub_class_intra_correlation muss in [0.0, 1.0] sein "
                f"(erhalten: {value})"
            )
        return v

    @field_validator(
        'price_refresh_primary_provider',
        'price_refresh_fallback_provider',
        'reference_data_active_provider',
        'id_mapping_active_provider',
        'macro_assumptions_active_provider',
        'target_market_price_provider',
        'target_reference_data_provider',
        'target_id_mapping_provider',
        'target_macro_core_provider',
        'target_macro_euro_provider',
        'target_macro_swiss_provider',
        'target_enterprise_reference_provider',
    )
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        return value.strip().lower().replace('-', '_').replace(' ', '_')

    @field_validator(
        'log_max_bytes',
        'log_backup_count',
        'access_token_expire_minutes',
        'login_max_attempts',
        'login_window_seconds',
        'login_lockout_seconds',
        'recent_log_lines_default',
        'recent_log_lines_max',
        'market_data_daily_refresh_max_symbols',
    )
    @classmethod
    def validate_positive_numbers(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('value must be greater than 0')
        return value


    @field_validator('app_port')
    @classmethod
    def validate_app_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError('app_port must be between 1 and 65535')
        return value

    @field_validator('trusted_proxy_count')
    @classmethod
    def validate_trusted_proxy_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError('trusted_proxy_count must be >= 0')
        return value

    @field_validator('price_scheduler_hour')
    @classmethod
    def validate_price_scheduler_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError('price_scheduler_hour must be between 0 and 23')
        return value

    @field_validator('price_scheduler_minute')
    @classmethod
    def validate_price_scheduler_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError('price_scheduler_minute must be between 0 and 59')
        return value

    @field_validator('market_data_daily_refresh_hour')
    @classmethod
    def validate_market_data_daily_refresh_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError('market_data_daily_refresh_hour must be between 0 and 23')
        return value

    @field_validator('market_data_daily_refresh_minute')
    @classmethod
    def validate_market_data_daily_refresh_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError('market_data_daily_refresh_minute must be between 0 and 59')
        return value

    @model_validator(mode='after')
    def validate_cors_safety(self):
        """Sprint U-58/60 (2026-06-01): CORS-Audit-Safety.

        Regeln:
        - allow_origins darf NIE '*' enthalten — wuerde mit
          allow_credentials=True (in main.py hardcoded) eine Browser-Spec-
          Violation triggern und die Middleware ohne Schutz laufen lassen.
        - In Production: KEINE localhost/127.0.0.1-Origins (Browser-
          Berater-Setups, kein Dev-Loophole).
        """
        if any(str(o).strip() == '*' for o in self.cors_origins):
            raise ValueError(
                'cors_origins darf nicht "*" enthalten — '
                'mit allow_credentials=True ist das Browser-Spec-Verletzung. '
                'Liste konkrete Origins auf (Electron app://., '
                'http://localhost:5173 fuer Dev, etc.).'
            )
        if self.app_env == 'production':
            forbidden = [
                o for o in self.cors_origins
                if 'localhost' in str(o) or '127.0.0.1' in str(o)
            ]
            if forbidden:
                raise ValueError(
                    f'cors_origins in production darf keine localhost-'
                    f'Origins enthalten: {forbidden}'
                )
        return self

    @field_validator('backup_scheduler_hour')
    @classmethod
    def validate_backup_scheduler_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError('backup_scheduler_hour must be between 0 and 23')
        return value

    @field_validator('backup_scheduler_minute')
    @classmethod
    def validate_backup_scheduler_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError('backup_scheduler_minute must be between 0 and 59')
        return value

    @field_validator('backup_retain_days')
    @classmethod
    def validate_backup_retain_days(cls, value: int) -> int:
        if value < 0:
            raise ValueError('backup_retain_days must be >= 0 (0 = nie aufraeumen)')
        return value

    @field_validator('backup_keep_minimum')
    @classmethod
    def validate_backup_keep_minimum(cls, value: int) -> int:
        if value < 1:
            raise ValueError('backup_keep_minimum muss >= 1 sein (Katastrophen-Schutz)')
        return value

    @field_validator('aggregator_cache_ttl_seconds')
    @classmethod
    def validate_aggregator_cache_ttl(cls, value: int) -> int:
        if value < 0:
            raise ValueError('aggregator_cache_ttl_seconds muss >= 0 sein (0 = effektiv aus)')
        return value

    @field_validator('aggregator_cache_max_size')
    @classmethod
    def validate_aggregator_cache_max_size(cls, value: int) -> int:
        if value < 1:
            raise ValueError('aggregator_cache_max_size muss >= 1 sein')
        return value

    @model_validator(mode='after')
    def validate_security(self):
        if self.app_env == 'production' and self.optimizer_mode != 'stochastic':
            raise ValueError(
                'production requires optimizer_mode=stochastic; house_matrix '
                'is reserved for the audited internal solver fallback.'
            )
        if self.app_env in {'staging', 'production'} and self.secret_key == DEFAULT_SECRET_KEY:
            raise ValueError('secret_key must be overridden outside development/test')
        uses_postgres = bool(
            self.database_url
            and str(self.database_url).strip().lower().startswith(("postgresql://", "postgresql+"))
        )
        if self.app_env == 'production' and not uses_postgres and not (self.db_use_sqlcipher and self.db_key):
            raise ValueError('production requires PostgreSQL or db_use_sqlcipher=true with a non-empty db_key')
        # #299-Security-Follow-up #5: Tenant-Isolation-Backstop erzwingen. Auf
        # Server-Deployments (PostgreSQL = Tier-2/3, mandantenfaehig) MUSS in
        # staging/production der App-Layer-Filter strikt sein — sonst waere eine
        # Row mit vergessenem tenant_id (NULL) tenant-uebergreifend sichtbar
        # (Guertel + Hosentraeger zur DB-seitigen RLS, die nur bei nicht-Superuser-
        # Rolle greift). Tier-1 (SQLite-Desktop, single-tenant) ist nicht betroffen.
        if self.app_env in {'staging', 'production'} and uses_postgres and not self.strict_tenant_isolation:
            raise ValueError(
                'strict_tenant_isolation muss in staging/production mit PostgreSQL '
                'aktiv sein (Multi-Tenant-Isolation-Backstop).'
            )
        if self.db_use_sqlcipher and not self.db_key:
            raise ValueError('db_key must be set when db_use_sqlcipher=true')
        if self.recent_log_lines_default > self.recent_log_lines_max:
            raise ValueError('recent_log_lines_default must not exceed recent_log_lines_max')
        # Sprint U-59 (2026-06-01): Bearer-Token-TTL hard cap in production.
        # 24h Maximum = ein Arbeitstag, danach Re-Login. Verhindert dass
        # versehentlich JAHRE-Tokens generiert werden (Token-Diebstahl-
        # Window-Mitigation). Dev/test bleiben frei (z.B. fuer Long-running
        # Integration-Tests).
        if self.app_env == 'production' and self.access_token_expire_minutes > 1440:
            raise ValueError(
                f'access_token_expire_minutes={self.access_token_expire_minutes} '
                f'exceeds 1440 (24h) in production. Reduziere TTL um '
                f'Token-Diebstahl-Window zu begrenzen.'
            )
        return self


settings = Settings()
