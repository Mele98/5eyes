import pytest

from config import DEFAULT_SECRET_KEY, Settings


PRODUCTION_CORS_ORIGINS = ['https://app.5eyes.local']


def test_production_requires_sqlcipher_and_db_key():
    with pytest.raises(ValueError, match='db_use_sqlcipher=true'):
        Settings(
            app_env='production',
            secret_key='prod-secret',
            db_use_sqlcipher=False,
            db_key=None,
            cors_origins=PRODUCTION_CORS_ORIGINS,
        )


def test_production_accepts_encrypted_database_configuration():
    settings = Settings(
        app_env='production',
        secret_key='prod-secret',
        db_use_sqlcipher=True,
        db_key='prod-db-key',
        cors_origins=PRODUCTION_CORS_ORIGINS,
    )

    assert settings.db_use_sqlcipher is True
    assert settings.db_key == 'prod-db-key'


def test_development_can_still_run_without_sqlcipher():
    settings = Settings(
        app_env='development',
        secret_key=DEFAULT_SECRET_KEY,
        db_use_sqlcipher=False,
        db_key=None,
    )

    assert settings.app_env == 'development'


def test_backup_keep_minimum_validator_returns_the_validated_value():
    """OPS-003 (Codex-Audit 2026-08-25): der Validator warf zwar bei
    ungueltigen Werten, hatte aber kein `return value` -- Pydantic
    uebernahm dadurch `None` als validierten Wert. services/backup.py::
    _prune_old_backups() rechnet `all_backups[keep_minimum:]`; mit
    `keep_minimum=None` schuetzt dieser Slice KEINE der neuesten Backups
    mehr (statt die konfigurierte Mindestanzahl auszunehmen), das
    Katastrophen-Schutznetz war also lautlos deaktiviert."""
    settings = Settings(
        app_env='development',
        secret_key=DEFAULT_SECRET_KEY,
        db_use_sqlcipher=False,
        db_key=None,
        backup_keep_minimum=5,
    )

    assert settings.backup_keep_minimum == 5


def test_backup_keep_minimum_still_rejects_values_below_one():
    with pytest.raises(ValueError, match='backup_keep_minimum'):
        Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            db_use_sqlcipher=False,
            db_key=None,
            backup_keep_minimum=0,
        )


def test_staging_rejects_default_secret_key():
    """staging muss secret_key explizit setzen (kein Placeholder)."""
    with pytest.raises(ValueError, match='secret_key'):
        Settings(
            app_env='staging',
            secret_key=DEFAULT_SECRET_KEY,
            db_use_sqlcipher=True,
            db_key='staging-db-key',
        )


def test_production_rejects_default_secret_key():
    """production muss secret_key explizit setzen."""
    with pytest.raises(ValueError, match='secret_key'):
        Settings(
            app_env='production',
            secret_key=DEFAULT_SECRET_KEY,
            db_use_sqlcipher=True,
            db_key='prod-db-key',
            cors_origins=PRODUCTION_CORS_ORIGINS,
        )


def test_sqlcipher_enabled_requires_db_key():
    """Auch in development: sqlcipher=true ohne db_key ist ungueltig."""
    with pytest.raises(ValueError, match='db_key'):
        Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            db_use_sqlcipher=True,
            db_key=None,
        )


def test_recent_log_default_must_not_exceed_max():
    """recent_log_lines_default <= recent_log_lines_max ist Invariante."""
    with pytest.raises(ValueError, match='recent_log_lines_default'):
        Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            recent_log_lines_default=600,
            recent_log_lines_max=500,
        )


def test_optimizer_mode_defaults_to_stochastic():
    """Stochastik ist das finale Produktionsmodell; House bleibt Fallback."""
    settings = Settings(
        app_env='development',
        secret_key=DEFAULT_SECRET_KEY,
    )
    assert settings.optimizer_mode == 'stochastic'


def test_optimizer_mode_accepts_explicit_nonproduction_modes():
    """Erlaubte Werte fuer optimizer_mode."""
    for mode in ('house_matrix', 'shadow_stochastic', 'stochastic'):
        settings = Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            optimizer_mode=mode,
        )
        assert settings.optimizer_mode == mode


def test_optimizer_mode_rejects_unimplemented_iterative_mode():
    with pytest.raises(ValueError, match='optimizer_mode'):
        Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            optimizer_mode='iterative',
        )


@pytest.mark.parametrize('mode', ['house_matrix', 'shadow_stochastic'])
def test_production_requires_active_stochastic_model(mode):
    with pytest.raises(ValueError, match='optimizer_mode=stochastic'):
        Settings(
            app_env='production',
            secret_key='prod-secret',
            db_use_sqlcipher=True,
            db_key='prod-db-key',
            cors_origins=PRODUCTION_CORS_ORIGINS,
            optimizer_mode=mode,
        )


def test_optimizer_mode_rejects_unknown_value():
    """Unbekanntes optimizer_mode -> Validation-Fehler."""
    with pytest.raises(ValueError, match='optimizer_mode'):
        Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            optimizer_mode='quantum_ai_solver',
        )
