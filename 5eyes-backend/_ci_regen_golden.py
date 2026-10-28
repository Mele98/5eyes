"""TEMPORAER (GOAL-AXIS-VALUATION-YEAR-001, Engine v18): erzeugt die
CH-Golden-Fixtures auf dem Linux-CI-Runner neu. Nutzt den Snapshot-Builder des
Testmoduls selbst. Ausgabeverzeichnis als erstes Argument; mit
FORCE_ENGINE_VERSION wird die Version im Inhalts-Seed erzwungen (Fix-Effekt
ohne Seed-Effekt). Wird im naechsten Commit wieder entfernt."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

from test_golden_snapshot_ch_regression import COMBOS, _build_ch_snapshot  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from database import Base  # noqa: E402
import services.optimizer.solver as solver_module  # noqa: E402

forced = os.environ.get("FORCE_ENGINE_VERSION")
if forced:
    solver_module.OPTIMIZER_ENGINE_VERSION = forced
    print(f"forced engine version: {forced}")

OUT_DIR = Path(sys.argv[1]).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

for combo in COMBOS:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / f"{combo['name']}.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        session_factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        try:
            snapshot = _build_ch_snapshot(session_factory, combo)
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()
    out_path = OUT_DIR / f"{combo['name']}.json"
    out_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path}")
