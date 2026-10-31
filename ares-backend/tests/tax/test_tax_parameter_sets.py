from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models.tax  # noqa: F401
from database import Base
from services.tax.parameters import (
    get_country_parameter_sets,
    list_current_regions,
    seed_default_tax_parameter_sets,
)


def test_seed_default_tax_parameter_sets_is_idempotent(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tax_params.db'}",
        connect_args={"check_same_thread": False},
    )
    SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        with SessionFactory() as session:
            assert seed_default_tax_parameter_sets(session) == 3
            session.commit()
        with SessionFactory() as session:
            assert seed_default_tax_parameter_sets(session) == 0
            assert "ZH" in list_current_regions(session, "CH", 2026)
            params = get_country_parameter_sets(session, "CH", 2026)
            assert params["ZH"]["wealth_tax_bps"] == 35
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_parameter_lookup_falls_back_to_builtin_ch_defaults(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tax_params_empty.db'}",
        connect_args={"check_same_thread": False},
    )
    SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        with SessionFactory() as session:
            params = get_country_parameter_sets(session, "CH", 2026)
            assert sorted(params) == ["GE", "ZG", "ZH"]
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

