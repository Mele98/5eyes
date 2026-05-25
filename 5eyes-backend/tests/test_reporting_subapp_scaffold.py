"""Sprint U-P22.1 — Statische Contract-Tests für das React-Sub-App-Scaffold.

Prüft, dass die Setup-Dateien der Reporting-Sub-App existieren und die
zugesicherten Eigenschaften haben (Schema, Dependencies, Design-Tokens,
Branding-Compliance). Läuft komplett ohne `npm install` — wir validieren
nur Dateien auf der Disk.

Analog zum bestehenden Pattern `test_frontend_admin_market_data_panel.py`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPORTING_ROOT = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "reporting"
)


def _read(relative: str) -> str:
    """Liest eine Datei aus dem reporting/-Verzeichnis als Text."""
    path = REPORTING_ROOT / relative
    assert path.exists(), f"Erwartete Scaffold-Datei fehlt: {relative}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Dateistruktur — alle erwarteten Setup-Files vorhanden
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", [
    "package.json",
    "vite.config.ts",
    "tailwind.config.ts",
    "postcss.config.cjs",
    "tsconfig.json",
    "tsconfig.node.json",
    "index.html",
    ".gitignore",
    "README.md",
    "src/main.tsx",
    "src/App.tsx",
    "src/design/tokens.ts",
    "src/styles/globals.css",
])
def test_scaffold_file_exists(relative: str):
    """Jede Setup-Datei muss existieren."""
    assert (REPORTING_ROOT / relative).exists(), (
        f"Scaffold-Datei fehlt: {relative}"
    )


# ---------------------------------------------------------------------------
# 2. package.json — valid JSON + Pflicht-Dependencies
# ---------------------------------------------------------------------------

def test_package_json_is_valid_and_declares_required_dependencies():
    pkg = json.loads(_read("package.json"))
    assert pkg["name"] == "5eyes-reporting"
    assert pkg["type"] == "module"
    # Pflicht-Dependencies aus User-Spec
    deps = pkg.get("dependencies") or {}
    for required in ("react", "react-dom", "react-router-dom",
                     "recharts", "framer-motion"):
        assert required in deps, (
            f"Dependency '{required}' fehlt in package.json"
        )
    # Pflicht-DevDependencies für Vite + Tailwind + TS
    dev = pkg.get("devDependencies") or {}
    for required in ("vite", "@vitejs/plugin-react", "tailwindcss",
                     "postcss", "autoprefixer", "typescript"):
        assert required in dev, (
            f"DevDependency '{required}' fehlt in package.json"
        )
    # Pflicht-Scripts
    scripts = pkg.get("scripts") or {}
    for required in ("dev", "build", "typecheck"):
        assert required in scripts, f"Script '{required}' fehlt"


# ---------------------------------------------------------------------------
# 3. tailwind.config.ts — Design-Tokens vollständig
# ---------------------------------------------------------------------------

def test_tailwind_config_declares_design_tokens():
    """Alle Color-Familien aus der Spec müssen im Theme deklariert sein.
    Wir prüfen das statisch über String-Suche (kein TS-Compiler nötig)."""
    content = _read("tailwind.config.ts")
    required_color_families = [
        "canvas",   # Offwhite Hintergrund
        "ink",      # Dunkles Navy
        "accent",   # Petrol/Teal
        "rule",     # Linien
        "gold",     # Gold-Akzent
        "status",   # Ampel
    ]
    for family in required_color_families:
        assert f"{family}:" in content, (
            f"Color-Familie '{family}' fehlt im Tailwind-Theme"
        )
    # Status-Ampel braucht alle 4 Zustände (inkl. neutral für nicht_beurteilbar)
    for status in ("gruen", "gelb", "rot", "neutral"):
        assert status in content, (
            f"Status-Token '{status}' fehlt im Tailwind-Theme"
        )
    # Font-Families: serif + sans (Editorial-Look)
    assert "serif" in content
    assert "sans" in content
    # Editorial-Spacing
    assert "page-x" in content or "page-y" in content


# ---------------------------------------------------------------------------
# 4. tokens.ts — Chart-Palette + Synchronizität mit Tailwind
# ---------------------------------------------------------------------------

def test_tokens_ts_exports_chart_palette():
    content = _read("src/design/tokens.ts")
    assert "export const colors" in content
    assert "export const typography" in content
    assert "export const chartPalette" in content
    # Synchronizitäts-Check: Tailwind UND tokens.ts haben dieselben
    # Status-Farben (Drift = sofortiger Test-Fail)
    tailwind = _read("tailwind.config.ts")
    for hex_color in ("#FAFAF6", "#0F1C2E", "#2C5F5F"):
        assert hex_color in tailwind, f"Tailwind missing {hex_color}"
        assert hex_color in content, f"tokens.ts missing {hex_color}"


# ---------------------------------------------------------------------------
# 5. App.tsx — Routing für Report-Pfad
# ---------------------------------------------------------------------------

def test_app_tsx_declares_report_route():
    content = _read("src/App.tsx")
    # React Router DOM Imports
    assert "react-router-dom" in content
    # Report-Route mit mandateId-Parameter
    assert "/mandates/:mandateId/report" in content


# ---------------------------------------------------------------------------
# 6. vite.config.ts — Backend-Proxy + Dist-Output
# ---------------------------------------------------------------------------

def test_vite_config_proxies_backend_endpoints():
    content = _read("vite.config.ts")
    assert "localhost:8000" in content, (
        "Backend-Proxy fehlt — Frontend kann API nicht erreichen"
    )
    assert "^/mandates/.*/advisory-report$" in content
    assert "/admin" in content
    assert "outDir" in content and "dist" in content


# ---------------------------------------------------------------------------
# 7. globals.css — Tailwind-Direktiven + Print-Layout
# ---------------------------------------------------------------------------

def test_globals_css_has_tailwind_directives_and_print_layer():
    content = _read("src/styles/globals.css")
    assert "@tailwind base" in content
    assert "@tailwind components" in content
    assert "@tailwind utilities" in content
    # Print-Layout-Block (Spec verlangt identische Bildschirm + Print)
    assert "@media print" in content


# ---------------------------------------------------------------------------
# 8. Branding-Compliance — keine Dritt-Marken im Scaffold
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", [
    "README.md",
    "index.html",
    "src/App.tsx",
    "src/main.tsx",
    "tailwind.config.ts",
    "src/design/tokens.ts",
])
def test_no_third_party_brands_in_scaffold(relative: str):
    """Memory-Regel: keine Dritt-Marken in Code/Texten — auch nicht im
    Scaffold-Boilerplate."""
    content = _read(relative).lower()
    forbidden = (
        "ubs", "pictet", "julius bär", "julius baer",
        "swiss life", "3eyes", "ppc metrics",
    )
    for brand in forbidden:
        assert brand not in content, (
            f"Verbotene Marke '{brand}' in {relative}"
        )


# ---------------------------------------------------------------------------
# 9. .gitignore — node_modules und dist sind ignoriert
# ---------------------------------------------------------------------------

def test_gitignore_covers_build_artifacts():
    content = _read(".gitignore")
    assert "node_modules" in content
    assert "dist" in content


# ---------------------------------------------------------------------------
# 10. README — Setup-Instruktionen für User
# ---------------------------------------------------------------------------

def test_readme_documents_setup_and_dev_commands():
    content = _read("README.md")
    # Setup-Befehle müssen drinstehen, damit User es überhaupt starten kann
    assert "npm install" in content
    assert "npm run dev" in content
    assert "npm run build" in content
    # Hinweis auf Backend-Endpoint, damit klar ist wo die Daten herkommen
    assert "/mandates/" in content and "advisory-report" in content


# ---------------------------------------------------------------------------
# 11. tsconfig.json — strict mode + JSX
# ---------------------------------------------------------------------------

def test_tsconfig_uses_strict_mode_and_react_jsx():
    # TS-JSON erlaubt Kommentare → robust parsen
    raw = _read("tsconfig.json")
    # Kommentare entfernen für JSON-Parse
    no_comments = re.sub(r'^\s*//.*$', '', raw, flags=re.MULTILINE)
    config = json.loads(no_comments)
    opts = config.get("compilerOptions") or {}
    assert opts.get("strict") is True
    assert opts.get("jsx") == "react-jsx"
    assert opts.get("moduleResolution") == "bundler"
