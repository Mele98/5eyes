from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import base64
import ctypes
import hmac
import os
import secrets
import sys
import tempfile

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import core.db_location as _db_location


DEFAULT_SECRET_KEY = "CHANGE_ME_IN_PRODUCTION_USE_STRONG_RANDOM_KEY"

# CERT-OPTIMIZER-OBJECTIVE-001 / OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001
# (docs/audits/2026-10-08-optimizer-objective-evidence-and-goal-weighting-
# certification-spec.md, Sec. 6.1): the goal-weighting mode that drives the
# stochastic optimizer's objective mathematics (up to 50x between a "hart"
# and an "opportunistisch" goal, see services/optimizer/objective.py
# HARDNESS_WEIGHT) used to be read ad-hoc via
# ``os.environ.get("OPTIMIZER_GOAL_WEIGHTING", "equal")`` with ANY
# unrecognized value (typo, empty string, ...) silently collapsing to the
# "equal" default -- no error, no warning, indistinguishable from an unset
# variable. This is the single, centrally validated, fail-closed definition
# of the allowed values; both the typed Settings field below and
# services.optimizer.objective.resolve_goal_weighting_mode() call it so
# there is exactly one place that decides what a legal value is.
GOAL_WEIGHTING_MODES = ("equal", "hardness")
# GOAL-HARDNESS-DEFAULT-001 (CIO-Entscheid 2026-10-18, Engine
# ``saa_resampled_v7``): der Haertegrad wirkt standardmaessig. Vorher war
# "equal" der Default (ADR-011 Entscheid 2, "Mittelung" der Referenzmethodik), womit ein
# als "hart" erfasstes Ziel rechnerisch identisch mit "primaer" war, obwohl
# die Erfassungsmaske die Wahl anbietet. "equal" bleibt als expliziter
# Opt-out erhalten. Begruendung: docs/planning/2026-10-18-maximize-goal-and-
# hardness.md; Gewichte und Wirkung: services/optimizer/objective.py
# (HARDNESS_WEIGHT, GOAL_HARDNESS_POLICY_VERSION).
DEFAULT_GOAL_WEIGHTING_MODE = "hardness"


def validate_goal_weighting_mode(raw: str | None) -> str:
    """Normalize + fail-closed validate OPTIMIZER_GOAL_WEIGHTING.

    - Unset (``None``) resolves to the documented default
      ``DEFAULT_GOAL_WEIGHTING_MODE`` (``"hardness"`` since
      GOAL-HARDNESS-DEFAULT-001; ``"equal"`` before).
    - Any other value is trimmed and lower-cased before comparison, so
      ``" EQUAL "`` / ``"HARDNESS"`` canonicalize to their lowercase form.
    - Anything else -- including an explicit empty/whitespace-only string
      and a typo such as ``"hardnes"`` -- raises ``ValueError`` instead of
      silently falling back to ``"equal"``. A misconfiguration must be loud,
      never indistinguishable from "unset".
    """
    if raw is None:
        return DEFAULT_GOAL_WEIGHTING_MODE
    normalized = raw.strip().lower()
    if normalized not in GOAL_WEIGHTING_MODES:
        raise ValueError(
            "OPTIMIZER_GOAL_WEIGHTING="
            f"{raw!r} is not a recognized goal-weighting mode. Allowed: "
            f"{', '.join(GOAL_WEIGHTING_MODES)} (leave unset for the "
            f"documented default {DEFAULT_GOAL_WEIGHTING_MODE!r})."
        )
    return normalized


# OPTIMIZER-OBJECTIVE-VARIANTS-001: zulaessige Primaerterme der Zielfunktion.
# Gleiches Muster und derselbe Grund wie GOAL_WEIGHTING_MODES eine Ebene
# hoeher -- genau eine Stelle entscheidet, was ein legaler Wert ist, und ein
# Tippfehler ist laut, nicht stillschweigend der Default.
#
# "goal_shortfall" ist der dokumentierte Default und die Methodik, auf die
# die gesamte Zielerreichungs-/Zertifizierungsschicht aufbaut. Die uebrigen
# Varianten ERSETZEN nur den Primaerterm; die Goal-Chance-Penalty bleibt in
# JEDER Variante aktiv (siehe services/optimizer/objective_variants.py), damit
# eine Risikomass-Optimierung nie eine Allokation ohne Ziel-Untergrenze
# liefert.
OBJECTIVE_MODES = (
    "goal_shortfall",
    "cvar_return",
    "max_drawdown",
    "min_volatility",
    "max_return",
)


def validate_objective_mode(raw: str | None) -> str:
    """Normalize + fail-closed validate OPTIMIZER_OBJECTIVE.

    - Unset (``None``) resolves to the documented default ``"goal_shortfall"``.
    - Any other value is trimmed and lower-cased before comparison.
    - Anything else -- including an explicit empty/whitespace-only string and
      a typo such as ``"max_drowdown"`` -- raises ``ValueError`` instead of
      silently falling back. Which mathematics produced an allocation must
      never be indistinguishable from "unset".
    """
    if raw is None:
        return "goal_shortfall"
    normalized = raw.strip().lower()
    if normalized not in OBJECTIVE_MODES:
        raise ValueError(
            "OPTIMIZER_OBJECTIVE="
            f"{raw!r} is not a recognized objective mode. Allowed: "
            f"{', '.join(OBJECTIVE_MODES)} (leave unset for the documented "
            "default 'goal_shortfall')."
        )
    return normalized


