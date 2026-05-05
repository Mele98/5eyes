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
    db_path: str = str(Path.home() / '5eyes' / '5eyes.db')
    db_echo: bool = False
    db_key: str | None = None
    db_use_sqlcipher: bool = False
    db_bootstrap_schema_on_startup: bool = True

    # Auth
    secret_key: str = DEFAULT_SECRET_KEY
    algorithm: str = 'HS256'
    access_token_expire_minutes: int = 480
    login_rate_limit_enabled: bool = True
    login_max_attempts: int = 5
    login_window_seconds: int = 60
    login_lockout_seconds: int = 600

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

    # Price refresh
    price_scheduler_enabled: bool = True
    price_scheduler_timezone: str = 'Europe/Zurich'
    price_scheduler_hour: int = 6
    price_scheduler_minute: int = 0
    price_refresh_max_attempts: int = 2
    price_refresh_retry_delay_seconds: float = 1.0

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

    # System / diagnostics
    recent_log_lines_default: int = 120
    recent_log_lines_max: int = 500

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

    @model_validator(mode='after')
    def validate_security(self):
        if self.app_env in {'staging', 'production'} and self.secret_key == DEFAULT_SECRET_KEY:
            raise ValueError('secret_key must be overridden outside development/test')
        if self.app_env == 'production' and not (self.db_use_sqlcipher and self.db_key):
            raise ValueError('production requires db_use_sqlcipher=true and a non-empty db_key')
        if self.db_use_sqlcipher and not self.db_key:
            raise ValueError('db_key must be set when db_use_sqlcipher=true')
        if self.recent_log_lines_default > self.recent_log_lines_max:
            raise ValueError('recent_log_lines_default must not exceed recent_log_lines_max')
        return self


settings = Settings()
