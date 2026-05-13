"""Pre-Flight-Check fuer den Aggregator-Switch.

Prueft die User-`.env` auf alles, was die Multi-Source-Datenpipeline
(P1-P20) zum Live-Betrieb braucht. Druckt einen klaren Bericht und
gibt einen Exit-Code zurueck.

Aufruf:
    python scripts/check_env_for_pipeline.py
    python scripts/check_env_for_pipeline.py --env-file /pfad/zu/.env

Exit-Codes:
    0 = Alles ok, aggregator-tauglich.
    1 = Mindestens ein WARN-Item — Pipeline funktioniert aber suboptimal.
    2 = ERROR — Pipeline wird nicht funktionieren (z.B. Aggregator aktiv,
        aber kein einziger gratis-Provider konfiguriert).

Idempotent. Liest die .env nur, schreibt nirgends.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Finding:
    level: str  # "OK", "WARN", "ERROR"
    setting: str
    message: str


def _read_env(path: Path) -> dict[str, str]:
    """Minimaler dotenv-Parser. Kein Escape, kein Multi-Line."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _env_or_default(env: dict[str, str], key: str, default: str = "") -> str:
    raw = env.get(key)
    if raw is not None:
        return raw
    return os.environ.get(key, default)


def check_pipeline_config(env: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []

    primary = _env_or_default(env, "PRICE_REFRESH_PRIMARY_PROVIDER", "yfinance").lower()
    fallback = _env_or_default(env, "PRICE_REFRESH_FALLBACK_PROVIDER", "stooq").lower()
    providers_raw = _env_or_default(env, "MARKET_DATA_PROVIDERS",
                                    "yfinance,stooq,alphavantage").lower()
    providers = [p.strip() for p in providers_raw.split(",") if p.strip()]

    aggregator_mode = primary == "aggregator" or fallback == "aggregator"
    if aggregator_mode:
        findings.append(Finding("OK", "PRICE_REFRESH_PRIMARY_PROVIDER",
                                f"Aggregator-Modus aktiv (primary={primary}, fallback={fallback})"))
    else:
        findings.append(Finding(
            "WARN", "PRICE_REFRESH_PRIMARY_PROVIDER",
            f"Aggregator nicht aktiv (primary={primary}). Setze =aggregator um die Multi-Source-Pipeline zu nutzen.",
        ))

    if not providers:
        findings.append(Finding("ERROR", "MARKET_DATA_PROVIDERS",
                                "Leere Provider-Liste."))
    else:
        findings.append(Finding("OK", "MARKET_DATA_PROVIDERS",
                                f"Fallback-Chain: {' -> '.join(providers)}"))
        for p in providers:
            if p not in {"yfinance", "stooq", "alphavantage", "twelvedata"}:
                findings.append(Finding(
                    "WARN", "MARKET_DATA_PROVIDERS",
                    f"Provider '{p}' nicht im bekannten Set "
                    f"(yfinance/stooq/alphavantage/twelvedata).",
                ))

    if "alphavantage" in providers:
        if _env_or_default(env, "ALPHAVANTAGE_API_KEY"):
            findings.append(Finding("OK", "ALPHAVANTAGE_API_KEY", "vorhanden"))
        else:
            findings.append(Finding(
                "WARN", "ALPHAVANTAGE_API_KEY",
                "alphavantage in Provider-Chain, aber kein Key gesetzt — Provider wird als unhealthy markiert.",
            ))

    if "twelvedata" in providers:
        if _env_or_default(env, "TWELVEDATA_API_KEY"):
            findings.append(Finding("OK", "TWELVEDATA_API_KEY", "vorhanden"))
        else:
            findings.append(Finding(
                "WARN", "TWELVEDATA_API_KEY",
                "twelvedata in Provider-Chain, aber kein Key gesetzt — Provider wird als unhealthy markiert.",
            ))

    if aggregator_mode and not any(
        p in providers for p in ("yfinance", "stooq", "alphavantage", "twelvedata")
    ):
        findings.append(Finding(
            "ERROR", "MARKET_DATA_PROVIDERS",
            "Aggregator-Modus aktiv, aber kein einziger bekannter Provider in der Chain.",
        ))

    return findings


def check_scheduler_config(env: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    scheduler_on = _env_or_default(env, "PRICE_SCHEDULER_ENABLED", "true").lower() == "true"
    if scheduler_on:
        findings.append(Finding("OK", "PRICE_SCHEDULER_ENABLED", "Scheduler aktiv"))
    else:
        findings.append(Finding(
            "WARN", "PRICE_SCHEDULER_ENABLED",
            "Scheduler aus — Cache-Purge und Validation laufen nicht automatisch.",
        ))

    cache_purge = _env_or_default(env, "MARKET_DATA_CACHE_PURGE_ENABLED", "true").lower() == "true"
    if cache_purge:
        findings.append(Finding("OK", "MARKET_DATA_CACHE_PURGE_ENABLED",
                                "Daily Cache-Purge aktiv"))
    else:
        findings.append(Finding("WARN", "MARKET_DATA_CACHE_PURGE_ENABLED",
                                "Cache-Purge aus — abgelaufene Eintraege bleiben in DB liegen."))

    validation = _env_or_default(env, "MARKET_DATA_VALIDATION_ENABLED", "false").lower() == "true"
    if validation:
        syms_raw = _env_or_default(env, "MARKET_DATA_VALIDATION_SYMBOLS", "")
        syms = [s.strip() for s in syms_raw.split(",") if s.strip()]
        if not syms:
            findings.append(Finding(
                "WARN", "MARKET_DATA_VALIDATION_SYMBOLS",
                "Validation aktiv, aber Symbol-Liste leer. Validation skippt.",
            ))
        else:
            findings.append(Finding(
                "OK", "MARKET_DATA_VALIDATION_SYMBOLS",
                f"{len(syms)} Symbole konfiguriert",
            ))
    else:
        findings.append(Finding(
            "OK", "MARKET_DATA_VALIDATION_ENABLED",
            "Validation aus (default — opt-in via =true).",
        ))

    return findings


def run_checks(env_path: Path) -> tuple[list[Finding], int]:
    env = _read_env(env_path)
    findings: list[Finding] = []
    findings.extend(check_pipeline_config(env))
    findings.extend(check_scheduler_config(env))

    has_error = any(f.level == "ERROR" for f in findings)
    has_warn = any(f.level == "WARN" for f in findings)
    if has_error:
        return findings, 2
    if has_warn:
        return findings, 1
    return findings, 0


def format_findings(findings: Iterable[Finding], env_path: Path) -> str:
    lines = []
    lines.append("=== Pipeline Pre-Flight Check ===")
    lines.append(f".env-Pfad: {env_path}")
    lines.append("")
    for f in findings:
        prefix = {
            "OK": "[ OK  ]",
            "WARN": "[WARN ]",
            "ERROR": "[ERROR]",
        }.get(f.level, "[ ??  ]")
        lines.append(f"{prefix} {f.setting:42s} {f.message}")
    lines.append("")
    n_ok = sum(1 for f in findings if f.level == "OK")
    n_warn = sum(1 for f in findings if f.level == "WARN")
    n_err = sum(1 for f in findings if f.level == "ERROR")
    lines.append(f"Summary: {n_ok} OK, {n_warn} WARN, {n_err} ERROR")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", default=None,
        help="Pfad zur .env-Datei (default: 5eyes-backend/.env oder ./.env)",
    )
    args = parser.parse_args(argv)

    if args.env_file:
        env_path = Path(args.env_file)
    else:
        here = Path(__file__).resolve()
        candidates = [
            here.parent.parent / "5eyes-backend" / ".env",
            here.parent.parent / ".env",
            Path.cwd() / ".env",
        ]
        env_path = next((c for c in candidates if c.exists()), candidates[0])

    findings, exit_code = run_checks(env_path)
    print(format_findings(findings, env_path))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
