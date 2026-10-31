"""Conformance-Vertrag fuer TaxRegime-Implementierungen.

# Zweck
Eine Regime-Implementierung kann das Protocol formal erfuellen, aber
trotzdem semantisch falsch sein (z.B. negativer Steuerbetrag, falsche
Einheiten-Skalierung, Mutation statt Immutability).

Der ConformanceContract definiert die LAUFZEIT-Anforderungen, die
jede produktive Regime-Implementierung erfuellen muss. Drittanbieter
koennen ihre Implementierung gegen diesen Contract testen — als CI-
Stage in ihrem eigenen Repo — und im Output ihren Conformance-Report
mitliefern.

# Verwendung im 3rd-Party-CI
    from services.tax.sdk import ConformanceContract

    def test_my_regime_is_conformant():
        report = ConformanceContract().run(MyRegime())
        assert report.passed, report.format_failures()

# Versionierung
ConformanceContract.VERSION pinnt die Vertrags-Version. Externe
Implementierungen koennen damit gegen eine spezifische Vertrags-
Version testen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from services.tax.base import TaxContext, TaxRegime, TaxResult


@dataclass(frozen=True)
class ConformanceRequirement:
    """Eine einzelne pruefbare Conformance-Anforderung.

    id ist stabil ueber Vertrags-Versionen (Drift-Test-Anker).
    description ist user-facing (geht in Report-Output).
    severity 'mandatory' = MUSS, 'recommended' = SOLL.
    """

    id: str
    description: str
    severity: str = "mandatory"
    check: Callable[[TaxRegime], tuple[bool, str]] | None = None


@dataclass
class ConformanceReport:
    """Ergebnis eines Conformance-Runs gegen eine Regime-Instanz."""

    regime_id: str
    contract_version: str
    passed_requirements: list[str] = field(default_factory=list)
    failed_requirements: list[tuple[str, str]] = field(default_factory=list)
    """Liste von (requirement_id, error_message)-Tuples."""
    warnings: list[tuple[str, str]] = field(default_factory=list)
    """Liste von (requirement_id, message) fuer SOLL-Verletzungen."""

    @property
    def passed(self) -> bool:
        """True wenn alle MUSS-Anforderungen erfuellt sind."""
        return not self.failed_requirements

    def format_failures(self) -> str:
        """Menschen-lesbarer Bericht fuer pytest-Fail-Output."""
        if self.passed and not self.warnings:
            return f"All conformance checks passed for {self.regime_id}"
        lines = [f"Conformance-Report fuer {self.regime_id}:"]
        for rid, msg in self.failed_requirements:
            lines.append(f"  [FAIL][MANDATORY] {rid}: {msg}")
        for rid, msg in self.warnings:
            lines.append(f"  [WARN][RECOMMENDED] {rid}: {msg}")
        return "\n".join(lines)


class ConformanceContract:
    """Definiert die Pflicht- und Soll-Anforderungen an eine
    TaxRegime-Implementierung.

    Jede Requirement-Check hat eine kleine Test-Funktion die gegen eine
    Regime-Instanz laeuft. Der Contract selbst ist read-only — neue
    Anforderungen kommen via Major/Minor-Version-Bump.
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self.requirements: list[ConformanceRequirement] = list(_BUILTIN_REQUIREMENTS)

    def run(self, regime: TaxRegime) -> ConformanceReport:
        """Fuehrt alle Requirements gegen die Regime-Instanz aus."""
        report = ConformanceReport(
            regime_id=getattr(regime, "id", "<unknown>"),
            contract_version=self.VERSION,
        )
        for req in self.requirements:
            if req.check is None:
                continue
            try:
                ok, msg = req.check(regime)
            except Exception as exc:  # noqa: BLE001 — fang ALLE Fehler
                ok = False
                msg = f"check raised {type(exc).__name__}: {exc}"
            if ok:
                report.passed_requirements.append(req.id)
            elif req.severity == "mandatory":
                report.failed_requirements.append((req.id, msg))
            else:
                report.warnings.append((req.id, msg))
        return report


# ---------------------------------------------------------------------------
# Built-in Conformance-Requirements
# ---------------------------------------------------------------------------

def _ctx() -> TaxContext:
    return TaxContext(
        year_index=0,
        calendar_year=2026,
        wealth_rappen=1_000_000_00,  # 1 Mio CHF in Rappen
        age=45,
    )


def _check_has_id(regime: TaxRegime) -> tuple[bool, str]:
    rid = getattr(regime, "id", None)
    if isinstance(rid, str) and rid.strip():
        return True, "ok"
    return False, "regime.id muss nicht-leerer String sein"


def _check_has_country_code(regime: TaxRegime) -> tuple[bool, str]:
    cc = getattr(regime, "country_code", None)
    if isinstance(cc, str) and len(cc) == 2 and cc.isupper():
        return True, "ok"
    return False, f"country_code '{cc}' muss ISO 3166-1 alpha-2 sein (z.B. 'CH')"


