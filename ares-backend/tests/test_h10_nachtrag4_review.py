"""H10 Nachtrag 4: Delta-Pruefung 1b40bd02 (Dok. 86 ab Z. 10952).

N-899-10 Subprozess-Schutz fuer Shell-Kommandozeilen (shell=True, cmd /c,
PowerShell, os.system, posix_spawn) und statischer Scan auf
``sys.executable -c`` mit Netzwerk-Imports, N-899-11 UDP sendto/sendmsg,
N-899-12 Kundennamen (Produktbegriff nur mit Produktkontext, Kurznamen,
Doppelnamen), N-899-13 Update-Feed-URL im gepackten Build vom
Electron-Hauptprozess. N-899-14 (Test-Naht nur im Testmodus) pruefen die
Node-Tests in ares-desktop/tests/update-gate.test.js. Werte sind Testwerte.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import egress_manifest as em
from services import privacy_versions as pv
from tests.h10_support import all_channel_states, api

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


@pytest.fixture(autouse=True)
def _guard_off():
    yield
    em.deactivate()
    em.update_channel_states(None)


def _guard(**settings_values):
    em.activate(SimpleNamespace(**settings_values), channel_states=all_channel_states(em.load_manifest()))


# ── N-899-10 Shell-Kommandozeilen ─────────────────────────────────────────────

@pytest.mark.parametrize(("executable", "argv"), [
    ("/bin/sh", ["/bin/sh", "-c", "curl https://tracker.example/x"]),
    ("/bin/bash", ["/bin/bash", "-lc", "cd /tmp && wget https://tracker.example/x"]),
    (r"C:\WINDOWS\system32\cmd.exe", r'C:\WINDOWS\system32\cmd.exe /c "curl https://tracker.example/x"'),
    ("powershell.exe", ["powershell.exe", "-Command", "Invoke-WebRequest -Uri https://tracker.example/x"]),
    ("pwsh", ["pwsh", "-c", "Start-BitsTransfer https://tracker.example/x C:/t"]),
    ("/usr/bin/env", ["/usr/bin/env", "FOO=1", "rsync", "a", "x@tracker.example:/b"]),
    ("/usr/bin/xargs", ["/usr/bin/xargs", "scp"]),
])
def test_network_tool_inside_shell_command_is_blocked(executable, argv):
    _guard()
    with pytest.raises(em.EgressBlocked) as blocked:
        em.check_subprocess(executable, argv)
    # ungebundenes Werkzeug -> Ziel verweigert; rsync/scp (Offsite-Kanal) hier nicht konfiguriert
    assert blocked.value.reason_code in {"EGRESS_DESTINATION_DENIED", "EGRESS_CHANNEL_DISABLED"}


@pytest.mark.parametrize(("executable", "argv"), [
    ("/bin/sh", ["/bin/sh", "-c", "ls -la /tmp"]),
    ("git", ["git", "commit", "-m", "curl wget ssh"]),  # kein Shell-Aufruf: Text ist kein Kommando
    (r"C:\WINDOWS\system32\cmd.exe", r'C:\WINDOWS\system32\cmd.exe /c "dir C:\data"'),
])
def test_local_shell_commands_pass(executable, argv):
    _guard()
    em.check_subprocess(executable, argv)


def test_shell_true_and_os_system_go_through_the_audit_hook():
    _guard()
    with pytest.raises(em.EgressBlocked):
        subprocess.run("curl https://tracker.example/x", shell=True, check=False)
    with pytest.raises(em.EgressBlocked):
        os.system("wget https://tracker.example/x")


@pytest.mark.skipif(not hasattr(os, "posix_spawn"), reason="posix_spawn nur auf POSIX")
def test_posix_spawn_is_checked():
    _guard()
    with pytest.raises(em.EgressBlocked):
        os.posix_spawn("/usr/bin/curl", ["curl", "https://tracker.example/x"], dict(os.environ))


def test_offsite_rsync_through_a_shell_still_needs_the_channel():
    target = "backup@nas.firma-a.example:/srv/ares"
    _guard(backup_offsite_enabled=True, backup_offsite_target=target)
    em.check_subprocess("rsync", ["rsync", "-a", "/x", target])  # gebundener Kanal, freigegeben
    with pytest.raises(em.EgressBlocked) as blocked:
        em.check_subprocess("/bin/sh", ["/bin/sh", "-c", "rsync -a /x backup@fremd.example:/srv"])
    assert blocked.value.reason_code == "EGRESS_DESTINATION_DENIED"


_NETWORK_IMPORT = re.compile(
    r"\b(?:import|from)\s+(?:socket|ssl|urllib|http|requests|httpx|aiohttp|smtplib|ftplib|telnetlib|"
    r"yfinance|websocket|paramiko)\b")
_PYTHON_NAMES = re.compile(r"^(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?$", re.IGNORECASE)


def _is_python_executable(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "executable":
        return isinstance(node.value, ast.Name) and node.value.id == "sys"
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(
        _PYTHON_NAMES.match(Path(node.value).name))


def python_inline_offenders(root: Path) -> list[str]:
    """N-899-10: ``[sys.executable|python, "-c", code]`` im Produktivcode.
    Gemeldet wird Code mit Netzwerk-Import und Code, der nicht statisch
    lesbar ist (kein Literal)."""
    offenders = []
    skip = {"tests", "alembic", "migrations", "venv", ".venv", "node_modules"}
    for path in root.rglob("*.py"):
        if path.relative_to(root).parts[0] in skip:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 3:
                continue
            elts = node.elts
            for i in range(len(elts) - 2):
                if not (_is_python_executable(elts[i]) and isinstance(elts[i + 1], ast.Constant)
                        and elts[i + 1].value == "-c"):
                    continue
                code = elts[i + 2]
                where = f"{path.relative_to(root).as_posix()}:{node.lineno}"
                if not (isinstance(code, ast.Constant) and isinstance(code.value, str)):
                    offenders.append(f"{where} (Code nicht statisch lesbar)")
                elif _NETWORK_IMPORT.search(code.value):
                    offenders.append(f"{where} (Netzwerk-Import)")
    return offenders


def test_no_inline_python_with_network_imports_in_product_code():
    assert python_inline_offenders(BACKEND) == []


def test_inline_python_scan_finds_network_imports(tmp_path):
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "bad.py").write_text(
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-c', 'import urllib.request; urllib.request.urlopen(\"https://x\")'])\n"
        "subprocess.run(['python3', '-c', CODE])\n"
        "subprocess.run([sys.executable, '-c', 'print(1)'])\n", encoding="utf-8")
    found = python_inline_offenders(tmp_path)
    assert len(found) == 2 and "Netzwerk-Import" in found[0] and "nicht statisch" in found[1]


# ── N-899-11 UDP ──────────────────────────────────────────────────────────────

def test_udp_sendto_to_non_manifest_address_is_blocked():
    _guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(em.EgressBlocked) as blocked:
            sock.sendto(b"x", ("203.0.113.9", 53))
        assert blocked.value.reason_code == "EGRESS_DESTINATION_DENIED"
        with pytest.raises(em.EgressBlocked):  # Name statt Adresse: wie Namensaufloesung geprueft
            em.check_connect(("tracker.unlisted.invalid", 9))
        sock.sendto(b"x", ("127.0.0.1", 9))  # lokal erlaubt
    finally:
        sock.close()


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="sendmsg nicht verfuegbar")
def test_udp_sendmsg_to_non_manifest_address_is_blocked():
    _guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(em.EgressBlocked):
            sock.sendmsg([b"x"], [], 0, ("203.0.113.9", 53))
    finally:
        sock.close()


# ── N-899-12 Kundennamen ──────────────────────────────────────────────────────

@pytest.fixture
def names():
    em.activate(SimpleNamespace(eodhd_api_key="T"), channel_states=all_channel_states(em.load_manifest()),
                client_name_provider=lambda: [("Peter", "Gold"), ("Eva", "Baer"), ("Li", "Wu"),
                                              ("Hans", "Mueller-Meier"), ("Anna", "Roche")])


@pytest.mark.parametrize("term", [
    "Peter Gold", "Gold", "Eva Baer", "Baer", "Wu", "LiWu", "Li Wu", "Mueller-Meier", "Mueller", "Meier",
    "Müller", "MuellerMeier", "H. Mueller", "Roche",  # "Roche": bewusst gesperrt (Datenschutz vor Komfort)
])
def test_client_names_are_blocked(names, term):
    assert em._client_name_hit(term), term


@pytest.mark.parametrize("term", [
    "Gold ETF", "Julius Baer", "Swiss Gold Fund", "GOLD.SW Gold", "Gold CH0047533549", "Wu ETF", "Hans",
    "iShares Core SPI",
])
def test_product_context_and_first_names_pass(names, term):
    assert not em._client_name_hit(term), term


def test_blocked_search_explains_why(names):
    from tests.test_h10_c_dsg_03_egress_manifest import _raw_request

    with pytest.raises(em.EgressBlocked) as blocked:
        _raw_request("eodhd.com", "/api/search/Roche?api_token=T&fmt=json")
    assert blocked.value.reason_code == "EGRESS_CLIENT_NAME_DENIED"
    assert em.CLIENT_NAME_BLOCK_MESSAGE in str(blocked.value)
    assert "ISIN oder Ticker" in em.CLIENT_NAME_BLOCK_MESSAGE


# ── N-899-13 Feed-URL im gepackten Build ──────────────────────────────────────

def test_packaged_build_feed_url_comes_from_the_electron_main_process(tmp_path, monkeypatch):
    """Gepackter Zustand: kein ares-desktop/package.json im Pfad; die Feed-URL
    kommt nur als DESKTOP_UPDATE_FEED_URL vom Electron-Hauptprozess."""
    from services import dsg_governance

    packaged_root = tmp_path / "resources" / "backend"
    packaged_root.mkdir(parents=True)
    monkeypatch.setattr(pv.register_module, "REPO_ROOT", packaged_root)
    assert not (packaged_root / "ares-desktop" / "package.json").exists()
    channel = em.channel_by_id(em.load_manifest(), "updates.desktop")

    monkeypatch.setattr("config.settings.desktop_update_feed_url", "")
    assert pv.configured_hosts(channel) == [] and not dsg_governance._channel_configured(channel)

    monkeypatch.setattr("config.settings.desktop_update_feed_url", "https://updates.firma-a.example/ares")
    assert pv.configured_hosts(channel) == ["updates.firma-a.example"]
    assert dsg_governance._channel_configured(channel)
    first = pv.channel_contents({})["updates.desktop"]
    monkeypatch.setattr("config.settings.desktop_update_feed_url", "https://updates.firma-a.example/ares-beta")
    second = pv.channel_contents({})["updates.desktop"]
    assert first["configured_hosts"] == second["configured_hosts"]
    assert pv._content_hash(first) != pv._content_hash(second)  # auch ein Pfadwechsel verlangt neue Freigabe


def test_packaged_feed_url_change_blocks_until_reapproved(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.desktop_update_feed_url", "https://updates.firma-a.example/ares")
    with api(tmp_path) as (client, _current, _factory):
        status = client.get("/privacy/egress-status").json()
        assert any(c["channel_id"] == "updates.desktop" for c in status["blocked_channels"])
        assert client.post("/privacy/egress-manifest/approve", json={"keys": ["updates.desktop"]}).status_code == 200
        status = client.get("/privacy/egress-status").json()
        assert "updates.desktop" in status["approved_channels"]
        monkeypatch.setattr("config.settings.desktop_update_feed_url", "https://updates.firma-b.example/ares")
        status = client.get("/privacy/egress-status").json()
        assert "updates.desktop" not in status["approved_channels"]
        blocked = [c for c in status["blocked_channels"] if c["channel_id"] == "updates.desktop"]
        assert blocked and blocked[0]["reason_code"] == "EGRESS_HASH_MISMATCH"


def test_backend_does_not_read_the_desktop_package_json():
    source = (BACKEND / "services" / "privacy_versions.py").read_text(encoding="utf-8")
    assert "ares-desktop" not in source and "DESKTOP_PACKAGE_JSON" not in source


def test_desktop_update_gate_node_suite():
    if shutil.which("node") is None:
        pytest.skip("node fehlt")
    out = subprocess.run(["node", "--test", "tests/update-gate.test.js", "tests/update-egress-gate.test.js"],
                         cwd=str(REPO / "ares-desktop"), capture_output=True, text=True, encoding="utf-8",
                         timeout=120)
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-1000:]
