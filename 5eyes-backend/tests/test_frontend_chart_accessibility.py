"""Frontend: Barrierefreiheit Charts (Roadmap #105).

Chart.js zeichnet ausschliesslich auf <canvas> -- ohne zusaetzliche Attribute
ist der Inhalt fuer Screenreader-Nutzer unsichtbar. Dieser Contract-Test
stellt sicher, dass:

(a) die Haupt-Charts ein `role="img"` + aussagekraeftiges `aria-label` tragen
    (statisch im Markup ODER dynamisch per JS beim Chart-Rendering gesetzt),
(b) mindestens zwei der wichtigsten Charts (SOLL/IST-Vergleich,
    Asset-Allocation-Doughnut) einen versteckten (sr-only) Tabellen-Fallback
    mit <caption> besitzen, der die gleichen Daten als semantische Tabelle
    ausweist,
(c) die sr-only-Utility-Klasse tatsaechlich screenreader-sichtbar bleibt
    (kein `display:none`, das wird von Screenreadern ignoriert).
"""
from __future__ import annotations

import re
from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)

# Canvas-IDs der Chart.js-Charts, die inhaltlich Daten zeigen (Linien-/
# Doughnut-Charts). intro-world ist rein dekorativ (aria-hidden) und bewusst
# ausgenommen.
DATA_CHART_IDS = [
    "ch-sollist-soll",
    "ch-sollist-ist",
    "ch-ist",
    "ch-dn",
    "ch-opt",
    "ch-aa-current",
]

# Die wichtigsten Charts, die zusaetzlich einen sr-only Tabellen-Fallback
# brauchen: SOLL/IST-Vergleich (2 Charts) + Asset-Allocation-Doughnut.
TABLE_FALLBACK_IDS = ["ch-sollist-soll", "ch-sollist-ist", "ch-dn"]


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_html_file_exists():
    assert HTML_PATH.is_file(), f"Monolith nicht gefunden: {HTML_PATH}"


def test_data_charts_have_role_img_and_aria_label_in_markup():
    """Jeder Daten-Chart-Canvas hat statisch role="img" + aria-label im HTML.

    Dynamische Updates (siehe unten) verfeinern das Label spaeter mit echten
    Werten, aber ein sinnvoller Default muss schon im Markup stehen, damit
    ein Screenreader auch vor dem ersten JS-Render etwas Sinnvolles liest.
    """
    html = _html()
    for chart_id in DATA_CHART_IDS:
        pattern = re.compile(
            r'<canvas\s+id="' + re.escape(chart_id) + r'"[^>]*>',
        )
        match = pattern.search(html)
        assert match, f"Canvas #{chart_id} nicht gefunden"
        tag = match.group(0)
        assert 'role="img"' in tag, f"#{chart_id}: role=\"img\" fehlt"
        assert re.search(r'aria-label="[^"]{5,}"', tag), (
            f"#{chart_id}: aria-label fehlt oder ist leer"
        )


def test_decorative_canvas_stays_aria_hidden():
    html = _html()
    match = re.search(r'<canvas\s+id="intro-world"[^>]*>', html)
    assert match, "Dekorativer intro-world-Canvas nicht gefunden"
    assert 'aria-hidden="true"' in match.group(0)


def test_sr_only_utility_class_defined_and_not_display_none():
    html = _html()
    assert re.search(r"\.sr-only\s*\{[^}]*\}", html), "sr-only-Klasse fehlt"
    block = re.search(r"\.sr-only\s*\{([^}]*)\}", html).group(1)
    assert "display:none" not in block.replace(" ", ""), (
        "sr-only darf kein display:none verwenden -- das wird von "
        "Screenreadern ignoriert (Klausur: offscreen-clip statt display:none)"
    )
    # Off-screen-Clip-Technik erkennbar (Standardmuster fuer sr-only).
    compact = block.replace(" ", "")
    assert "absolute" in compact and ("clip:rect(" in compact or "clip-path:" in compact)


def test_table_fallbacks_present_with_caption_for_key_charts():
    html = _html()
    for chart_id in TABLE_FALLBACK_IDS:
        table_id = f"{chart_id}-table"
        table_pattern = re.compile(
            r'<table\s+id="' + re.escape(table_id) + r'"[^>]*class="[^"]*sr-only[^"]*"[^>]*>'
            r"(.*?)</table>",
            re.DOTALL,
        )
        match = table_pattern.search(html)
        assert match, f"sr-only Tabellen-Fallback #{table_id} fehlt oder ist nicht sr-only"
        table_body = match.group(1)
        assert "<caption>" in table_body, f"#{table_id}: <caption> fehlt"
        assert "<th" in table_body, f"#{table_id}: keine <th>-Spaltenkoepfe"


def test_donut_table_filled_dynamically_from_allocation_state():
    """Der Donut-Tabellen-Fallback wird beim Allokations-Sync mit echten
    Anteilen/Betraegen befuellt (nicht nur ein leeres Geruest im Markup)."""
    html = _html()
    block = html.split(
        "function syncAllocationDonutFromStrategyState(", 1
    )[1].split("\nlet charts=", 1)[0]
    assert "ch-dn-table" in block
    assert "ch-dn" in block
    assert "setAttribute('aria-label'" in block or 'setAttribute("aria-label"' in block


def test_sollist_tables_filled_dynamically_from_projection_data():
    """Der SOLL/IST-Vergleichs-Tabellen-Fallback wird beim Rendern der
    Vergleichs-Charts mit den Kurvendaten (Jahr x Szenario) befuellt."""
    html = _html()
    block = html.split("function _renderSollIstCompare(", 1)[1].split(
        "\nfunction closeSollIstCompare(", 1
    )[0]
    assert "ch-sollist-soll-table" in block
    assert "ch-sollist-ist-table" in block
    assert "ch-sollist-soll-thead" in block
    assert "ch-sollist-ist-thead" in block
