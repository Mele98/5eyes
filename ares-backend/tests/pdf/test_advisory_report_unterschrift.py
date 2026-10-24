"""Sprint U-93 (2026-06-06): Tests fuer Unterschrift-Block am Advisory-Report Ende."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

ADVISORY_REPORT_PY = BACKEND_ROOT / "services" / "pdf" / "documents" / "advisory_report.py"


def _read_source() -> str:
    return ADVISORY_REPORT_PY.read_text(encoding="utf-8")


def test_unterschrift_imports_present():
    """Sicherstellen dass Import + Aufruf in advisory_report.py konstant bleibt."""
    src = _read_source()
    assert "from services.pdf.components.unterschrift import make_unterschrift_section" in src
    assert "make_unterschrift_section()" in src


def test_unterschrift_called_after_compliance_audit():
    """Source-Parse: make_unterschrift_section() muss NACH
    render_compliance_audit_section auftauchen (= letzte Sektion)."""
    src = _read_source()
    compliance_idx = src.rfind("render_compliance_audit_section(payload")
    unterschrift_idx = src.rfind("make_unterschrift_section()")
    assert compliance_idx > 0, "render_compliance_audit_section call nicht gefunden"
    assert unterschrift_idx > 0, "make_unterschrift_section call nicht gefunden"
    assert unterschrift_idx > compliance_idx, (
        "make_unterschrift_section() muss NACH render_compliance_audit_section "
        f"kommen (compliance@{compliance_idx}, unterschrift@{unterschrift_idx})"
    )


def test_unterschrift_has_pagebreak_before():
    """Vor dem Signatur-Block muss ein PageBreak stehen damit Unterschrift
    auf eigener Seite landet (PDF-Druck-Disziplin)."""
    src = _read_source()
    unterschrift_idx = src.find("make_unterschrift_section()")
    assert unterschrift_idx > 0
    # Suche letzten PageBreak vor make_unterschrift_section()
    before = src[:unterschrift_idx]
    last_pagebreak = before.rfind("PageBreak()")
    assert last_pagebreak > 0
    # Zwischen PageBreak und Unterschrift darf nicht mehr als ein
    # paar Statements liegen
    gap = src[last_pagebreak:unterschrift_idx]
    lines_in_gap = gap.count("\n")
    assert lines_in_gap < 10, (
        f"PageBreak und make_unterschrift_section duerfen nicht so weit "
        f"auseinander stehen (Gap={lines_in_gap} Zeilen)"
    )


def test_unterschrift_referenced_in_sprint_u93_comment():
    """U-93-Marker im Source — verhindert silent-removal beim Refactor."""
    src = _read_source()
    assert "U-93" in src
    assert "Signatur-Block" in src or "Unterschrift" in src
