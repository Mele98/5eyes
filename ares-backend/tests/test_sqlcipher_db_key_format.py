"""SQLCIPHER-DB-KEY-FORMAT-001 (Pruefrunde #864, S-1): Startvalidierung des SQLCipher-Schluessels.

Der Schluessel lief frueher auf zwei Wegen in die Datenbank (URL mit
quote_plus/unquote + Dialekt-``pragma key="..."`` vs. SQL-Literal in Bootstrap
und Backup). Ein Leerzeichen wurde still zu "+", ein ``"`` brach die Engine und
schrieb den Rest des Schluessels in die Exception. Jetzt gibt es einen Weg
(database.apply_sqlcipher_key) und eine fail-closed Formatpruefung beim Start:
32-512 Zeichen aus ``A-Z a-z 0-9 . _ ~ -``. Die Fehlermeldung nennt den
Schluessel nie -- weder die Meldung selbst noch der ValidationError (input_value).

Laeuft ohne sqlcipher3 (reine Konfigurationspruefung, in jedem Shard).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import DB_KEY_FORMAT_MESSAGE, Settings, db_key_format_ok  # noqa: E402

_MARK = "Zq7Mark"  # erkennbarer Teil jedes Schluessels, darf in keiner Meldung stehen


def _settings(key):
    return Settings(app_env="development", secret_key="x", db_use_sqlcipher=True, db_key=key)


BAD_KEYS = {
    "space": _MARK + "-" + "a" * 20 + " " + "b" * 20,
    "double_quote": _MARK + "-" + "a" * 20 + '"' + "b" * 20,
    "single_quote": _MARK + "-" + "a" * 20 + "'" + "b" * 20,
    "nul": _MARK + "-" + "a" * 20 + "\x00" + "b" * 20,
    "umlaut": _MARK + "-" + "a" * 20 + "ä" + "b" * 20,
    "plus": _MARK + "-" + "a" * 20 + "+" + "b" * 20,
    "percent": _MARK + "-" + "a" * 20 + "%41" + "b" * 20,
    "raw_key_form": "x'" + _MARK + "a" * 57 + "'",
    "too_short_31": _MARK + "-" + "a" * (31 - len(_MARK) - 1),
    "too_long_513": _MARK + "-" + "a" * (513 - len(_MARK) - 1),
}


@pytest.mark.parametrize("name", sorted(BAD_KEYS))
def test_invalid_db_key_fails_closed_without_leaking(name):
    key = BAD_KEYS[name]
    assert not db_key_format_ok(key)
    with pytest.raises(ValueError) as excinfo:
        _settings(key)
    text = str(excinfo.value) + repr(excinfo.value)
    assert DB_KEY_FORMAT_MESSAGE in str(excinfo.value)
    assert key not in text
    assert _MARK not in text, "kein Teil des Schluessels in Meldung oder input_value"


@pytest.mark.parametrize(
    "key",
    [
        "0123456789abcdef" * 4,
        "A" * 32,
        "aZ09._~-" * 4,
        "k" * 512,
    ],
)
def test_valid_db_key_is_accepted_and_not_in_repr(key):
    assert db_key_format_ok(key)
    settings = _settings(key)
    assert settings.db_key == key
    assert key not in repr(settings)


def test_db_key_not_validated_when_sqlcipher_off():
    # Klartext-Pfad unveraendert: ein (ungenutzter) Altwert blockiert den Start nicht.
    settings = Settings(app_env="development", secret_key="x", db_use_sqlcipher=False, db_key="kurz mit leer")
    assert settings.db_use_sqlcipher is False
