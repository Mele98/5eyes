"""G7 -- jede Rundungs-/Formatierstelle (Codex-Inventar 2026-11-11) ist klassifiziert.

Das Inventar ``scripts/inventory_2026_11_11_rounding_sites.py`` ist eine
unveraenderte Kopie des Codex-Sweeps (SHA-256 unten gepinnt). Die Klassifikation
(``scripts/classify_rounding_sites.py`` + Einzelentscheide
``docs/audits/2026-11-11-g7-rounding-site-overrides.json``) ordnet jede Datei:Zeile
MIGRATE (done/open), COMPUTATION_KEEP oder FALSE_POSITIVE zu.

* Keine unklassifizierte Stelle (neue rohe Rundung -> rot).
* Keine offene Stelle (MIGRATE/open = 0, H-153 Nachtrag 1): jede Anzeige-Rundung
  laeuft ueber den gemeinsamen Formatter; rechnende Rundung ist COMPUTATION_KEEP
  mit Begruendung.
* In den G7-Kernpfaden (H6-Grafik, Legende, Infokarte, Portfolio, Kostenausweis,
  Anlagestrategie-PDF) gibt es keine offene Stelle.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import classify_rounding_sites as C  # noqa: E402

INVENTORY_SHA256 = "dde6e3237730301b72b2d9f29ac6d43682f2ff88a60c64273d4795378a5978a4"
MAX_OPEN = 0

CORE_FILES = (
    "ares-desktop/frontend/aa-chart.js",
    "ares-backend/services/pdf/components/saa_donut.py",
    "ares-backend/services/pdf/components/saa_bar_table.py",
    "ares-backend/services/pdf/components/kostenausweis.py",
    "ares-backend/services/pdf/components/swiss_numbers.py",
    "ares-backend/services/pdf/documents/anlagestrategie.py",
    "ares-backend/services/pdf/documents/asset_allocation.py",
    "ares-backend/services/pdf/documents/portfolio.py",
    "ares-desktop/frontend/reporting/src/lib/format.ts",
    "ares-desktop/frontend/reporting/src/pages/Kostenausweis.tsx",
)


def test_inventory_script_is_the_unchanged_codex_copy():
    digest = hashlib.sha256((SCRIPTS / "inventory_2026_11_11_rounding_sites.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert digest == INVENTORY_SHA256


def test_every_inventory_site_is_classified():
    result = C.classify(ROOT)
    unclassified = [(r["file"], r["line"], r["source"][:100]) for r in result["sites"] if r["class"] == "UNCLASSIFIED"]
    assert unclassified == [], unclassified[:10]
    assert {r["class"] for r in result["sites"]} <= {"MIGRATE", "COMPUTATION_KEEP", "FALSE_POSITIVE"}


def test_no_open_display_rounding_remains():
    result = C.classify(ROOT)
    open_rows = [(r["file"], r["line"]) for r in result["sites"] if r["class"] == "MIGRATE" and r["status"] != "done"]
    assert len(open_rows) == MAX_OPEN == 0, open_rows
    keep_without_reason = [(r["file"], r["line"]) for r in result["sites"] if r["class"] == "COMPUTATION_KEEP" and not r["reason"]]
    assert keep_without_reason == []


def test_core_customer_evidence_paths_have_no_open_site():
    result = C.classify(ROOT)
    bad = [(r["file"], r["line"]) for r in result["sites"]
           if r["file"] in CORE_FILES and r["class"] == "MIGRATE" and r["status"] == "open"]
    assert bad == []