def _check_has_display_name(regime: TaxRegime) -> tuple[bool, str]:
    name = getattr(regime, "display_name", None)
    if isinstance(name, str) and name.strip():
        return True, "ok"
    return False, "display_name fehlt oder leer"


def _check_local_currency(regime: TaxRegime) -> tuple[bool, str]:
    cur = getattr(regime, "local_currency", None)
    if isinstance(cur, str) and len(cur) == 3 and cur.isupper():
        return True, "ok"
    return False, f"local_currency '{cur}' muss ISO 4217 sein (z.B. 'CHF')"


def _check_wealth_tax_nonneg(regime: TaxRegime) -> tuple[bool, str]:
    res = regime.annual_wealth_tax(_ctx())
    if not isinstance(res, TaxResult):
        return False, f"annual_wealth_tax muss TaxResult zurueckgeben, got {type(res).__name__}"
    if res.amount_rappen < 0:
        return False, f"amount_rappen={res.amount_rappen} ist negativ"
    return True, "ok"


def _check_capital_gains_returns_result(regime: TaxRegime) -> tuple[bool, str]:
    res = regime.capital_gains_tax(_ctx(), gains_rappen=10_000_00, holding_years=2)
    if not isinstance(res, TaxResult):
        return False, f"capital_gains_tax muss TaxResult zurueckgeben"
    if res.amount_rappen < 0:
        return False, "negativer Steuerbetrag"
    return True, "ok"


def _check_dividend_returns_result(regime: TaxRegime) -> tuple[bool, str]:
    res = regime.dividend_tax(_ctx(), dividend_income_rappen=5_000_00)
    if not isinstance(res, TaxResult):
        return False, "dividend_tax muss TaxResult zurueckgeben"
    if res.amount_rappen < 0:
        return False, "negativer Steuerbetrag"
    return True, "ok"


def _check_overrides_immutable(regime: TaxRegime) -> tuple[bool, str]:
    """with_overrides darf das Original NICHT mutieren."""
    if not hasattr(regime, "with_overrides"):
        return False, "with_overrides() fehlt"
    snapshot_id = regime.id
    snapshot_currency = regime.local_currency
    try:
        new_regime = regime.with_overrides({"wealth_tax_bps_pa": 999.0})
    except Exception as exc:  # noqa: BLE001
        return False, f"with_overrides raised {type(exc).__name__}: {exc}"
    if regime.id != snapshot_id:
        return False, "id wurde durch with_overrides mutiert"
    if regime.local_currency != snapshot_currency:
        return False, "local_currency wurde durch with_overrides mutiert"
    if new_regime is regime:
        # Erlaubt wenn override keinen Effekt hatte; aber wir wollen
        # zumindest pruefen dass das Pattern unterstuetzt ist.
        return True, "warn-only: with_overrides returned same instance"
    return True, "ok"


def _check_validate_parameters_callable(regime: TaxRegime) -> tuple[bool, str]:
    try:
        warnings = regime.validate_parameters({"wealth_tax_bps_pa": 50.0})
    except Exception as exc:  # noqa: BLE001
        return False, f"validate_parameters raised {type(exc).__name__}: {exc}"
    if not isinstance(warnings, tuple):
        return False, f"validate_parameters muss tuple zurueckgeben, got {type(warnings).__name__}"
    return True, "ok"


def _check_tariff_version_string(regime: TaxRegime) -> tuple[bool, str]:
    """SOLL: regime exponiert tariff_version-Property oder im TaxResult."""
    res = regime.annual_wealth_tax(_ctx())
    if not res.tariff_version or not isinstance(res.tariff_version, str):
        return False, "TaxResult.tariff_version sollte gesetzt sein"
    return True, "ok"


_BUILTIN_REQUIREMENTS: tuple[ConformanceRequirement, ...] = (
    ConformanceRequirement("R001-id", "regime.id ist nicht-leerer String", check=_check_has_id),
    ConformanceRequirement("R002-country", "country_code ist ISO 3166-1 alpha-2", check=_check_has_country_code),
    ConformanceRequirement("R003-name", "display_name ist gesetzt", check=_check_has_display_name),
    ConformanceRequirement("R004-currency", "local_currency ist ISO 4217", check=_check_local_currency),
    ConformanceRequirement("R005-wealth-nonneg", "annual_wealth_tax >= 0", check=_check_wealth_tax_nonneg),
    ConformanceRequirement("R006-capgains-result", "capital_gains_tax liefert TaxResult", check=_check_capital_gains_returns_result),
    ConformanceRequirement("R007-dividend-result", "dividend_tax liefert TaxResult", check=_check_dividend_returns_result),
    ConformanceRequirement("R008-overrides-immutable", "with_overrides mutiert nicht das Original", check=_check_overrides_immutable),
    ConformanceRequirement("R009-validate-tuple", "validate_parameters liefert tuple", check=_check_validate_parameters_callable),
    ConformanceRequirement(
        "R010-tariff-version", "TaxResult.tariff_version gesetzt",
        severity="recommended", check=_check_tariff_version_string,
    ),
)