def resolve_env_file() -> str:
    env_override = Path.cwd() / '.env'
    candidates = []
    if getattr(sys, '_MEIPASS', None):
        candidates.extend([
            Path(sys.executable).resolve().parent / '.env',
            Path(getattr(sys, '_MEIPASS')).resolve() / '.env',
        ])
    module_dir = Path(__file__).resolve().parent
    candidates.extend([
        env_override,
        module_dir / '.env',
        module_dir.parent / '.env',
    ])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return '.env'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=resolve_env_file(),
        env_file_encoding='utf-8',
        extra='ignore',
    )

    app_name: str = 'Ares API'
    app_version: str = '1.3.0'
    app_env: str = 'development'
    app_host: str = '127.0.0.1'
    app_port: int = 8000
    log_level: str = 'INFO'
    log_max_bytes: int = 2_000_000
    log_backup_count: int = 5

    # Database
    database_url: str | None = None
    # Default aus EINER Quelle (core/db_location.py); die Live-DB-Waechter
    # vergleichen gegen dieselbe Funktion.
    db_path: str = Field(default_factory=lambda: str(_db_location.default_db_path()))
    db_echo: bool = False
    db_key: str | None = None
    db_use_sqlcipher: bool = False
    db_bootstrap_schema_on_startup: bool = True

    # U-43 (Roadmap-Punkt 43, 2026-06-01): Log-Verzeichnis explizit
    # konfigurierbar. Vorher: gekoppelt an db_path.parent — sub-optimal
    # in packaged Electron (DB sollte ggf. in Backup-Volume liegen,
    # Logs aber in app.getPath('userData')/logs).
    # Leer = Fallback auf Path(db_path).parent (backwards-compat).
    log_dir: str = ''

    # Auth
    secret_key: str = DEFAULT_SECRET_KEY
    algorithm: str = 'HS256'
    access_token_expire_minutes: int = 480
    # Roadmap #28 (Standpunkt 2026-08-07): Refresh-Token-Rotation. Deutlich
    # laenger als access_token_expire_minutes -- der Sinn eines Refresh-Tokens
    # ist gerade, ein KURZES Access-Token (kleines Leck-Zeitfenster) mit einem
    # LANGEN, aber rotierenden (Reuse-Detection) Refresh-Token zu kombinieren,
    # statt ein einzelnes langlebiges Access-Token zu haben.
    refresh_token_expire_days: int = 30
    # AF-6 (2026-10-23): Token-Bindung an diese Installation. Jedes Access-
    # Token traegt iss/aud (Payload) und kid (Header); die Validierung
    # verlangt exakt diese Werte. Bewusste Wirkung beim Einfuehren bzw. beim
    # Aendern eines Werts: alle bisher ausgestellten Access-Tokens werden
    # abgelehnt -> einmalige Neuanmeldung. jwt_key_id benennt die Version
    # von secret_key; beim Schluesselwechsel mitwechseln.
    jwt_issuer: str = 'local-advisory-backend'
    jwt_audience: str = 'advisory-app'
    jwt_key_id: str = 'k1'
    # AF-6: globale Widerrufs-Untergrenze (ISO-8601 UTC, z.B.
    # 2026-10-23T12:00:00.000Z). Jedes Access-Token mit iat davor und jedes
    # Refresh-Token mit created_at davor wird abgelehnt -- fuer alle
    # Benutzer, ohne DB-Schreibzugriff. Leer = aus. Ergaenzt den
    # Widerruf je Benutzer (users.token_revoked_before).
    token_revoked_before: str | None = None
    login_rate_limit_enabled: bool = True
    login_max_attempts: int = 5
    login_window_seconds: int = 60
    login_lockout_seconds: int = 600
    # AUTH-03 (Mega-Audit 2026-08-04): X-Forwarded-For wurde bisher IMMER als
    # Klartext-Wahrheit fuer den Rate-Limit-Guard-Key genommen -- ohne einen
    # tatsaechlich davorstehenden Reverse-Proxy kann JEDER Client den Header
    # selbst setzen und bekommt pro Request einen frischen Guard-Key (voller
    # Rate-Limit-Bypass auf Login/Bootstrap-Admin/Password-Reset/Invite).
    # trusted_proxy_count = Anzahl der Reverse-Proxy-Hops, denen VOR dieser
    # Instanz vertraut wird. 0 (Default, Tier-1 ohne Proxy) = XFF komplett
    # ignorieren, echte TCP-Peer-Adresse (request.client.host) verwenden.
    # >0 (Tier-2/3 hinter N Reverse-Proxies): Rightmost-Hop-Parsing -- der
    # N-te Eintrag von RECHTS ist der echte Client, alles rechts davon sind
    # die eigenen (vertrauenswuerdigen) Proxy-Hops.
    trusted_proxy_count: int = 0

    # RESOURCE-003 (Codex-Audit 2026-08-27): die zwei schreibenden
    # Solver-Endpunkte (target-allocation/generate, .../sensitivity) hatten
    # keine Kapazitaetsgrenze -- ein fehlerhafter/boesartiger Advisor-Client
    # konnte beliebig viele teure NumPy-Modelllaeufe gleichzeitig anstossen
    # und damit die CPU/Speicher der Webworker fuer alle anderen Mandanten
    # verdraengen. solver_max_concurrent begrenzt die PROZESSWEITE (nicht
    # per-Tenant-faire) Anzahl gleichzeitig laufender Solver-Aufrufe; darueber
    # hinausgehende Requests werden VOR dem Datenladen mit 429 abgelehnt.
    solver_max_concurrent: int = 4

    # CORS / Electron
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            'null',
            'http://localhost:3000',
            'http://localhost:5173',
            'http://127.0.0.1:3000',
            'http://127.0.0.1:5173',
            'app://.',
        ]
    )
    cors_allow_origin_regex: str | None = r'^null$'
    # 2026-07-25 (Generalaudit): Passwort-Reset-/Invite-Links wurden bisher aus
    # dem (Client-kontrollierten!) Host/X-Forwarded-Host-Header konstruiert --
    # Host-Header-Injection auf dem OEFFENTLICHEN, unauthentifizierten
    # /auth/password-reset/request-Endpoint erlaubte einen gueltigen Reset-
    # Link auf eine Phishing-Domain fuer die HINTERLEGTE (echte) E-Mail-Adresse
    # des Opfers zu versenden (klassisches "Password-Reset-Poisoning"). Ist
    # public_base_url gesetzt, wird IMMER dieser vertrauenswuerdige Wert
    # genutzt (Header ignoriert). Fuer jede extern erreichbare Installation
    # (Tier 2/3, Browser-Hosting) MUSS dies konfiguriert werden. Bleibt NULL
    # (Tier-1-Desktop-Default, kein externer Zugriff), bleibt das bisherige
    # Header-Fallback-Verhalten unveraendert.
    public_base_url: str | None = None

    # Price refresh
    price_scheduler_enabled: bool = True
    price_scheduler_timezone: str = 'Europe/Zurich'
    price_scheduler_hour: int = 6
    price_scheduler_minute: int = 0
    price_refresh_max_attempts: int = 2
    price_refresh_retry_delay_seconds: float = 1.0
    # Mega-Audit (2026-08-04): der Stooq-Fallback-Batch-Loop
    # (price_updater._fetch_stooq_symbol_points) feuerte bisher eine
    # ungebremste Serie von HTTP-GETs ab -- am staerksten genau dann, wenn
    # der PRIMARY-Provider (yfinance) bereits ausfaellt und ALLE Symbole auf
    # Stooq zurueckfallen. Kleine feste Pause zwischen Requests, Default
    # konservativ (nicht gemessen, siehe PR-Kommentar).
    stooq_batch_throttle_seconds: float = 0.3

    # Market data provider strategy
    price_refresh_primary_provider: str = 'yfinance'
    price_refresh_fallback_provider: str = 'stooq'
    reference_data_active_provider: str = 'local_catalog'
    id_mapping_active_provider: str = 'product_symbol_or_isin'
    macro_assumptions_active_provider: str = 'manual_cma'
    target_market_price_provider: str = 'twelvedata'
    target_reference_data_provider: str = 'eodhd'
    target_id_mapping_provider: str = 'openfigi'
    target_macro_core_provider: str = 'fred'
    target_macro_euro_provider: str = 'ecb'
    target_macro_swiss_provider: str = 'snb'
    target_enterprise_reference_provider: str = 'six'
    twelvedata_api_key: str | None = None
    eodhd_api_key: str | None = None
    openfigi_api_key: str | None = None
    fred_api_key: str | None = None
    six_api_key: str | None = None
    alphavantage_api_key: str | None = None

    # V3 Sprint 2026-05 (Multi-Source Data Aggregator).
    # Komma-separierte Reihenfolge der Provider; erste = Primary.
    # Gueltige Werte: yfinance, stooq, alphavantage, twelvedata
    # Default: yfinance,stooq,alphavantage (gratis-only, Tier 1)
    market_data_providers: str = 'yfinance,stooq,alphavantage'
    market_data_unhealthy_ttl_seconds: int = 300

    # P15 — Scheduler-Hooks fuer Cache-Purge und Cross-Validation.
    # daily_cache_purge laeuft taeglich 03:00 lokal (purgt expired Cache-Eintraege).
    # weekly_validation laeuft sonntags 04:00 lokal (Median-Vergleich Provider).
    market_data_cache_purge_enabled: bool = True
    market_data_cache_purge_hour: int = 3
    market_data_cache_purge_minute: int = 0
    market_data_validation_enabled: bool = False
    market_data_validation_hour: int = 4
    market_data_validation_minute: int = 0
    market_data_validation_day_of_week: str = 'sun'
    market_data_validation_symbols: str = ''  # kommaseparierte Liste
    market_data_validation_threshold_bps: int = 300
    market_data_daily_refresh_enabled: bool = True
    # Mega-Audit (2026-08-04): lag per Werkseinstellung exakt auf derselben
    # Uhrzeit wie price_scheduler_hour/minute (06:00:00) -- beide Jobs feuerten
    # zeitgleich gegen dieselben unauthentifizierten Provider (yfinance/stooq)
    # und verdoppelten die Last genau im Risiko-Zeitfenster. 20 Min. Versatz
    # entzerrt das, ohne die Jobs inhaltlich zu aendern.
    market_data_daily_refresh_hour: int = 6
    market_data_daily_refresh_minute: int = 20
    market_data_daily_refresh_max_symbols: int = 500

    # P22 — Webhook-Notifier fuer Validation-Alerts. Default leer = no-op.
    market_data_alert_webhook_url: str = ''
    market_data_alert_webhook_timeout_seconds: float = 5.0

    # System / diagnostics
    recent_log_lines_default: int = 120
    recent_log_lines_max: int = 500

    # Sprint U-7 (2026-06-04): Content-Security-Policy + Permissions-Policy.
    csp_enabled: bool = True
    csp_policy: str = ''
    permissions_policy_enabled: bool = True
    hsts_enabled: bool = False

    # RESOURCE-001 (Codex-Audit 2026-08-27, docs/audits/2026-08-27-request-
    # ingestion-and-resource-governance-audit.md): globale Obergrenze fuer
    # eingehende Request-Bodies, durchgesetzt von core.middleware.
    # MaxBodySizeMiddleware BEVOR FastAPI/Starlette JSON oder Multipart
    # parst. Vorher gab es ausser CORS+RequestContext keine Body-Schranke --
    # ein unauthentifizierter Client konnte z.B. gegen den oeffentlichen
    # /auth/password-reset/request-Endpoint einen beliebig grossen Body
    # senden und wurde erst NACH vollstaendigem Puffern/Parsen abgelehnt.
    # Default 10 MiB ist grosszuegig bemessen relativ zum groessten bekannten
    # legitimen Payload (Fondsuniversum-CSV-Import, hart auf 2 MiB begrenzt,
    # siehe routers/review.py::_PRODUCT_IMPORT_MAX_FILE_BYTES) und dem
    # Bulk-JSON-Produktimport (max. 1000 Fonds), laesst aber genug Bounded-
    # Headroom fuer normales Wachstum, ohne unbegrenzt zu sein.
    max_request_body_bytes: int = 10 * 1024 * 1024

    # Sprint U-64 (2026-06-04): Telemetrie-Adapter (opt-in).
    telemetry_enabled: bool = False
    telemetry_dsn: str = ''
    telemetry_environment: str = ''
    telemetry_sample_rate: float = 1.0

    # U-8 — DB-Backup-Strategie (PR #106).
    backup_enabled: bool = True
    backup_dir: str = str(Path.home() / 'ares' / 'backups')
    backup_retain_days: int = 30
    backup_keep_minimum: int = 3
    backup_scheduler_enabled: bool = True
    backup_scheduler_timezone: str = 'Europe/Zurich'
    backup_scheduler_hour: int = 3
    backup_scheduler_minute: int = 0

    # Roadmap #15 (Off-Site-Backup-Replikation, 2026-08-07): das lokale,
    # verschluesselte SQLCipher-Backup (siehe backup_dir oben) schuetzt nicht
    # gegen einen Ausfall des Standorts selbst (Hardware/RZ-Ausfall). Opt-in
    # Kopie via rsync-ueber-SSH an einen zweiten CH-Standort. Default AUS --
    # erfordert einen bereits eingerichteten SSH-Zugang zum Ziel-Host.
    backup_offsite_enabled: bool = False
    # rsync-Zielangabe, z.B. "ares-offsite@backup-host.example:/srv/ares-offsite/"
    backup_offsite_target: str = ''
    backup_offsite_ssh_key_path: str = ''
    backup_offsite_ssh_port: int = 22
    # Sekunden, nach denen ein haengender rsync-Versuch abgebrochen wird --
    # ein Netzwerk-Hang darf den Backup-Scheduler nie blockieren.
    backup_offsite_timeout_seconds: int = 120

    # BACKUP-FAILURE-SILENT-LOG-ONLY-001 (Kontrollrunde 2026-09-27): ein
    # fehlgeschlagenes taegliches Backup landete bisher nur im Log
    # (logger.exception) -- kein Mechanismus informierte den Betreiber aktiv.
    # Bei einem Tier-1-Self-Hosted-Betrieb (kein zentrales Log-Monitoring)
    # koennten Backups wochenlang ausfallen, ohne dass es jemand bemerkt.
    # Wiederverwendet denselben opt-in Slack-/Discord-/generisch-Webhook-
    # Mechanismus wie services/market_data/notifier.py (P22) -- dediziertes
    # Setting statt Wiederverwendung von market_data_alert_webhook_url, da
    # ein Betreiber Backup- und Marktdaten-Alerts an unterschiedliche Kanaele
    # routen koennte. Default leer = no-op, kein Netzwerkverkehr.
    backup_alert_webhook_url: str = ''
    backup_alert_webhook_timeout_seconds: float = 5.0

    # U-19 — Aggregator-Cache (Roadmap-Punkt 19). compute_advisory_report
    # macht 17 Sektionen mit je mehreren DB-Queries; der Sub-App-User klickt
    # durch Sektionen und triggert pro Sektionsanzeige einen vollen Recompute.
    # In-Memory-TTL+LRU-Cache zwischen HTTP-Endpoint und Aggregator.
    aggregator_cache_enabled: bool = True
    aggregator_cache_ttl_seconds: int = 60
    aggregator_cache_max_size: int = 256

    # Optimizer (siehe docs/planning/2026-05-05-stochastic-optimizer-spec.md
    # und claude-bericht-Advisory-Methodik-assetallocation-optimierung-v3-codeplan.md).
    # Gueltige Werte:
    # - 'house_matrix': expliziter Legacy-/Notbetrieb; Solver wird nicht ausgefuehrt.
    # - 'iterative': reservierter Legacy-/Experimentmodus, faellt auf house_matrix.
    # - 'shadow_stochastic': Solver laeuft parallel; House-Matrix bleibt aktive
    #   Zielallokation. Solver-Ergebnis wird nur als Methodenvergleich geliefert
    #   und NICHT auf der TargetAllocation als optimization_* persistiert.
    # - 'stochastic' (default): finales Produktionsmodell. House Matrix liefert
    #   Initialisierung/Policy-Bounds und bleibt auditierter technischer Fallback.
    optimizer_mode: str = 'stochastic'

    # CERT-OPTIMIZER-OBJECTIVE-001 (2026-10-08): typed, startup-validated
    # counterpart to the env var the optimizer objective reads at run time
    # (services.optimizer.objective.resolve_goal_weighting_mode). Declared
    # here so deployment-config gates can assert the same fail-closed
    # contract ("equal" | "hardness", unset -> DEFAULT_GOAL_WEIGHTING_MODE, everything else
    # rejected) independently of any particular run. The objective module
    # remains the per-run source of truth because a config change must take
    # effect on the next optimizer run without a process restart; this field
    # exists for startup/deployment validation parity, not as the runtime
    # read path.
    optimizer_goal_weighting: str = DEFAULT_GOAL_WEIGHTING_MODE

    # Mean-Shift Importance Sampling fuer Tail-Risk im stochastic Optimizer
    # (Phase 5 der Stochastic-Optimizer-Spec). Default OFF, opt-in via
    # MC_IMPORTANCE_SAMPLING_ENABLED=true. Bringt 5-10x Varianz-Reduktion
    # bei Tail-Statistiken (P(Drawdown > X)) ohne Bias. Siehe
    # services/optimizer/importance_sampling.py.
    mc_importance_sampling_enabled: bool = False
    # Shift-Magnitude in Standard-Deviationen (typisch 0.3-1.0). Hoeher =
    # mehr Tail-Konzentration aber hoeherer Bias-Variance-Tradeoff.
    mc_importance_sampling_strength: float = 0.5
    # P1 (2026-06-06): Auto-Decision — IS wird automatisch aktiviert wenn der
    # Mandate-Context Tail-Schutz erfordert (konservatives Risikoprofil,
    # Decumulation, mindestens ein hart-Ziel). Default TRUE — das ist die
    # Verbesserung gegenueber dem urspruenglichen Phase-5 opt-in-Konzept.
    # Wenn mc_importance_sampling_enabled=True ueberschreibt das die
    # Auto-Decision (legacy force-on). Wenn beide False: nie IS.
    mc_importance_sampling_auto_enable: bool = True
    # Sprint C2-Wiring (2026-06-08): Default Tax-Modus fuer simulate_wealth_paths.
    # 'median' (Default) = Backwards-Compat. HNW-Mandate koennen via Admin auf
    # 'binned' setzen fuer per-Pfad-progressive-Tax-Berechnung. 'per_path' nur
    # fuer Audit-Strict-Modus (langsam).
    mc_default_tax_mode: str = "median"

    # W2-804-01 (2026-10-31): optionaler Pfad (ausserhalb des Repos) zu einem
    # JSON-Erwartungs-Manifest des externen Tax-Plugin-Bestands
    # (Env TAX_PLUGIN_EXPECTED_MANIFEST). Gesetzt: fehlende, doppelte,
    # unerwartete oder SDK-inkompatible Plugins stoppen den Boot hart.
    # Leer: Nullfall erlaubt, wird aber geloggt. Format siehe
    # services/tax/plugin_inventory.py.
    tax_plugin_expected_manifest: str = ''

    # ----- Sprint T1 (2026-06-08): 3-Tier-Hosting-Architektur -----
    # Bestimmt Deployment-Charakteristik des Backends.
    # 'tier1' (Default): Self-Hosted, single-tenant ('main'), kein Tenant-UI
    # 'tier2': Shared-Cloud, multi-tenant via RLS / JWT-claim
    # 'tier3': Dedicated-VPS, single-tenant per Instance, voll-Multi-User
    # Siehe docs/adr/ADR-009-3-tier-hosting-architecture.md
    deployment_tier: str = "tier1"
    # Tenancy-Modus — fuer Tier 1 + 3 = 'single', fuer Tier 2 = 'multi'.
    # Wird typischerweise vom Tier abgeleitet, kann aber manuell ueberschrieben
    # werden (z.B. Tier 1 Multi-User-Test-Setup).
    tenancy_mode: str = "single"
    # Tenant-Admin-UI fuer Super-Admin. Tier 2 = True, sonst False.
    tenant_admin_ui_enabled: bool = False
    # E1 (2026-06-14): Strikte Mandanten-Trennung. Default False = BC (Rows mit
    # tenant_id IS NULL gelten als zum eigenen Tenant gehoerig). True (Multi-Firma/
    # Staging) = NUR exakter Tenant-Match, NULL-Rows sind unsichtbar. Voraussetzung:
    # Backfill gelaufen + alle Creates setzen tenant_id (Client/Mandate/User/Baustein).
    strict_tenant_isolation: bool = False
    # E1 (2026-06-14): Pflicht-2FA. True (Staging/extern) = Nutzer ohne aktives
    # 2FA muessen es nach dem Login zwingend einrichten, bevor sie weiterarbeiten.
    require_2fa: bool = False

    # FIDLEG-Hard-Gate fuer die Eignungspruefung (Welle 2.1, 2026-07).
    # ELIG-GATE-001 (2026-10-25): Default TRUE (fail-closed). Die Strategie-/
    # Empfehlungs-Endpunkte blockieren mit HTTP 409, solange
    # audit_mandate_suitability() keine konforme, aktuelle Eignungspruefung
    # meldet (FIDLEG Art. 11-13); siehe suitability_gate_blocks(). Die
    # Produkteignung pro Position pruefen Generate (is_eligible_candidate) und
    # die Finalisierung unabhaengig von
    # diesem Flag. Abschalten nur explizit per Config.
    require_suitability_before_recommendation: bool = True

    # E1 (2026-06-14): SMTP fuer Einladungs-E-Mails (Onboarding). Default AUS —
    # ist es aus/unkonfiguriert, faellt der Invite-Flow auf Link-Copy zurueck
    # (kein harter Fehler). Stdlib-smtplib, keine neue Dependency.
    smtp_enabled: bool = False
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from: str = '5eyes <no-reply@5eyes.local>'
    smtp_use_tls: bool = True        # STARTTLS auf smtp_port
    smtp_timeout_seconds: int = 10

    # Phase-0 safety gate for external access. Staging sets this to False so
    # writes explicitly classified as real client data are rejected.
    allow_real_client_data: bool = True
    # Tenant-DEK envelope encryption. Production/Tier-2 should supply this via
    # env/vault (TENANT_MASTER_KEK); development can pass an explicit KEK in tests.
    tenant_master_kek: str = ''
    # RB-1: Pfad der DPAPI-geschuetzten KEK-Ablage (Datei im userData-Ordner der
    # Desktop-Shell; Electron setzt ihn beim Spawn). Leer = keine Ablage: die
    # KEK kommt dann ausschliesslich aus TENANT_MASTER_KEK (Server/Staging,
    # Tests). Siehe ``ensure_tenant_master_kek`` am Ende dieses Moduls.
    tenant_master_kek_file: str = ''

    # SEC-007 (Codex-Audit 2026-08-26): der bisherige `.sha256`-Sidecar neben
    # jedem Backup ist UNKEYED -- er beweist nur Zufallsintegritaet, nicht
    # Authentizitaet. Ein Angreifer mit Schreibrecht auf das Backup-Verzeichnis
    # kann Backup UND Sidecar gemeinsam ersetzen; der Restore-Pfad wuerde das
    # klaglos akzeptieren. Ist backup_hmac_key gesetzt (separat verwalteter
    # Schluessel, NICHT identisch mit db_key/secret_key/tenant_master_kek),
    # signiert services/backup.py zusaetzlich mit HMAC-SHA256 und der Restore
    # verifiziert/scheitert fail-closed bei fehlendem oder falschem Sidecar.
    # Default leer -> unveraendertes Verhalten (reiner Tier-1-Desktop-Betrieb,
    # kein zusaetzliches Schluesselmaterial zu verwalten).
    backup_hmac_key: str = ''

    # Browser-Hosting (2026-06-10): Haupt-App (ares.html) ueber das Backend
    # ausliefern, damit ein einzelner Host/Tunnel die komplette App im Browser
    # bereitstellt (Remote-Demo/Tier-2). Default AUS — Tier-1/Electron laedt die
    # HTML weiterhin lokal via file://. Nur fuer Browser-/Tunnel-Demos einschalten.
    serve_main_frontend: bool = False

    # Sprint U-P8 Fix M1 (2026-05-20): Block-Diagonal Sub-Asset-Class
    # Korrelation innerhalb eines Buckets. Default 1.0 = perfekt korreliert
    # (Backwards-Compat zur Bucket-Skalar-Vola). Werte < 1.0 aktivieren
    # echte Intra-Bucket-Diversifikation (z.B. CH-Equity ↔ EM-Equity ρ=0.7-0.8).
    # Inter-Bucket-Korrelationen bleiben aus _DEFAULT_CORRELATION_MATRIX
    # (siehe portfolio_engine._DEFAULT_CORRELATION_MATRIX).
    sub_class_intra_correlation: float = 1.0

    @field_validator('app_env')
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {'development', 'test', 'staging', 'production'}
        if normalized not in allowed:
            raise ValueError(f"app_env must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator('jwt_issuer', 'jwt_audience', 'jwt_key_id')
    @classmethod
    def validate_jwt_binding(cls, value: str) -> str:
        cleaned = str(value or '').strip()
        if not cleaned:
            raise ValueError('jwt_issuer, jwt_audience and jwt_key_id must not be empty')
        return cleaned

    @field_validator('token_revoked_before')
    @classmethod
    def validate_token_revoked_before(cls, value: str | None) -> str | None:
        # Fail-closed: ein unlesbarer Wert wuerde sonst still ignoriert und
        # der beabsichtigte Massenwiderruf liefe ins Leere.
        cleaned = str(value or '').strip()
        if not cleaned:
            return None
        raw = cleaned[:-1] + '+00:00' if cleaned.endswith('Z') else cleaned
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError('token_revoked_before must be an ISO-8601 timestamp') from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator('optimizer_mode')
    @classmethod
    def validate_optimizer_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {'house_matrix', 'shadow_stochastic', 'stochastic'}
        if normalized not in allowed:
            raise ValueError(f"optimizer_mode must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator('optimizer_goal_weighting')
    @classmethod
    def validate_optimizer_goal_weighting(cls, value: str) -> str:
        return validate_goal_weighting_mode(value)

    @field_validator('sub_class_intra_correlation')
    @classmethod
    def validate_sub_class_intra_correlation(cls, value: float) -> float:
        v = float(value)
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"sub_class_intra_correlation muss in [0.0, 1.0] sein "
                f"(erhalten: {value})"
            )
        return v

    @field_validator(
        'price_refresh_primary_provider',
        'price_refresh_fallback_provider',
        'reference_data_active_provider',
        'id_mapping_active_provider',
        'macro_assumptions_active_provider',
        'target_market_price_provider',
        'target_reference_data_provider',
        'target_id_mapping_provider',
        'target_macro_core_provider',
        'target_macro_euro_provider',
        'target_macro_swiss_provider',
        'target_enterprise_reference_provider',
    )
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        return value.strip().lower().replace('-', '_').replace(' ', '_')

    @field_validator(
        'log_max_bytes',
        'log_backup_count',
        'access_token_expire_minutes',
        'login_max_attempts',
        'login_window_seconds',
        'login_lockout_seconds',
        'recent_log_lines_default',
        'recent_log_lines_max',
        'market_data_daily_refresh_max_symbols',
        'solver_max_concurrent',
        'max_request_body_bytes',
    )
    @classmethod
    def validate_positive_numbers(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('value must be greater than 0')
        return value


    @field_validator('app_port')
    @classmethod
    def validate_app_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError('app_port must be between 1 and 65535')
        return value

    @field_validator('trusted_proxy_count')
    @classmethod
    def validate_trusted_proxy_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError('trusted_proxy_count must be >= 0')
        return value

    @field_validator('price_scheduler_hour')
    @classmethod
    def validate_price_scheduler_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError('price_scheduler_hour must be between 0 and 23')
        return value

    @field_validator('price_scheduler_minute')
    @classmethod
    def validate_price_scheduler_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError('price_scheduler_minute must be between 0 and 59')
        return value

    @field_validator('market_data_daily_refresh_hour')
    @classmethod
    def validate_market_data_daily_refresh_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError('market_data_daily_refresh_hour must be between 0 and 23')
        return value

    @field_validator('market_data_daily_refresh_minute')
    @classmethod
    def validate_market_data_daily_refresh_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError('market_data_daily_refresh_minute must be between 0 and 59')
        return value

    @model_validator(mode='after')
    def validate_cors_safety(self):
        """Sprint U-58/60 (2026-06-01): CORS-Audit-Safety.

        Regeln:
        - allow_origins darf NIE '*' enthalten — wuerde mit
          allow_credentials=True (in main.py hardcoded) eine Browser-Spec-
          Violation triggern und die Middleware ohne Schutz laufen lassen.
        - In Production: KEINE localhost/127.0.0.1-Origins (Browser-
          Berater-Setups, kein Dev-Loophole).
        """
        if any(str(o).strip() == '*' for o in self.cors_origins):
            raise ValueError(
                'cors_origins darf nicht "*" enthalten — '
                'mit allow_credentials=True ist das Browser-Spec-Verletzung. '
                'Liste konkrete Origins auf (Electron app://., '
                'http://localhost:5173 fuer Dev, etc.).'
            )
        if self.app_env == 'production':
            forbidden = [
                o for o in self.cors_origins
                if 'localhost' in str(o) or '127.0.0.1' in str(o)
            ]
            if forbidden:
                raise ValueError(
                    f'cors_origins in production darf keine localhost-'
                    f'Origins enthalten: {forbidden}'
                )
        return self

    @field_validator('backup_scheduler_hour')
    @classmethod
    def validate_backup_scheduler_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError('backup_scheduler_hour must be between 0 and 23')
        return value

    @field_validator('backup_scheduler_minute')
    @classmethod
    def validate_backup_scheduler_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError('backup_scheduler_minute must be between 0 and 59')
        return value

    @field_validator('backup_retain_days')
    @classmethod
    def validate_backup_retain_days(cls, value: int) -> int:
        if value < 0:
            raise ValueError('backup_retain_days must be >= 0 (0 = nie aufraeumen)')
        return value

    @field_validator('backup_keep_minimum')
    @classmethod
    def validate_backup_keep_minimum(cls, value: int) -> int:
        if value < 1:
            raise ValueError('backup_keep_minimum muss >= 1 sein (Katastrophen-Schutz)')
        return value

    @field_validator('aggregator_cache_ttl_seconds')
    @classmethod
    def validate_aggregator_cache_ttl(cls, value: int) -> int:
        if value < 0:
            raise ValueError('aggregator_cache_ttl_seconds muss >= 0 sein (0 = effektiv aus)')
        return value

    @field_validator('aggregator_cache_max_size')
    @classmethod
    def validate_aggregator_cache_max_size(cls, value: int) -> int:
        if value < 1:
            raise ValueError('aggregator_cache_max_size muss >= 1 sein')
        return value

    @model_validator(mode='after')
    def validate_security(self):
        if self.app_env == 'production' and self.optimizer_mode != 'stochastic':
            raise ValueError(
                'production requires optimizer_mode=stochastic; house_matrix '
                'is reserved for the audited internal solver fallback.'
            )
        if self.app_env in {'staging', 'production'} and self.secret_key == DEFAULT_SECRET_KEY:
            raise ValueError('secret_key must be overridden outside development/test')
        # SEC-002 (Codex-Audit 2026-08-26): der obige Check lehnte nur den EXAKTEN
        # Default-Platzhalter ab -- ein triviales secret_key='x' wurde klaglos
        # akzeptiert. HS256-JWTs mit einem erratbaren Schlüssel lassen sich mit
        # jeder bekannten aktiven User-ID faelschen (get_current_user() laedt die
        # Rolle zwar aus der DB, uebernimmt aber genau diese Rolle). Mindestens
        # 32 Zeichen (~256 Bit fuer zufaelliges ASCII-Schlüsselmaterial) ist die
        # von der JWT-Spezifikation fuer HS256 empfohlene Mindestlaenge. Volle
        # Entropie-Pruefung, Secret-Manager/HSM-Herkunft, DB-/KEK-/Webhook-Key-
        # Wiederverwendungs-Check und iss/aud/kid/Rotationsvertrag sind ein
        # groesseres, separates Vorhaben (nicht Teil dieses Fixes).
        if self.app_env in {'staging', 'production'} and len(self.secret_key) < 32:
            raise ValueError(
                'secret_key must be at least 32 characters long in staging/production '
                '(HS256 minimum recommended key size)'
            )
        # SEC-002: algorithm war ein freier String -- ein versehentlich (oder
        # boesartig ueber die Umgebung) gesetztes 'none' oder ein asymmetrischer
        # Algorithmus wuerde von jwt.decode(algorithms=[settings.algorithm])
        # unveraendert als erlaubt uebernommen. Diese App signiert/verifiziert
        # ausschliesslich HS256 (siehe services/auth.py-Migrationskommentar zur
        # jose->PyJWT-Umstellung); das wird jetzt als hartes Literal erzwungen.
        if self.algorithm != 'HS256':
            raise ValueError("algorithm must be 'HS256' (the only algorithm this app signs/verifies)")
        uses_postgres = bool(
            self.database_url
            and str(self.database_url).strip().lower().startswith(("postgresql://", "postgresql+"))
        )
        if self.app_env == 'production' and not uses_postgres and not (self.db_use_sqlcipher and self.db_key):
            raise ValueError('production requires PostgreSQL or db_use_sqlcipher=true with a non-empty db_key')
        # #299-Security-Follow-up #5: Tenant-Isolation-Backstop erzwingen. Auf
        # Server-Deployments (PostgreSQL = Tier-2/3, mandantenfaehig) MUSS in
        # staging/production der App-Layer-Filter strikt sein — sonst waere eine
        # Row mit vergessenem tenant_id (NULL) tenant-uebergreifend sichtbar
        # (Guertel + Hosentraeger zur DB-seitigen RLS, die nur bei nicht-Superuser-
        # Rolle greift). Tier-1 (SQLite-Desktop, single-tenant) ist nicht betroffen.
        if self.app_env in {'staging', 'production'} and uses_postgres and not self.strict_tenant_isolation:
            raise ValueError(
                'strict_tenant_isolation muss in staging/production mit PostgreSQL '
                'aktiv sein (Multi-Tenant-Isolation-Backstop).'
            )
        if self.db_use_sqlcipher and not self.db_key:
            raise ValueError('db_key must be set when db_use_sqlcipher=true')
        if self.recent_log_lines_default > self.recent_log_lines_max:
            raise ValueError('recent_log_lines_default must not exceed recent_log_lines_max')
        # Sprint U-59 (2026-06-01): Bearer-Token-TTL hard cap in production.
        # 24h Maximum = ein Arbeitstag, danach Re-Login. Verhindert dass
        # versehentlich JAHRE-Tokens generiert werden (Token-Diebstahl-
        # Window-Mitigation). Dev/test bleiben frei (z.B. fuer Long-running
        # Integration-Tests).
        if self.app_env == 'production' and self.access_token_expire_minutes > 1440:
            raise ValueError(
                f'access_token_expire_minutes={self.access_token_expire_minutes} '
                f'exceeds 1440 (24h) in production. Reduziere TTL um '
                f'Token-Diebstahl-Window zu begrenzen.'
            )
        # RECOV-002 (Codex-Audit 2026-08-27): smtp_use_tls war frei
        # abschaltbar; services/mailer.py sendet bei False Login und
        # Reset-/Invite-Mail (inkl. SMTP-Passwort) unverschluesselt. Der
        # vollstaendige Fixvertrag (expliziter starttls/smtps-Transportmodus,
        # fail-closed bei Zustellfehler statt nur Warnung) ist ein
        # groesseres, separates Vorhaben -- dieser Fix schliesst nur die
        # konkret nachgewiesene Klartext-SMTP-in-Produktion-Luecke.
        if self.app_env in {'staging', 'production'} and self.smtp_enabled and not self.smtp_use_tls:
            raise ValueError(
                'smtp_use_tls must be true in staging/production when smtp_enabled=true '
                '(plaintext SMTP would send reset/invite bearer tokens and the SMTP '
                'password unencrypted)'
            )
        return self


settings = Settings()


# --- RunContext (K-3, Phase 2 Modularisierung) ---------------------------------
# "Ein Lauf kennt seine Mathematik": die Werte, die ein Engine-Lauf bisher
# verstreut und zu beliebigen Zeitpunkten aus ``settings`` bzw. dem Mandat las,
# werden EINMAL zu Beginn des Laufs eingefroren und durch den Lauf gereicht.
# Eine Settings-Aenderung waehrend des Laufs wirkt fuer die migrierten Leser
# nicht mehr. Liegt hier und nicht in einem eigenen Modul: Erzeuger und
# Konsumenten importieren config ohnehin (Architektur-Ratsche fan_out), und
# der Typ selbst importiert nichts Internes -- die aufgeloeste Jurisdiktion
# (``jurisdictions.resolve.resolve_pack``) wird vom Erzeuger uebergeben.
class RunContextMandateMismatch(ValueError):
    """Ein RunContext wurde fuer ein anderes Mandat gebildet als den Lauf."""


@dataclass(frozen=True, slots=True)
class RunContext:
    """Eingefrorener Kontext genau eines Engine-Laufs fuer genau ein Mandat.

    - ``mandate_id``: ``mandate.id`` des Mandats, aus dem der Kontext gebildet
      wurde. Leser, die einen uebergebenen Kontext nutzen, pruefen ihn mit
      ``ensure_bound_to(mandate)`` (Abweichung = ``RunContextMandateMismatch``).
    - ``jurisdiction``: der aufgeloeste Code ``resolve_pack(mandate).code`` --
      exakt der Wert der heutigen Formel ``mandate.jurisdiction or "CH"``
      (ohne Normalisierung), eingefroren zum Laufbeginn.
    - ``jurisdiction_source``: Herkunft laut ``ResolvedPack.source``.
    - ``resolved_pack``: das ``ResolvedPack`` selbst (fuer Pack-Version/-Hash
      in spaeteren Schritten, z.B. Evidence), unveraendert durchgereicht.
    - ``optimizer_mode``: ``settings.optimizer_mode`` zum Laufbeginn.
    - ``bound_mandate``: das Mandatsobjekt, aus dem der Kontext gebildet wurde
      (nur fuer die Bindungspruefung ungespeicherter Mandate ohne ``id``;
      nicht Teil von Vergleich/Repr).
    """

    mandate_id: Any
    jurisdiction: Any
    jurisdiction_source: str
    resolved_pack: Any
    optimizer_mode: str
    bound_mandate: Any = field(default=None, compare=False, repr=False)

    @classmethod
    def capture(
        cls, resolved_pack: Any, source: Any = None, *, mandate_id: Any, mandate: Any = None,
    ) -> "RunContext":
        """Friert ``resolved_pack`` und die Lauf-Settings fuer ``mandate_id`` ein.

        ``source`` ist das Settings-Objekt, aus dem gelesen wird (Default:
        ``config.settings``); der Erzeuger uebergibt das Objekt, das er bisher
        selbst gelesen haette, damit Monkeypatches identisch wirken.
        ``mandate_id`` ist Pflicht (``None`` nur fuer Mandate ohne ``id``).
        ``mandate`` (optional) ist das Mandatsobjekt selbst; nur damit gilt
        ein Kontext mit ``mandate_id=None`` als an genau dieses (ungespeicherte)
        Objekt gebunden (siehe ``ensure_bound_to``).
        """
        cfg = settings if source is None else source
        return cls(
            mandate_id=mandate_id,
            jurisdiction=resolved_pack.code,
            jurisdiction_source=str(resolved_pack.source),
            resolved_pack=resolved_pack,
            optimizer_mode=cfg.optimizer_mode,
            bound_mandate=mandate,
        )

    def ensure_bound_to(self, mandate: Any) -> "RunContext":
        """Wirft ``RunContextMandateMismatch``, wenn ``mandate.id`` nicht die
        Mandats-ID dieses Kontexts ist; sonst ``self``.

        Verglichen wird nur die Mandats-ID, nicht die Jurisdiktion: ein Lauf
        behaelt die beim Laufbeginn eingefrorene Jurisdiktion, auch wenn das
        Mandatsobjekt sich waehrend des Laufs aendert.

        Fail-closed bei fehlender ID: ``None == None`` ist KEINE Bindung --
        sonst waeren zwei verschiedene ungespeicherte Mandate (beide
        ``id=None``) als "dasselbe Mandat" durchgegangen. Fehlt die ID auf
        einer Seite, gilt der Kontext nur dann als gebunden, wenn beide IDs
        ``None`` sind UND ``mandate`` exakt das Objekt ist, aus dem der Kontext
        gebildet wurde (``capture(..., mandate=...)``, ``build_run_context``).
        """
        mandate_id = getattr(mandate, "id", None)
        if mandate_id is None or self.mandate_id is None:
            bound = (
                mandate_id is None
                and self.mandate_id is None
                and self.bound_mandate is not None
                and mandate is self.bound_mandate
            )
        else:
            bound = mandate_id == self.mandate_id
        if not bound:
            raise RunContextMandateMismatch(
                f"RunContext gehoert zu Mandat {self.mandate_id!r}, der Lauf zu Mandat "
                f"{mandate_id!r}; ein RunContext gilt nur fuer das Mandat, aus dem er "
                "gebildet wurde."
            )
        return self


# --- HTTP-Identitaet gegenueber externen Diensten -------------------------------
# Ein einziger Ort fuer den User-Agent ausgehender Requests (Marktdaten-Provider,
# Referenzdaten, Alert-Webhook), Format ``Ares/<version>``. Liegt hier und nicht in
# einem eigenen Modul: die Aufrufer importieren config ohnehin (Architektur-Ratsche,
# kein zusaetzlicher Import je Client).
HTTP_PRODUCT_TOKEN = "Ares"


def user_agent() -> str:
    """``Ares/<app_version>`` fuer API-Clients und Webhooks."""
    return f"{HTTP_PRODUCT_TOKEN}/{settings.app_version}"


def browser_compatible_user_agent() -> str:
    """User-Agent fuer HTML-Quellen, die einen Browser-Praefix erwarten.

    Der ``Mozilla/5.0``-Praefix bleibt wie bisher erhalten; nur das
    Produkt-Token in Klammern folgt dem ``Ares/<version>``-Format.
    """
    return f"Mozilla/5.0 ({user_agent()})"


# ---------------------------------------------------------------------------
# Demo-/Staging-Passwoerter (nie im Quellcode). Liegt im Konfigurationsmodul,
# weil nur dieses die Umgebung lesen darf (Architektur-Ratsche env_readers).
# Die Seed-Skripte importieren das erst NACH dem Setzen von DB_PATH, denn der
# Import dieses Moduls instanziiert ``settings`` (inkl. db_path).
# ---------------------------------------------------------------------------
MIN_PASSWORD_LENGTH = 12


def demo_password(env_name: str) -> tuple[str, str]:
    """``(passwort, herkunft)``; herkunft = Variablenname oder ``"zufaellig"``.

    Ein Demo-Passwort kommt entweder aus einer Umgebungsvariable (fuer
    reproduzierbare Kollegen-Tests) oder wird pro Lauf zufaellig erzeugt und
    vom aufrufenden Skript einmal ausgegeben.
    """
    value = os.environ.get(env_name, "").strip()
    if value:
        if len(value) < MIN_PASSWORD_LENGTH:
            raise SystemExit(
                f"{env_name} ist kuerzer als {MIN_PASSWORD_LENGTH} Zeichen -- abgebrochen."
            )
        return value, env_name
    return secrets.token_urlsafe(18), "zufaellig"


# ---------------------------------------------------------------------------
# RB-1: Master-KEK beim Erststart erzeugen und per DPAPI (Benutzer-Scope)
# ablegen. Liegt im Konfigurationsmodul, weil die KEK ein Konfigurationswert
# ist (``settings.tenant_master_kek``, die Quelle fuer services.tenant_crypto)
# und weil ein eigenes Modul den Fan-out von ``main`` oder ``config``
# erhoehen wuerde (Architektur-Ratsche).
#
# Vertrag (gilt auch fuer den Migrator, der die Ziel-KEK hier ablegt):
#   Datei  = KEK_STORE_MAGIC + DPAPI-Blob
#   Blob   = CryptProtectData(KEK als ASCII-Fernet-Key, Entropie
#            KEK_STORE_ENTROPY, Flags CRYPTPROTECT_UI_FORBIDDEN) -- Benutzer-
#            Scope (kein CRYPTPROTECT_LOCAL_MACHINE): nur dasselbe Windows-
#            Konto kann die Datei entschluesseln.
# Invarianten: die KEK wird nie geloggt, eine vorhandene Ablage wird nie
# ueberschrieben oder geloescht, und ohne Ablage wird bei vorhandener
# Datenbank keine neue KEK erzeugt (das wuerde Bestandsdaten unlesbar machen).
# ---------------------------------------------------------------------------
KEK_STORE_MAGIC = b"ARES-KEK-DPAPI/1\n"
KEK_STORE_ENTROPY = b"ares.tenant-master-kek.store.v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04

# W4-c-Andockstelle: Solange der Vorgaengervertrag (KEK v1 mit Rueckfall auf
# SECRET_KEY) gilt, startet eine Bestandsinstallation ohne KEK weiter ueber
# diesen Rueckfall -- hier wird dann nur KEINE KEK erzeugt. W4-c (KEK-Pflicht)
# setzt diesen Schalter auf True: vorhandene Datenbank ohne KEK = Abbruch.
KEK_REQUIRED_FOR_EXISTING_DATA = False


class KekStoreError(RuntimeError):
    """Die Master-KEK laesst sich nicht sicher bereitstellen (Start abbrechen)."""


# W4-c / AF-4: Pruefung der Master-KEK ohne Rueckfall auf SECRET_KEY oder einen
# Platzhalter. Sie steht hier und nicht in services.tenant_crypto, damit der
# Start (main.lifespan, vor init_db) sie ohne zusaetzliche Modulkante aufrufen
# kann (Architektur-Ratsche); services.tenant_crypto nutzt dieselbe Pruefung.
MISSING_TENANT_MASTER_KEK_MESSAGE = (
    "TENANT_MASTER_KEK fehlt: Ares startet nicht ohne eigene Master-KEK. "
    "Einen Fernet-Key erzeugen (python -c \"from cryptography.fernet import "
    "Fernet; print(Fernet.generate_key().decode())\") und als "
    "TENANT_MASTER_KEK in der Konfiguration setzen; eine Bestandsinstallation "
    "bringt ihn aus der Zielkonfiguration des Migrators mit."
)


def tenant_master_kek_problem(raw: "str | bytes | None", *, secret_key: str = "") -> "str | None":
    """Grund, warum ``raw`` keine zulaessige Master-KEK ist; ``None`` wenn zulaessig."""
    value = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    if not value.strip():
        return MISSING_TENANT_MASTER_KEK_MESSAGE
    if value == DEFAULT_SECRET_KEY:
        return (
            "TENANT_MASTER_KEK ist der oeffentliche Platzhalter aus dem Quellcode "
            "und damit kein Geheimnis. Einen eigenen Fernet-Key setzen."
        )
    if secret_key and value == secret_key:
        return (
            "TENANT_MASTER_KEK ist identisch mit SECRET_KEY. Der JWT-Schluessel "
            "darf nicht zugleich die Master-KEK sein; einen eigenen Fernet-Key setzen."
        )
    return None


def require_tenant_master_kek(cfg: "Settings | None" = None) -> None:
    """Startpruefung (Lifespan, vor init_db): ohne gueltige Master-KEK startet Ares nicht."""
    cfg = cfg if cfg is not None else settings
    problem = tenant_master_kek_problem(
        str(getattr(cfg, "tenant_master_kek", "") or "").strip(),
        secret_key=str(getattr(cfg, "secret_key", "") or ""),
    )
    if problem:
        raise KekStoreError(problem)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


class WindowsDpapi:
    """CryptProtectData/CryptUnprotectData im Benutzer-Scope (nur Windows)."""

    flags = CRYPTPROTECT_UI_FORBIDDEN

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    def _call(self, name: str, data: bytes, entropy: bytes) -> bytes:
        if not self.available():
            raise KekStoreError(
                "Die DPAPI-Ablage der Master-KEK gibt es nur unter Windows; "
                "TENANT_MASTER_KEK direkt setzen."
            )
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        func = getattr(crypt32, name)
        func.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
        ]
        func.restype = ctypes.c_int
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        in_buf = ctypes.create_string_buffer(data, len(data))
        ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
        in_blob = _DataBlob(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
        ent_blob = _DataBlob(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
        out_blob = _DataBlob()
        ok = func(ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None,
                  self.flags, ctypes.byref(out_blob))
        if not ok:
            raise KekStoreError(f"DPAPI {name} fehlgeschlagen (Windows-Fehler {ctypes.get_last_error()}).")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))

    def protect(self, data: bytes, entropy: bytes) -> bytes:
        return self._call("CryptProtectData", data, entropy)

    def unprotect(self, blob: bytes, entropy: bytes) -> bytes:
        return self._call("CryptUnprotectData", blob, entropy)


def _is_fernet_key(value: str) -> bool:
    try:
        return len(value) == 44 and len(base64.urlsafe_b64decode(value.encode("ascii"))) == 32
    except (ValueError, UnicodeEncodeError):
        return False


def _existing_database(cfg: "Settings") -> str | None:
    """Ort einer schon vorhandenen Datenbank (gleiche Aufloesung wie ``database``)."""
    url = str(getattr(cfg, "database_url", None) or "").strip()
    if url:
        sqlite_file = _db_location.sqlite_url_file(url)
        if sqlite_file is None:
            # Server-Datenbank (oder :memory:): Bestand nicht pruefbar -> wie vorhanden.
            return "DATABASE_URL"
        db_file = sqlite_file
    else:
        db_file = Path(str(cfg.db_path))
    db_file = db_file.expanduser()
    for candidate in (db_file, db_file.with_name(db_file.name + "-wal")):
        if candidate.exists():
            return str(db_file)
    return None


def _read_kek_store(path: Path, protector) -> str:
    raw = path.read_bytes()
    if not raw.startswith(KEK_STORE_MAGIC):
        raise KekStoreError(
            f"Die KEK-Ablage {path} hat ein unbekanntes Format. Sie wird weder "
            "ueberschrieben noch ersetzt; Ares startet nicht."
        )
    try:
        value = protector.unprotect(raw[len(KEK_STORE_MAGIC):], KEK_STORE_ENTROPY).decode("ascii")
    except (KekStoreError, UnicodeDecodeError, OSError) as exc:
        raise KekStoreError(
            f"Die KEK-Ablage {path} laesst sich nicht entschluesseln (anderes "
            "Windows-Konto, fremdes Profil oder beschaedigte Datei). Ares startet "
            "nicht und erzeugt KEINE neue KEK, weil vorhandene Daten sonst "
            "unlesbar wuerden. Datei nicht loeschen; aus Sicherung/Treuhand "
            "wiederherstellen."
        ) from exc
    if not _is_fernet_key(value):
        raise KekStoreError(f"Die KEK-Ablage {path} enthaelt keinen gueltigen Schluessel.")
    return value


def _write_kek_store_exclusive(path: Path, payload: bytes) -> bool:
    """Schreibt die Ablage atomar; ``False``, wenn sie schon existiert (nie ueberschreiben)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:
            pass
        try:
            os.link(tmp_name, path)  # scheitert, wenn das Ziel existiert
        except FileExistsError:
            return False
        except OSError:
            # Dateisystem ohne Hardlinks: exklusives Anlegen als Rueckfall.
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            try:
                out = os.open(str(path), flags, 0o600)
            except FileExistsError:
                return False
            with os.fdopen(out, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        return True
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def ensure_tenant_master_kek(
    cfg: "Settings | None" = None,
    *,
    protector=None,
    require_for_existing_data: bool | None = None,
) -> str:
    """Stellt ``cfg.tenant_master_kek`` vor ``init_db`` bereit; liefert das Ergebnis.

    Ergebnisse (nie mit KEK-Wert): ``disabled`` (keine Ablage konfiguriert),
    ``configured`` (TENANT_MASTER_KEK gesetzt), ``loaded`` (aus der Ablage),
    ``generated`` (Erststart: neu erzeugt, abgelegt und zurueckgelesen),
    ``legacy-existing-db`` (Bestandsdatenbank ohne KEK unter dem
    Vorgaengervertrag: nichts erzeugt). Jeder unsichere Zustand wirft
    :class:`KekStoreError`.
    """
    cfg = cfg if cfg is not None else settings
    store_setting = str(getattr(cfg, "tenant_master_kek_file", "") or "").strip()
    if not store_setting:
        return "disabled"
    protector = protector if protector is not None else WindowsDpapi()
    required = KEK_REQUIRED_FOR_EXISTING_DATA if require_for_existing_data is None else require_for_existing_data
    store = Path(store_setting).expanduser()
    explicit = str(getattr(cfg, "tenant_master_kek", "") or "").strip()

    if explicit:
        if store.exists():
            stored = _read_kek_store(store, protector)
            if not hmac.compare_digest(stored.encode("ascii"), explicit.encode("utf-8")):
                raise KekStoreError(
                    f"TENANT_MASTER_KEK widerspricht der KEK-Ablage {store}. Ares "
                    "startet nicht, weil eine falsche KEK Mandantendaten unlesbar "
                    "macht. Eine der beiden Quellen entfernen."
                )
        return "configured"

    if store.exists():
        cfg.tenant_master_kek = _read_kek_store(store, protector)
        return "loaded"

    existing = _existing_database(cfg)
    if existing is not None:
        if required:
            raise KekStoreError(
                f"Die Datenbank {existing} existiert, aber es gibt keine Master-KEK "
                f"(weder TENANT_MASTER_KEK noch Ablage {store}). Ares erzeugt in "
                "diesem Fall keine neue KEK, weil die vorhandenen Daten sonst "
                "unlesbar wuerden. Bestandsdaten mit dem Migrator uebernehmen oder "
                "die KEK-Ablage aus Sicherung/Treuhand zurueckspielen."
            )
        return "legacy-existing-db"

    if not protector.available():
        raise KekStoreError(
            f"Erststart ohne Master-KEK, aber keine DPAPI verfuegbar ({store}). "
            "TENANT_MASTER_KEK direkt setzen."
        )
    new_kek = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    payload = KEK_STORE_MAGIC + protector.protect(new_kek.encode("ascii"), KEK_STORE_ENTROPY)
    if not _write_kek_store_exclusive(store, payload):
        # Paralleler Start war schneller: dessen KEK gilt, unsere wird verworfen.
        cfg.tenant_master_kek = _read_kek_store(store, protector)
        return "loaded"
    try:
        round_trip = _read_kek_store(store, protector)
    except KekStoreError:
        round_trip = ""
    if not hmac.compare_digest(round_trip.encode("ascii"), new_kek.encode("ascii")):
        # Eben in diesem Lauf angelegt, noch keine Datenbank: gefahrlos entfernbar.
        try:
            store.unlink()
        except OSError:
            pass
        raise KekStoreError(f"Die neu angelegte KEK-Ablage {store} liess sich nicht zuruecklesen.")
    cfg.tenant_master_kek = new_kek
    return "generated"
