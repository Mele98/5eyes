"""Browser-Hosting (2026-06-10): Haupt-App (ares.html) via Backend ausliefern.

Gated via settings.serve_main_frontend. Diese Tests sichern das SAFE-BY-DEFAULT-
Verhalten: standardmaessig AUS, damit Tier-1/Electron die Haupt-App NICHT
oeffentlich serviert. Der Positiv-Pfad (Flag an -> GET /app/ares.html == 200,
+ vendor/chart.min.js + /app-Redirect) wurde manuell via curl gegen ein
Test-Backend verifiziert (siehe PR); ein importlib.reload-Test wuerde in der
~3800-Test-Suite Flakiness riskieren.
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from config import Settings  # noqa: E402
import main  # noqa: E402


def test_serve_main_frontend_defaults_false():
    """Safe-by-default: Tier-1/Electron serviert die Haupt-App nicht oeffentlich."""
    assert Settings().serve_main_frontend is False


def test_main_frontend_not_served_when_disabled():
    """Bei deaktiviertem Flag (Default) ist /app/ares.html nicht gemountet."""
    client = TestClient(main.app)
    assert client.get("/app/ares.html").status_code == 404
