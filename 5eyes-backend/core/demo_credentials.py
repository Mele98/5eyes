"""Passwoerter fuer synthetische Demo-/Staging-Accounts -- nie im Quellcode.

Ein Demo-Passwort kommt entweder aus einer Umgebungsvariable (fuer
reproduzierbare Kollegen-Tests) oder wird pro Lauf zufaellig erzeugt und vom
aufrufenden Skript einmal ausgegeben. Ein Literal im Repository waere fuer
jeden mit Lesezugriff ein gueltiges Login, sobald eine Staging-Instanz
erreichbar ist (Tunnel-Skripte in docs/deploy).
"""
from __future__ import annotations

import os
import secrets

MIN_PASSWORD_LENGTH = 12


def demo_password(env_name: str) -> tuple[str, str]:
    """``(passwort, herkunft)``; herkunft = Variablenname oder ``"zufaellig"``."""
    value = os.environ.get(env_name, "").strip()
    if value:
        if len(value) < MIN_PASSWORD_LENGTH:
            raise SystemExit(
                f"{env_name} ist kuerzer als {MIN_PASSWORD_LENGTH} Zeichen -- abgebrochen."
            )
        return value, env_name
    return secrets.token_urlsafe(18), "zufaellig"
