"""Roadmap #76 (Admin-Menue-Redesign, 2026-07-23): Contract-Test fuer die
Kategorie-Gruppierung der System-Administration-Sektionen im Admin-Modal.

Ziel: keine Sektion geht bei der Reorganisation versehentlich verloren, und
jede Sektion ist genau einer sinnvollen Ober-Kategorie (data-admin-category)
zugeordnet. adminShowSection() bleibt id-basiert und unveraendert -- dieser
Test prueft nur die HTML-Struktur/Navigation, keine Fachlogik.

2026-07-29 (Laender-Skalierung): 18. Sektion "Fonds-Universum"
(sec-product-universe) unter der bestehenden Kategorie "daten" ergaenzt.
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)

# Die 17 System-Administration-Sektionen (sec-* Panel-IDs) und ihr jeweiliger
# Nav-Button (asec-*). Reihenfolge ist irrelevant fuer die Zuordnung, nur die
# Menge muss vollstaendig sein.
EXPECTED_SECTIONS = {
    "sec-health": "asec-health",
    "sec-shadow-comparison-aggregate": "asec-shadow-comparison-aggregate",
    "sec-audit": "asec-audit",
    "sec-markt": "asec-markt",
    "sec-market-data": "asec-market-data",
    "sec-override": "asec-override",
    "sec-returns": "asec-returns",
    "sec-acprices": "asec-acprices",
    "sec-product-universe": "asec-product-universe",
    "sec-cma": "asec-cma",
    "sec-cma-rv": "asec-cma-rv",
    "sec-cma-inf": "asec-cma-inf",
    "sec-cma-sub": "asec-cma-sub",
    "sec-policy": "asec-policy",
    "sec-users": "asec-users",
    "sec-newuser": "asec-newuser",
    "sec-db": "asec-db",
    "sec-update": "asec-update",
}

# Erwartete Kategorie je Nav-Button nach der Reorganisation. Compliance fasst
# Shadow-Aggregat (speist das Compliance-Template) und Protokoll (Audit-Trail)
# zusammen -- vorher zwei isolierte Ein-Punkt-Gruppen ("Status"/"Audit").
EXPECTED_CATEGORY_BY_BUTTON = {
    "asec-health": "dashboard",
    "asec-shadow-comparison-aggregate": "compliance",
    "asec-audit": "compliance",
    "asec-markt": "daten",
    "asec-market-data": "daten",
    "asec-override": "daten",
    "asec-returns": "daten",
    "asec-acprices": "daten",
    "asec-product-universe": "daten",
    "asec-cma": "annahmen",
    "asec-cma-rv": "annahmen",
    "asec-cma-inf": "annahmen",
    "asec-cma-sub": "annahmen",
    "asec-policy": "annahmen",
    "asec-users": "zugriff",
    "asec-newuser": "zugriff",
    "asec-db": "wartung",
    "asec-update": "wartung",
}

EXPECTED_CATEGORY_LABELS = {
    "dashboard": "Dashboard",
    "compliance": "Compliance",
    # Labels wie im HTML kodiert (&amp; statt &) -- der Regex liest die
    # Rohdaten, nicht das gerenderte DOM.
    "daten": "Daten &amp; Marktdaten",
    "annahmen": "Kapitalmarkt-Annahmen",
    "zugriff": "Benutzer &amp; Zugriff",
    "wartung": "Wartung &amp; Betrieb",
}


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def _admin_sidebar_block(html: str) -> str:
    start = html.index('<div class="admin-sidebar">')
    end = html.index("<!-- ─── CONTENT ─── -->", start)
    assert end > start
    return html[start:end]


def test_all_18_sections_still_present():
    html = _html()
    for sec_id, asec_id in EXPECTED_SECTIONS.items():
        assert f'id="{sec_id}"' in html, f"Sektion {sec_id} fehlt im Admin-Panel"
        assert f'id="{asec_id}"' in html, f"Nav-Button {asec_id} fehlt im Admin-Sidebar"
        assert f"adminShowSection('{sec_id}')" in html, (
            f"Nav-Button {asec_id} ist nicht mehr an adminShowSection('{sec_id}') gebunden"
        )
    assert len(EXPECTED_SECTIONS) == 18


def test_every_nav_button_has_exactly_one_category():
    sidebar = _admin_sidebar_block(_html())
    button_pattern = re.compile(
        r'<button\s+id="(asec-[\w-]+)"[^>]*data-admin-category="([\w-]+)"',
        re.DOTALL,
    )
    found = dict(button_pattern.findall(sidebar))
    assert found == EXPECTED_CATEGORY_BY_BUTTON, (
        "Kategorie-Zuordnung der Nav-Buttons hat sich veraendert (Sektion "
        "verloren, verschoben oder ohne data-admin-category zurueckgeblieben)."
    )


def test_category_labels_present_and_grounded_in_real_sections():
    sidebar = _admin_sidebar_block(_html())
    label_pattern = re.compile(
        r'<div class="admin-nav-label" data-admin-category="([\w-]+)">([^<]+)</div>'
    )
    labels = dict(label_pattern.findall(sidebar))
    assert set(labels) == set(EXPECTED_CATEGORY_LABELS), (
        "Kategorie-Liste im Sidebar-Header stimmt nicht mit der erwarteten "
        "Ober-Kategorie-Struktur ueberein."
    )
    for key, expected_label in EXPECTED_CATEGORY_LABELS.items():
        assert labels[key] == expected_label

    # Jede Kategorie muss mindestens einen der 17 realen Nav-Buttons enthalten
    # -- keine erfundene Kategorie ohne Inhalt.
    used_categories = set(EXPECTED_CATEGORY_BY_BUTTON.values())
    assert used_categories == set(EXPECTED_CATEGORY_LABELS)


def test_no_orphan_admin_sec_btn_without_category():
    sidebar = _admin_sidebar_block(_html())
    all_buttons = re.findall(r'<button\s+id="(asec-[\w-]+)"', sidebar)
    assert len(all_buttons) == 18
    assert set(all_buttons) == set(EXPECTED_CATEGORY_BY_BUTTON)
