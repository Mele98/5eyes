"""E1: TOTP-Service (RFC 6238) — Known-Answer + Roundtrip + Drift-Fenster."""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import totp

# RFC 6238 Appendix B: Secret ASCII "12345678901234567890" (Base32), SHA1.
# T=59s -> 8-stellig 94287082 -> 6-stellig 287082.
_RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_rfc6238_known_answer():
    assert totp.totp_at(_RFC_SECRET, 59) == "287082"


def test_verify_roundtrip():
    sec = totp.generate_secret()
    code = totp.totp_at(sec, 1_700_000_000)
    assert totp.verify(sec, code, 1_700_000_000) is True


def test_verify_rejects_wrong_code():
    sec = totp.generate_secret()
    code = totp.totp_at(sec, 1_700_000_000)
    wrong = "000000" if code != "000000" else "111111"
    assert totp.verify(sec, wrong, 1_700_000_000) is False


def test_verify_drift_window():
    sec = totp.generate_secret()
    t = 1_700_000_000
    code = totp.totp_at(sec, t)
    # Gleicher 30s-Schritt -> gueltig
    assert totp.verify(sec, code, t + 29) is True
    # Nachbarschritt (innerhalb window=1) -> gueltig
    assert totp.verify(sec, code, t + 31) is True
    # Zwei Schritte entfernt -> ausserhalb des Fensters
    assert totp.verify(sec, code, t + 61) is False


def test_verify_rejects_malformed():
    sec = totp.generate_secret()
    assert totp.verify(sec, "abc", 1) is False
    assert totp.verify(sec, "12345", 1) is False   # falsche Laenge
    assert totp.verify(sec, "", 1) is False
    assert totp.verify("", "123456", 1) is False


def test_verify_does_not_crash_near_epoch():
    """Kontrollrunde 2026-09-21: bei timestamp < window*period (hier: 5s,
    period=30, window=1) wird counter+w fuer w=-1 negativ -- struct.pack
    warf vorher ungefangen struct.error statt False/True zu liefern."""
    sec = totp.generate_secret()
    code = totp.totp_at(sec, 5)  # counter=0
    assert totp.verify(sec, code, timestamp=5) is True
    assert totp.verify(sec, "000000" if code != "000000" else "111111", timestamp=5) is False


def test_verify_at_timestamp_zero_does_not_crash():
    sec = totp.generate_secret()
    assert totp.verify(sec, "123456", timestamp=0) is False


def test_provisioning_uri_format():
    uri = totp.provisioning_uri("ABC234", "advisor@firma.ch", issuer="5eyes")
    assert uri.startswith("otpauth://totp/")
    assert "secret=ABC234" in uri
    assert "issuer=5eyes" in uri
