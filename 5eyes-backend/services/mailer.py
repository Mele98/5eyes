"""E-Mail-Versand (E1, 2026-06-14) — stdlib-only (smtplib/email), keine Dependency.

Aktuell genutzt fuer Einladungs-/Onboarding-Mails. Dependency- und config-soft:
ist SMTP nicht aktiviert/konfiguriert, liefert `send_invite_email` False und der
Aufrufer faellt auf Link-Copy zurueck — NIE ein 500 wegen Mail-Problemen.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from config import settings

logger = logging.getLogger(__name__)


def mail_configured() -> bool:
    """True, wenn SMTP eingeschaltet UND minimal konfiguriert ist."""
    return bool(
        getattr(settings, "smtp_enabled", False)
        and str(getattr(settings, "smtp_host", "")).strip()
        and str(getattr(settings, "smtp_from", "")).strip()
    )


def _send(msg: EmailMessage) -> bool:
    host = str(settings.smtp_host).strip()
    port = int(getattr(settings, "smtp_port", 587) or 587)
    timeout = int(getattr(settings, "smtp_timeout_seconds", 10) or 10)
    user = str(getattr(settings, "smtp_user", "") or "")
    password = str(getattr(settings, "smtp_password", "") or "")
    use_tls = bool(getattr(settings, "smtp_use_tls", True))
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            if use_tls:
                server.starttls(context=ssl.create_default_context())
            if user:
                server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as exc:  # pragma: no cover - Netzwerk/Server-spezifisch
        logger.warning("E-Mail-Versand fehlgeschlagen (Fallback Link-Copy): %s", exc)
        return False


def _build_invite_message(to_email: str, full_name: str, invite_link: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Ihr Zugang zu 5eyes — Konto aktivieren"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    greeting = (full_name or "").strip() or "willkommen"
    text = (
        f"Hallo {greeting},\n\n"
        "Sie wurden zu 5eyes eingeladen. Bitte aktivieren Sie Ihr Konto ueber den "
        "folgenden Link und setzen Sie Ihr Passwort. Danach richten Sie die "
        "Zwei-Faktor-Authentifizierung ein.\n\n"
        f"{invite_link}\n\n"
        "Der Link ist 7 Tage gueltig und nur einmal verwendbar.\n\n"
        "Falls Sie diese Einladung nicht erwartet haben, ignorieren Sie diese "
        "E-Mail.\n\n"
        "— 5eyes"
    )
    msg.set_content(text)
    return msg


def send_invite_email(to_email: str | None, full_name: str, invite_link: str) -> bool:
    """Versendet die Einladung. Liefert True nur bei tatsaechlichem Versand,
    sonst False (nicht konfiguriert, keine Adresse, oder Versandfehler) —
    der Aufrufer zeigt dann den Link zum manuellen Versenden."""
    if not mail_configured():
        return False
    to_email = (to_email or "").strip()
    if not to_email:
        return False
    return _send(_build_invite_message(to_email, full_name, invite_link))
