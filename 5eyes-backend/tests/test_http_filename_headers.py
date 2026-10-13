"""Content-Disposition-Header muessen ASCII sein (RFC 7230/6266).

Befund 2026-10-12, im Ende-zu-Ende-Durchlauf des Mock-Mandanten "Thierry
Gössi" gefunden. Alle zwoelf Dokument-Endpunkte bauten ihren Dateinamen mit

    "".join(c if c.isalnum() else "_" for c in name)

Die Absicht war ein ASCII-sicherer Name. `str.isalnum()` ist in Python aber
UNICODE-bewusst -- `"ö".isalnum()` ist `True` --, also liess der Sanitizer
jeden Unicode-Buchstaben durch.

Zwei gemessene Schweregrade:

    "Gössi"  -> Byte 0xF6 roh im Header (Starlette kodiert Latin-1).
                Nicht konform; ein strikt UTF-8 dekodierender Client bricht
                ab.
    "Łukasz" -> `"Ł".encode("latin-1")` WIRFT, und zwar in
                `Response.__init__` -- also nach dem Rendern und ausserhalb
                jedes try/except des Endpunkts: HTTP 500. Das FIDLEG-
                Pflichtdokument war fuer solche Mandanten nicht
                herunterladbar.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.responses import Response

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.http_filenames import (  # noqa: E402
    ascii_filename_component,
    content_disposition,
)


# ---------------------------------------------------------------------------
# Der Befund selbst: Starlette als Zeuge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Gössi", "Łukasz", "Şahin", "李明", "Müller-Ødegård", "Nováková"],
)
def test_header_value_survives_starlette_header_encoding(name):
    """Der erzeugte Header muss durch Starlettes Latin-1-Kodierung kommen.

    Das ist der eigentliche Vertrag: nicht "sieht hübsch aus", sondern
    "erzeugt keine Exception und keinen kaputten Byte-Strom". Deshalb wird
    hier ein echtes `Response`-Objekt gebaut -- genau der Pfad, der im
    Befund warf.
    """
    header = content_disposition(f"kostenausweis-{name}.pdf")
    response = Response(content=b"%PDF-1.4", headers={"Content-Disposition": header})
    raw = dict(response.raw_headers)[b"content-disposition"]
    assert raw.decode("ascii")  # wirft, wenn ein Byte > 0x7F drin ist


@pytest.mark.parametrize("name", ["Łukasz", "Şahin", "李明"])
def test_naive_sanitizer_would_still_raise(name):
    """Gegenprobe am alten Verfahren -- der Befund ist real, nicht vermutet.

    Dieser Test schlaegt fehl, wenn jemand `isalnum()` fuer ausreichend
    haelt und zum alten Muster zurueckkehrt: er zeigt, dass genau dieses
    Muster bei nicht-Latin-1-Namen WIRFT.
    """
    naive = "".join(c if c.isalnum() else "_" for c in name)
    with pytest.raises(UnicodeEncodeError):
        Response(
            content=b"x",
            headers={"Content-Disposition": f'inline; filename="{naive}.pdf"'},
        )


# ---------------------------------------------------------------------------
# Umschrift und Rueckfall
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Gössi", "Goessi"),
        ("Müller", "Mueller"),
        ("Bäckerei", "Baeckerei"),
        ("Strauß", "Strauss"),
        ("Łukasz", "Lukasz"),
        ("Ødegård", "Oedegaard"),
        ("Nováková", "Novakova"),
        ("Şahin", "Sahin"),
    ],
)
def test_german_transliteration_before_unicode_decomposition(raw, expected):
    """"Gössi" wird "Goessi", nicht "Gossi".

    Die Reihenfolge ist der Punkt: ohne die vorgezogene Umschrift wuerde die
    NFKD-Zerlegung das Trema einfach verwerfen. Im deutschsprachigen Raum
    ist "oe" die uebliche Schreibung, und der Dateiname ist das, was der
    Berater im Download-Ordner wiederfinden muss.
    """
    assert ascii_filename_component(raw) == expected


def test_name_without_latin_script_falls_back_instead_of_emptying():
    """Ein rein nicht-lateinischer Name darf keinen leeren Dateinamen ergeben."""
    assert ascii_filename_component("李明") == "dokument"
    assert ascii_filename_component("李明", fallback="mandat") == "mandat"


def test_exact_name_is_preserved_in_rfc6266_parameter():
    header = content_disposition("kostenausweis-Gössi.pdf")
    assert 'filename="kostenausweis-Goessi.pdf"' in header
    # Der exakte Name reist prozentkodiert mit -- ASCII, aber verlustfrei.
    assert "filename*=UTF-8''kostenausweis-G%C3%B6ssi.pdf" in header


def test_pure_ascii_name_gets_no_redundant_parameter():
    """Gegenprobe: ohne Sonderzeichen bleibt der Header schlank.

    Sonst waere nicht zu unterscheiden, ob `filename*` etwas beitraegt oder
    bloss immer angehaengt wird.
    """
    header = content_disposition("advisory-report-TG-M-001.pdf")
    assert header == 'inline; filename="advisory-report-TG-M-001.pdf"'
    assert "filename*" not in header


def test_hyphens_and_underscores_survive():
    """Lesbarkeit: "kostenausweis-Goessi" darf nicht zu Unterstrich-Brei werden."""
    assert ascii_filename_component("kostenausweis-Goessi_2026") == (
        "kostenausweis-Goessi_2026"
    )


def test_disposition_type_is_passed_through():
    assert content_disposition("x.pdf", disposition="attachment").startswith(
        "attachment; "
    )


# ---------------------------------------------------------------------------
# Header-Injektion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        'x"; evil="1',
        "x\r\nX-Injected: 1",
        "x\nSet-Cookie: a=b",
        'x"; filename="other',
        "x; evil=1",
    ],
)
def test_filename_cannot_inject_a_header(hostile):
    """Der Dateiname stammt aus KUNDENDATEN -- er ist eine Eingabe.

    Ein Mandatsname mit Anfuehrungszeichen oder Zeilenumbruch darf keinen
    zweiten Header und keinen zweiten Parameter erzeugen.
    """
    header = content_disposition(f"{hostile}.pdf")
    assert header.isascii()
    assert "\r" not in header and "\n" not in header
    # Genau zwei Anfuehrungszeichen: die um den Rueckfallnamen.
    assert header.count('"') == 2
    # Genau ein `filename=`-Parameter (der kodierte heisst `filename*=`).
    assert header.count("filename=") == 1


def test_empty_and_none_names_are_handled():
    for value in ("", "   ", None):
        header = content_disposition(value)  # type: ignore[arg-type]
        assert header == 'inline; filename="dokument"'
