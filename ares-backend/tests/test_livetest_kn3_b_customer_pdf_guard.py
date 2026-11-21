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
* KN5 / N-917R4-01: keine internen Pruef-/Diagnosewerte (technische
  Bezeichner, Seeds, englische Statuswoerter, CamelCase/UPPER_SNAKE) -- in
  allen 12 Kunden-PDFs eines Verzehr- UND eines Reserve-Falls; begruendete,
  ortsgebundene Allowlist (``TECHNICAL_ALLOWLIST``).
* KN6 / N-917R5-02: dritter Fall «Bestand + ESG-Abweichung» (Bestaende je
  Titel erfasst -> Depotcheck mit gespeichertem Depot-Snapshot; ESG-Vorgabe
  Negativ-Screening mit bewusst zugelassenem und uebergewichtetem Thema ->
  Zeile «Abweichungen von der ESG-Vorgabe»). Damit laufen auch
  die bedingten Kundentext-Zweige durch alle Waechter.
* KN7 / N-928-01/-02: keine UUID und keine Hex-Folge ab 16 Zeichen in
  Kunden-PDFs (allgemeine Regel); Sektion 19 und 27 des Advisory-Reports
  widersprechen sich zur Eignungspruefung nie.
* KN8 / N-929-01: der Fall «Bestand + ESG» hat einen Beratungsprotokoll-
  Eintrag, damit Sektion 16 (Pruefsumme, Pruefergebnis) durch alle Waechter
  laeuft.

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
        from tests.fee_agreement_fixture import set_test_fee_agreement

        set_test_fee_agreement(api)  # EXE-P (H-187): kein Gebuehren-Default mehr
        advisor_id = api("GET", "/auth/me")[1]["id"]
        # Rechtliche Angaben mit echten Umlauten (Benutzerdaten sind nicht Teil
        # des Umlaut-Waechters, sie sollen ihn aber auch nicht ausloesen).
        onboarding.TEST_LEGAL_PROFILE = CLEAN_LEGAL_PROFILE
        mid = _seed_case(api, db_path, advisor_id, DEPLETION_CASE)["mid"]
        reserve = _seed_case(api, db_path, advisor_id, RESERVE_CASE)
        holdings_esg = _seed_case(api, db_path, advisor_id, HOLDINGS_ESG_CASE)
        results = _render_all(api, mid)
        reserve_results = _render_all(api, reserve["mid"])
        holdings_esg_results = _render_all(api, holdings_esg["mid"])
        out = os.environ.get("ARES_KN3_PDF_GUARD_OUT")
        if out:
            for case, rendered_case in (("verzehr", results), ("reserve", reserve_results),
                                        ("bestand_esg", holdings_esg_results)):
                Path(out, case).mkdir(parents=True, exist_ok=True)
                for name, (status, text) in rendered_case.items():
                    Path(out, case, f"{name}.txt").write_text(f"{status}\n{text}", encoding="utf-8")
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
        yield {"pdfs": results, "restart": (before, after),
               "cases": {"verzehr": results, "reserve": reserve_results,
                         "bestand_esg": holdings_esg_results},
               "reserve_generate": reserve["generate"], "holdings_esg": holdings_esg}
    finally:
        onboarding.TEST_LEGAL_PROFILE = original_profile
        _stop(proc)
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def rendered(live):
    return live["pdfs"]


@pytest.fixture(scope="module")
def rendered_all(live):
    """Beide Faelle; Schluessel ``(fall, dokument)``."""
    return {(case, name): value for case, pdfs in live["cases"].items() for name, value in pdfs.items()}


DEPLETION_CASE = {
    "client_number": "KN3-DEPL-1", "first_name": "Verena", "last_name": "Verzehr-Fiktiv",
    "date_of_birth": "1960-05-01", "mandate_number": "M-KN3-DEPL-1",
    "depot_rappen": 500_000_00, "expense_rappen": 60_000_00, "preferences": None,
}
# KN5: Reserve-Fall -- Mindestreserve ueber dem internen Liquiditaetsdeckel, also
# eine externe Reserve ausserhalb der Strategie; kein Verzehr.
RESERVE_CASE = {
    "client_number": "KN5-RES-1", "first_name": "Rainer", "last_name": "Reserve-Fiktiv",
    "date_of_birth": "1975-03-01", "mandate_number": "M-KN5-RES-1",
    "depot_rappen": 400_000_00, "expense_rappen": None,
    "preferences": {"limits": {"minReserve": "CHF 150'000"}},
}


