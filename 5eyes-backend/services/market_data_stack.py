from __future__ import annotations

from pathlib import Path
from typing import Any

from config import resolve_env_file, settings


PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "yfinance": {
        "label": "Yahoo Finance via yfinance",
        "automation_fit": "hoch",
        "api_key_required": False,
        "contract_required": False,
        "scope": "Community-basierter Preisabruf fuer Bewertung, Drift und Rebalancing in V1.",
    },
    "stooq": {
        "label": "Stooq CSV",
        "automation_fit": "hoch",
        "api_key_required": False,
        "contract_required": False,
        "scope": "Leichter Fallback fuer EOD-Preise einzelner Ticker.",
    },
    "local_catalog": {
        "label": "Lokaler Produktkatalog",
        "automation_fit": "hoch",
        "api_key_required": False,
        "contract_required": False,
        "scope": "Kuratiertes Override fuer Produktnamen, Proxies und synthetische Par-Werte.",
    },
    "product_symbol_or_isin": {
        "label": "Produkt-Stammdaten (Symbol/ISIN)",
        "automation_fit": "hoch",
        "api_key_required": False,
        "contract_required": False,
        "scope": "Direkte Zuordnung aus gepflegten Produktstammdaten.",
    },
    "manual_cma": {
        "label": "Manuell versionierte Kapitalmarktannahmen",
        "automation_fit": "mittel",
        "api_key_required": False,
        "contract_required": False,
        "scope": "Aktiver V1-Pfad fuer Capital Market Assumptions und House-Matrix-Logik.",
    },
    "twelvedata": {
        "label": "Twelve Data",
        "automation_fit": "hoch",
        "api_key_required": True,
        "api_key_setting": "twelvedata_api_key",
        "contract_required": False,
        "scope": "Breite Multi-Asset-Preisversorgung inklusive REST und WebSocket.",
    },
    "eodhd": {
        "label": "EODHD",
        "automation_fit": "hoch",
        "api_key_required": True,
        "api_key_setting": "eodhd_api_key",
        "contract_required": False,
        "scope": "Fund-, Referenz-, Corporate-Action- und Mapping-nahe Daten.",
    },
    "openfigi": {
        "label": "OpenFIGI",
        "automation_fit": "hoch",
        "api_key_required": False,
        "api_key_optional": True,
        "api_key_setting": "openfigi_api_key",
        "contract_required": False,
        "scope": "ISIN-, FIGI- und Symbol-Mapping fuer saubere Master-Data-Pfade.",
    },
    "fred": {
        "label": "FRED",
        "automation_fit": "hoch",
        "api_key_required": True,
        "api_key_setting": "fred_api_key",
        "contract_required": False,
        "scope": "Globale Makrozeitreihen, Zinsen und vintagierbare Observationsdaten.",
    },
    "ecb": {
        "label": "ECB Data Portal",
        "automation_fit": "hoch",
        "api_key_required": False,
        "contract_required": False,
        "scope": "Offizielle Eurozonen- und FX-Serien via SDMX REST.",
    },
    "snb": {
        "label": "SNB Datenportal",
        "automation_fit": "hoch",
        "api_key_required": False,
        "contract_required": False,
        "scope": "Offizielle Schweizer Zins-, FX- und Konjunkturzeitreihen.",
    },
    "six": {
        "label": "SIX Financial Information",
        "automation_fit": "mittel",
        "api_key_required": True,
        "api_key_setting": "six_api_key",
        "contract_required": True,
        "scope": "Enterprise-Qualitaet fuer Pricing, Referenzdaten und Schweiz-lastige Wertpapiere.",
    },
    "polygon": {
        "label": "Polygon / Massive",
        "automation_fit": "hoch",
        "api_key_required": True,
        "contract_required": False,
        "scope": "Optionaler Low-Latency-Upgrade-Pfad fuer US-lastige Echtzeitdaten.",
    },
}


