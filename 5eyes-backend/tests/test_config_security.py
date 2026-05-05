import pytest

from config import DEFAULT_SECRET_KEY, Settings


def test_production_requires_sqlcipher_and_db_key():
    with pytest.raises(ValueError, match='db_use_sqlcipher=true'):
        Settings(
            app_env='production',
            secret_key='prod-secret',
            db_use_sqlcipher=False,
            db_key=None,
        )


def test_production_accepts_encrypted_database_configuration():
    settings = Settings(
        app_env='production',
        secret_key='prod-secret',
        db_use_sqlcipher=True,
        db_key='prod-db-key',
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


def test_optimizer_mode_defaults_to_house_matrix():
    """Default optimizer_mode soll house_matrix sein (kein Verhaltens-Change)."""
    settings = Settings(
        app_env='development',
        secret_key=DEFAULT_SECRET_KEY,
    )
    assert settings.optimizer_mode == 'house_matrix'


def test_optimizer_mode_accepts_iterative_and_stochastic():
    """Erlaubte Werte fuer optimizer_mode."""
    for mode in ('house_matrix', 'iterative', 'stochastic'):
        settings = Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            optimizer_mode=mode,
        )
        assert settings.optimizer_mode == mode


def test_optimizer_mode_rejects_unknown_value():
    """Unbekanntes optimizer_mode -> Validation-Fehler."""
    with pytest.raises(ValueError, match='optimizer_mode'):
        Settings(
            app_env='development',
            secret_key=DEFAULT_SECRET_KEY,
            optimizer_mode='quantum_ai_solver',
        )
