"""Roadmap #74: Contract-Test fuer den Dark-Mode-Toggle im Frontend-Monolith.

CI-Variablen (var(--...)) waren laut CTO-Bericht bereits vorhanden -- dieser
Test haerte NUR den fehlenden Teil ab: den Theme-Switch selbst (Umschalt-
Funktion, dunkles Variablen-Set, localStorage-Persistenz) sowie den
FOUC-Schutz beim Start. Muster: test_cashflow_type_correction_contract.py
(String-Kontrakt-Checks direkt gegen den HTML-Monolithen).
"""
from pathlib import Path

FRONTEND = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND.read_text(encoding="utf-8")


def test_theme_toggle_function_exists_and_flips_dataset_theme():
    html = _html()

    assert "function toggleTheme()" in html
    assert "function applyTheme(theme,persist)" in html
    assert "document.documentElement.dataset.theme=t;" in html
    assert "getCurrentTheme()==='dark'?'light':'dark'" in html


def test_theme_toggle_button_is_wired_in_topbar():
    html = _html()

    assert 'id="btn-theme-toggle"' in html
    assert 'onclick="toggleTheme()"' in html
    assert "function updateThemeToggleIcon()" in html


def _dark_theme_block(html: str) -> str:
    """Isolate the :root[data-theme="dark"]{...} declaration block only
    (up to its first closing brace) so assertions don't accidentally spill
    into unrelated CSS rules that follow it in the minified stylesheet."""
    start = html.index(':root[data-theme="dark"]')
    open_brace = html.index("{", start)
    close_brace = html.index("}", open_brace)
    return html[start : close_brace + 1]


def test_dark_theme_css_variable_block_exists():
    html = _html()

    assert ':root[data-theme="dark"]' in html

    dark_block = _dark_theme_block(html)

    # Gleiche Systematik wie das Basis-:root (n0-n9 Neutrals, g0-g5 Gold-
    # Akzente, pos/neg/warn Signalfarben) muss im Dark-Block wieder auftauchen.
    for token in (
        "--n9:", "--n8:", "--n7:", "--n6:", "--n5:",
        "--n4:", "--n3:", "--n2:", "--n1:", "--n0:",
        "--g5:", "--g4:", "--g3:", "--g1:", "--g0:",
        "--pos:", "--pos-lt:", "--neg:", "--neg-lt:", "--warn:", "--warn-lt:",
        "--surface:", "--bg:", "--bg2:", "--b1:", "--b2:",
    ):
        assert token in dark_block, f"{token} fehlt im dark-Theme-Block"


def test_chrome_tokens_preserve_navy_gold_identity_across_themes():
    html = _html()

    # Topbar/Sidebar/Primary-Buttons/Badges sind Vollflaechen mit hartkodiertem
    # weissem Text -- die duerfen sich beim Theme-Wechsel NICHT umfaerben,
    # sonst waere z.B. die Topbar hell mit unsichtbarem weissem Text.
    assert "--chrome-n6:" in html
    assert "--chrome-n7:" in html
    assert "--chrome-n8:" in html
    assert ".topbar{height:48px;background:var(--chrome-n8);" in html
    assert ".sidebar{width:188px;min-width:188px;background:var(--chrome-n7);" in html

    dark_block = _dark_theme_block(html)
    # Die Chrome-Tokens werden bewusst NICHT im Dark-Block ueberschrieben.
    assert "--chrome-n6" not in dark_block
    assert "--chrome-n7" not in dark_block
    assert "--chrome-n8" not in dark_block


def test_theme_preference_persisted_in_local_storage():
    html = _html()

    assert "THEME_STORAGE_KEY='5eyes_theme'" in html
    assert "localStorage.getItem(THEME_STORAGE_KEY)" in html
    assert "localStorage.setItem(THEME_STORAGE_KEY,theme)" in html
    # FOUC-Schutz: frueher Inline-Read direkt am Anfang von <body>, noch vor
    # dem restlichen App-Skript, mit demselben Storage-Key.
    body_start = html.index("<body>")
    early_slice = html[body_start : body_start + 800]
    assert "localStorage.getItem('5eyes_theme')" in early_slice
    assert "document.documentElement.dataset.theme=v;" in early_slice


def test_theme_icon_sync_wired_into_app_init():
    html = _html()

    init_app_start = html.index("async function initApp() {")
    init_app_slice = html[init_app_start : init_app_start + 400]
    assert "updateThemeToggleIcon();" in init_app_slice


def test_chart_colors_read_from_theme_aware_css_variables():
    html = _html()

    assert "--chart-axis:" in html
    assert "--chart-grid:" in html
    assert "function chartAxisColor()" in html
    assert "function chartGridColor()" in html
    assert "function refreshThemedChartColors()" in html
    # Keine hartkodierten Achsfarben mehr an den bekannten Chart.js-Stellen.
    assert "color:'#7a8299'" not in html
