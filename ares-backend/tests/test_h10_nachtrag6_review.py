"""H10 Nachtrag 6: Delta-Pruefung 0465a1ed (Dok. 86 ab Z. 11535).

N-899-17 Banner-Text je Fall ("Nach dem Update" nur bei Wechsel der
Manifest-Version, geaenderte Angaben/Ziele, fehlende Freigabe, fehlende
Angaben) mit korrekter Einzahl/Mehrzahl und Knopf je Fall ("Jetzt freigeben"
bzw. "Angaben ergaenzen" mit Ziel-Feld). N-899-18 Ausfuehrungs-Scan mit
Alias-Importen und nicht-literalem Programm (Mutationstests). Playwright fuer
"Angaben ergaenzen": tests/test_e2e_h10_egress_banner_playwright.py.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from services import dsg_governance as gov
from services import egress_manifest as em
from tests.h10_exec_scan import scan_source, scan_tree
from tests.h10_support import api
from tests.test_h10_nachtrag5_review import EXEC_EXCEPTIONS

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


# ── N-899-17 Grammatik ────────────────────────────────────────────────────────

@pytest.mark.parametrize(("labels", "expected"), [
    (["E-Mail"], "E-Mail ist"),
    (["Marktdaten"], "Marktdaten sind"),
    (["Updates"], "Updates sind"),
    (["externe Datensicherung"], "externe Datensicherung ist"),
    (["Marktdaten", "Marktdaten"], "Marktdaten sind"),
    (["E-Mail", "Updates"], "E-Mail und Updates sind"),
    (["Marktdaten", "E-Mail", "Updates"], "Marktdaten, E-Mail und Updates sind"),
])
def test_subject_and_verb_agree(labels, expected):
    assert gov._plain_subject(labels) == expected


def _b(cid, cls, code, change=None, field=None, owner_block=None):
    return {"channel_id": cid, "class": cls, "reason_code": code, "change": change, "owner_field": field,
            "owner_block": owner_block}


def test_each_case_has_its_own_sentence():
    lines = gov.plain_summary([
        _b("market_data.stooq", "market_data", "EGRESS_HASH_MISMATCH", "manifest_update"),
        _b("mail.smtp", "mail", "EGRESS_HASH_MISMATCH", "changed"),
        _b("updates.desktop", "updates", "EGRESS_MANIFEST_MISSING", "unapproved"),
    ])
    assert lines == [
        "Nach dem Update muss die Datenübermittlung einmal neu freigegeben werden – Marktdaten sind bis dahin "
        "pausiert.",
        "Angaben zur Datenübermittlung wurden geändert – bitte einmal neu freigeben (E-Mail ist bis dahin "
        "pausiert).",
        "Die Datenübermittlung muss einmal freigegeben werden – Updates sind bis dahin pausiert.",
    ]


def test_owner_gap_also_reported_when_hash_is_stale():
    lines = gov.plain_summary([_b("mail.smtp", "mail", "EGRESS_HASH_MISMATCH", "changed",
                                  "egress.mail.smtp.guarantee", "EGRESS_GUARANTEE_MISSING")])
    assert "Für E-Mail fehlen noch Angaben (Land/Garantie des Anbieters)." in lines


def test_button_per_case():
    assert gov.banner_action([]) is None
    assert gov.banner_action([_b("x", "market_data", "EGRESS_MANIFEST_MISSING", "unapproved")]) == {
        "label": "Jetzt freigeben", "field": None}
    assert gov.banner_action([
        _b("x", "market_data", "EGRESS_MANIFEST_MISSING", "unapproved"),
        _b("mail.smtp", "mail", "EGRESS_GUARANTEE_MISSING", field="egress.mail.smtp.destination_country"),
    ]) == {"label": "Angaben ergänzen", "field": "egress.mail.smtp.destination_country"}


# ── N-899-17 echte Faelle ueber die API ───────────────────────────────────────

def _mail(monkeypatch):
    monkeypatch.setattr("config.settings.smtp_enabled", True)
    monkeypatch.setattr("config.settings.smtp_host", "smtp.a.example")


def _mail_values(client):
    for key in ("destination_country", "guarantee", "legal_basis"):
        assert client.put(f"/privacy/owner-fields/egress.mail.smtp.{key}",
                          json={"value": f"TESTWERT {key}"}).status_code == 200


def test_fresh_install_asks_for_first_approval(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        status = client.get("/privacy/egress-status").json()
    assert status["plain_summary"][0].startswith("Die Datenübermittlung muss einmal freigegeben werden – ")
    assert status["plain_summary"][0].endswith(" sind bis dahin pausiert.")
    assert status["action"] == {"label": "Jetzt freigeben", "field": None}


def test_changed_settings_are_not_called_an_update(tmp_path, monkeypatch):
    _mail(monkeypatch)
    with api(tmp_path) as (client, _current, _factory):
        _mail_values(client)
        client.post("/privacy/egress-manifest/approve", json={})
        assert client.get("/privacy/egress-status").json()["approved"] is True
        monkeypatch.setattr("config.settings.smtp_host", "smtp.b.example")
        status = client.get("/privacy/egress-status").json()
    assert status["plain_summary"] == [
        "Angaben zur Datenübermittlung wurden geändert – bitte einmal neu freigeben (E-Mail ist bis dahin "
        "pausiert)."]
    assert not any(line.startswith("Nach dem Update") for line in status["plain_summary"])
    assert status["action"]["label"] == "Jetzt freigeben"


def test_manifest_version_change_is_called_an_update(tmp_path, monkeypatch):
    with api(tmp_path) as (client, _current, _factory):
        client.post("/privacy/egress-manifest/approve", json={})
        assert client.get("/privacy/egress-status").json()["approved"] is True
        manifest = copy.deepcopy(em.load_manifest())
        manifest["manifest_version"] = manifest["manifest_version"] + "-neu"
        monkeypatch.setattr(em, "load_manifest", lambda path=None: manifest)
        status = client.get("/privacy/egress-status").json()
    assert status["plain_summary"][0].startswith(
        "Nach dem Update muss die Datenübermittlung einmal neu freigegeben werden – Marktdaten")
    assert status["plain_summary"][0].endswith(" sind bis dahin pausiert.")


def test_missing_owner_values_lead_to_the_field(tmp_path, monkeypatch):
    _mail(monkeypatch)
    with api(tmp_path) as (client, _current, _factory):
        client.post("/privacy/egress-manifest/approve", json={})
        status = client.get("/privacy/egress-status").json()
    assert status["plain_summary"] == ["Für E-Mail fehlen noch Angaben (Land/Garantie des Anbieters)."]
    assert status["action"] == {"label": "Angaben ergänzen", "field": "egress.mail.smtp.destination_country"}


# ── N-899-18 Ausfuehrungs-Scan (Mutationstests) ───────────────────────────────

@pytest.mark.parametrize(("source", "kind"), [
    ("from os import system\nsystem('ls')\n", "shell"),
    ("from os import system as s\ns('ls')\n", "shell"),
    ("from os import popen as p\np('ls')\n", "shell"),
    ("import os as o\no.system('ls')\n", "shell"),
    ("from subprocess import run as r\nr('ls', shell=True)\n", "shell"),
    ("from subprocess import getoutput\ngetoutput('ls')\n", "shell"),
    ("import subprocess as sp\nsp.Popen(['pwsh', '-c', 'x'])\n", "shell"),
    ("import asyncio\nasyncio.create_subprocess_shell('ls')\n", "shell"),
    ("import subprocess\nprog = 'curl'\nsubprocess.run([prog, 'x'])\n", "programm-variabel"),
    ("import subprocess as sp\nsp.check_output(cmd)\n", "programm-variabel"),
    ("from subprocess import Popen\nPopen(build_cmd())\n", "programm-variabel"),
    ("import subprocess\nsubprocess.run([f'{tool}', 'x'])\n", "programm-variabel"),
    ("import os\nos.posix_spawn(path, [path], {})\n", "programm-variabel"),
    ("import os\nos.execv(exe, [exe])\n", "programm-variabel"),
    ("import os\nos.spawnv(os.P_WAIT, exe, [exe])\n", "programm-variabel"),
    ("import asyncio\nasyncio.create_subprocess_exec(exe)\n", "programm-variabel"),
    ("import subprocess\nsubprocess.run(args=cmd)\n", "programm-variabel"),
])
def test_mutation_is_detected(source, kind):
    assert [f[2] for f in scan_source(source, "svc/x.py")] == [kind]


@pytest.mark.parametrize("source", [
    "import subprocess\nsubprocess.run(['git', 'status'])\n",
    "import subprocess\nsubprocess.run('git status')\n",
    "from subprocess import run\nrun(['rsync', '-a', 'x', 'y'], shell=False)\n",
    "def system(x):\n    return x\nsystem('ls')\n",  # eigene Funktion gleichen Namens
])
def test_literal_non_shell_calls_pass(source):
    assert scan_source(source, "svc/x.py") == []


def test_mutated_product_file_is_caught(tmp_path):
    """Eine zusaetzliche Ausfuehrung in einer bisher sauberen Funktion einer
    Produktdatei wird gemeldet und ist von keiner Ausnahme gedeckt."""
    source = (BACKEND / "services" / "backup.py").read_text(encoding="utf-8")
    mutated = source + "\n\ndef _mutant(prog):\n    from os import system as run_it\n    run_it(prog)\n"
    target = tmp_path / "ares-backend" / "services"
    target.mkdir(parents=True)
    (target / "backup.py").write_text(mutated, encoding="utf-8")
    findings = scan_tree(tmp_path / "ares-backend", tmp_path)
    new = [f for f in findings if f[0] not in EXEC_EXCEPTIONS]
    assert new == [("ares-backend/services/backup.py::_mutant", new[0][1], "shell")]


def test_exception_is_scoped_to_its_function(tmp_path):
    source = "import subprocess\n\ndef replicate_offsite(cmd):\n    subprocess.run(cmd)\n\n" \
             "def other(cmd):\n    subprocess.run(cmd)\n"
    keys = {f[0] for f in scan_source(source, "ares-backend/services/backup.py")}
    assert keys == {"ares-backend/services/backup.py::replicate_offsite", "ares-backend/services/backup.py::other"}
    assert "ares-backend/services/backup.py::other" not in EXEC_EXCEPTIONS
