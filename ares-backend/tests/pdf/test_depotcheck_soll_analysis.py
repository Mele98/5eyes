from __future__ import annotations

from dataclasses import replace
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from services.pdf.base import DepotCheckData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer


def _context() -> PDFContext:
    return PDFContext(
        mandate_name="Muster Mandat",
        advisor_name="Anna Beratung",
        advisor_org="Beratungshaus",
        report_date=date(2026, 6, 7),
        audit_hash="depotcheck-test",
    )


def _data() -> DepotCheckData:
    return DepotCheckData(
        mandate_number="M-SOLL-01",
        total_advisory_wealth_rappen=1_000_000_00,
        target_allocation_bps={
            "equities": 5000,
            "bonds": 2500,
            "real_estate": 1000,
            "alternatives": 1000,
            "liquidity": 500,
        },
        bucket_bands_bps={
            "equities": (4500, 5500),
            "bonds": (2000, 3000),
            "real_estate": (500, 1500),
            "alternatives": (500, 1500),
            "liquidity": (250, 1000),
        },
        sub_allocations=[
            {
                "asset_class": "equities",
                "sub_asset_class": "Aktien Welt",
                "weight_bps": 3500,
                "amount_rappen": 350_000_00,
                "products": 2,
            },
            {
                "asset_class": "equities",
                "sub_asset_class": "Aktien Schweiz",
                "weight_bps": 1500,
                "amount_rappen": 150_000_00,
                "products": 1,
            },
            {
                "asset_class": "bonds",
                "sub_asset_class": "Obligationen CHF",
                "weight_bps": 2500,
                "amount_rappen": 250_000_00,
                "products": 2,
            },
        ],
        risk_profile_label="Ausgewogen",
        risk_metrics={
            "expected_return_bps": 430,
            "expected_vol_bps": 890,
            "max_drawdown_bps": 2200,
            "var_95_bps": 1450,
            "horizon_years": 12,
        },
        soll_country_exposure_bps={"Schweiz": 3500, "USA": 3000, "Europa": 2000, "Asien": 1500},
        soll_sector_exposure_bps={"Technologie": 2500, "Finanzen": 2200, "Industrie": 1800},
        soll_currency_exposure_bps={"CHF": 5200, "USD": 3000, "EUR": 1800},
        soll_concentration_hhi={
            "country": 2600,
            "sector": 1800,
            "currency": 3900,
            "top_positions": 1450,
        },
        top_positions=[
            {
                "product_name": "Globaler Aktienfonds",
                "isin": "CH0000000001",
                "sub_asset_class": "Aktien Welt",
                "weight_bps": 1800,
                "amount_rappen": 180_000_00,
            },
            {
                "product_name": "CHF Obligationenfonds",
                "isin": "CH0000000002",
                "sub_asset_class": "Obligationen CHF",
                "weight_bps": 1400,
                "amount_rappen": 140_000_00,
            },
        ],
        stress_scenarios=[
            {
                "label": "Finanzkrise",
                "period": "2008-2009",
                "cumulative_return_bps": -1800,
                "max_drawdown_bps": 2400,
                "recovery_months": 28,
            }
        ],
        cost_disclosure={
            "data_pending": False,
            "cost_items": [
                {
                    "label": "Produktkosten",
                    "frequency": "jaehrlich",
                    "rate_bps": 35,
                    "amount_rappen": 3_500_00,
                    "basis_label": "Zielportfolio",
                }
            ],
            "totals": {
                "one_time_bps": 15,
                "one_time_rappen": 1_500_00,
                "annual_bps": 35,
                "annual_rappen": 3_500_00,
                "first_year_bps": 50,
                "first_year_rappen": 5_000_00,
            },
        },
        performance={
            "data_pending": False,
            "wealth_path_rappen": [
                (2019, 100_000_00),
                (2020, 106_000_00),
                (2021, 115_000_00),
                (2022, 108_000_00),
                (2023, 119_000_00),
            ],
            "benchmark_wealth_path_rappen": [
                (2019, 100_000_00),
                (2020, 104_000_00),
                (2021, 111_000_00),
                (2022, 106_000_00),
                (2023, 115_000_00),
            ],
            "metrics": {
                "total_return_bps": 1900,
                "cagr_bps": 444,
                "vol_bps": 820,
                "sharpe_x100": 44,
                "max_drawdown_bps": 610,
                "best_year_bps": 850,
                "worst_year_bps": -610,
                "win_rate_x100": 7500,
                "positive_years": 3,
                "years_count": 4,
                "start_value_rappen": 100_000_00,
                "end_value_rappen": 119_000_00,
            },
            "benchmark_metrics": {
                "total_return_bps": 1500,
                "cagr_bps": 356,
                "vol_bps": 760,
                "sharpe_x100": 36,
                "max_drawdown_bps": 450,
                "best_year_bps": 670,
                "worst_year_bps": -450,
                "win_rate_x100": 7500,
                "positive_years": 3,
                "years_count": 4,
                "start_value_rappen": 100_000_00,
                "end_value_rappen": 115_000_00,
            },
        },
        qualitative_assessment=(
            "Die Zielstruktur ist breit diversifiziert und fuer die "
            "dokumentierte Beratung nachvollziehbar."
        ),
    )


