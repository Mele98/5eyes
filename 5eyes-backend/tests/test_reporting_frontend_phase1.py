"""Static contracts for U-P23 PR C reporting navigation."""
from __future__ import annotations

import re
from pathlib import Path

REPORTING_ROOT = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "reporting"
)
SRC = REPORTING_ROOT / "src"


def _read(relative: str) -> str:
    path = SRC / relative
    assert path.exists(), f"Erwartete Datei fehlt: src/{relative}"
    return path.read_text(encoding="utf-8")


def test_phase1_pages_and_sidebar_exist():
    for relative in (
        "pages/Disclaimer.tsx",
        "pages/Inhaltsverzeichnis.tsx",
        "components/Sidebar.tsx",
    ):
        assert (SRC / relative).exists(), f"Datei fehlt: src/{relative}"


def test_disclaimer_page_renders_all_hinweise():
    content = _read("pages/Disclaimer.tsx")
    assert "data-testid=\"report-page-disclaimer\"" in content
    assert "data.hinweise.map" in content
    assert "Rechtliche Hinweise" in content


def test_inhaltsverzeichnis_page_renders_backend_chapters():
    content = _read("pages/Inhaltsverzeichnis.tsx")
    assert "data-testid=\"report-page-toc\"" in content
    assert "data.kapitel.map" in content
    assert "Inhaltsverzeichnis" in content


def test_sidebar_lists_all_17_sections_and_active_state():
    content = _read("components/Sidebar.tsx")
    assert "data-testid=\"report-sidebar\"" in content
    # Sektionen 1-16 = Standard-Report. Sektion 17 = Compliance-Audit
    # (Sub-App-Aggregation der Backend-Sektionen 19-23). Sektion 18 =
    # Eignung (SuitabilityCheck per Mandat, Sprint U-FINMA-3, re-arch
    # 2026-06-09).
    assert content.count("id: '") == 18
    for title in (
        "Titelblatt",
        "Disclaimer",
        "Inhaltsverzeichnis",
        "Ausgangslage",
        "Positionen",
        "Asset Allocation",
        "Risikowährungen",
        "Weiteres Vorgehen",
        "Beratungsprotokoll",
    ):
        assert title in content
    assert "activeSection" in content


def test_app_declares_phase1_routes_and_placeholders():
    content = _read("App.tsx")
    assert "path=\"/mandates/:mandateId/report\"" in content
    assert "path=\"/mandates/:mandateId/report/cover\"" in content
    assert "SECTION_ROUTES.filter" in content
    assert "sectionId === 'disclaimer'" in content
    assert "sectionId === 'toc'" in content
    assert "PendingSection" in content


def test_no_forbidden_customer_facing_phrases():
    combined = "\n".join(
        _read(relative)
        for relative in (
            "App.tsx",
            "pages/Disclaimer.tsx",
            "pages/Inhaltsverzeichnis.tsx",
            "components/Sidebar.tsx",
        )
    ).lower()
    assert "garantiert" not in combined
    assert "erhöhen sie ihr risiko" not in combined


def test_no_third_party_brands_in_phase1_frontend():
    combined = "\n".join(
        _read(relative)
        for relative in (
            "App.tsx",
            "pages/Disclaimer.tsx",
            "pages/Inhaltsverzeichnis.tsx",
            "components/Sidebar.tsx",
        )
    ).lower()
    forbidden = (
        "ubs", "pictet", "julius bär", "julius baer",
        "swiss life", "3eyes", "ppc metrics",
    )
    for brand in forbidden:
        assert brand not in combined, f"Verbotene Marke '{brand}' gefunden"


def test_sidebar_has_stable_section_numbers():
    content = _read("components/Sidebar.tsx")
    numbers = [int(value) for value in re.findall(r"nr: (\d+)", content)]
    # Sektion 17 = Compliance-Audit (Sub-App-Aggregation der
    # Backend-Sektionen 19-23, siehe PR #163 + #165). Sektion 18 =
    # Eignung (SuitabilityCheck per Mandat, Sprint U-FINMA-3).
    assert numbers == list(range(1, 19))
