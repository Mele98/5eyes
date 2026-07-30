"""WP-DataPipeline (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Echte Marktdaten -> "data_derived" CapitalMarketAssumption-Kandidaten.

Baut auf dem additiven Schema aus WP1 auf (models/allocation.py::
CapitalMarketAssumption.jurisdiction/status/source_detail/computed_at/
computed_by/equity_home_*/bonds_home_ig_*/real_estate_home_*) und dem
bereits vorhandenen, aber bislang nur in Tests genutzten Berechnungscode
(services/rates/nelson_siegel.py::fit_nelson_siegel,
services/equity_valuation/mean_reversion.py::KGVMeanReversionModel).

WICHTIG (Constraint 1, harte Vorgabe des Arbeitspakets): dieses Modul wird
NIRGENDS aus der bestehenden Engine (services/portfolio_engine.py) oder aus
services/jurisdiction/resolve.py|provisional_gate.py aufgerufen -- es liefert
ausschliesslich einen NEUEN, INAKTIVEN CMA-Kandidaten (is_current=0), den ein
Mensch in einem spaeteren, noch nicht gebauten Router-Arbeitspaket explizit
freigeben/aktivieren muss. Der CH-Pfad (jurisdiction IS NULL / "CH") wird von
diesem Modul nicht beruehrt.

WICHTIG (Constraint 2, harte Vorgabe): es werden NIEMALS erfundene/geschaetzte
Kapitalmarkt-Zahlen fuer eine neue Jurisdiktion persistiert. Jede Zinskurve
kommt aus einer echten, oeffentlich dokumentierten FRED-/ECB-Serie (siehe
_YIELD_CURVE_REGISTRY); jeder KGV-Proxy kommt aus einem echten yfinance-
ETF-`trailingPE`-Abruf (explizit als "ETF-Trailing-KGV-Proxy, kein reines
Index-KGV" dokumentiert) oder bleibt None. Real-Estate-/Alternatives-
Risikopraemien werden bewusst NICHT berechnet, weil keine echte, oeffentliche
Datenquelle dafuer identifiziert wurde -- die entsprechenden CMA-Felder
bleiben NULL (ehrliches, unvollstaendiges Ergebnis statt Erfindung).

Governance: jede erzeugte Zeile bekommt status="data_derived" (mindestens
ein Feld real berechnet) oder "provisional" (kein Feld real berechnet).
NUR status="committee_approved"-Zeilen duerfen laut Vorgabe (spaeteres
Arbeitspaket) in Kundendokumente einfliessen -- diese Durchsetzung ist NICHT
Teil dieses Moduls.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np
from sqlalchemy.orm import Session

from models.allocation import CapitalMarketAssumption
from services.equity_valuation.mean_reversion import KGVMeanReversionModel
from services.market_data.macro import ECBMacroProvider, FREDMacroProvider
from services.rates.nelson_siegel import fit_nelson_siegel

logger = logging.getLogger(__name__)


COMPUTED_BY = "system:cma_data_pipeline"
"""Wert fuer CapitalMarketAssumption.computed_by / .created_by auf von
diesem Modul erzeugten Kandidaten-Zeilen."""


class JurisdictionDataPipelineError(Exception):
    """Basisklasse fuer alle Fehler dieses Moduls."""


class NoYieldCurveSourceConfiguredError(JurisdictionDataPipelineError):
    """Fuer diese Jurisdiktion ist keine Zinskurven-Quelle (FRED/ECB)
    konfiguriert. Es wird bewusst KEINE Zahl erfunden -- der Aufrufer muss
    diesen Fall explizit behandeln (z.B. Jurisdiktion vorerst nicht anbieten)."""


class InsufficientYieldCurveDataError(JurisdictionDataPipelineError):
    """Der konfigurierte Provider hat zu wenige verwertbare Datenpunkte
    geliefert (< 3, siehe services/rates/nelson_siegel.py::fit_nelson_siegel:
    'Need >= 3 data points')."""


# ---------------------------------------------------------------------------
# Registry: Jurisdiktion -> (Provider-Name, Zinskurven-Serien).
#
# NUR echte, oeffentlich dokumentierte Serien-Codes -- keine erfundenen
# Werte, siehe Modul-Docstring Constraint 2.
# ---------------------------------------------------------------------------

_YIELD_CURVE_REGISTRY: dict[str, tuple[str, tuple[tuple[float, str], ...]]] = {
    # US-Treasury "Daily Treasury Par Yield Curve Rates" (Constant Maturity).
    # DGS3MO/DGS1/DGS2/DGS5/DGS10/DGS30 sind die offiziellen, oeffentlich
    # dokumentierten FRED-Serien-Codes fuer diese taeglichen US-Staatsanleihen-
    # Renditen (https://fred.stlouisfed.org/series/DGS10 usw.).
    "US": (
        "fred",
        (
            (0.25, "DGS3MO"),
            (1.0, "DGS1"),
            (2.0, "DGS2"),
            (5.0, "DGS5"),
            (10.0, "DGS10"),
            (30.0, "DGS30"),
        ),
    ),
    # Euro-Area AAA-rated Government Bond Yield Curve, ECB SDW-Dataflow "YC"
    # (Financial market data / yield curve spot rates), Instrument "G_N_A"
    # (government bonds, nominal, all bonds), Provider "4F", Data-Type
    # "SV_C_YM" (spot rate, continuous compounding, yield curve). Deutschland
    # hat keine eigene, oeffentlich-kostenlose Multi-Maturitaets-Zinskurve bei
    # FRED/ECB -- die Euro-Area-AAA-Kurve (ueberwiegend deutsche Bundes-
    # anleihen als AAA-Constituent) wird als bestverfuegbarer, ECHTER
    # oeffentlicher Proxy verwendet und EXPLIZIT als solcher in
    # source_detail dokumentiert (keine erfundene Landes-Kurve).
    "DE": (
        "ecb",
        (
            (1.0, "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y"),
            (2.0, "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y"),
            (5.0, "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y"),
            (10.0, "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"),
            (30.0, "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_30Y"),
        ),
    ),
}

# PE-Proxy-Ticker: breite, liquide Index-ETFs. yfinance `trailingPE` auf
# einem ETF ist ein ETF-Trailing-KGV-Proxy, KEIN reines Index-KGV -- das wird
# in compute_cma_candidate_for_jurisdiction()'s source_detail explizit
# dokumentiert. Fehlt eine Jurisdiktion hier, gibt
# fetch_equity_pe_proxy_for_jurisdiction() None zurueck (kein Crash, keine
# erfundene Zahl).
_PE_PROXY_TICKERS: dict[str, str] = {
    "US": "SPY",  # SPDR S&P 500 ETF Trust
    "DE": "EWG",  # iShares MSCI Germany ETF
}

# Generischer, jurisdiktions-UNABHAENGIGER Shiller-CAPE-Langfrist-Referenz-
# wert. services/equity_valuation/mean_reversion.py::KGVMeanReversionModel
# dokumentiert selbst "kgv_fair: Langfristiger fair value (Shiller-CAPE
# Mittel ueber 100J: ~16-18)" -- das ist ein akademischer, laender-
# UNABHAENGIGER Referenzwert des Modells selbst, KEIN fuer eine neue
# Jurisdiktion erfundener KGV-Wert (Constraint 2 betrifft landesspezifische
# Erfindungen). Konservativ (Memory feedback_conservative_values): unteres
# Ende der vom Modell dokumentierten Bandbreite.
_GENERIC_SHILLER_CAPE_FAIR_VALUE = 16.0
_KGV_ALPHA_DEFAULT = 0.15  # Modell-Default, siehe KGVMeanReversionModel.alpha
_KGV_HORIZON_YEARS = 10  # strategischer SAA-Horizont (analog Sprint-7-Doku)

# Fenster fuer den "aktuellsten verfuegbaren"-Abruf pro Serie. 30 Tage
# ueberbrueckt Wochenenden/Feiertage/Publikationsverzug zuverlaessig.
_LOOKBACK_DAYS = 30


def _build_fred_provider() -> FREDMacroProvider:
    """Factory fuer den FRED-Provider (in Tests via monkeypatch ersetzbar,
    analog zum Mock-Session-Muster in tests/test_market_data_macro.py)."""
    return FREDMacroProvider(api_key=os.environ.get("FRED_API_KEY"))


def _build_ecb_provider() -> ECBMacroProvider:
    """Factory fuer den ECB-Provider (in Tests via monkeypatch ersetzbar).
    ECB SDW braucht keinen API-Key."""
    return ECBMacroProvider()


def _fetch_pe_ticker_info(ticker: str) -> dict:
    """Lazy yfinance-Import (in Tests via monkeypatch ersetzbar), analog zum
    bestehenden Lazy-Import-Muster in
    services/market_data/providers/yfinance_provider.py::YFinanceProvider._yfinance
    -- damit dieses Modul auch ohne installiertes yfinance importierbar ist."""
    import yfinance as yf  # type: ignore[import-not-found]

    t = yf.Ticker(ticker)
    info = getattr(t, "info", None)
    return info if isinstance(info, dict) else {}


def fetch_yield_curve_for_jurisdiction(jurisdiction: str) -> list[tuple[float, int]]:
    """Holt eine echte Zinskurve (Maturity in Jahren, Yield in bps) fuer eine
    Jurisdiktion ueber FRED oder ECB (siehe _YIELD_CURVE_REGISTRY fuer die je
    Jurisdiktion konfigurierte, echte oeffentliche Serie).

    Returns:
        Liste von (maturity_years, yield_bps)-Tupeln, mindestens 3 Punkte
        (Voraussetzung fuer services/rates/nelson_siegel.py::fit_nelson_siegel).

    Raises:
        NoYieldCurveSourceConfiguredError: kein Provider fuer diese
            Jurisdiktion konfiguriert -- es wird NIEMALS eine Zahl erfunden.
        InsufficientYieldCurveDataError: der Provider hat fuer weniger als 3
            der konfigurierten Serien einen aktuellen Datenpunkt geliefert.
    """
    key = (jurisdiction or "").strip().upper()
    entry = _YIELD_CURVE_REGISTRY.get(key)
    if entry is None:
        raise NoYieldCurveSourceConfiguredError(
            f"Keine Zinskurven-Quelle (FRED/ECB) fuer Jurisdiktion '{jurisdiction}' "
            f"konfiguriert. Bekannt: {sorted(_YIELD_CURVE_REGISTRY.keys())}."
        )
    provider_name, series = entry
    today = Date.today()
    window_start = today - timedelta(days=_LOOKBACK_DAYS)

    if provider_name == "fred":
        provider = _build_fred_provider()
    elif provider_name == "ecb":
        provider = _build_ecb_provider()
    else:  # pragma: no cover - Registry-interne Konsistenz, nicht von aussen erreichbar
        raise NoYieldCurveSourceConfiguredError(
            f"Unbekannter Provider-Typ '{provider_name}' fuer Jurisdiktion '{jurisdiction}'."
        )

    points: list[tuple[float, int]] = []
    for maturity_years, series_code in series:
        series_points = provider.get_series(series_code, window_start, today)
        if not series_points:
            logger.warning(
                "Kein aktueller Datenpunkt fuer %s-Serie '%s' (Jurisdiktion %s)",
                provider_name, series_code, key,
            )
            continue
        latest = series_points[-1]
        # FRED/ECB liefern Renditen als Prozent (z.B. 4.25 = 4.25%) -> bps.
        yield_bps = int(round(float(latest.value) * 100))
        points.append((maturity_years, yield_bps))

    if len(points) < 3:
        raise InsufficientYieldCurveDataError(
            f"Nur {len(points)} von {len(series)} konfigurierten Zinskurven-Punkten "
            f"fuer Jurisdiktion '{key}' via {provider_name} erhalten (mind. 3 fuer "
            f"Nelson-Siegel-Fit noetig)."
        )
    return points


def fetch_equity_pe_proxy_for_jurisdiction(jurisdiction: str) -> int | None:
    """Liefert einen KGV-Proxy fuer eine Jurisdiktion, oder None wenn keine
    verlaessliche Quelle existiert.

    ACHTUNG: der Wert ist ein ETF-Trailing-KGV-Proxy (yfinance `trailingPE`
    des in _PE_PROXY_TICKERS hinterlegten breiten Index-ETFs), KEIN reines
    Index-KGV -- compute_cma_candidate_for_jurisdiction() dokumentiert das
    explizit in source_detail.

    Gibt None zurueck (nie 0, nie geschaetzt) wenn:
    - kein Ticker fuer die Jurisdiktion in _PE_PROXY_TICKERS hinterlegt ist,
    - der Datenabruf fehlschlaegt (yfinance fehlt / Netzwerkfehler / o.ae.),
    - das info-dict kein 'trailingPE' enthaelt.
    """
    key = (jurisdiction or "").strip().upper()
    ticker = _PE_PROXY_TICKERS.get(key)
    if ticker is None:
        return None

    try:
        info = _fetch_pe_ticker_info(ticker)
    except Exception as exc:  # noqa: BLE001 - PE-Proxy ist optional, nie fatal
        logger.warning(
            "PE-Proxy-Abruf fehlgeschlagen fuer Jurisdiktion %s (Ticker %s): %s",
            key, ticker, exc,
        )
        return None

    if not isinstance(info, dict):
        return None
    pe = info.get("trailingPE")
    if pe is None:
        return None
    try:
        return int(round(float(pe)))
    except (TypeError, ValueError):
        return None


def compute_cma_candidate_for_jurisdiction(
    db: Session,
    jurisdiction: str,
    as_of_date: str,
) -> CapitalMarketAssumption:
    """Orchestriert fetch_yield_curve_for_jurisdiction() +
    fetch_equity_pe_proxy_for_jurisdiction() zu einem NEUEN, INAKTIVEN
    CapitalMarketAssumption-Kandidaten fuer eine Nicht-CH-Jurisdiktion.

    - Zinskurve (Pflicht): fit_nelson_siegel() auf den echten, ueber
      fetch_yield_curve_for_jurisdiction() geholten Punkten. Der 5-Jahres-
      Punkt der gefitteten Kurve (analog zum bestehenden CH-Muster in
      services/optimizer/scenario_engine.py, dort yield_at(5) fuer den
      Bonds-Bucket) wird als bonds_home_ig_return_bps persistiert.
    - Equity-KGV-Mean-Reversion (optional, nur wenn ein PE-Proxy verfuegbar
      war): equity_home_return_bps = NS.short_rate_bps() (Risk-Free-
      Komponente, analog zur Konvention in
      services/risk_premium/model.py Docstring) + KGVMeanReversionModel(...)
      .expected_annual_return_adjustment_bps(10 Jahre). Ohne PE-Proxy bleibt
      equity_home_return_bps NULL -- es wird KEIN Ersatzwert erfunden.
    - Real-Estate-/Alternatives-Felder bleiben immer NULL (keine echte,
      oeffentliche Praemien-Datenquelle in diesem Arbeitspaket identifiziert).
    - status="data_derived" wenn mindestens ein Feld real berechnet wurde
      (das ist wegen der Zinskurven-Pflicht praktisch immer der Fall, sobald
      diese Funktion ueberhaupt zurueckkehrt statt zu werfen), sonst
      "provisional".
    - is_current wird NICHT gesetzt (bleibt 0) -- ein Mensch muss den
      Kandidaten in einem spaeteren Arbeitspaket explizit aktivieren.

    Persistiert die Zeile via db.add() + db.flush() (NICHT db.commit() --
    das obliegt dem Aufrufer/Test).

    Raises:
        NoYieldCurveSourceConfiguredError, InsufficientYieldCurveDataError:
            siehe fetch_yield_curve_for_jurisdiction() -- diese Exceptions
            werden bewusst NICHT abgefangen, ein Kandidat ohne echte
            Zinskurve wird nie erzeugt.
    """
    key = (jurisdiction or "").strip().upper()
    as_of = Date.fromisoformat(as_of_date)

    yield_points = fetch_yield_curve_for_jurisdiction(key)
    provider_name, series_registry = _YIELD_CURVE_REGISTRY[key]

    maturities = np.array([m for m, _ in yield_points], dtype=np.float64)
    yields_bps = np.array([y for _, y in yield_points], dtype=np.float64)
    curve = fit_nelson_siegel(maturities, yields_bps)

    bonds_home_ig_return_bps = int(round(float(curve.yield_at(5.0))))

    equity_home_return_bps: int | None = None
    kgv_detail: dict | None = None
    pe_proxy = fetch_equity_pe_proxy_for_jurisdiction(key)
    if pe_proxy is not None:
        risk_free_bps = curve.short_rate_bps()
        model = KGVMeanReversionModel(
            kgv_current=float(pe_proxy),
            kgv_fair=_GENERIC_SHILLER_CAPE_FAIR_VALUE,
            alpha=_KGV_ALPHA_DEFAULT,
        )
        adjustment_bps = model.expected_annual_return_adjustment_bps(_KGV_HORIZON_YEARS)
        equity_home_return_bps = int(round(risk_free_bps + adjustment_bps))
        kgv_detail = {
            "pe_proxy_ticker": _PE_PROXY_TICKERS[key],
            "pe_proxy_value_kgv_current": pe_proxy,
            "pe_proxy_kind": "ETF-Trailing-KGV-Proxy (yfinance trailingPE), kein reines Index-KGV",
            "kgv_fair_generic_shiller_cape": _GENERIC_SHILLER_CAPE_FAIR_VALUE,
            "kgv_fair_source": (
                "Genereller, jurisdiktionsunabhaengiger Modell-Referenzwert aus "
                "services/equity_valuation/mean_reversion.py Docstring "
                "('Shiller-CAPE Mittel ueber 100J: ~16-18'), konservatives unteres "
                "Ende -- keine landesspezifische Schaetzung."
            ),
            "alpha": _KGV_ALPHA_DEFAULT,
            "horizon_years": _KGV_HORIZON_YEARS,
            "risk_free_bps_component": round(risk_free_bps, 2),
            "formula": (
                "equity_home_return_bps = round(NelsonSiegelCurve.short_rate_bps() + "
                "KGVMeanReversionModel(kgv_current=pe_proxy, kgv_fair=16.0, alpha=0.15)"
                ".expected_annual_return_adjustment_bps(horizon_years=10))"
            ),
        }
    else:
        kgv_detail = {
            "skipped_reason": (
                "Kein verlaesslicher PE-Proxy fuer diese Jurisdiktion verfuegbar "
                "(fetch_equity_pe_proxy_for_jurisdiction() lieferte None) -- "
                "equity_home_return_bps bleibt bewusst NULL, kein Ersatzwert erfunden."
            ),
        }

    computed_values = [bonds_home_ig_return_bps, equity_home_return_bps]
    status = "data_derived" if any(v is not None for v in computed_values) else "provisional"

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    source_detail = {
        "jurisdiction": key,
        "fetched_at_utc": now_iso,
        "yield_curve": {
            "provider": provider_name,
            "series": [
                {"maturity_years": m, "series_code": c} for m, c in series_registry
            ],
            "fetched_points_bps": [
                {"maturity_years": m, "yield_bps": y} for m, y in yield_points
            ],
            "nelson_siegel_fit": curve.to_dict(),
            "formula": (
                "bonds_home_ig_return_bps = round(NelsonSiegelCurve.yield_at(5.0)) "
                "nach fit_nelson_siegel(maturities, yields_bps) ueber die "
                "fetched_points_bps oben (analog zur bestehenden CH-5J-Konvention "
                "in services/optimizer/scenario_engine.py)."
            ),
        },
        "equity_kgv_mean_reversion": kgv_detail,
        "notes": (
            "real_estate_home_return_bps/real_estate_home_vol_bps und alle "
            "*_vol_bps-Felder bleiben NULL: keine oeffentliche, verlaessliche "
            "Vola-/Risikopraemien-Datenquelle in diesem Arbeitspaket identifiziert "
            "-- bewusst nicht erfunden (Constraint 2)."
        ),
    }

    cma = CapitalMarketAssumption(
        id=f"cma-{key.lower()}-data-derived-{uuid.uuid4()}",
        assumption_set_name=f"{key}-data-derived-{as_of.isoformat()}",
        version=1,
        valid_from=as_of.isoformat(),
        is_current=0,
        jurisdiction=key,
        status=status,
        source_detail=json.dumps(source_detail, ensure_ascii=False),
        computed_at=now_iso,
        computed_by=COMPUTED_BY,
        bonds_home_ig_return_bps=bonds_home_ig_return_bps,
        equity_home_return_bps=equity_home_return_bps,
        created_by=COMPUTED_BY,
        created_at=now_iso,
        updated_at=now_iso,
    )
    db.add(cma)
    db.flush()
    return cma