# KN6 / N-917R5-02: Bestand je Titel + ESG-Abweichung. Negativ-Screening mit
# Tabak «bewusst zugelassen» (Begruendung Pflicht) und Verteidigung
# «uebergewichten» -> beide sind dokumentierte Abweichungen von der Vorgabe.
ESG_DEVIATION_REASON = (
    "Kundin hält Tabaktitel bewusst aus Familientradition, im Beratungsgespräch "
    "schriftlich bestätigt (fiktiv)"
)
HOLDINGS_ESG_CASE = {
    "client_number": "KN6-BES-1", "first_name": "Bettina", "last_name": "Bestand-Fiktiv",
    "date_of_birth": "1970-08-01", "mandate_number": "M-KN6-BES-1",
    "depot_rappen": 600_000_00, "expense_rappen": None,
    "preferences": {
        "policy": {**UI_PREFERENCES["policy"], "esg": "negative_screening"},
        "tilts": {"tobacco": "allow", "defense": "overweight"},
        "tiltReasons": {"tobacco": ESG_DEVIATION_REASON},
    },
    "holdings": True,
    # KN8 / N-929-01: ein Beratungsprotokoll-Eintrag, damit Sektion 16 des
    # Advisory-Reports (Pruefsumme + Pruefergebnis) im Waechter steht.
    "advisory_log": True,
}

# KN8: fiktiver Protokolleintrag ueber die echte API (Pflichtfelder U-FINMA-2.1).
ADVISORY_LOG_ENTRY = {
    "entry_type": "Jahresreview", "title": "Jahresgespräch (fiktiv)",
    "description": "Strategie, Risikoprofil und Bestand besprochen; keine Änderung beschlossen (fiktiv).",
    "decision": "Kein Handlungsbedarf", "entry_datetime": "2026-11-20T10:00:00.000Z",
    "duration_minutes": 45, "communication_channel": "persoenlich", "language": "de",
    "topics": ["Strategie", "Risikoprofil"], "risk_warnings_given": ["Marktrisiko"],
    "cost_disclosure_given": True, "status": "Empfohlen",
}


SYNTHETIC_PRICE_RAPPEN = 100_00  # synthetischer Kurs CHF 100.00 je Anteil (Testvektor)


def _record_holdings(api, db_path, mid):
    """Bestand je Titel ueber die oeffentliche Route (manuell, heutiger
    Stichtag) fuer die CHF-Titel der Empfehlung: Stueckzahl = Zielbetrag /
    synthetischer Tageskurs (in der Wegwerf-DB hinterlegt, Quelle «manual»).
    Danach erzeugt der Depotcheck einen gespeicherten Depot-Snapshot."""
    import datetime as _dt
    import sqlite3
    import uuid

    status, runs = api("GET", f"/mandates/{mid}/recommendations")
    assert status == 200, runs
    run_id = sorted(runs, key=lambda r: r.get("created_at") or "")[-1]["id"]
    status, positions = api("GET", f"/mandates/{mid}/recommendations/{run_id}/positions")
    assert status == 200 and positions, positions
    today = _dt.date.today().isoformat()
    con = sqlite3.connect(str(db_path))
    try:
        currency = dict(con.execute("SELECT id, currency FROM products").fetchall())
        chf = [p for p in positions if int(p.get("target_amount_rappen") or 0) > 0
               and str(currency.get(p["product_id"]) or "").upper() == "CHF"]
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        for position in chf:
            con.execute(
                "INSERT OR IGNORE INTO price_history (id, product_id, price_date, price_rappen, currency, source, "
                "fetched_at) VALUES (?, ?, ?, ?, 'CHF', 'manual', ?)",
                (str(uuid.uuid4()), position["product_id"], today, SYNTHETIC_PRICE_RAPPEN, now))
        con.commit()
    finally:
        con.close()
    for position in chf:
        amount = int(position["target_amount_rappen"])
        units_milli = amount * 1000 // SYNTHETIC_PRICE_RAPPEN
        status, body = api("PUT", f"/mandates/{mid}/recommendations/{run_id}/positions/{position['id']}/holding", {
            "units_milli": units_milli, "market_value_rappen": units_milli * SYNTHETIC_PRICE_RAPPEN // 1000,
            "as_of_date": today, "source": "manual", "depot_bank": "Testbank Fiktiv",
            "notes": "Bestand (fiktiv)"})
        assert status == 200, body
    assert chf, positions
    return len(chf)


