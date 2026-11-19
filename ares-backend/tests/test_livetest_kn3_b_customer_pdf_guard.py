"""KN3-B: Waechter ueber ALLE Kunden-PDFs (gerendert, Text ausgelesen).

Echter Backend-Prozess (Temp-DB/HOME/APPDATA, Wegwerf-KEK, freier Port),
Ersteinrichtung mit Firma «Testfirma Fiktiv Einzel GmbH» und Beraterin «Erika
Testberaterin», ein Verzehr-Fall (Depot CHF 500'000, Lebenshaltung CHF 60'000
p.a.), Strategie, Produktlauf, Finalisieren und Publizieren ueber die echte
API. Danach wird jeder Kunden-PDF-Endpunkt abgerufen und der Text ausgelesen.

* N-917R2-02 (E2E2-03-Regel): bei Verzehr kein «−100»/«-100» bei Rendite/CAGR
  und kein «100.0 %» bei Drawdown -- in keinem Kunden-PDF.
* N-917R2-04 / E2E3-03 (E2E2-11): keine ASCII-Umschrift (ae/oe/ue statt
  ä/ö/ü) in deutschen Woertern; begruendete Allowlist (``UMLAUT_ALLOWLIST``).
  «ss» ist Schweizer Rechtschreibung (kein «ß», E2E2-12) und wird nicht
  beanstandet.
* E2E3-04: der Firmenkopf traegt den Firmennamen aus den Firmenangaben, nie
  den Beraternamen als Firma.

Kein Browser. Eigener CI-Job «KN3-B Kunden-PDF-Waechter» (das Budget des
Frontend-Jobs ist ausgeschoepft); lokal mit ``ARES_KN3_PDF_GUARD=1``.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
COMPANY = "Testfirma Fiktiv Einzel GmbH"
ADVISOR = "Erika Testberaterin"
USER, PWD = "kn3pdf", "Kn3PdfGuard-Pass-2026!"

# Jeder Kunden-PDF-Endpunkt (routers/pdf_reports.py). Ein Endpunkt, der fuer den
# Verzehr-Fall fachlich nicht erzeugbar ist, steht mit Begruendung in
# NOT_RENDERABLE; jeder andere muss 200 liefern.
CUSTOMER_PDFS = (
    "anlagestrategie", "assetallocation", "risikoprofil", "portfolio", "vertrag", "contract-signoff",
    "protokoll", "depotcheck", "backtest", "advisory-report", "cost-disclosure", "kundeninformation",
)
NOT_RENDERABLE: dict[str, str] = {}

pytestmark = pytest.mark.skipif(
    os.environ.get("ARES_KN3_PDF_GUARD") != "1",
    reason="Kunden-PDF-Waechter laeuft im eigenen CI-Job (ARES_KN3_PDF_GUARD=1)",
)


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Api:
    def __init__(self, base: str):
        self.base, self.token = base, None

    def __call__(self, method, path, body=None, raw=False):
        import json

        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = resp.read()
                return resp.status, (data if raw else json.loads(data or b"null"))
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:2000]


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


UI_PREFERENCES = {
    "policy": {"esg": "none", "hedging": "none", "homeBias": "ch_focus", "universe": "funds_only"},
    "assetClasses": {"altsGold": True, "bondsDuration": "Langfristig", "bondsInvestmentGrade": True,
                     "equitiesGeo": "Schweiz Fokus", "equitiesLargeCap": True},
    "product": {"fundsOnly": True},
}

CLEAN_LEGAL_PROFILE = {
    "legal_name": COMPANY,
    "address_street": "Teststrasse 1",
    "address_postal_code": "8000",
    "address_city": "Zürich",
    "address_country": "CH",
    "business_activity": "Vermögensverwaltung und Anlageberatung (fiktiv)",
    "supervision_type": "vermoegensverwalter_finig",
    "supervisory_authority": "Aufsichtsbehörde (fiktiv)",
    "supervisory_organisation": "Aufsichtsorganisation (fiktiv)",
    "license_reference": None,
    "ombudsman_name": "Ombudsstelle (fiktiv)",
    "ombudsman_address": "Musterweg 2, 3000 Bern (fiktiv)",
    "contact_phone": None,
    "contact_email": "kontakt@example.invalid",
    "contact_website": None,
}


@pytest.fixture(scope="module")
def live():
    """Verzehr-Fall ueber die echte API; alle Kunden-PDFs ({name: (status,
    text|body)}) und der Zustand vor/nach einem echten App-Neustart."""
    from cryptography.fernet import Fernet

    import tests.client_onboarding_fixture as onboarding
    from core import sustainability_preference as sp
    from tests.risk_fixture_helpers import standard_risk_payload
    from tests.test_livetest_e2b_strategy_blocks import _finalize_and_publish

    tmp = Path(tempfile.mkdtemp(prefix="kn3b_pdf_"))
    for sub in ("home", "appdata", "localappdata"):
        (tmp / sub).mkdir()
    db_path = tmp / "kn3b_pdf.db"
    kek = Fernet.generate_key().decode()
    port = _free_port()
    proc = _start_backend(tmp, db_path, kek, port)
    base = f"http://127.0.0.1:{port}"
    original_profile = onboarding.TEST_LEGAL_PROFILE
    try:
        api = _Api(base)
        status, body = api("POST", "/auth/bootstrap-admin", {
            "username": USER, "password": PWD, "full_name": ADVISOR, "company_name": COMPANY,
            "home_jurisdiction": "CH"})
        assert status == 201, body
        status, body = api("POST", "/auth/login", {"username": USER, "password": PWD})
        assert status == 200, body
        api.token = body["access_token"]
        advisor_id = api("GET", "/auth/me")[1]["id"]
        status, client = api("POST", "/clients", {
            "client_number": "KN3-DEPL-1", "first_name": "Verena", "last_name": "Verzehr-Fiktiv",
            "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": "1960-05-01",
            "canton": "ZH"})
        assert status == 201, client
        cid = client["id"]
        status, mandate = api("POST", f"/clients/{cid}/mandates",
                              {"mandate_number": "M-KN3-DEPL-1", "mandate_type": "Anlageberatung"})
        assert status == 201, mandate
        mid = mandate["id"]
        assert api("POST", f"/mandates/{mid}/risk-assessments", standard_risk_payload())[0] == 201
        status, body = api("POST", f"/clients/{cid}/wealth-positions", {
            "label": "Depot CHF (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
            "current_value_rappen": 500_000_00, "currency": "CHF", "depot_bank": "Testbank Fiktiv",
            "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000})
        assert status in (200, 201), body
        status, body = api("POST", f"/clients/{cid}/cashflows", {
            "cashflow_type": "Expense", "label": "Lebenshaltung (fiktiv)", "amount_rappen": 60_000_00,
            "currency": "CHF", "frequency": "jaehrlich", "nature": "wiederkehrend", "valid_from": "2026-12-01",
            "valid_until": None, "is_inflation_linked": True})
        assert status in (200, 201), body
        status, body = api("POST", f"/mandates/{mid}/sustainability-preferences", {
            "questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
            "response_status": "declined", "esg_relevance": None, "esg_characteristic": None,
            "exclusions": [], "information_acknowledged": False, "client_confirmed": True,
            "capture_channel": "in_person"})
        assert status == 201, body
        # KN4-B / E2E4-03: Strategiebaustein-Praeferenzen wie ein ueber die
        # Oberflaeche angelegter Kunde (vorher {} -- Rohschluessel blieben unentdeckt).
        status, body = api("POST", f"/mandates/{mid}/target-allocation/generate", {"preferences": UI_PREFERENCES})
        assert status == 200, body
        status, body = api("POST", f"/mandates/{mid}/recommendations/generate", {})
        assert status == 200, body
        # Rechtliche Angaben mit echten Umlauten (Benutzerdaten sind nicht Teil
        # des Umlaut-Waechters, sie sollen ihn aber auch nicht ausloesen).
        onboarding.TEST_LEGAL_PROFILE = CLEAN_LEGAL_PROFILE
        _finalize_and_publish(api, db_path, mid)
        results = {}
        for name in CUSTOMER_PDFS:
            status, data = api("GET", f"/mandates/{mid}/reports/{name}.pdf", raw=True)
            results[name] = (status, _pdf_text(data) if status == 200 else data.decode("utf-8", "replace"))
        out = os.environ.get("ARES_KN3_PDF_GUARD_OUT")
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            for name, (status, text) in results.items():
                Path(out, f"{name}.txt").write_text(f"{status}\n{text}", encoding="utf-8")
        # N-917R2-01 (live): App-Neustart auf derselben Datenbank. Ersteinrichtung
        # und Publikation stammen aus der ersten Sitzung; danach darf sich weder
        # der Status noch eine gebundene Zeile aendern.
        before = (_publication(api, mid), _dependency_rows(db_path))
        _stop(proc)
        port = _free_port()
        proc = _start_backend(tmp, db_path, kek, port)
        api = _Api(f"http://127.0.0.1:{port}")
        status, body = api("POST", "/auth/login", {"username": USER, "password": PWD})
        assert status == 200, body
        api.token = body["access_token"]
        after = (_publication(api, mid), _dependency_rows(db_path))
        yield {"pdfs": results, "restart": (before, after)}
    finally:
        onboarding.TEST_LEGAL_PROFILE = original_profile
        _stop(proc)
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def rendered(live):
    return live["pdfs"]


def _start_backend(tmp, db_path, kek, port):
    """Isolierter Backend-Prozess (Temp-HOME/APPDATA/DB, Wegwerf-KEK); derselbe
    Aufruf fuer den ersten Start und den Neustart auf derselben Datenbank."""
    env = {
        **os.environ,
        "HOME": str(tmp / "home"), "USERPROFILE": str(tmp / "home"),
        "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "localappdata"),
        "DB_PATH": str(db_path), "SECRET_KEY": "kn3b-pdf-guard-secret-key-0123456789abcdef",
        "PRICE_SCHEDULER_ENABLED": "0", "BACKUP_SCHEDULER_ENABLED": "0",
        "MARKET_DATA_CACHE_PURGE_ENABLED": "0", "LOGIN_RATE_LIMIT_ENABLED": "0",
        "APP_ENV": "development", "TENANT_MASTER_KEK": kek,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            return proc
        except Exception:  # noqa: BLE001 - Server startet noch
            if proc.poll() is not None:
                break
            time.sleep(1)
    _stop(proc)
    raise RuntimeError("Backend nicht gestartet")


def _stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)


def _publication(api, mid):
    status, body = api("GET", f"/mandates/{mid}/allocation-publication")
    assert status == 200, body
    freshness = body.get("freshness") or {}
    return body.get("publication_status"), freshness.get("status"), body.get("reason_code")


def _dependency_rows(db_path):
    """Alle Zeilen der Freshness-Abhaengigkeitstabellen (ohne updated_at)."""
    import sqlite3

    from models.snapshots import DEPENDENCY_SOURCES

    rows = {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        for table in sorted(DEPENDENCY_SOURCES):
            try:
                data = con.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.OperationalError:
                continue
            rows[table] = sorted(
                tuple(sorted((key, row[key]) for key in row.keys() if key != "updated_at")) for row in data
            )
    finally:
        con.close()
    return rows


def _texts(rendered):
    return {name: text for name, (status, text) in rendered.items() if status == 200}


def test_every_customer_pdf_renders_for_the_depletion_case(rendered):
    failed = {name: (status, body[:300]) for name, (status, body) in rendered.items()
              if status != 200 and name not in NOT_RENDERABLE}
    assert not failed, failed
    # Positivkontrolle: der Fall ist wirklich ein Verzehr-Fall.
    assert any("aufgebraucht ab" in text for text in _texts(rendered).values())


_MINUS_100 = re.compile(r"[−\-–]\s?100(?:[.,]0+)?\s?%")
_DRAWDOWN_100 = re.compile(r"drawdown[^\n%]{0,40}?\b100(?:[.,]0+)?\s?%", re.IGNORECASE)


def test_no_minus_100_and_no_100_percent_drawdown_on_depletion(rendered):
    offenders = {}
    for name, text in _texts(rendered).items():
        flat = " ".join(text.split())
        hits = [m.group(0) for m in _MINUS_100.finditer(flat)] + [m.group(0) for m in _DRAWDOWN_100.finditer(flat)]
        hits += [ctx for ctx in re.findall(r".{0,30}100\.0 %.{0,10}", flat) if "drawdown" in ctx.lower()]
        if hits:
            offenders[name] = hits
    assert not offenders, offenders


def test_guard_patterns_detect_the_old_output():
    """Positivkontrolle der Muster (Befund-Texte aus Dok. 118 / H-167 R2)."""
    assert _MINUS_100.search("Erw. Rendite −100.0 %")
    assert _MINUS_100.search("Median CAGR -100.00 %")
    assert _DRAWDOWN_100.search("Max Drawdown 100.0 %")
    assert not _MINUS_100.search("CHF -1'227'410")


# ── N-917R2-04 / E2E3-03: ASCII-Umschriften in Kunden-PDFs ───────────────────

# Token aus Buchstaben UND Ziffern: Hashes/Kennungen (z. B. "3f2efeae9") enthalten
# Ziffern und sind keine Woerter (siehe umlaut_transliterations).
_WORD = re.compile(r"[A-Za-z0-9ÄÖÜäöüß]+")
# Begruendete Allowlist: Buchstabenfolgen ae/oe/ue, die im Deutschen (bzw. in
# englischen Fachbegriffen) KEIN Umlaut sind.
UMLAUT_ALLOWLIST: dict[str, str] = {
    "eue": "Diphthong eu + e: neue, Steuer, teuer, Treue",
    "aue": "Diphthong au + e: Dauer, vorausschauend, Haltedauer",
    "que": "qu + e: Quelle, konsequent, Frequenz",
    "uell": "Endung -uell: aktuell, individuell, manuell",
    "value": "englischer Fachbegriff Value-at-Risk",
    "ttoe": "Komposita Brutto-/Netto- + e: Bruttoeinkommen, Nettoertrag",
    "risikoe": "Komposita Risiko- + e: Risikoeinschätzung",
    "kontoe": "Komposita Konto- + e: Kontoeröffnung",
    "koeff": "Koeffizient",
    "zuerst": "zu + erst",
}
# Ganze Woerter, die Codes sind (keine Prosa): unveraenderlich gebunden.
UMLAUT_CODE_WORDS: dict[str, str] = {
    "praeferenzen": "Fragebogen-Kennung 'praeferenzen-v1' (QUESTIONNAIRE_VERSION, Teil des Definitions-Hashes)",
}


def umlaut_transliterations(text: str) -> list[str]:
    """Woerter mit ae/oe/ue, wo im Deutschen ein Umlaut steht. «ss» ist
    Schweizer Rechtschreibung (kein «ß») und wird nicht beanstandet."""
    found = []
    for match in _WORD.finditer(text):
        word = match.group(0)
        lower = word.lower()
        if lower in UMLAUT_CODE_WORDS or any(ch.isdigit() for ch in word):
            continue
        if word == lower and set(word) <= set("abcdef"):
            continue  # Bruchstueck eines Hex-Hashes (Zeilenumbruch), kein Wort
        legit: set[int] = set()
        for pattern in UMLAUT_ALLOWLIST:
            start = lower.find(pattern)
            while start != -1:
                legit.update(range(start, start + len(pattern)))
                start = lower.find(pattern, start + 1)
        if any(lower[i:i + 2] in ("ae", "oe", "ue") and not {i, i + 1} <= legit for i in range(len(lower) - 1)):
            found.append(word)
    return found


def test_no_ascii_umlaut_transliteration_in_customer_pdfs(rendered):
    offenders = {name: sorted(set(umlaut_transliterations(text))) for name, text in _texts(rendered).items()}
    offenders = {name: words for name, words in offenders.items() if words}
    assert not offenders, offenders


def test_umlaut_detector_positive_and_negative_controls():
    # Befund-Texte (Dok. 118 E2E3-03, H-167 R2 N-917R2-02/-04).
    assert umlaut_transliterations("Vermoegensverwalter mit Bewilligung der FINMA") == ["Vermoegensverwalter"]
    assert umlaut_transliterations("Aktien Schwellenlaender") == ["Schwellenlaender"]
    assert umlaut_transliterations("Persoenlicher Advisory-Report, Waehrung, Liquiditaet") == [
        "Persoenlicher", "Waehrung", "Liquiditaet"]
    assert umlaut_transliterations("Fuer dieses Mandat ... uebergeben") == ["Fuer", "uebergeben"]
    # Kein Umlaut: Diphthonge, -uell, qu, Komposita, Fachbegriffe, Schweizer ss.
    assert umlaut_transliterations(
        "neue Steuern, aktuell, individuelle, Haltedauer, Quelle, konsequent, Bruttoeinkommen, "
        "Value-at-Risk, Strasse, Massnahme, Fragebogen praeferenzen-v1") == []


# ── E2E3-04: Firmenkopf = Firmenname, nie der Beratername ────────────────────


def test_header_brand_is_the_firm_never_the_advisor(rendered):
    texts = _texts(rendered)
    as_brand = {name for name, text in texts.items() if ADVISOR.upper() in text}
    assert not as_brand, as_brand
    # Jedes Kunden-PDF mit Firmenkopf zeigt den Firmennamen aus den Firmenangaben
    # (der Advisory-Report fuehrt keine Firmenzeile, nur "Berater/Beraterin").
    missing = {name for name, text in texts.items()
               if name != "advisory-report" and COMPANY.upper() not in text.upper()}
    assert not missing, missing


# ── N-917R2-01 (live): erster Neustart nach der Ersteinrichtung ──────────────


def test_first_restart_after_setup_keeps_publication_and_bound_rows(live):
    (status_before, rows_before), (status_after, rows_after) = live["restart"]
    assert status_before[:2] == ("PUBLISHED", "FRESH"), status_before
    assert status_after == status_before, (status_before, status_after)
    changed = sorted(table for table in rows_before if rows_before[table] != rows_after.get(table))
    assert not changed, changed
    # Positivkontrolle: Kunde und Position tragen von Anfang an den Mandanten.
    assert all(dict(row).get("tenant_id") == "main" for row in rows_before["clients"])
    assert all(dict(row).get("tenant_id") == "main" for row in rows_before["wealth_positions"])


# ── KN4-B / E2E4-03: keine Rohschluessel und keine Python-Werte ──────────────

_RAW_KEY = re.compile(r"\b[a-z]+[A-Z][A-Za-z]*\s*:\s*\S")
_PYTHON_VALUE = re.compile(r"\b(True|False|None)\b")


def test_no_raw_preference_keys_or_python_values_in_customer_pdfs(rendered):
    offenders = {}
    for name, text in _texts(rendered).items():
        flat = " ".join(text.split())
        hits = _RAW_KEY.findall(flat) + _PYTHON_VALUE.findall(flat)
        if hits:
            offenders[name] = hits[:8]
    assert not offenders, offenders
    # Positivkontrolle: die Praeferenzen erscheinen als Kundentext.
    assert "Heimmarkt Schweiz bevorzugt" in " ".join(_texts(rendered)["contract-signoff"].split())


def test_raw_key_patterns_detect_the_old_output():
    old = "Dokumentierte Präferenzen: hedging: none; homeBias: ch_focus; altsGold: True; fundsOnly: True."
    assert _RAW_KEY.search(old) and _PYTHON_VALUE.search(old)
    assert not _RAW_KEY.search("Seite 2: Übersicht; Datum: 19.11.2026")


# ── KN4-B / E2E4-04: Depot als Vermoegensposition erfasst ────────────────────


def test_depotcheck_never_claims_no_depot_when_depot_position_exists(rendered):
    text = " ".join(_texts(rendered)["depotcheck"].split())
    assert "kein Depot erfasst" not in text, text[:600]
