"""Delta-Pruefung #864 (T-2, T-3): Secrets der Konfiguration erscheinen weder in
einem ValidationError noch in ``repr(settings)``.

- T-2: pydantic zeigt bei Modell-Validierungsfehlern sonst ``input_value`` = die
  gesamte Eingabe (inkl. DB_KEY, SECRET_KEY, SMTP-Passwort, KEK) in Exception
  und Log. ``Settings`` setzt deshalb ``hide_input_in_errors=True``.
- T-3: ``repr(settings)`` (Debug-Ausgaben, Tracebacks mit lokalen Variablen,
  Logging von Objekten) zeigte jedes Secret im Klartext. Die Secret-Felder haben
  ``repr=False``; ihre Werte und alle Verwender bleiben unveraendert (``str``).

Laeuft ohne sqlcipher3 und ohne Umgebung (reine Konfigurationspruefung).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import Settings  # noqa: E402

# Jedes Secret-Feld der Konfiguration mit einem eindeutig markierten Wert.
SECRET_FIELDS = {
    "secret_key": "MARKsecretkey" + "s" * 40,
    "db_key": "MARKdbkey" + "d" * 40,
    "smtp_password": "MARKsmtppassword",
    "tenant_master_kek": "MARKtenantkek",
    "backup_hmac_key": "MARKbackuphmac",
    "database_url": "sqlite:////tmp/MARKdburl.db",
    "twelvedata_api_key": "MARKtwelvedata",
    "eodhd_api_key": "MARKeodhd",
    "openfigi_api_key": "MARKopenfigi",
    "fred_api_key": "MARKfred",
    "six_api_key": "MARKsix",
    "alphavantage_api_key": "MARKalphavantage",
    "market_data_alert_webhook_url": "https://hooks.example.invalid/MARKmdwebhook",
    "backup_alert_webhook_url": "https://hooks.example.invalid/MARKbackupwebhook",
    "telemetry_dsn": "https://MARKtelemetry@example.invalid/1",
}


def _markers(values: dict[str, str]) -> list[str]:
    out = []
    for value in values.values():
        start = value.index("MARK")
        out.append(value[start:start + 12])
    return out


def test_validation_error_never_shows_secret_inputs():
    """T-2: ein Modell-Validierungsfehler (hier: ungueltiges db_key-Format bei
    aktivem SQLCipher) darf keinen der uebergebenen Secret-Werte zeigen."""
    values = {
        "smtp_password": SECRET_FIELDS["smtp_password"],
        "secret_key": SECRET_FIELDS["secret_key"],
        "tenant_master_kek": SECRET_FIELDS["tenant_master_kek"],
        "db_key": "MARKdbkey with space and more than 32 chars",
    }
    with pytest.raises(ValueError) as excinfo:
        Settings(app_env="development", db_use_sqlcipher=True, **values)
    text = str(excinfo.value) + repr(excinfo.value)
    for marker in _markers(values):
        assert marker not in text, marker
    assert "input_value" not in text


def test_validation_error_of_other_checks_hides_inputs_too():
    """T-2: gilt fuer jede Modellpruefung, nicht nur fuer db_key."""
    values = {
        "smtp_password": SECRET_FIELDS["smtp_password"],
        "tenant_master_kek": SECRET_FIELDS["tenant_master_kek"],
        "db_key": SECRET_FIELDS["db_key"],
    }
    with pytest.raises(ValueError) as excinfo:
        # production ohne PostgreSQL und ohne SQLCipher ist unzulaessig
        Settings(app_env="production", secret_key=SECRET_FIELDS["secret_key"], db_use_sqlcipher=False, **values)
    text = str(excinfo.value) + repr(excinfo.value)
    for marker in _markers({**values, "secret_key": SECRET_FIELDS["secret_key"]}):
        assert marker not in text, marker
    # pydantic kuerzt input_value in der Anzeige -- ein Marker kann zufaellig im
    # ausgelassenen Mittelteil liegen. Deshalb zusaetzlich: gar keine Eingabe.
    assert "input_value" not in text
