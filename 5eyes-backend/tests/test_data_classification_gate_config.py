"""Roadmap #91: Konfigurations-Haerte des Phase-0-Daten-Klassifizierungs-Gates.

`test_data_classification_gate.py` deckt den eigentlichen Write-Gate-Vertrag
ab (enforce_data_classification blockt "real" bei allow_real_client_data=False).
Diese Datei sichert zusaetzlich die Config-Ebene ab: der Gate-Schalter selbst
darf nicht durch einen einfachen Konfigurationsfehler (Typo, leerer Wert,
fehlende Einstellung) STILL in einen unerwarteten Zustand kippen.

Verifizierter IST-Vertrag (services/data_classification.py + config.py):
- `Settings.allow_real_client_data` ist `bool = True` (Default = Gate OFFEN).
  Das ist laut Kommentar in config.py bewusst so gewaehlt: Phase-0-Block ist
  ein OPT-IN fuer Staging/Demo-Umgebungen, nicht der generelle Produktions-
  default. Dieser Test fixiert NUR den heutigen, dokumentierten Wert als
  Regression-Guard (falls jemand den Default versehentlich umdreht, faellt
  das hier auf - mit Verweis auf die Sicherheitsfolgen in beide Richtungen).
- Ein syntaktisch ungueltiger Bool-Wert in der Env-Variable
  ALLOW_REAL_CLIENT_DATA (z.B. Typo "flase", oder Leerstring) lässt
  pydantic-settings beim Settings()-Konstruktor mit einem ValidationError
  FAIL LOUD abbrechen - es gibt KEINEN stillen Fallback auf einen der beiden
  Bool-Werte. Ein Konfigurationsfehler kann das Gate also nicht unbemerkt
  in einen falschen Zustand kippen; er verhindert den Start ueberhaupt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import Settings  # noqa: E402  (Pfad-Setup muss zuerst laufen)


def _settings_kwargs_without_env_file() -> dict:
    # env_file wird bewusst deaktiviert, damit ein lokal vorhandenes .env
    # (z.B. mit ALLOW_REAL_CLIENT_DATA=False fuer Staging) das Default-Verhalten
    # in diesem Test nicht verdeckt - wir wollen den reinen Klassen-Default
    # bzw. reine Env-Var-Effekte pruefen, nicht die aktuelle Deploy-Config.
    return {"_env_file": None}


def test_allow_real_client_data_default_is_open_gate(monkeypatch):
    """Regression-Guard auf den heute dokumentierten Default (config.py: 'Phase-0
    safety gate ... Staging sets this to False'). Faellt dieser Test um, hat
    jemand den Default geaendert, ohne die Tragweite (Staging-Verhalten koennte
    sich unbemerkt aendern) zu dokumentieren."""
    monkeypatch.delenv("ALLOW_REAL_CLIENT_DATA", raising=False)

    fresh = Settings(**_settings_kwargs_without_env_file())

    assert fresh.allow_real_client_data is True


@pytest.mark.parametrize("bad_value", ["", "flase", "yes-please", "maybe"])
def test_invalid_boolean_env_value_fails_loud_not_silently(monkeypatch, bad_value):
    """Ein Tippfehler in ALLOW_REAL_CLIENT_DATA darf NICHT unbemerkt zu einem der
    beiden Bool-Zustaende (offenes oder geschlossenes Gate) fuehren - er muss den
    Settings()-Aufbau mit einem harten Fehler stoppen."""
    monkeypatch.setenv("ALLOW_REAL_CLIENT_DATA", bad_value)

    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs_without_env_file())


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("false", False),
        ("False", False),
        ("0", False),
    ],
)
def test_valid_boolean_env_value_is_parsed_unambiguously(monkeypatch, env_value, expected):
    """Gegenprobe zu obigem Test: gueltige Werte werden weiterhin korrekt und
    eindeutig geparst (kein falsches Fail-Loud bei legitimer Konfiguration)."""
    monkeypatch.setenv("ALLOW_REAL_CLIENT_DATA", env_value)

    fresh = Settings(**_settings_kwargs_without_env_file())

    assert fresh.allow_real_client_data is expected
