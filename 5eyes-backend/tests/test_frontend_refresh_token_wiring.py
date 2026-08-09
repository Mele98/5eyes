"""Refresh-Token-Rotation im Frontend (2026-08-09, Roadmap #28 Frontend-Teil).

Der Backend-Endpoint POST /auth/refresh existierte bereits seit 2026-08-07/08
(Roadmap #28), wurde vom Frontend aber nie aufgerufen -- jede Session starb
exakt bei access_token_expire_minutes (Default 8h) ohne stille Erneuerung.
Diese Tests pinnen per Quelltext-Assertion (konsistent mit den uebrigen
test_frontend_*-Tests, kein Node/DOM-Runtime im Testbaum):
1. Der Refresh-Token bekommt einen eigenen Speicherplatz (nicht denselben
   Slot wie der Access-Token).
2. API.fetch() versucht bei 401 ZUERST einen stillen Refresh + Retry, bevor
   es zum harten Logout-Fallback kommt.
3. Jede Stelle, die einen Access-Token aus einer TokenResponse speichert
   (Login, Invite-Accept, Bootstrap-Admin), speichert auch den mitgelieferten
   refresh_token. Logout und der harte 401-Fallback loeschen beide.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_refresh_token_storage_functions_exist_and_are_distinct_from_access_token():
    html = _html()
    assert "async setRefreshToken(t) {" in html
    assert "async getRefreshToken() {" in html
    assert "'5eyes_refresh_token'" in html
    # Eigener Slot, nicht wiederverwendeter Access-Token-Key.
    assert "sessionStorage.setItem('5eyes_refresh_token'" in html
    assert "sessionStorage.setItem('5eyes_token'" in html


def test_try_refresh_token_calls_auth_refresh_endpoint_directly():
    html = _html()
    start = html.index("async _tryRefreshToken()")
    end = html.index("\n  async fetch(path, options={})", start)
    body = html[start:end]
    assert "base + '/auth/refresh'" in body
    assert "refresh_token: rt" in body
    # Dedupliziert parallele 401s auf einen gemeinsamen In-Flight-Request.
    assert "this._refreshInFlight" in body


def test_fetch_attempts_silent_refresh_before_hard_logout_on_401():
    html = _html()
    start = html.index("if (res.status === 401 && token")
    end = html.index("if (!res.ok) {", start)
    body = html[start:end]
    assert "API._tryRefreshToken()" in body
    assert "_isRetryAfterRefresh: true" in body
    # Auth-Endpoints selbst duerfen keinen Refresh-Loop ausloesen.
    assert "!path.startsWith('/auth/refresh')" in body
    # Erst wenn der Refresh scheitert (oder es schon ein Retry war), wird
    # ausgeloggt -- UND beide Tokens werden dabei geloescht, nicht nur einer.
    assert "await API.setToken(null);" in body
    assert "await API.setRefreshToken(null);" in body


def test_every_access_token_issuing_flow_also_stores_refresh_token():
    html = _html()
    for anchor in (
        "const data = await API.post('/auth/login', loginPayload);",
        "var res=await API.post('/auth/invite/accept'",
        "const data = await API.post('/auth/bootstrap-admin', {",
    ):
        idx = html.index(anchor)
        window = html[idx:idx + 400]
        assert "setRefreshToken" in window, f"kein setRefreshToken() nach: {anchor!r}"


def test_logout_clears_both_tokens():
    html = _html()
    start = html.index("async function doLogout()")
    end = html.index("\n}", start)
    body = html[start:end]
    assert "await API.setToken(null);" in body
    assert "await API.setRefreshToken(null);" in body