def _provider_meta(name: str | None) -> dict[str, Any] | None:
    key = str(name or "").strip().lower()
    if not key:
        return None
    entry = PROVIDER_CATALOG.get(key)
    if entry is None:
        return {
            "name": key,
            "label": key,
            "automation_fit": "unbekannt",
            "api_key_required": False,
            "api_key_optional": False,
            "api_key_present": None,
            "contract_required": False,
            "configured": True,
            "scope": None,
        }
    api_key_setting = entry.get("api_key_setting")
    api_key_present = bool(getattr(settings, str(api_key_setting), None)) if api_key_setting else None
    api_key_required = bool(entry.get("api_key_required"))
    api_key_optional = bool(entry.get("api_key_optional"))
    contract_required = bool(entry.get("contract_required"))
    configured = True
    if api_key_required:
        configured = bool(api_key_present)
    elif api_key_optional:
        configured = True
    if contract_required and not api_key_present:
        configured = False
    return {
        "name": key,
        "label": entry.get("label") or key,
        "automation_fit": entry.get("automation_fit") or "unbekannt",
        "api_key_required": api_key_required,
        "api_key_optional": api_key_optional,
        "api_key_present": api_key_present,
        "contract_required": contract_required,
        "configured": configured,
        "scope": entry.get("scope"),
    }


def _resolved_env_path() -> Path:
    candidate = Path(resolve_env_file())
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def _role_payload(
    *,
    label: str,
    current_primary: str | None,
    current_fallback: str | None = None,
    target_primary: str | None,
    target_fallback: str | None = None,
    current_wired: bool,
    target_wired: bool,
    notes: str,
) -> dict[str, Any]:
    return {
        "label": label,
        "notes": notes,
        "current": {
            "wired": current_wired,
            "primary": _provider_meta(current_primary),
            "fallback": _provider_meta(current_fallback),
        },
        "target": {
            "wired": target_wired,
            "primary": _provider_meta(target_primary),
            "fallback": _provider_meta(target_fallback),
        },
    }