def _text(pdf: bytes) -> tuple[PdfReader, str]:
    reader = PdfReader(BytesIO(pdf))
    return reader, "\n".join(page.extract_text() or "" for page in reader.pages)


def test_depotcheck_is_target_only_and_structurally_complete():
    reader, text = _text(ReportLabRenderer().render_depotcheck(_context(), _data()))

    assert len(reader.pages) >= 10
    for anchor in (
        "Hauptanlageklassen",
        "Subanlageklassen",
        "Laenderallokation",
        "Sektorallokation",
        "Waehrungsallokation",
        "Risikoanalyse",
        "Diversifikation und Klumpenrisiken",
        "Kosten und Gebuehren",
        "Performancevergleich",
        "Qualitative Einschaetzung",
    ):
        assert anchor in text
    assert "IST vs." not in text
    assert "Drift-Tabelle" not in text


def test_depotcheck_contains_target_details_and_benchmark():
    _, text = _text(ReportLabRenderer().render_depotcheck(_context(), _data()))

    assert "Aktien Welt" in text
    assert "Schweiz" in text
    assert "Technologie" in text
    assert "USD" in text
    assert "Globaler Aktienfonds" in text
    assert "Benchmark" in text
    assert "Gesamtkosten erstes Jahr" in text
    assert "breit diversifiziert" in text


def test_depotcheck_degraded_payload_still_renders():
    pdf = ReportLabRenderer().render_depotcheck(
        _context(),
        DepotCheckData(
            mandate_number="M-EMPTY",
            performance={"data_pending": True, "note": "Daten ausstehend."},
            cost_disclosure={"data_pending": True, "note": "Daten ausstehend."},
        ),
    )
    reader, text = _text(pdf)

    assert pdf.startswith(b"%PDF")
    assert len(reader.pages) >= 10
    assert "Daten ausstehend" in text


def test_depotcheck_dense_realistic_payload_stays_on_eleven_pages():
    data = replace(
        _data(),
        soll_country_exposure_bps={
            f"Land {index:02d}": max(50, 2200 - index * 150)
            for index in range(12)
        },
        soll_sector_exposure_bps={
            f"Sektor {index:02d}": max(50, 2400 - index * 165)
            for index in range(12)
        },
        top_positions=[
            {
                "product_name": f"Zielposition {index:02d}",
                "sub_asset_class": f"Subanlageklasse {index:02d}",
                "weight_bps": 1600 - index * 100,
                "amount_rappen": (160_000 - index * 10_000) * 100,
            }
            for index in range(10)
        ],
    )

    reader, text = _text(ReportLabRenderer().render_depotcheck(_context(), data))

    assert len(reader.pages) == 11
    assert "Land 11" in text
    assert "Sektor 11" in text
    assert "Zielposition 09" in text
