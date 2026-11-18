"""H10 Nachtrag 5: Delta-Pruefung 9d9d56ee (Dok. 86 ab Z. 11165).

N-899-15 PowerShell-Aliase und .NET-Netzwerkklassen, cmd-Escape (^) und
PowerShell-Backtick, statischer Scan auf jeden Shell-Aufruf im Produktcode
(nur mit begruendeter Ausnahme). N-899-16 Banner in Alltagssprache (Status
liefert Klartext; technische Angaben nur in der Detailansicht; Playwright in
der echten App: tests/test_e2e_h10_egress_banner_playwright.py).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services import dsg_governance as gov
from services import egress_manifest as em
from tests.h10_exec_scan import scan_tree
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


# N-899-15/-18: Shell-Aufrufe und Ausfuehrungen mit nicht-literalem Programm
# im Produktcode nur mit begruendeter Ausnahme (Schluessel pfad::funktion).
EXEC_EXCEPTIONS: dict[str, str] = {
    "ares-backend/services/backup.py::replicate_offsite":
        "Programm fest 'rsync' (Liste in derselben Funktion); Ziel und Kanal prueft der Laufzeitschutz "
        "(operator.backup_offsite).",
    "scripts/packaging_smoke.py::run_restart_smoke":
        "CI/Release-Werkzeug: startet die eben gebaute Backend-EXE (Pfad aus dem Build), kein Produktlauf.",
    "scripts/packaging_smoke.py::run_start_smoke":
        "CI/Release-Werkzeug: startet die eben gebaute Backend-EXE (Pfad aus dem Build), kein Produktlauf.",
    "scripts/pytest_supervisor.py::run":
        "CI-Werkzeug: fuehrt die uebergebene Test-Kommandozeile ohne Shell aus, kein Produktlauf.",
    "scripts/security_gate.py::_run_data_integrity_audit_smoke":
        "CI-Werkzeug: sys.executable mit festem Repo-Skript, kein Produktlauf.",
    "scripts/security_gate.py::main":
        "CI-Werkzeug: sys.executable -m pytest, kein Produktlauf.",
}


def _product_exec_findings():
    return [f for root in (BACKEND, REPO / "scripts") if root.exists() for f in scan_tree(root, REPO)]


def test_every_shell_call_in_product_code_needs_a_justified_exception():
    findings = _product_exec_findings()
    assert [f for f in findings if f[0] not in EXEC_EXCEPTIONS] == []
    assert not [f for f in findings if f[2] == "shell"]  # Shell-Aufrufe: derzeit keine, auch nicht als Ausnahme
    assert all(reason.strip() for reason in EXEC_EXCEPTIONS.values())
    assert set(EXEC_EXCEPTIONS) <= {f[0] for f in findings}, "veraltete Ausnahme"


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
    assert [f[2] for f in scan_tree(tmp_path)] == ["shell"] * 7


# ── N-899-16 Klartext ─────────────────────────────────────────────────────────

def _blocked(cid, cls, code, change=None):
    return {"channel_id": cid, "class": cls, "reason_code": code, "change": change}


def test_plain_summary_after_update_and_owner_gaps():
    lines = gov.plain_summary([
        _blocked("market_data.stooq", "market_data", "EGRESS_HASH_MISMATCH", "manifest_update"),
        _blocked("market_data.yfinance", "market_data", "EGRESS_HASH_MISMATCH", "manifest_update"),
        _blocked("mail.smtp", "mail", "EGRESS_HASH_MISMATCH", "manifest_update"),
        _blocked("updates.desktop", "updates", "EGRESS_HASH_MISMATCH", "manifest_update"),
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
    assert gov.plain_summary([_blocked("mail.smtp", "mail", "EGRESS_MANIFEST_MISSING", "unapproved")]) == [
        "Die Datenübermittlung muss einmal freigegeben werden – E-Mail ist bis dahin pausiert."]


def test_status_carries_plain_summary_and_advisor_hint(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        status = client.get("/privacy/egress-status").json()
    assert status["plain_summary"] and status["plain_summary"][0].startswith(
        "Die Datenübermittlung muss einmal freigegeben werden – Marktdaten")
    assert status["advisor_hint"] == "Bitte Administrator informieren."
    assert all("EGRESS_" not in line for line in status["plain_summary"])
