"""Round-53 red test for audit finding CMA-EQUITY-MEASUREMENT-BASIS-001.

See docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md.

Finding: services/jurisdiction/data_pipeline.py::compute_cma_candidate_for_jurisdiction()
feeds an ETF-level `trailingPE` proxy (yfinance `info["trailingPE"]`, fetched via
fetch_equity_pe_proxy_for_jurisdiction()) directly into
services/equity_valuation/mean_reversion.py::KGVMeanReversionModel as `kgv_current`,
compared against a single hardcoded, jurisdiction-independent
`_GENERIC_SHILLER_CAPE_FAIR_VALUE = 16.0` as `kgv_fair`.

The module's own docstrings/comments explicitly acknowledge these are two different
measurement bases:
  - fetch_equity_pe_proxy_for_jurisdiction() docstring: "der Wert ist ein
    ETF-Trailing-KGV-Proxy ... KEIN reines Index-KGV"
  - source_detail["equity_kgv_mean_reversion"]["pe_proxy_kind"]:
    "ETF-Trailing-KGV-Proxy (yfinance trailingPE), kein reines Index-KGV"
  - _GENERIC_SHILLER_CAPE_FAIR_VALUE comment: "Generischer, jurisdiktions-
    UNABHAENGIGER Shiller-CAPE-Langfrist-Referenzwert"

Despite this, there is NO code anywhere in the call path (compute_cma_candidate_
for_jurisdiction -> KGVMeanReversionModel) that checks, flags, or records whether
the two measurement bases (ETF trailing P/E vs. 100-year Shiller-CAPE average) are
compatible before mixing them into a single mean-reversion adjustment that feeds
equity_home_return_bps. This test proves that gap by construction: it mocks the
yield-curve provider and the yfinance PE fetch using exactly the established
monkeypatch pattern from tests/test_cma_data_pipeline.py (no real network access),
then asserts that the persisted candidate's source_detail records a measurement-
basis-compatibility judgement. That field/check does not exist today, so the
assertion fails with a KeyError -- not an import/setup/network error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401
import services.jurisdiction.data_pipeline as dp
from tests.test_cma_data_pipeline import _FakeProvider, _points  # reuse established mock pattern


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_equity_measurement_basis.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _patch_full_de_curve(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    provider = _FakeProvider(
        {code: _points(v)[:1] for code, v in zip(series_codes, [2.0, 2.3, 2.6, 2.9, 3.1])}
    )
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-EQUITY-MEASUREMENT-BASIS-001 -- round 53 red test, see audit "
        "docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md"
    ),
)
def test_pe_proxy_and_generic_cape_are_mixed_without_measurement_basis_compatibility_check(
    session_factory, monkeypatch
):
    """Documents CMA-EQUITY-MEASUREMENT-BASIS-001: an ETF trailingPE (a specific,
    single-fund, trailing-earnings valuation metric) is compared directly against
    a generic 100-year Shiller-CAPE fair value of 16.0 with no transformation and
    no compatibility gate, even though both measurement bases are explicitly named
    as different in the surrounding comments.

    This asserts the presence of a measurement-basis-compatibility judgement in the
    persisted source_detail -- the thing that SHOULD exist if this mismatch were
    actually guarded against. No such field exists anywhere in data_pipeline.py or
    in KGVMeanReversionModel today, so this fails with a KeyError, not for an
    unrelated reason (no network call is made; the yield-curve provider and the
    yfinance PE fetch are both monkeypatched per the pattern already established in
    tests/test_cma_data_pipeline.py).
    """
    _patch_full_de_curve(monkeypatch)
    # Concrete, realistic ETF trailingPE value (yfinance info["trailingPE"]).
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {"trailingPE": 22.0})

    with session_factory() as db:
        cma = dp.compute_cma_candidate_for_jurisdiction(db, "DE", "2026-07-30")
        db.commit()

        kgv_detail = json.loads(cma.source_detail)["equity_kgv_mean_reversion"]

        # Sanity check confirming the mismatch is real and unmitigated: the raw
        # ETF trailingPE proxy (22.0) is used verbatim as kgv_current against the
        # generic, jurisdiction-independent CAPE fair value (16.0) -- two different
        # measurement bases per the module's own docstrings, mixed with zero
        # transformation.
        assert kgv_detail["pe_proxy_value_kgv_current"] == 22.0
        assert kgv_detail["kgv_fair_generic_shiller_cape"] == dp._GENERIC_SHILLER_CAPE_FAIR_VALUE
        assert kgv_detail["pe_proxy_kind"] == (
            "ETF-Trailing-KGV-Proxy (yfinance trailingPE), kein reines Index-KGV"
        )

        # The assertion that SHOULD hold if a measurement-basis-compatibility gate
        # existed: the persisted detail would record whether trailingPE and the
        # generic Shiller-CAPE fair value were judged compatible before being
        # mixed. No such key is ever written today -> KeyError.
        assert "measurement_basis_compatible" in kgv_detail
        assert kgv_detail["measurement_basis_compatible"] is True