def _provider_requirement_issue(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    if meta.get("contract_required") and not meta.get("api_key_present"):
        return "Vertrag/API-Key fehlt"
    if meta.get("api_key_required") and not meta.get("api_key_present"):
        return "API-Key fehlt"
    return None


def _provider_operational_warning(role_name: str, meta: dict[str, Any] | None, *, is_fallback: bool) -> str | None:
    if not meta:
        return None
    provider_name = str(meta.get("name") or "").strip().lower()
    if role_name == "market_prices" and provider_name == "yfinance":
        return "Yahoo Finance ist ein Community-Feed und kann im Live-Betrieb rate-limitiert sein."
    if role_name == "market_prices" and provider_name == "stooq":
        return (
            "Stooq ist nur ein Best-Effort-EOD-Fallback und fuer Schweiz-/internationale Titel nicht durchgaengig verlaesslich."
            if is_fallback
            else "Stooq ist nur ein Best-Effort-EOD-Feed und fuer institutionelle Produktuniversen nicht das Zielbild."
        )
    if role_name == "reference_data" and provider_name == "local_catalog":
        return "Referenzdaten laufen aktuell ueber den lokalen Produktkatalog; Corporate Actions und Fondsmetadaten sind damit noch nicht vollautomatisch."
    if role_name == "id_mapping" and provider_name == "product_symbol_or_isin":
        return "Identifier-Mapping nutzt aktuell nur gepflegte Produktstammdaten; externer ISIN/FIGI-Abgleich ist noch nicht vollaktiv."
    if role_name.startswith("macro") and provider_name == "manual_cma":
        return "Makroannahmen sind aktuell manuell versioniert; offizielle Zeitreihenfeeds sind noch nicht live verdrahtet."
    return None


def get_market_data_setup_status(provider_roles: dict[str, Any] | None = None) -> dict[str, Any]:
    roles = provider_roles or get_market_data_provider_roles()
    env_path = _resolved_env_path()
    current_missing: list[dict[str, Any]] = []
    target_missing: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not env_path.exists():
        warnings.append("Keine Backend-.env gefunden; externe Provider laufen nur mit Prozessvariablen oder spaeter gesetzten Keys.")

    for role_name, role in roles.items():
        role_label = str(role.get("label") or role_name)
        for stage_name in ("current", "target"):
            stage = role.get(stage_name) or {}
            stage_wired = bool(stage.get("wired"))
            if stage_name == "current" and not stage_wired:
                continue
            for slot_name in ("primary", "fallback"):
                meta = stage.get(slot_name)
                if not meta:
                    continue
                issue = _provider_requirement_issue(meta)
                warning = _provider_operational_warning(role_name, meta, is_fallback=(slot_name == "fallback"))
                if warning and warning not in warnings:
                    warnings.append(warning)
                if not issue:
                    continue
                payload = {
                    "role": role_name,
                    "role_label": role_label,
                    "stage": stage_name,
                    "slot": slot_name,
                    "provider": meta.get("name"),
                    "provider_label": meta.get("label"),
                    "issue": issue,
                }
                if stage_name == "current":
                    current_missing.append(payload)
                else:
                    target_missing.append(payload)
                    message = f"{role_label}: {meta.get('label')} ({slot_name}) {issue.lower()}."
                    if message not in warnings:
                        warnings.append(message)

    return {
        "env_file": str(env_path),
        "env_file_exists": env_path.exists(),
        "current_ready": not current_missing,
        "target_key_ready": not target_missing,
        "current_missing_requirements": current_missing,
        "target_missing_requirements": target_missing,
        "warnings": warnings,
    }


def get_market_data_provider_roles() -> dict[str, Any]:
    return {
        "market_prices": _role_payload(
            label="Marktpreise Bewertung/Rebalancing",
            current_primary=settings.price_refresh_primary_provider,
            current_fallback=settings.price_refresh_fallback_provider,
            target_primary=settings.target_market_price_provider,
            target_fallback=settings.target_reference_data_provider,
            current_wired=True,
            target_wired=False,
            notes="Aktive Runtime fuer Preisrefresh, Drift und Rebalancing; Zielbild fuer breitere Multi-Asset-Abdeckung.",
        ),
        "reference_data": _role_payload(
            label="Referenzdaten Fonds/Produkte",
            current_primary=settings.reference_data_active_provider,
            current_fallback=None,
            target_primary=settings.target_reference_data_provider,
            target_fallback=settings.target_enterprise_reference_provider,
            current_wired=True,
            target_wired=False,
            notes="Produktnahe Stammdaten, Corporate Actions und Fonds-/ETF-Metadaten.",
        ),
        "id_mapping": _role_payload(
            label="Identifier- und Symbol-Mapping",
            current_primary=settings.id_mapping_active_provider,
            current_fallback=settings.reference_data_active_provider,
            target_primary=settings.target_id_mapping_provider,
            target_fallback=settings.target_reference_data_provider,
            current_wired=True,
            target_wired=False,
            notes="Saubere Uebersetzung zwischen ISIN, FIGI, Ticker und internen Produktobjekten.",
        ),
        "macro_core": _role_payload(
            label="Makrodaten global / Eurozone",
            current_primary=settings.macro_assumptions_active_provider,
            current_fallback=None,
            target_primary=settings.target_macro_core_provider,
            target_fallback=settings.target_macro_euro_provider,
            current_wired=True,
            target_wired=False,
            notes="Makroserien fuer Zinsen, Inflation, Wachstumsannahmen und FX-Kontext.",
        ),
        "macro_switzerland": _role_payload(
            label="Makrodaten Schweiz",
            current_primary=settings.macro_assumptions_active_provider,
            current_fallback=None,
            target_primary=settings.target_macro_swiss_provider,
            target_fallback=settings.target_macro_core_provider,
            current_wired=True,
            target_wired=False,
            notes="Schweizer offizielle Serien fuer CHF-, SNB- und Konjunkturkontext.",
        ),
        "enterprise_reference": _role_payload(
            label="Institutioneller Schweiz-/Enterprise-Feed",
            current_primary=None,
            current_fallback=None,
            target_primary=settings.target_enterprise_reference_provider,
            target_fallback=None,
            current_wired=False,
            target_wired=False,
            notes="Optionaler Upgrade-Pfad fuer SIX-/Enterprise-Qualitaet in produktiven Bank-Setups.",
        ),
    }
