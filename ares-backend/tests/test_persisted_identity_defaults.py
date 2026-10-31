"""W4-d: persistierte Produkt-Identitaeten == Zieltexte des Migrators.

Der externe Migrator benennt in Bestandsdatenbanken genau vier Namensfelder in
place um (gleiche Zeilen, gleiche ids; der Monte-Carlo-Seed haengt an
``capital_market_assumptions.id``, nicht am Namen). Damit eine migrierte und
eine frisch geseedete Installation dieselben Texte tragen, muessen die
Produkt-Defaults exakt die dokumentierten Zieltexte des Migrators sein
(Migrator-README M-5, Dossier D1-D3). Der Migrator wird nicht importiert; er
gehoert nie ins Produkt.

Ausserdem: TOTP-Issuer fuer Neu-Provisionierungen, Kalender-Identitaet
(PRODID, Kalendername, UID ohne erfundene Domain) und kein erfundener
SMTP-Absender.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: F401,E402  (registriert alle Models)

# Dokumentierte Zieltexte des Migrators (Abgleich, kein Import).
MIGRATOR_POLICY_NAME = "Ares V1 Standard"            # optimizer_policies.policy_name
MIGRATOR_CMA_NAME = "Ares V1 Hausmeinung"            # capital_market_assumptions.assumption_set_name
MIGRATOR_CMA_SOURCE = "Ares Default Runtime"         # capital_market_assumptions.source
MIGRATOR_SYSTEM_CONFIG_VERSION = "Ares App Version"  # system_config.description (key 'version')


def test_engine_default_names_match_migrator_target_texts():
    import services.portfolio_engine as engine

    assert engine.DEFAULT_POLICY_NAME == MIGRATOR_POLICY_NAME
    assert engine.DEFAULT_CMA_NAME == MIGRATOR_CMA_NAME


def test_auto_seeded_policy_and_cma_carry_the_target_texts(tmp_path):
    from models.allocation import CapitalMarketAssumption, OptimizerPolicy
    from services.portfolio_engine import ensure_runtime_reference_data

    configure_mappers()
    engine = create_engine(f"sqlite:///{tmp_path / 'identity-defaults.db'}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            policy, cma = ensure_runtime_reference_data(db, "identity-test-user")
            db.commit()
            assert policy.policy_name == MIGRATOR_POLICY_NAME
            assert cma.assumption_set_name == MIGRATOR_CMA_NAME
            assert cma.source == MIGRATOR_CMA_SOURCE
            assert db.query(OptimizerPolicy).count() == 1
            assert db.query(CapitalMarketAssumption).count() == 1
            # Bestand wird nicht neu geseedet: die Auswahl laeuft ueber
            # is_current, nicht ueber den Namen (gleiche id -> gleicher MC-Seed).
            again_policy, again_cma = ensure_runtime_reference_data(db, "identity-test-user")
            assert (again_policy.id, again_cma.id) == (policy.id, cma.id)
    finally:
        engine.dispose()


def test_bootstrap_system_config_version_description_matches_migrator():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript((BACKEND_ROOT / "ares_schema.sql").read_text(encoding="utf-8"))
        row = conn.execute("SELECT description FROM system_config WHERE key = 'version'").fetchone()
    finally:
        conn.close()
    assert row == (MIGRATOR_SYSTEM_CONFIG_VERSION,)


def test_totp_issuer_for_new_provisioning_is_ares():
    from services import totp

    uri = totp.provisioning_uri("ABC234", "berater@firma.example")
    assert uri.startswith("otpauth://totp/Ares%3Aberater%40firma.example?")
    assert "&issuer=Ares&" in uri
    router_src = (BACKEND_ROOT / "routers" / "auth.py").read_text(encoding="utf-8")
    assert 'issuer="Ares")' in router_src


# ---------------------------------------------------------------------------
# Kalender (ICS)
# ---------------------------------------------------------------------------


def test_ics_identity_without_domain(monkeypatch):
    from config import settings
    from services import review_calendar_feed as feed

    monkeypatch.setattr(settings, "ares_domain", "")
    assert feed.ICS_PRODID == "-//Ares//Advisory Calendar//DE"
    assert feed.event_uid("t-123") == "ares-trigger-t-123"
    assert "@" not in feed.event_uid("t-123")


def test_ics_uid_domain_comes_only_from_config(monkeypatch):
    from config import settings
    from services import review_calendar_feed as feed

    assert feed.event_uid("t-123", "kalender.firma.example") == "ares-trigger-t-123@kalender.firma.example"
    # einzige Quelle der Domain: der Router reicht settings.ares_domain herein,
    # das Feed-Modul selbst liest keine Konfiguration
    router_src = (BACKEND_ROOT / "routers" / "review.py").read_text(encoding="utf-8")
    assert "build_ics_feed(db, user, uid_domain=settings.ares_domain)" in router_src
    feed_src = (BACKEND_ROOT / "services" / "review_calendar_feed.py").read_text(encoding="utf-8")
    assert "from config import" not in feed_src and "settings" not in feed_src
    monkeypatch.setattr(settings, "ares_domain", "kalender.firma.example")
    assert feed.event_uid("t-123") == "ares-trigger-t-123", "ohne Uebergabe keine Domain"


def test_ics_feed_header_and_event_uid(monkeypatch):
    from config import settings
    from services import review_calendar_feed as feed

    monkeypatch.setattr(settings, "ares_domain", "")
    lines = feed._all_day_event(
        uid=feed.event_uid("t-9"), dtstamp="20261024T000000Z", due_date="2026-11-01",
        summary="Ares Review: Test", description="Mandat: M-1",
    )
    assert "UID:ares-trigger-t-9" in lines
    src = (BACKEND_ROOT / "services" / "review_calendar_feed.py").read_text(encoding="utf-8")
    assert 'f"PRODID:{ICS_PRODID}",' in src
    assert '"X-WR-CALNAME:Ares",' in src
    assert "uid=event_uid(trigger.id, uid_domain)," in src


def test_ares_domain_has_no_default_and_is_validated():
    from config import Settings

    assert Settings(_env_file=None).ares_domain == ""
    assert Settings(_env_file=None, ares_domain="Firma.Example").ares_domain == "firma.example"
    for bad in ("https://firma.example", "a@firma.example", "firma.example/x", "firma .example",
                "firma.example\r\nX-INJ:1", "localhost"):
        with pytest.raises(ValueError):
            Settings(_env_file=None, ares_domain=bad)


def test_frontend_ics_download_uses_ares_prodid_and_no_domain():
    html = (BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html").read_text(encoding="utf-8")
    assert html.count("PRODID:-//Ares//Advisory Calendar//DE") == 2
    uids = re.findall(r"UID:'\+(\w+)\+'([^\\]*)\\r\\n", html)
    assert sorted(uids) == [("datVal", "-ares"), ("stamp", "-ares")]


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------


def test_smtp_sender_has_no_invented_default():
    from config import Settings

    assert Settings(_env_file=None).smtp_from == ""
