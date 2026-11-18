"""K2 (Dok. 115) -- statische Vertraege der Berater-Oberflaeche.

* E2E-10: keine Drittbank-Namen als Vorgabe, Option oder Platzhalter in den
  Frontendquellen und im Demo-Fall; ohne Wahl geht keine Depotbank an die
  Empfehlung (die Positionsbegruendung nennt dann keinen Banknamen).
* E2E-17: keine statischen Demo-Mandate/Platzhalterdaten im Monolithen.
* E2E-02: ``single_person_firm`` ist in der Oberflaeche setzbar (nicht nur per API).
* Der neue Teil ``advisor-guidance.js`` ist genau einmal eingebunden und gehoert
  zum Monolith-Bundle (Budget, Verbots-Guards).
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.monolith_source import read_frontend_sources, read_monolith_bundle

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "ares-desktop" / "frontend"
# Drittbanken, die frueher als Vorgabe/Platzhalter im Produkt standen (Fremdmarken-Verbot).
BANKS = re.compile(r"\b(UBS AG|UBS,|ZKB|Raiffeisen|Swissquote|PostFinance|BEKB|Sichtguthaben UBS|Depot UBS)\b")


def test_no_third_party_bank_names_in_frontend_sources():
    src = read_frontend_sources()
    hits = sorted(set(m.group(0) for m in BANKS.finditer(src)))
    assert hits == [], hits


def test_gegenprobe_bank_pattern_detects_old_default():
    assert BANKS.search("var b=getInputValue('recipe-depot-bank')||'UBS AG Zürich';")
    assert BANKS.search('<select><option>ZKB</option></select>')


def test_recommendation_depot_bank_defaults_to_none():
    bundle = read_monolith_bundle()
    calls = re.findall(r"getInputValue\('recipe-depot-bank'\)\|\|([^;]+);", bundle)
    assert calls and set(calls) <= {"null", "'')"}, calls  # nie ein vorbelegter Bankname


def test_foundation_demo_case_uses_neutral_bank_labels():
    text = (REPO / "ares-backend" / "services" / "foundation_example.py").read_text(encoding="utf-8")
    assert not BANKS.search(text.replace("\\u00fc", "ü"))
    assert "Depotbank (Muster)" in text


def test_no_static_demo_mandates_or_placeholder_people():
    html = read_monolith_bundle()
    for needle in ("Familie Mueller-Weber", 'data-pid="HH-001"', 'id="alert-count"', "CHF 3.9 Mio",
                   'id="m-edit-depot"', 'id="m-edit-hypo"', 'id="m-edit-custom"', 'id="m-edit-immo"'):
        assert needle not in html, needle


def test_single_person_firm_is_settable_in_the_ui_and_module_is_bundled():
    from tests.monolith_source import EXTRACTED_PARTS

    # read_monolith_bundle() prueft selbst, dass jede Einbindung genau einmal vorkommt.
    assert ("advisor-guidance.js", "js") in EXTRACTED_PARTS
    module = (FRONTEND / "advisor-guidance.js").read_text(encoding="utf-8")
    assert "single_person_firm" in module
    assert "API.put('/tenants/me', {single_person_firm: want})" in module
    bundle = read_monolith_bundle()
    assert "function publishFourEyesFlow" in bundle and "askSinglePersonFirmAfterBootstrap" in bundle
