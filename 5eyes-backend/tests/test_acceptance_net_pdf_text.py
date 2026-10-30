"""Abnahmenetz G4: Text der rechtlich relevanten PDF-Dokumente eingefroren.

Laenderpaket-Schritt X0 (nur Tests). Spaetere Schritte (X3 DocumentSet fuer
Rechts- und Pflichttexte, X5 Fragebogen als Daten, X9 Formatting) muessen
einen leeren Text-Diff liefern.

Die Dokumente entstehen ueber die echten PDF-Endpunkte einer frischen
Installation mit festem Berichtsdatum. Je Seite wird der mit ``pypdf``
extrahierte Text normalisiert (UUIDs, Zeitstempel, Datumswerte, Uhrzeiten und
Hex-Hashes maskiert) und ohne Leerraum gehasht; damit ist der Vergleich
unabhaengig von Abstands-Heuristiken der Textextraktion und vom
Zeilenende des Betriebssystems. Schriften sind im Repo eingebettet
(``assets/fonts``), der Umbruch ist deshalb plattformgleich.

Nicht abgedeckt (weggelassen statt flakey): Dokumente, deren Inhalt aus
einem Optimierer-/Monte-Carlo-Lauf stammt (Anlagestrategie, Asset
Allocation, Portfolio, Depotcheck, Backtest, Advisory-Report); deren
Zahlen sind ueber Plattformen nicht bitgleich (siehe Golden-Snapshot-Regel).
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.acceptance_net_install import advisory_scenario  # noqa: E402
from tests.acceptance_net_support import (  # noqa: E402
    assert_matches_baseline,
    dump_actual,
    mask_text,
    text_fingerprint,
)
from tests.risk_fixture_helpers import standard_risk_payload  # noqa: E402

FIXED_REPORT_DATE = _dt.date(2026, 1, 15)

DOCUMENTS = {
    "risikoprofil": "/mandates/{mandate}/reports/risikoprofil.pdf",
    "vertrag": "/mandates/{mandate}/reports/vertrag.pdf",
    "protokoll": "/mandates/{mandate}/reports/protokoll.pdf",
}


class _FixedDate(_dt.date):
    @classmethod
    def today(cls):  # noqa: D401 - festes Berichtsdatum
        return cls(FIXED_REPORT_DATE.year, FIXED_REPORT_DATE.month, FIXED_REPORT_DATE.day)


def _page_texts(pdf_bytes: bytes) -> list[str]:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() or "" for page in reader.pages]


@pytest.fixture(scope="module")
def pdf_texts(tmp_path_factory) -> dict[str, list[str]]:
    import routers.pdf_reports as pdf_reports

    texts: dict[str, list[str]] = {}
    db_file = tmp_path_factory.mktemp("acceptance-pdf") / "fresh.db"
    with advisory_scenario(db_file) as (client, _factory, ids), pytest.MonkeyPatch.context() as mp:
        mp.setattr(pdf_reports, "date", _FixedDate)
        mandate = ids["advisory"]
        created = client.post(f"/mandates/{mandate}/risk-assessments", json=standard_risk_payload())
        assert created.status_code == 201, created.text
        for name, url in DOCUMENTS.items():
            response = client.get(url.format(mandate=mandate))
            assert response.status_code == 200, (name, response.status_code, response.text[:300])
            assert response.content[:5] == b"%PDF-"
            texts[name] = _page_texts(response.content)
    for name, pages in texts.items():
        dump_actual(f"pdf_text/{name}.txt", "\n\n=== Seite ===\n\n".join(mask_text(p) for p in pages))
    return texts


def test_pdf_page_texts_match_baseline(pdf_texts):
    assert_matches_baseline("pdf_text_ch.json", {
        name: {"pages": len(pages), "page_text": [text_fingerprint(p) for p in pages]}
        for name, pages in pdf_texts.items()
    })


def test_pdf_text_extraction_is_deterministic(pdf_texts, tmp_path):
    # Zweiter Lauf auf einer zweiten frischen Installation: gleiche Fingerprints.
    import routers.pdf_reports as pdf_reports

    with advisory_scenario(tmp_path / "second.db") as (client, _factory, ids), pytest.MonkeyPatch.context() as mp:
        mp.setattr(pdf_reports, "date", _FixedDate)
        mandate = ids["advisory"]
        assert client.post(f"/mandates/{mandate}/risk-assessments", json=standard_risk_payload()).status_code == 201
        second = {
            name: [text_fingerprint(p) for p in _page_texts(client.get(url.format(mandate=mandate)).content)]
            for name, url in DOCUMENTS.items()
        }
    first = {name: [text_fingerprint(p) for p in pages] for name, pages in pdf_texts.items()}
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
