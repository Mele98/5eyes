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
