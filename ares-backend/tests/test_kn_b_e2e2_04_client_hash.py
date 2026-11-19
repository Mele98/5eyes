"""KN-B / E2E2-04: Der Kunden-Siegel haengt nur an relevanten Kundenfeldern.

Befund (Dok. 117): Eine reine Berufsaenderung machte die publizierte
Soll-Allokation ungueltig (``CCX_INPUT_STALE``), weil die Kante "client" die
ganze Kundenzeile band (models/snapshots.py, nur ``updated_at`` volatil).

Jetzt sind nur Spalten mit ``info={ADVISORY_HASH_EXEMPT_INFO_KEY: True}``
(Beruf, Arbeitgeber, Beruf Partner/in, Notizen) ausgenommen -- im Hook
(models/snapshots.py) und im Manifest/Pull (services/effective_input_manifest.py).

* Vollstaendigkeit: jede Spalte ist entweder gebunden oder bewusst ausgenommen.
* Waechter: kein Engine-/Payload-/Eignungs-/PDF-Modul liest eine ausgenommene
  Spalte; jede dort gelesene Kundenspalte ist gebunden.
* Querschnitt: Beruf/Arbeitgeber/Notizen aendern -> FRESH und PUBLISHED;
  Geburtsdatum oder Kanton (Steuerdomizil) aendern -> STALE.
* Uebergang: ein vor dem Wechsel mit der ganzen Zeile versiegelter Entscheid
  bleibt aktuell (keine Entwertung des Bestands), bis sich die Zeile aendert.

Gegenprobe: Markierung aus models/clients.py entfernen (oder ``_hash_exempt``
immer False) -> Querschnitt rot; ``legacy_hash`` nicht pruefen -> Uebergang rot.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import inspect as sa_inspect

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p2_invalidation import _envelope
from tests.test_ccx_p4_allocation_publish import _published, _state

BACKEND = Path(__file__).resolve().parents[1]
EXPECTED_EXEMPT = {"profession", "employer", "partner_profession", "notes"}
# Module ausserhalb der Beratungskette (Stammdaten-CRUD, Datenschutz/Loeschung,
# Export, Demo-Fall). Alles uebrige unter services/, core/, routers/ zaehlt als
# Engine/Payload/Eignung/PDF-Kette.
NON_PIPELINE = {
    "routers/clients.py", "routers/client_portal.py", "services/client_erasure.py",
    "services/privacy_erasure_inventory.py", "services/privacy_subject_requests.py",
    "services/foundation_example.py", "services/data_export.py", "services/dsg_governance.py",
    "services/review_calendar_feed.py", "services/erasure_restore.py",
}


def _client_columns():
    from models.clients import Client

    return {attr.key for attr in sa_inspect(Client).column_attrs}


def test_every_client_column_is_bound_or_explicitly_exempt():
    import models.snapshots as snapshots
    from models.clients import ADVISORY_HASH_EXEMPT_INFO_KEY, CLIENT_HASH_COLUMNS, CLIENT_HASH_EXEMPT_COLUMNS

    assert snapshots.HASH_EXEMPT_INFO_KEY == ADVISORY_HASH_EXEMPT_INFO_KEY
    assert set(CLIENT_HASH_EXEMPT_COLUMNS) == EXPECTED_EXEMPT
    assert not set(CLIENT_HASH_COLUMNS) & EXPECTED_EXEMPT
    # KN3-B / N-917R2-01: tenant_id ist Mandantengrenze, nicht Beratungsinhalt.
    assert "tenant_id" not in CLIENT_HASH_COLUMNS
    assert set(CLIENT_HASH_COLUMNS) | EXPECTED_EXEMPT | {"updated_at", "tenant_id"} == _client_columns()
    # Im Zweifel gebunden: Geburtsdatum, Zivilstand, Wohnsitz/Kanton, Haushalt ...
    for column in ("date_of_birth", "partner_date_of_birth", "civil_status", "country_of_residence", "canton",
                   "household_type", "client_classification", "salutation", "language", "deleted_at"):
        assert column in CLIENT_HASH_COLUMNS, column


def _pipeline_sources():
    for folder in ("services", "core", "routers"):
        for path in sorted((BACKEND / folder).rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel not in NON_PIPELINE:
                yield rel, path.read_text(encoding="utf-8")


def _client_reads(source: str, columns: set[str]) -> set[str]:
    names = "|".join(sorted(columns, key=len, reverse=True))
    patterns = (
        rf"\b\w*client\w*\.({names})\b",
        rf"\bClient\.({names})\b",
        rf"getattr\(\s*\w*client\w*\s*,\s*[\"']({names})[\"']",
        rf"\b\w*client\w*\[\s*[\"']({names})[\"']\s*\]",
    )
    found: set[str] = set()
    for pattern in patterns:
        found.update(re.findall(pattern, source))
    return found


def test_guard_pipeline_reads_only_bound_client_columns():
    """Waechter: jede von Engine/Payload/Eignung/PDF gelesene Kundenspalte ist
    im Siegel; keine ausgenommene Spalte wird dort gelesen."""
    from models.clients import ADVISORY_TENANT_BOUNDARY_COLUMNS, CLIENT_HASH_COLUMNS

    # KN3-B / N-917R2-01: tenant_id wird zur Mandantentrennung gelesen (Auth,
    # Scope, RLS), nie als Beratungsinhalt -- deshalb nicht Teil dieses Scans.
    columns = _client_columns() - {"id"} - ADVISORY_TENANT_BOUNDARY_COLUMNS
    offenders = {}
    seen: set[str] = set()
    for rel, source in _pipeline_sources():
        reads = _client_reads(source, columns)
        seen |= reads
        bad = reads - set(CLIENT_HASH_COLUMNS)
        if bad:
            offenders[rel] = sorted(bad)
    assert not offenders, f"Gelesene, aber nicht gebundene Kundenfelder: {offenders}"
    # Positivkontrolle: der Scan findet die bekannten Lesestellen.
    assert {"date_of_birth", "partner_date_of_birth", "client_classification"} <= seen, seen


def test_guard_detects_exempt_read():
    """Positivkontrolle des Waechter-Musters."""
    assert _client_reads("x = mandate.client.profession", EXPECTED_EXEMPT) == {"profession"}
    assert _client_reads('getattr(client, "employer", None)', EXPECTED_EXEMPT) == {"employer"}


def _mutate(session_factory, mid, **values):
    from models.clients import Client
    from models.mandates import Mandate

    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        client = db.get(Client, mandate.client_id)
        for key, value in values.items():
            setattr(client, key, value)
        db.commit()


def _status(session_factory, mid, envelope_id):
    with session_factory() as db:
        env = tuple(_envelope(db, envelope_id)[:2])
    state = _state(session_factory, mid)
    return env, state.status, state.reason_code


def test_irrelevant_client_fields_keep_publication_fresh(session_factory):
    _advisor, _approver, mid, _aid, _run, decision = _published(session_factory, "kn-cf")
    before = _status(session_factory, mid, decision.envelope_id)
    assert before == (("SEALED", "FRESH"), "PUBLISHED", None), before
    _mutate(session_factory, mid, profession="Architektin (fiktiv)")
    _mutate(session_factory, mid, employer="Testfirma Fiktiv", partner_profession="Lehrer (fiktiv)",
            notes="Telefon und E-Mail im Gespraech aktualisiert")
    assert _status(session_factory, mid, decision.envelope_id) == before


def test_birth_date_change_makes_publication_stale(session_factory):
    _advisor, _approver, mid, _aid, _run, decision = _published(session_factory, "kn-dob")
    _mutate(session_factory, mid, date_of_birth="1961-02-03")
    env, status, code = _status(session_factory, mid, decision.envelope_id)
    assert env == ("SEALED", "STALE") and status == "PUBLICATION_INVALID" and code == "CCX_INPUT_STALE"


def test_tax_domicile_change_makes_publication_stale(session_factory):
    _advisor, _approver, mid, _aid, _run, decision = _published(session_factory, "kn-tax")
    with session_factory() as db:
        from models.clients import Client
        from models.mandates import Mandate

        current = db.get(Client, db.get(Mandate, mid).client_id).canton
    _mutate(session_factory, mid, canton="BE" if current != "BE" else "ZH")
    env, status, code = _status(session_factory, mid, decision.envelope_id)
    assert env == ("SEALED", "STALE") and status == "PUBLICATION_INVALID" and code == "CCX_INPUT_STALE"


def test_decision_sealed_with_full_row_stays_current_until_the_row_changes(session_factory, monkeypatch):
    """Uebergang: Bestand (Kante ueber die ganze Kundenzeile) wird nicht entwertet."""
    import services.effective_input_manifest as manifest

    original = manifest._columns
    # KN4-B / N-917R3-06: Uebergang nur fuer Altsiegel -- hier wird ein Altsiegel
    # simuliert, also gilt es als vor dem Stichtag versiegelt.
    monkeypatch.setattr(manifest, "LEGACY_PROJECTION_SEALED_BEFORE", "9999-12-31T00:00:00.000Z")
    # Altsiegel: ganze Zeile inkl. Beruf und Mandantengrenze (vor KN-B und KN3-B).
    monkeypatch.setattr(manifest, "_columns", lambda model, include_exempt=False, include_boundary=False:
                        original(model, include_exempt=True, include_boundary=True))
    _advisor, _approver, mid, _aid, _run, decision = _published(session_factory, "kn-leg")
    monkeypatch.setattr(manifest, "_columns", original)
    assert _status(session_factory, mid, decision.envelope_id) == (("SEALED", "FRESH"), "PUBLISHED", None)
    # Die alte Bindung umfasste den Beruf: eine Aenderung entwertet diesen Bestand.
    _mutate(session_factory, mid, profession="Architektin (fiktiv)")
    _env, status, code = _status(session_factory, mid, decision.envelope_id)
    assert status == "PUBLICATION_INVALID" and code == "CCX_INPUT_STALE"