def _seed_case(api, db_path, advisor_id, case):
    """Kunde, Mandat, Risikoprofil, Depot, (Ausgaben), Nachhaltigkeit,
    Strategie, Produktlauf, Finalisieren und Publizieren ueber die echte API."""
    from core import sustainability_preference as sp
    from tests.risk_fixture_helpers import standard_risk_payload
    from tests.test_livetest_e2b_strategy_blocks import _finalize_and_publish

    status, client = api("POST", "/clients", {
        "client_number": case["client_number"], "first_name": case["first_name"],
        "last_name": case["last_name"], "advisor_id": advisor_id, "household_type": "Einzelperson",
        "date_of_birth": case["date_of_birth"], "canton": "ZH"})
    assert status == 201, client
    cid = client["id"]
    status, mandate = api("POST", f"/clients/{cid}/mandates",
                          {"mandate_number": case["mandate_number"], "mandate_type": "Anlageberatung"})
    assert status == 201, mandate
    mid = mandate["id"]
    assert api("POST", f"/mandates/{mid}/risk-assessments", standard_risk_payload())[0] == 201
    status, body = api("POST", f"/clients/{cid}/wealth-positions", {
        "label": "Depot CHF (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
        "current_value_rappen": case["depot_rappen"], "currency": "CHF", "depot_bank": "Testbank Fiktiv",
        "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000})
    assert status in (200, 201), body
    if case["expense_rappen"]:
        status, body = api("POST", f"/clients/{cid}/cashflows", {
            "cashflow_type": "Expense", "label": "Lebenshaltung (fiktiv)", "amount_rappen": case["expense_rappen"],
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
    preferences = {**UI_PREFERENCES, **(case["preferences"] or {})}
    status, generate = api("POST", f"/mandates/{mid}/target-allocation/generate", {"preferences": preferences})
    assert status == 200, generate
    status, body = api("POST", f"/mandates/{mid}/recommendations/generate", {})
    assert status == 200, body
    recorded = _record_holdings(api, db_path, mid) if case.get("holdings") else 0
    _finalize_and_publish(api, db_path, mid)
    if case.get("advisory_log"):
        status, body = api("POST", f"/mandates/{mid}/advisory-log", ADVISORY_LOG_ENTRY)
        assert status == 201, body
        assert body["integrity_hash"] and body["integrity_verified"] is True, body
    return {"mid": mid, "generate": generate, "holdings": recorded}


def _render_all(api, mid):
    results = {}
    for name in CUSTOMER_PDFS:
        status, data = api("GET", f"/mandates/{mid}/reports/{name}.pdf", raw=True)
        results[name] = (status, _pdf_text(data) if status == 200 else data.decode("utf-8", "replace"))
    return results


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


def test_every_customer_pdf_renders_for_the_reserve_case(live):
    rendered = live["cases"]["reserve"]
    failed = {name: (status, body[:300]) for name, (status, body) in rendered.items()
              if status != 200 and name not in NOT_RENDERABLE}
    assert not failed, failed
    # Positivkontrolle: der Fall hat wirklich eine Reserve ausserhalb der Strategie
    # und ist kein Verzehr-Fall.
    assert live["reserve_generate"]["external_reserve_rappen"] > 0, live["reserve_generate"].get("external_reserve_rappen")
    assert not any("aufgebraucht ab" in text for text in _texts(rendered).values())
    # KN5 / N-917R4-02: die echte API liefert die Reserve getrennt im Bucket-Schema.
    generate = live["reserve_generate"]
    liq = [b for b in generate["buckets"] if b.get("reserve_rappen") is not None]
    assert len(liq) == 1 and liq[0]["reserve_rappen"] == generate["external_reserve_rappen"], generate["buckets"]
    assert all(b["comparison_basis"] == "strategy" for b in generate["buckets"]), generate["buckets"]
    assert liq[0]["current_strategy_amount_rappen"] == liq[0]["current_amount_rappen"] - liq[0]["reserve_rappen"]


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


def test_no_ascii_umlaut_transliteration_in_customer_pdfs(rendered_all):
    offenders = {name: sorted(set(umlaut_transliterations(text))) for name, text in _texts(rendered_all).items()}
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


def test_header_brand_is_the_firm_never_the_advisor(rendered_all):
    texts = _texts(rendered_all)
    as_brand = {name for name, text in texts.items() if ADVISOR.upper() in text}
    assert not as_brand, as_brand
    # Jedes Kunden-PDF mit Firmenkopf zeigt den Firmennamen aus den Firmenangaben
    # (der Advisory-Report fuehrt keine Firmenzeile, nur "Berater/Beraterin").
    missing = {name for name, text in texts.items()
               if name[1] != "advisory-report" and COMPANY.upper() not in text.upper()}
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
# KN4-B / DEMO-B3: interne Diagnose-/Rohwerte der Berechnung.
_DIAGNOSTIC = re.compile(r"\bstochastic\b|\bhouse_matrix\b|\bFALLBACK\b|\bFallback\b|\bIS (?:in)?aktiv\b|"
                         r"Optimizer-Modus|Importance Sampling|Recommendation-Methodology")


def test_no_raw_preference_keys_or_python_values_in_customer_pdfs(rendered, rendered_all):
    offenders = {}
    for name, text in _texts(rendered_all).items():
        flat = " ".join(text.split())
        hits = _RAW_KEY.findall(flat) + _PYTHON_VALUE.findall(flat) + _DIAGNOSTIC.findall(flat)
        if hits:
            offenders[name] = hits[:8]
    assert not offenders, offenders
    # Positivkontrolle: die Praeferenzen erscheinen als Kundentext.
    assert "Heimmarkt Schweiz bevorzugt" in " ".join(_texts(rendered)["contract-signoff"].split())


def test_raw_key_patterns_detect_the_old_output():
    old = "Dokumentierte Präferenzen: hedging: none; homeBias: ch_focus; altsGold: True; fundsOnly: True."
    assert _RAW_KEY.search(old) and _PYTHON_VALUE.search(old)
    assert not _RAW_KEY.search("Seite 2: Übersicht; Datum: 19.11.2026")
    assert _DIAGNOSTIC.search("Berechnungsmethode stochastic") and _DIAGNOSTIC.search("FALLBACK 0 IS inaktiv")
    assert not _DIAGNOSTIC.search("Berechnungsmethode stochastische Optimierung (Monte-Carlo)")


# ── KN4-B / E2E4-04: Depot als Vermoegensposition erfasst ────────────────────


def test_depotcheck_never_claims_no_depot_when_depot_position_exists(rendered):
    text = " ".join(_texts(rendered)["depotcheck"].split())
    assert "kein Depot erfasst" not in text, text[:600]


# -- KN5 / N-917R4-01: keine internen Pruef-/Diagnosewerte ------------------

# Klassen technischer Rohwerte (Befund-Texte H-176-Pruefung, A_advisory-report):
_TECHNICAL = re.compile(
    r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"            # UPPER_SNAKE (Reason-Codes)
    r"|\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"           # lower_snake (Felder/Tabellen)
    r"|\b[a-z]+[A-Z][A-Za-z0-9]*\b"                 # camelCase
    r"|\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b"          # CamelCase (Klassen)
    r"|\b[A-Z]{2,4} V\d+\b"                        # interne Versionskennung («TBI V1»)
    r"|\b\d{10,}\b"                                # Seeds/lange Kennzahlen
    # Englische Status-/Technikwoerter, auch in Grossbuchstaben («TOTAL-LOGS»).
    r"|\b(?i:seed|converged|diverged|pending|failed|succeeded|active|inactive|shadow|emergency|"
    r"payload|optimizer|engine|polic(?:y|ies)|snapshot|sprint|pipeline|buckets?|hard-cap|cascade|"
    r"read-only|reasons?|logs|required|stage|foundation|anchor|recovery|returns?)\b"
)
# Ortsgebundene Allowlist: (Dokument, Fundstelle) -> Begruendung. Gilt nur in
# genau diesem Dokument (beide Faelle); dieselbe Fundstelle anderswo ist rot.
TECHNICAL_ALLOWLIST: dict[tuple[str, str], str] = {
    ("contract-signoff", "revDSG"): "Gesetzesabkuerzung (revidiertes Datenschutzgesetz), Rechtstext",
    ("anlagestrategie", "iSAA"): "im Satz eingefuehrte Abkuerzung «individuelle strategische Asset Allokation (iSAA)»",
    ("advisory-report", "iSAA"): "dieselbe Abkuerzung, im Methodik-Absatz erklaert",
    ("kundeninformation", "VertragsabschlussInformationen"):
        "Textauslese verbindet Titel «… vor Vertragsabschluss» und Untertitel «Informationen nach Art. 8 …»",
    ("vertrag", "UmsetzungsplanDokument"):
        "Textauslese verbindet Zeilenende «Umsetzungsplan» und folgende Zeile «Dokument …»",
}


# CCX-P5 / N-929-02: Kurzreferenzen hinter einem Etikett («Audit:»,
# «Beratungsentscheid:», «FX-Basis», «Prüfwert», «Prüfsumme», «Entscheid-Nr.»)
# sind gewollte Kundenhinweise (8 bis 12 Hex-Zeichen). Bestehen sie zufaellig
# nur aus Ziffern, schlug das Muster «lange Kennzahl» an (H-179, lokal mit
# 020970979213). Ohne Etikett bleibt jede lange Zahl rot.
_SHORT_REFERENCE_LABELS = ("Audit:", "Beratungsentscheid:", "FX-Basis", "Prüfwert", "Prüfsumme", "Entscheid-Nr.")
_SHORT_REFERENCE = re.compile(
    "(" + "|".join(re.escape(label) for label in _SHORT_REFERENCE_LABELS) + ")"
    + r":? ?[0-9a-f]{8,12}(?![0-9a-f])"
)


def technical_hits(name: str, text: str) -> list[str]:
    flat = _SHORT_REFERENCE.sub(lambda m: m.group(1) + " <Kurzreferenz>", " ".join(text.split()))
    return [hit for hit in (m.group(0) for m in _TECHNICAL.finditer(flat))
            if (name, hit) not in TECHNICAL_ALLOWLIST]


def test_no_internal_diagnostic_values_in_customer_pdfs(rendered_all):
    offenders = {}
    for (case, name), text in _texts(rendered_all).items():
        hits = technical_hits(name, text)
        if hits:
            offenders[f"{case}/{name}"] = sorted(set(hits))[:12]
    assert not offenders, offenders
    # Positivkontrolle: die kundenrelevanten Aussagen stehen als Text da.
    advisory = " ".join(_texts(rendered_all)[("verzehr", "advisory-report")].split())
    assert "Methodik der Produktempfehlung" in advisory
    assert "Bearbeitungsstand des Mandats" in advisory
    assert "Berechnungsmethode: stochastische Optimierung (Monte-Carlo)" in advisory


def test_allowlist_entries_are_used_and_located():
    """Jeder Allowlist-Eintrag nennt Dokument + Fundstelle + Begruendung; ein
    erlaubter Ausdruck in einem anderen Dokument bleibt rot."""
    assert all(name in CUSTOMER_PDFS and hit and reason for (name, hit), reason in TECHNICAL_ALLOWLIST.items())
    assert technical_hits("contract-signoff", "gemäss revDSG") == []
    assert technical_hits("portfolio", "gemäss revDSG") == ["revDSG"]


def test_short_reference_labels_are_not_technical_values_but_other_long_numbers_are():
    for label in _SHORT_REFERENCE_LABELS:
        assert technical_hits("anlagestrategie", f"{label} 020970979213 · Fassung 1") == [], label
    assert technical_hits("risikoprofil", "Entscheid-Nr. 02097097 · wirksam") == []
    # Gegenproben: ohne Etikett, zu lang oder neben dem Etikett bleibt es rot.
    assert technical_hits("anlagestrategie", "Lauf 020970979213") == ["020970979213"]
    assert technical_hits("anlagestrategie", "Prüfwert 0209709792131") == ["0209709792131"]
    assert technical_hits("anlagestrategie", "Prüfwert 0209709792 Lauf 4417709213") == ["4417709213"]


def test_technical_patterns_detect_the_old_output():
    """Gegenprobe mit den Befund-Texten (gerendert auf d1dc, H-176-Pruefung)."""
    old = [
        "Seed / Pfade Seed 5948716738976139969 / 2000 Pfade",
        "Letzter Optimizer-Status converged",
        "Keine Suitability-Verstösse im Audit-Payload.",
        "Keine Read-only-Reasons im Audit-Payload.",
        "TOTAL-LOGS 0 REQUIRED 1",
        "Liquidity-Cascade emergency Stage Hard-Cap 3.0 %",
        "Keine zweite OptimizerPolicy für einen A/B-Vergleich vorhanden.",
        "Kenntnislücke [KNOWLEDGE_GAP_ASSET_CLASS]: Die SAA enthält Aktien",
        "Datenquelle: asset_class_annual_returns; TargetAllocation",
        "TBI V1 - strategische Soll-Allokation",
        "(ch_bucket_correlation_default v1)",
        "Foundation-Variante — volle Marktdaten-Pipeline kommt in Sprint U-P11.",
    ]
    for line in old:
        assert technical_hits("advisory-report", line), line
    clean = ("Berechnungsmethode: stochastische Optimierung (Monte-Carlo). Die Berechnung ist "
             "abgeschlossen und erfüllt die Prüfkriterien. Das Mandat kann bei Bedarf angepasst "
             "werden. Liquiditätsquote der Strategie: 3.02 % (übliche Obergrenze 3.00 %). "
             "Max Drawdown 10.4 %, VaR 95 %, Länder-HHI 3171, CHF 1'227'410, 20.11.2026, "
             "Musterprodukt Aktien Schweiz, FIDLEG, FINMA, Retrozession, OK")
    assert technical_hits("advisory-report", clean) == []


# -- KN6 / N-917R5-02: Fall «Bestand + ESG-Abweichung» -------------------------


def test_every_customer_pdf_renders_for_the_holdings_esg_case(live):
    rendered = live["cases"]["bestand_esg"]
    failed = {name: (status, body[:300]) for name, (status, body) in rendered.items()
              if status != 200 and name not in NOT_RENDERABLE}
    assert not failed, failed
    texts = {name: " ".join(text.split()) for name, text in _texts(rendered).items()}
    # Positivkontrollen: der Fall hat wirklich Bestaende (gespeicherter
    # Depot-Snapshot im Depotcheck) und eine dokumentierte ESG-Abweichung.
    assert live["holdings_esg"]["holdings"] > 0
    assert re.search(r"Datenstand: Bestandsstichtag \d{2}\.\d{2}\.\d{4}, Prüfsumme [0-9a-f]{8}\.",
                     texts["depotcheck"]), texts["depotcheck"][-1500:]
    assert "Abweichungen von der ESG-Vorgabe" in texts["anlagestrategie"]
    assert "Tabak bewusst zugelassen" in texts["anlagestrategie"]
    assert "Verteidigung übergewichtet" in texts["anlagestrategie"]
    # Keine internen Kennungen des Snapshots im Kundentext.
    assert "Depot-Snapshot" not in texts["depotcheck"] and "Hash " not in texts["depotcheck"]


def test_conditional_branches_render_customer_text():
    """Zweige, die kein Live-Fall erreicht (Solver ohne Ergebnis, Execution-only/
    institutionell, Angemessenheit, unbekannte Pruefgrundlage), als
    Unit-Rendering gegen dieselben Waechter."""
    from services.pdf.components.compliance_audit import CUSTOMER_SUITABILITY_TEXTS, customer_suitability_text
    from services.pdf.components.goal_achievability import make_limiting_factor_line

    texts = [make_limiting_factor_line("solver_konvergenz").getPlainText()]
    texts += list(CUSTOMER_SUITABILITY_TEXTS.values())
    texts.append(customer_suitability_text({"is_compliant": True})[1])
    # KN7: Bestaetigungstexte des Beratungsentscheids, Leerzustaende/Pills von
    # Sektion 27 und die Kundenfassung des Override-Nachweises (Risikoprofil).
    from services.pdf.base import RisikoprofilData
    from services.pdf.documents import advisory_report as ar, contract_signoff as cs
    from services.pdf.documents.risikoprofil import customer_decision_reference_text

    texts += [*cs._ADVISOR_CONFIRM_CHECKED.values(), *cs._ACK_CHECKED.values(),
              cs._ADVISOR_CONFIRM_WITHOUT_CHECK, cs._ACK_WITHOUT_CHECK,
              *ar._SS_EMPTY_TITLES.values(), *(v[0] for v in ar._SUITABILITY_STATUS_OVERRIDE_PILL.values())]
    for kw in ({"override_decision_verified": True}, {"override_decision_verified": False},
               {"override_decision_id": None}):
        texts.append(customer_decision_reference_text(RisikoprofilData(**{
            "risk_profile_label": "Ausgewogen", "risk_capacity_score": 50, "risk_tolerance_score": 50,
            "override_decision_id": "3f1c2b9a-7d4e-4c21-9a8b-0c5d6e7f8a9b", **kw})))
    for text in texts:
        assert not technical_hits("advisory-report", text), text
        assert not umlaut_transliterations(text), text
    assert "Optimierer" not in texts[0] and "Fallback" not in texts[0]


# -- KN7 (H-181-Pruefung, N-928-01/-02): Kennungen und Eignungsaussagen --------


def test_no_uuid_or_long_hex_in_customer_pdfs(rendered_all):
    """Allgemeine Regel (CTO-Nachtrag H-181, Punkt 4): kein Kunden-PDF zeigt eine
    UUID oder eine Hex-Folge ab 16 Zeichen (volle Hashes, interne Kennungen).
    Kunden sehen hoechstens eine 8-stellige Pruefsumme/Nummer; die vollen Werte
    stehen in DB, Audit-Log und Berater-/Audit-Fassung. Gegenprobe:
    test_kn7_customer_suitability_and_references::test_internal_id_rule_detects_the_old_output."""
    from tests.test_kn7_customer_suitability_and_references import internal_id_hits

    offenders = {}
    for (case, name), text in _texts(rendered_all).items():
        hits = internal_id_hits(text)
        if hits:
            offenders[f"{case}/{name}"] = sorted(set(hits))[:6]
    assert not offenders, offenders
    # Positivkontrolle: die Kurzform steht da (Protokoll: Nachhaltigkeits-Nachweis).
    protokoll = " ".join(_texts(rendered_all)[("verzehr", "protokoll")].split())
    assert re.search(r"Prüfsumme Definition [0-9a-f]{8} · Erfassung [0-9a-f]{8}", protokoll), protokoll[-1200:]
    # KN8 / N-929-01: Sektion 16 mit Protokolleintrag (Fall «Bestand + ESG») --
    # 8-stellige Pruefsumme und das echte Pruefergebnis des Dienstes.
    advisory = " ".join(_texts(rendered_all)[("bestand_esg", "advisory-report")].split())
    assert "AKTIVE EINTRÄGE 1" in advisory, advisory[-2500:]
    assert re.search(r"INTEGRITÄT Prüfsumme [0-9a-f]{8} · verifiziert", advisory), advisory[-2500:]
    assert "Persönlich" in advisory


def test_sections_19_and_27_never_contradict_in_live_cases(rendered_all):
    """N-928-01: Sektion 27 (Eignungspruefung) und Sektion 19 (Compliance-Audit)
    widersprechen sich im selben Kunden-PDF nie -- in allen Live-Faellen."""
    from tests.test_kn7_customer_suitability_and_references import suitability_contradictions

    offenders = {}
    for (case, name), text in _texts(rendered_all).items():
        if name != "advisory-report":
            continue
        found = suitability_contradictions(" ".join(text.split()))
        if found:
            offenders[case] = found
    assert not offenders, offenders
    advisory = " ".join(_texts(rendered_all)[("verzehr", "advisory-report")].split())
    # Positivkontrolle: Sektion 19 bestaetigt die Pruefung, Sektion 27 sagt dasselbe.
    assert "liegt die erforderliche Geeignetheitsprüfung vor" in advisory
    assert "Eignungsprüfung im Risikoprofil dokumentiert" in advisory
