"""L2d: a completed DSG key deletion must invalidate an active KeyReader.

The exact product tree and SHA are mandatory.  The test uses only the product
test fixture's temporary database.  It never falls back to an owner profile.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PRODUCT = os.environ.get("ARES_PRODUCT_ROOT")
EXPECTED = os.environ.get("ARES_EXPECTED_SHA")
if not PRODUCT or not EXPECTED:
    raise RuntimeError("Set ARES_PRODUCT_ROOT and ARES_EXPECTED_SHA; refusing fallback")
ROOT = Path(PRODUCT).resolve()
BACKEND = ROOT / "ares-backend"
TESTS = BACKEND / "tests"
if not BACKEND.is_dir():
    raise RuntimeError(f"Not an Ares product root: {ROOT}")
for path in (str(BACKEND), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)
HEAD = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
).stdout.strip()
if HEAD != EXPECTED:
    raise RuntimeError(f"Expected {EXPECTED}, got {HEAD}; refusing cross-SHA verdict")

from h8_support import sf  # noqa: E402,F401
from services import pii_vault  # noqa: E402


def test_active_key_reader_cannot_decrypt_after_key_shredding(sf):
    with sf() as db:
        envelope = pii_vault.seal_for_client(db, "c-1", "SYNTHETISCHER TESTTEXT")
        db.commit()

        reader = pii_vault.KeyReader(db)
        assert pii_vault.reveal(db, envelope, reader=reader) == "SYNTHETISCHER TESTTEXT"

        assert pii_vault.shred_client_keys(db, "c-1") == 1
        # The deletion is committed before either postcondition is checked;
        # this is not an observation of an unfinished transaction.
        db.commit()

        # Positive control: the persisted deletion is effective for a fresh
        # reader.  A failure below is therefore specifically a stale cache,
        # not a broken shredding operation or fixture.
        assert pii_vault.reveal(db, envelope, reader=pii_vault.KeyReader(db)) is None

        # Contract: once deletion is effective, no already active reader may
        # keep using the old key material.  An invalidated reader may either
        # reload the tombstone (None) or refuse reuse explicitly after close.
        try:
            after = pii_vault.reveal(db, envelope, reader=reader)
        except RuntimeError as exc:
            assert "closed" in str(exc).lower() or "geschlossen" in str(exc).lower()
        else:
            assert after is None
