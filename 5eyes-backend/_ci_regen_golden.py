"""TEMPORARY, one-off: regenerate golden CH-snapshot fixtures on the actual
CI platform (Ubuntu + pinned numpy/scipy), since SLSQP convergence drifts a
few hundred CHF per rebalancing step between platforms even with identical
library versions. Removed again once its output is captured. Reuses the
test module's own snapshot builder so output is byte-for-byte what
test_golden_ch_snapshot_matches_frozen_fixture() will assert against.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

from test_golden_snapshot_ch_regression import COMBOS, FIXTURES_DIR, _build_ch_snapshot  # noqa: E402

import tempfile  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from database import Base  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "_ci_regen_output"
OUT_DIR.mkdir(exist_ok=True)

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
