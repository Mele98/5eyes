import pytest
from pydantic import ValidationError

from schemas.users import BootstrapAdminRequest


def test_bootstrap_admin_request_requires_minimum_password_length():
    with pytest.raises(ValidationError):
        BootstrapAdminRequest(
            username='admin',
            password='short',
            full_name='Admin User',
        )


def test_bootstrap_admin_request_accepts_valid_payload():
    # Kontrollrunde 2026-09-21: email ist jetzt EmailStr -- .test ist eine
    # IANA-reservierte TLD (RFC 2606), die email-validator standardmaessig
    # als nicht zustellbar ablehnt. Auf eine normale Domain umgestellt.
    payload = BootstrapAdminRequest(
        username='admin',
        password='sufficiently-long',
        full_name='Admin User',
        email='admin@example.com',
    )
    assert payload.username == 'admin'


def test_bootstrap_admin_request_rejects_comma_separated_email():
    """Kontrollrunde 2026-09-21 (Mailer-Audit): email war bisher reiner str
    (anders als jedes Schwester-Feld) -- eine Komma-Liste haette bis zu
    services/mailer.py durchgereicht werden und dort eine verdeckte
    Envelope-Zweit-Zustellung ausgeloest."""
    with pytest.raises(ValidationError):
        BootstrapAdminRequest(
            username='admin',
            password='sufficiently-long',
            full_name='Admin User',
            email='admin@example.com, attacker@evil.com',
        )


def test_bootstrap_admin_request_rejects_crlf_in_email():
    with pytest.raises(ValidationError):
        BootstrapAdminRequest(
            username='admin',
            password='sufficiently-long',
            full_name='Admin User',
            email='admin@example.com\r\nBcc: attacker@evil.com',
        )
