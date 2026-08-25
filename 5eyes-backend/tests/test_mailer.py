"""E1 (2026-06-14): Einladungs-E-Mail — config-gated, stdlib-only, graceful.

Kein echter Netzwerk-Versand: smtplib.SMTP wird durch ein Fake ersetzt.
Kernzusicherung: ohne SMTP-Konfiguration KEIN Versand (False), nie ein Crash.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.mailer as mailer
from config import settings


class _FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=10):
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


def _configure(monkeypatch, **over):
    base = dict(smtp_enabled=True, smtp_host="smtp.example.test", smtp_port=587,
                smtp_user="u", smtp_password="p", smtp_from="5eyes <no-reply@5eyes.test>",
                smtp_use_tls=True, smtp_timeout_seconds=5)
    base.update(over)
    for k, v in base.items():
        monkeypatch.setattr(settings, k, v)


def test_not_configured_returns_false(monkeypatch, fake_smtp):
    monkeypatch.setattr(settings, "smtp_enabled", False)
    assert mailer.send_invite_email("a@b.test", "Max", "https://x/app?invite=T") is False
    assert _FakeSMTP.sent == []


def test_configured_but_no_recipient_returns_false(monkeypatch, fake_smtp):
    _configure(monkeypatch)
    assert mailer.send_invite_email("", "Max", "https://x/app?invite=T") is False
    assert mailer.send_invite_email(None, "Max", "https://x/app?invite=T") is False
    assert _FakeSMTP.sent == []


def test_sends_when_configured(monkeypatch, fake_smtp):
    _configure(monkeypatch)
    ok = mailer.send_invite_email("mitarbeiter@firma.test", "Max Muster", "https://host/app/5eyes_v2.html?invite=TOK")
    assert ok is True
    assert len(_FakeSMTP.sent) == 1
    msg = _FakeSMTP.sent[0]
    assert msg["To"] == "mitarbeiter@firma.test"
    assert "TOK" in msg.get_content()
    assert "5eyes" in msg["From"]


def test_send_failure_is_swallowed(monkeypatch):
    """Versandfehler -> False, kein Crash (Aufrufer faellt auf Link-Copy zurueck)."""
    _configure(monkeypatch)

    class _BoomSMTP(_FakeSMTP):
        def send_message(self, msg):
            raise OSError("smtp down")

    monkeypatch.setattr(mailer.smtplib, "SMTP", _BoomSMTP)
    assert mailer.send_invite_email("a@b.test", "Max", "https://x/app?invite=T") is False


def test_mail_configured_flag(monkeypatch):
    monkeypatch.setattr(settings, "smtp_enabled", False)
    assert mailer.mail_configured() is False
    _configure(monkeypatch)
    assert mailer.mail_configured() is True
    monkeypatch.setattr(settings, "smtp_host", "")
    assert mailer.mail_configured() is False
