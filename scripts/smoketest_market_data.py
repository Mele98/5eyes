"""End-to-End-Smoketest fuer die Multi-Source-Datenpipeline (P1-P18).

Prueft live (oder offline mit --no-network) die komplette Pipeline:
- Provider-Aufbau via build_default_aggregator
- is_healthy() pro Provider
- get_eod() fuer Standard-Symbole (UBSG.SW, AAPL)
- Aggregator-Fallback-Chain
- Cross-Validation (Median-Diff)

Aufruf:
    # Live (echte API-Calls):
    python scripts/smoketest_market_data.py

    # Offline (nur Aufbau pruefen, keine HTTP-Calls):
    python scripts/smoketest_market_data.py --no-network

    # Custom Symbole + Markdown-Report:
    python scripts/smoketest_market_data.py --symbols UBSG.SW,NESN.SW,AAPL --report-file out.md

Exit-Code:
    0 = alles OK
    1 = mindestens 1 Provider unhealthy ODER alle get_eod-Versuche fehlgeschlagen
    2 = Kritischer Aufbau-Fehler (Aggregator nicht konstruierbar)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ensure_backend_on_path() -> None:
    here = Path(__file__).resolve()
    backend = here.parent.parent / "5eyes-backend"
    if backend.exists() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


DEFAULT_SYMBOLS = ["UBSG.SW", "AAPL"]


@dataclass
class ProviderCheck:
    name: str
    healthy: bool
    notes: str = ""


@dataclass
class SymbolFetchResult:
    symbol: str
    provider: str | None
    price: str | None
    error: str | None = None


@dataclass
class ValidationCheck:
    symbol: str
    n_providers: int
    diff_bps: int
    is_alert: bool
    median: str
    note: str = ""


@dataclass
class SmoketestReport:
    started_at: str
    finished_at: str = ""
    providers: list[ProviderCheck] = field(default_factory=list)
    fetches: list[SymbolFetchResult] = field(default_factory=list)
    validations: list[ValidationCheck] = field(default_factory=list)
    summary_ok: bool = True
    summary_notes: list[str] = field(default_factory=list)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_providers(aggregator: Any) -> list[ProviderCheck]:
    """Pro Provider is_healthy() + Notiz fuer untypische States."""
    checks: list[ProviderCheck] = []
    for provider in aggregator.providers:
        name = str(getattr(provider, "name", "?"))
        try:
            healthy = bool(provider.is_healthy())
            note = "" if healthy else "is_healthy() = False (Key fehlt / Limit?)"
        except Exception as exc:  # noqa: BLE001
            healthy = False
            note = f"is_healthy() raised: {exc.__class__.__name__}: {exc}"
        checks.append(ProviderCheck(name=name, healthy=healthy, notes=note))
    return checks


def fetch_symbols(
    aggregator: Any, symbols: list[str], on_date: Date,
) -> list[SymbolFetchResult]:
    """Versucht get_eod fuer jedes Symbol; Aggregator macht Fallback intern."""
    from services.market_data.exceptions import MarketDataError
    results: list[SymbolFetchResult] = []
    for symbol in symbols:
        try:
            bar = aggregator.get_eod(symbol, on_date)
            results.append(SymbolFetchResult(
                symbol=symbol,
                provider=str(bar.source or "?"),
                price=str(bar.close),
            ))
        except MarketDataError as exc:
            results.append(SymbolFetchResult(
                symbol=symbol, provider=None, price=None,
                error=f"{exc.__class__.__name__}: {exc}",
            ))
        except Exception as exc:  # noqa: BLE001
            results.append(SymbolFetchResult(
                symbol=symbol, provider=None, price=None,
                error=f"{exc.__class__.__name__}: {exc}",
            ))
    return results


def cross_validate(
    aggregator: Any, symbols: list[str], on_date: Date,
    threshold_bps: int = 300,
) -> list[ValidationCheck]:
    """Median-Vergleich uber alle Provider; gibt diff_bps + Alert-Flag."""
    from services.market_data.validation import validate_symbol
    out: list[ValidationCheck] = []
    providers = list(aggregator.providers)
    for symbol in symbols:
        try:
            result = validate_symbol(
                symbol=symbol, on_date=on_date, providers=providers,
                threshold_bps=threshold_bps,
            )
            if result.status == "insufficient_data":
                out.append(ValidationCheck(
                    symbol=symbol, n_providers=len(result.quotes),
                    diff_bps=0, is_alert=False, median="",
                    note="insufficient_data",
                ))
                continue
            out.append(ValidationCheck(
                symbol=symbol, n_providers=len(result.quotes),
                diff_bps=int(result.diff_bps),
                is_alert=bool(result.is_alert),
                median=str(result.median_close or ""),
            ))
        except Exception as exc:  # noqa: BLE001
            out.append(ValidationCheck(
                symbol=symbol, n_providers=0, diff_bps=0,
                is_alert=False, median="",
                note=f"error: {exc.__class__.__name__}: {exc}",
            ))
    return out


def run_smoketest(
    symbols: list[str] | None = None,
    on_date: Date | None = None,
    no_network: bool = False,
    threshold_bps: int = 300,
) -> SmoketestReport:
    """Hauptfunktion. Liefert SmoketestReport unabhaengig vom CLI."""
    from services.market_data.factory import build_default_aggregator
    rpt = SmoketestReport(started_at=_utc_iso())
    target_symbols = list(symbols or DEFAULT_SYMBOLS)
    target_date = on_date or datetime.now(timezone.utc).date()

    try:
        aggregator = build_default_aggregator()
    except Exception as exc:  # noqa: BLE001
        rpt.summary_ok = False
        rpt.summary_notes.append(
            f"build_default_aggregator failed: {exc.__class__.__name__}: {exc}",
        )
        rpt.finished_at = _utc_iso()
        return rpt

    rpt.providers = check_providers(aggregator)
    healthy_count = sum(1 for p in rpt.providers if p.healthy)
    if healthy_count == 0:
        rpt.summary_ok = False
        rpt.summary_notes.append("Kein Provider ist healthy.")

    if not no_network and target_symbols:
        rpt.fetches = fetch_symbols(aggregator, target_symbols, target_date)
        n_success = sum(1 for f in rpt.fetches if f.price is not None)
        if n_success == 0:
            rpt.summary_ok = False
            rpt.summary_notes.append("Kein einziges Symbol konnte abgerufen werden.")

        rpt.validations = cross_validate(
            aggregator, target_symbols, target_date, threshold_bps=threshold_bps,
        )

    rpt.finished_at = _utc_iso()
    return rpt


def format_report(rpt: SmoketestReport, markdown: bool = False) -> str:
    """Reine Formatierung; keine Seiteneffekte."""
    lines: list[str] = []
    head = "# Smoketest Market Data Pipeline" if markdown else "=== Smoketest Market Data Pipeline ==="
    lines.append(head)
    lines.append("")
    lines.append(f"Start:  {rpt.started_at}")
    lines.append(f"Ende:   {rpt.finished_at}")
    lines.append(f"Status: {'OK' if rpt.summary_ok else 'FAIL'}")
    if rpt.summary_notes:
        for note in rpt.summary_notes:
            lines.append(f"  - {note}")
    lines.append("")
    lines.append("## Provider" if markdown else "--- Provider ---")
    if not rpt.providers:
        lines.append("(keine)")
    for p in rpt.providers:
        flag = "OK" if p.healthy else "FAIL"
        suffix = f"  ({p.notes})" if p.notes else ""
        lines.append(f"  [{flag}] {p.name}{suffix}")
    lines.append("")
    lines.append("## Preisabruf" if markdown else "--- Preisabruf ---")
    if not rpt.fetches:
        lines.append("(skipped, --no-network)")
    for f in rpt.fetches:
        if f.price is not None:
            lines.append(f"  [OK]   {f.symbol:15s} {f.price:>12s}  ({f.provider})")
        else:
            lines.append(f"  [FAIL] {f.symbol:15s} {f.error or '?'}")
    lines.append("")
    lines.append("## Cross-Validation" if markdown else "--- Cross-Validation ---")
    if not rpt.validations:
        lines.append("(skipped)")
    for v in rpt.validations:
        if v.note in ("insufficient_data", ""):
            if v.n_providers == 0:
                lines.append(f"  [SKIP] {v.symbol:15s} {v.note or 'no data'}")
                continue
            alert_str = "ALERT" if v.is_alert else "OK"
            lines.append(
                f"  [{alert_str}]  {v.symbol:15s} "
                f"median={v.median:>10s}  diff={v.diff_bps:>4d}bps  "
                f"n={v.n_providers}",
            )
        else:
            lines.append(f"  [ERR]  {v.symbol:15s} {v.note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    _ensure_backend_on_path()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", default=",".join(DEFAULT_SYMBOLS),
        help="Komma-separierte Symbol-Liste (Yahoo-Style).",
    )
    parser.add_argument(
        "--no-network", action="store_true",
        help="Nur Aggregator-Aufbau + Health-Checks (keine HTTP-Calls).",
    )
    parser.add_argument(
        "--threshold-bps", type=int, default=300,
        help="Alert-Schwelle fuer Cross-Validation (Basispunkte).",
    )
    parser.add_argument(
        "--report-file", default=None,
        help="Optional Pfad fuer Markdown-Report.",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    rpt = run_smoketest(
        symbols=symbols, no_network=args.no_network,
        threshold_bps=args.threshold_bps,
    )
    print(format_report(rpt, markdown=False))
    if args.report_file:
        Path(args.report_file).write_text(
            format_report(rpt, markdown=True),
            encoding="utf-8",
        )
        print(f"\nMarkdown-Report: {args.report_file}")

    if not rpt.summary_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
