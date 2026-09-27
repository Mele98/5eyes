"""RESTORE-DRILL-NEVER-PERFORMED-001 (Kontrollrunde 2026-09-27).

docs/deploy/disaster-recovery-plan.md Abschnitt 5 verlangt einen mindestens
quartalsweisen Restore-Drill -- die Protokoll-Tabelle war seit Erstellung
des Plans (2026-06-15) leer. scripts/restore_drill.py macht daraus einen
wiederholbaren Befehl statt einer einmaligen manuellen Uebung.

Diese Tests fuehren den ECHTEN Backup->Verlust->Restore-Zyklus des Scripts
aus (kein Mock der Kernfunktionen) -- nur der Sandbox-Charakter (immer ein
frisches tempfile.mkdtemp()-Verzeichnis, nie settings.db_path/backup_dir)
macht das gefahrlos wiederholbar in der Test-Suite.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

SCRIPT_PATH = BACKEND_ROOT / "scripts" / "restore_drill.py"


def _load_drill_module():
    spec = importlib.util.spec_from_file_location("restore_drill", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_script_file_exists():
    assert SCRIPT_PATH.is_file(), f"Restore-Drill-Skript fehlt: {SCRIPT_PATH}"


def test_full_drill_succeeds_and_cleans_up(monkeypatch, capsys):
    drill = _load_drill_module()
    monkeypatch.setattr(sys, "argv", ["restore_drill.py"])

    exit_code = drill.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "RESTORE-DRILL-BEFUND" in captured.out
    assert "Status:              OK -- keine Abweichungen" in captured.out
    assert "Datenerhalt:         Marker-Zeile intakt" in captured.out
    assert "Fertige Tabellenzeile" in captured.out


def test_drill_never_touches_real_settings_paths(monkeypatch):
    """Sicherheitsnetz: der Drill darf niemals settings.db_path oder
    settings.backup_dir lesen -- ein Tippfehler hier wuerde sonst gegen
    echte Kunden-/Mandantendaten laufen statt gegen eine Sandbox.

    Strukturelle Pruefung statt Text-Grep auf die Docstring-Prosa (die
    settings.db_path/backup_dir bewusst ERWAEHNT, um zu erklaeren was NICHT
    passiert): das Skript darf `config.settings` gar nicht erst importieren
    -- dann kann es diese Pfade auch nicht versehentlich lesen.
    """
    drill = _load_drill_module()

    assert not hasattr(drill, "settings"), (
        "restore_drill.py importiert config.settings -- damit koennte ein "
        "kuenftiger Tippfehler versehentlich echte Kunden-/Mandantendaten "
        "statt der isolierten Sandbox treffen."
    )

    monkeypatch.setattr(sys, "argv", ["restore_drill.py"])
    assert drill.main() == 0


def test_keep_workdir_flag_preserves_sandbox(monkeypatch, capsys, tmp_path):
    drill = _load_drill_module()
    # tempfile.mkdtemp() faellt auf den System-Temp zurueck; wir lenken es in
    # tmp_path um, damit der Test nichts im echten System-Temp hinterlaesst.
    monkeypatch.setattr(drill.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["restore_drill.py", "--keep-workdir"])

    exit_code = drill.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "--keep-workdir gesetzt: Sandbox bleibt erhalten" in captured.out
    sandboxes = list(tmp_path.glob("5eyes-restore-drill-*"))
    assert len(sandboxes) == 1
    assert (sandboxes[0] / "source" / "drill.db").is_file()
    assert list((sandboxes[0] / "backups").glob("*.db"))


def test_sandbox_is_removed_without_keep_flag(monkeypatch, tmp_path):
    drill = _load_drill_module()
    monkeypatch.setattr(drill.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["restore_drill.py"])

    exit_code = drill.main()

    assert exit_code == 0
    assert list(tmp_path.glob("5eyes-restore-drill-*")) == []


def test_integrity_check_helper_reports_ok_on_healthy_db(tmp_path):
    drill = _load_drill_module()
    db_path = tmp_path / "healthy.db"
    marker = drill._create_sandbox_source_db(db_path)
    assert drill._integrity_check(db_path) == "ok"
    assert drill._read_marker(db_path) == marker
