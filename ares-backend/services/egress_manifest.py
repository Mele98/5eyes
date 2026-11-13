"""H10 C-DSG-03: zentrales, fail-closed Egress-Manifest mit Laufzeitschutz.

``config/outbound_processing_manifest.json`` listet jeden ausgehenden Kanal
des Backends mit Zielhost(s), Zweck, Klasse, erlaubten Datenfeldern,
Empfaengerstaat und Garantie (Owner-Felder, nie vorbelegt). Dieses Modul

* prueft das Manifest (``manifest_problems``, CI-Gate),
* setzt es zur Laufzeit durch: ein Audit-Hook (``sys.addaudithook``) prueft
  jede Namensaufloesung (``socket.getaddrinfo``), jeden urllib-Request vor
  dem Verbindungsaufbau (``urllib.Request``: URL und Body) und jeden
  gesendeten HTTP-Block (``http.client.send``: Request-Zeile, Query,
  Formular-/JSON-Body). Erfasst sind damit alle Python-Netzwerkpfade (urllib,
  requests, yfinance, smtplib, Fehlerdienst-SDK). Nicht im Manifest =
  blockiert. Bei requests/urllib3 gehen Kopfzeilen und Body getrennt hinaus:
  Kopf und Query sind dann geprueft, ein beanstandeter Body wird vor dem
  Senden gestoppt.

Blockiert wird mit ``EgressBlocked`` (eine ``OSError``), d. h. wie ein
Verbindungsfehler: Provider fallen sauber auf ihren Fehlerpfad zurueck, die
App laeuft weiter. Protokolliert werden nur Kanal, Host und Grund, nie der
Inhalt.

Datenminimierung: Kanaele ohne Personendaten muessen ``allowed_fields``
fuehren; jeder andere Parameter- oder JSON-Schluessel wird blockiert. Werte
werden zusaetzlich auf Personendaten-Muster geprueft (UUID = Kunden-/
Mandats-ID, E-Mail, IBAN, AHV-Nummer). Kanaele mit Personendaten laufen erst,
wenn der Verantwortliche Staat und Garantie bestaetigt hat.

Grenzen (im Manifest ausgewiesen): native Bibliotheken mit eigenen Sockets
(Bloomberg ``blpapi``), die Electron-Shell (eigenes Update-Gate, Renderer per
CSP auf localhost) und Kommandozeilen-Skripte ausserhalb des App-Prozesses.
"""
from __future__ import annotations

import ipaddress
import json
import unicodedata
import logging
import re
import socket
import sys
import threading
import time as _time
from collections import deque
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, unquote, urlsplit

from core.evidence import SCHEME_V1, evidence_hash
from core.reason_codes import ReasonCode

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
MANIFEST_PATH = BACKEND_ROOT / "config" / "outbound_processing_manifest.json"

CHANNEL_CLASSES = (
    "market_data", "reference_data", "macro_data", "alerting", "mail", "telemetry",
    "operator_infrastructure", "updates",
)
REQUIRED_CLASSES = ("market_data", "updates", "telemetry")
ENFORCEMENTS = ("python_runtime_guard", "native_library", "desktop_update_gate", "subprocess_guard")
# N-899-01: Netzwerkwerkzeuge, deren Aufruf (subprocess) an einen Kanal mit
# ``subprocess_tools`` gebunden sein muss.
NETWORK_TOOLS = frozenset({
    "rsync", "ssh", "scp", "sftp", "ftp", "tftp", "curl", "wget", "rclone", "aws", "az", "gsutil", "ncat",
    "telnet", "bitsadmin", "invoke-webrequest", "invoke-restmethod", "start-bitstransfer",
})
# N-899-10: Shells und Startwerkzeuge, deren Argumentstring auf
# Netzwerkwerkzeuge durchsucht wird (shell=True, cmd /c, PowerShell, os.system).
SHELL_TOOLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "cmd", "powershell", "pwsh"})
WRAPPER_TOOLS = frozenset({"env", "nice", "nohup", "timeout", "sudo", "xargs", "stdbuf", "ionice", "start",
                           "busybox"})
_SHELL_SEPARATORS = re.compile(r"[;&|()`\n]+|\$\(")
# Entfernte Ziele user@host:/pfad bzw. host:pfad; Windows-Laufwerke (C:\) zaehlen nicht.
_REMOTE_TOKEN = re.compile(r"^(?:rsync://)?(?:[^@\s/:\\]+@)?([A-Za-z0-9][A-Za-z0-9.\-]+):(?![\\/]{0,1}\\)")
NON_BLOCKING_GUARANTEES = ("NOT_REQUIRED", "OPERATOR_INFRASTRUCTURE")
# Feldnamen erzwingen (Standard) oder -- nur fuer anbietergesteuerte Ablaeufe
# ohne Personendaten, mit Begruendung -- nur die Werte pruefen.
FIELD_POLICY_ALLOWLIST = "allowlist"
FIELD_POLICY_SCREEN_ONLY = "screen_values_only"
FIELD_POLICIES = (FIELD_POLICY_ALLOWLIST, FIELD_POLICY_SCREEN_ONLY)
VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "uuid": re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b"),
    "ahv": re.compile(r"\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b"),
}
_REQUEST_LINE = re.compile(rb"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|CONNECT) (\S+) HTTP/1\.[01]\r\n")
_LOOPBACK_NAMES = frozenset({"localhost", "0.0.0.0", "::", "ip6-localhost", "ip6-loopback"})
_RECENT_LIMIT = 200


class ManifestUnavailable(RuntimeError):
    """Manifest fehlt oder ist kein gueltiges JSON."""


class EgressBlocked(PermissionError):
    """Ausgehende Verbindung durch das Egress-Manifest blockiert."""

    def __init__(self, reason_code: str, message: str, *, channel: str | None = None, host: str | None = None):
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code
        self.channel = channel
        self.host = host


@lru_cache(maxsize=4)
def _load(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestUnavailable(f"Egress-Manifest nicht lesbar: {path.name}: {exc}") from exc


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    return json.loads(json.dumps(_load(str(path or MANIFEST_PATH))))


def manifest_hash(manifest: dict[str, Any]) -> str:
    return evidence_hash(manifest, scheme=SCHEME_V1)


def channels(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return list(manifest.get("channels") or [])


def channel_by_id(manifest: dict[str, Any], channel_id: str) -> dict[str, Any] | None:
    return next((c for c in channels(manifest) if c.get("id") == channel_id), None)


def blocking_owner_keys(channel: dict[str, Any]) -> list[str]:
    """Owner-Felder, ohne die ein Kanal nicht laeuft (alle mit Sperrwirkung
    ``channel``: Staat, Garantie, Grundlage, ggf. Zielhost, Verschluesselung)."""
    keys = []
    for node in channel.values():
        if isinstance(node, dict) and node.get("owner_field") and node.get("blocking") == "channel":
            keys.append(node["owner_field"])
    return keys


def manifest_problems(manifest: dict[str, Any], *, check_files: bool = True) -> list[str]:
    problems: list[str] = []
    if manifest.get("policy") != "fail_closed":
        problems.append("Manifest-Policy ist nicht fail_closed")
    if not str(manifest.get("manifest_version") or "").strip():
        problems.append("Manifest ohne manifest_version")
    for name in manifest.get("forbidden_value_patterns") or []:
        if name not in VALUE_PATTERNS:
            problems.append(f"unbekanntes Wertmuster {name}")
    seen: set[str] = set()
    hosts: dict[str, str] = {}
    present_classes: set[str] = set()
    for channel in channels(manifest):
        cid = str(channel.get("id") or "?")
        if cid in seen:
            problems.append(f"{cid}: Kanal doppelt")
        seen.add(cid)
        klass = channel.get("class")
        present_classes.add(str(klass))
        if klass not in CHANNEL_CLASSES:
            problems.append(f"{cid}: unbekannte Klasse {klass}")
        if channel.get("enforcement") not in ENFORCEMENTS:
            problems.append(f"{cid}: unbekannte Durchsetzung {channel.get('enforcement')}")
        if not str(channel.get("purpose") or "").strip():
            problems.append(f"{cid}: Zweck fehlt")
        if not str(channel.get("transmitted_data") or "").strip():
            problems.append(f"{cid}: uebermittelte Daten nicht beschrieben")
        if not isinstance(channel.get("personal_data"), bool):
            problems.append(f"{cid}: personal_data muss true/false sein")
        country = channel.get("destination_country")
        if not (isinstance(country, dict) and country.get("owner_field")):
            problems.append(f"{cid}: destination_country ist kein Owner-Feld")
        guarantee = channel.get("guarantee") or {}
        if channel.get("personal_data") is True and channel.get("guarantee", {}).get("status") != "OPERATOR_INFRASTRUCTURE":
            if not guarantee.get("owner_field") or guarantee.get("blocking") != "channel":
                problems.append(f"{cid}: Kanal mit Personendaten ohne sperrendes Garantie-Owner-Feld")
            if not (isinstance(country, dict) and country.get("blocking") == "channel"):
                problems.append(f"{cid}: Kanal mit Personendaten ohne sperrendes Staats-Owner-Feld")
            basis = channel.get("legal_basis") or {}
            if not basis.get("owner_field") or basis.get("blocking") != "channel":
                problems.append(f"{cid}: Kanal mit Personendaten ohne sperrendes Grundlage-Owner-Feld")
        elif not guarantee.get("owner_field"):
            if guarantee.get("status") not in NON_BLOCKING_GUARANTEES or not str(guarantee.get("reason") or "").strip():
                problems.append(f"{cid}: Garantie ohne Status/Begruendung")
        for host in channel.get("hosts") or []:
            normalized = _normalize_host(host)
            if normalized != host:
                problems.append(f"{cid}: Host {host} nicht normalisiert")
            if normalized in hosts:
                problems.append(f"{cid}: Host {host} auch in {hosts[normalized]}")
            hosts[normalized] = cid
        is_guarded = channel.get("enforcement") == "python_runtime_guard"
        if channel.get("enforcement") == "subprocess_guard" and not channel.get("subprocess_tools"):
            problems.append(f"{cid}: Subprozess-Kanal ohne subprocess_tools")
        for tool in channel.get("subprocess_tools") or []:
            if tool not in NETWORK_TOOLS:
                problems.append(f"{cid}: unbekanntes Netzwerkwerkzeug {tool}")
        if is_guarded and not (channel.get("hosts") or channel.get("host_from_setting")):
            problems.append(f"{cid}: Laufzeitkanal ohne Host")
        if is_guarded and channel.get("personal_data") is False and not channel.get("allowed_fields"):
            problems.append(f"{cid}: Kanal ohne Personendaten braucht allowed_fields (Datenminimierung)")
        policy = channel.get("field_policy", FIELD_POLICY_ALLOWLIST)
        if policy not in FIELD_POLICIES:
            problems.append(f"{cid}: unbekannte field_policy {policy}")
        if policy == FIELD_POLICY_SCREEN_ONLY:
            if channel.get("personal_data") is not False:
                problems.append(f"{cid}: screen_values_only nur fuer Kanaele ohne Personendaten")
            if not str(channel.get("field_policy_reason") or "").strip():
                problems.append(f"{cid}: screen_values_only ohne Begruendung")
        for field, pattern in (channel.get("field_patterns") or {}).items():
            if field not in (channel.get("allowed_fields") or []):
                problems.append(f"{cid}: Muster fuer nicht erlaubtes Feld {field}")
            try:
                re.compile(pattern)
            except re.error:
                problems.append(f"{cid}: ungueltiges Muster fuer {field}")
        for pattern in channel.get("path_patterns") or []:
            try:
                re.compile(pattern)
            except re.error:
                problems.append(f"{cid}: ungueltiges Pfadmuster")
        if not channel.get("code_references"):
            problems.append(f"{cid}: keine Code-Referenz")
        if check_files:
            for rel in channel.get("code_references") or []:
                if not (REPO_ROOT / rel).is_file():
                    problems.append(f"{cid}: Code-Referenz {rel} existiert nicht")
    for klass in REQUIRED_CLASSES:
        if klass not in present_classes:
            problems.append(f"Pflichtklasse {klass} fehlt")
    for flow in manifest.get("excluded_flows") or []:
        if not str(flow.get("reason") or "").strip():
            problems.append(f"{flow.get('id')}: Ausnahme ohne Begruendung")
    return problems


# ── Laufzeitschutz ────────────────────────────────────────────────────────────

def _normalize_host(host: Any) -> str:
    text = str(host or "").strip().lower().rstrip(".")
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


def _host_from_setting(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    remote = _REMOTE_TOKEN.match(text)
    if "://" not in text and remote:  # rsync/scp-Ziel user@host:/pfad
        return _normalize_host(remote.group(1))
    if "://" not in text:
        text = f"//{text}"
    try:
        return _normalize_host(urlsplit(text).hostname)
    except ValueError:
        return ""


def is_loopback(host: str) -> bool:
    if not host or host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _GuardState:
    def __init__(self) -> None:
        self.active = False
        self.installed = False
        self.manifest: dict[str, Any] | None = None
        self.manifest_error: str | None = None
        self.manifest_sha256: str | None = None
        self.settings: Any = None
        # None = keine Freigabe-Information -> jeder Kanal gesperrt (fail-closed)
        self.channel_states: dict[str, dict[str, Any]] | None = None
        self.recent_blocked: deque[dict[str, Any]] = deque(maxlen=_RECENT_LIMIT)
        self.pending_events: list[dict[str, Any]] = []
        self.event_sink: Any = None
        self.client_name_provider: Any = None
        self.flusher: threading.Thread | None = None
        self.stop_flusher = threading.Event()
        self.resolved: dict[str, float] = {}
        self.allowed_counts: dict[tuple[str, str], int] = {}
        self.counter_sink: Any = None
        self.lock = threading.Lock()
        self.local = threading.local()


_STATE = _GuardState()


def _setting(name: str, settings_obj: Any = None) -> Any:
    source = settings_obj if settings_obj is not None else _STATE.settings
    return getattr(source, name, None) if source is not None else None


def channel_enabled(channel: dict[str, Any], settings_obj: Any = None) -> bool:
    return all(bool(_setting(name, settings_obj)) for name in channel.get("requires_settings") or [])


def channel_hosts(channel: dict[str, Any], settings_obj: Any = None) -> list[str]:
    hosts = [_normalize_host(h) for h in channel.get("hosts") or []]
    if channel.get("host_from_setting"):
        dynamic = _host_from_setting(_setting(channel["host_from_setting"], settings_obj))
        if dynamic:
            hosts.append(dynamic)
    return hosts


def resolve_channel(host: str) -> dict[str, Any] | None:
    if _STATE.manifest is None:
        return None
    for channel in channels(_STATE.manifest):
        if channel.get("enforcement") != "python_runtime_guard":
            continue
        if host in channel_hosts(channel):
            return channel
    return None


def _block(reason_code: str, message: str, *, host: str, channel: str | None) -> None:
    entry = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason_code": reason_code, "channel": channel, "host": host,
    }
    record = {"manifest_sha256": _STATE.manifest_sha256,
              "payload_schema_hash": payload_schema_hash(getattr(_STATE.local, "shape", None))}
    if _STATE.manifest is not None and channel:
        found = channel_by_id(_STATE.manifest, channel) or {}
        state = (_STATE.channel_states or {}).get(channel) or {}
        record.update({"channel_class": found.get("class"),
                       "manifest_version": _STATE.manifest.get("manifest_version"),
                       "channel_sha256": state.get("current_sha256")})
    with _STATE.lock:
        _STATE.recent_blocked.append(entry)
        _STATE.pending_events.append({**entry, **(record or {})})
    logger.warning("Egress blockiert | reason=%s channel=%s host=%s", reason_code, channel, host)
    raise EgressBlocked(reason_code, message, channel=channel, host=host)


def check_host(raw_host: Any) -> dict[str, Any] | None:
    """Prueft einen Zielhost; liefert den Kanal (``None`` fuer lokal)."""
    host = _normalize_host(raw_host)
    if is_loopback(host):
        return None
    if _STATE.manifest is None:
        _block(ReasonCode.EGRESS_MANIFEST_MISSING, _STATE.manifest_error or "Manifest fehlt",
               host=host, channel=None)
    channel = resolve_channel(host)
    if channel is None:
        _block(ReasonCode.EGRESS_DESTINATION_DENIED, f"{host} ist kein Kanal des Egress-Manifests",
               host=host, channel=None)
    if not channel_enabled(channel):
        _block(ReasonCode.EGRESS_CHANNEL_DISABLED, f"Kanal {channel['id']} ist nicht konfiguriert",
               host=host, channel=channel["id"])
    _apply_channel_state(channel, host)
    return channel


def _apply_channel_state(channel: dict[str, Any], host: str) -> None:
    state = (_STATE.channel_states or {}).get(channel["id"])
    if state is None or (not state.get("approval_exempt") and not state.get("approved_sha256")):
        _block(ReasonCode.EGRESS_MANIFEST_MISSING, f"Kanal {channel['id']}: keine freigegebene Fassung",
               host=host, channel=channel["id"])
    if not state.get("approval_exempt") and state.get("approved_sha256") != state.get("current_sha256"):
        _block(ReasonCode.EGRESS_HASH_MISMATCH,
               f"Kanal {channel['id']}: freigegebene Fassung weicht vom aktuellen Manifest ab",
               host=host, channel=channel["id"])
    block = state.get("owner_block")
    if block == ReasonCode.EGRESS_CONSENT_OR_BASIS_MISSING:
        _block(ReasonCode.EGRESS_CONSENT_OR_BASIS_MISSING,
               f"Kanal {channel['id']}: Grundlage der Bekanntgabe nicht erfasst", host=host, channel=channel["id"])
    if block == ReasonCode.EGRESS_DESTINATION_DENIED:
        _block(ReasonCode.EGRESS_DESTINATION_DENIED,
               f"Kanal {channel['id']}: bestaetigter Zielhost passt nicht zur Einstellung", host=host,
               channel=channel["id"])
    if block:
        _block(ReasonCode.EGRESS_GUARANTEE_MISSING,
               f"Kanal {channel['id']}: Pflichtangaben (Staat/Garantie/Verschluesselung) nicht bestaetigt",
               host=host, channel=channel["id"])


def _tool_name(raw: Any) -> str:
    name = Path(str(raw or "").strip().strip("\"'")).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _split_command(text: str) -> list[str]:
    return [t.strip("\"'") for t in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', text)]


def _network_invocations(executable: Any, args: list[str]) -> list[tuple[str, list[str]]]:
    """N-899-10: alle Aufrufe von Netzwerkwerkzeugen, auch versteckt in einer
    Shell-Kommandozeile (``sh -c``, ``cmd /c``, PowerShell, ``os.system``) oder
    hinter Startwerkzeugen (``env``, ``nice``, ``xargs`` ...)."""
    tool = _tool_name(executable or (args[0] if args else ""))
    if tool in NETWORK_TOOLS:
        return [(tool, args[1:])]
    first = _tool_name(args[0]) if args else ""
    if tool not in SHELL_TOOLS | WRAPPER_TOOLS and first not in SHELL_TOOLS | WRAPPER_TOOLS:
        return []
    found = []
    # Anfuehrungszeichen entfernen: cmd /c "curl ..." bzw. sh -c 'curl ...'
    command = " ".join(args).replace('"', " ").replace("'", " ")
    for segment in _SHELL_SEPARATORS.split(command):
        tokens = segment.split()
        for index, token in enumerate(tokens):
            name = _tool_name(token)
            if name in NETWORK_TOOLS:
                found.append((name, tokens[index + 1:]))
                break
    return found


def check_shell_command(command: Any) -> None:
    """N-899-10: ``os.system``/Shell-Kommandozeile."""
    check_subprocess("sh", ["sh", "-c", str(command or "")])


def check_subprocess(executable: Any, argv: Any) -> None:
    """N-899-01/-10: Netzwerkwerkzeuge (rsync, ssh, curl ...) nur ueber einen
    freigegebenen Kanal mit ``subprocess_tools``; jedes entfernte Ziel in den
    Argumenten muss ein Host dieses Kanals sein. Shell-Kommandozeilen werden
    nach Netzwerkwerkzeugen durchsucht."""
    if isinstance(argv, (list, tuple)):
        args = [str(a) for a in argv]
    else:  # Windows: Kommandozeile als Zeichenkette (list2cmdline)
        args = _split_command(str(argv or ""))
    for tool, tool_args in _network_invocations(executable, args):
        _check_network_tool(tool, tool_args)


def _check_network_tool(tool: str, tool_args: list[str]) -> None:
    args = [tool, *tool_args]
    if _STATE.manifest is None:
        _block(ReasonCode.EGRESS_MANIFEST_MISSING, _STATE.manifest_error or "Manifest fehlt",
               host=tool, channel=None)
    channel = next((c for c in channels(_STATE.manifest) if tool in (c.get("subprocess_tools") or [])), None)
    if channel is None:
        _block(ReasonCode.EGRESS_DESTINATION_DENIED, f"Netzwerkwerkzeug {tool} ist an keinen Kanal gebunden",
               host=tool, channel=None)
    hosts = channel_hosts(channel)
    remote = [m.group(1).lower() for m in (_REMOTE_TOKEN.match(a) for a in args[1:]) if m]
    target = remote[0] if remote else (hosts[0] if hosts else tool)
    if not channel_enabled(channel):
        _block(ReasonCode.EGRESS_CHANNEL_DISABLED, f"Kanal {channel['id']} ist nicht konfiguriert",
               host=target, channel=channel["id"])
    for host in remote:
        if host not in hosts:
            _block(ReasonCode.EGRESS_DESTINATION_DENIED, f"Kanal {channel['id']}: Ziel {host} nicht freigegeben",
                   host=host, channel=channel["id"])
    _apply_channel_state(channel, target)
    _count_allowed(channel["id"])


_RESOLVED_TTL_SECONDS = 600.0


def _remember_resolution(host: str, port: Any) -> None:
    """Aufgeloeste Adressen erlaubter Hosts merken; ``socket.connect`` darf
    nur diese (oder lokale) Adressen erreichen."""
    with _STATE.lock:
        if _STATE.resolved.get(f"host:{host}", 0) >= _time.monotonic():
            return
    try:
        infos = socket.getaddrinfo(host, port or 443)
    except OSError:
        return
    expiry = _time.monotonic() + _RESOLVED_TTL_SECONDS
    with _STATE.lock:
        _STATE.resolved[f"host:{host}"] = expiry
        for info in infos:
            _STATE.resolved[str(info[4][0])] = expiry


def check_connect(address: Any) -> None:
    """N-899-08: direkter Socket-Connect nur zu lokalen Adressen oder zu
    Adressen, die zuvor fuer einen erlaubten Manifest-Host aufgeloest wurden."""
    if not isinstance(address, tuple) or not address:
        return  # AF_UNIX u. a.
    host = _normalize_host(address[0])
    if is_loopback(host):
        return
    try:
        ipaddress.ip_address(host)
    except ValueError:
        check_host(host)  # Name statt Adresse: wie Namensaufloesung pruefen
        return
    with _STATE.lock:
        expiry = _STATE.resolved.get(host)
    if expiry is not None and expiry >= _time.monotonic():
        return
    if resolve_channel(host) is not None:  # IP-Literal als Manifest-Host
        check_host(host)
        return
    _block(ReasonCode.EGRESS_DESTINATION_DENIED, f"Direkte Verbindung zu {host} ist kein Manifest-Ziel",
           host=host, channel=None)


_GERMAN_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})
# N-899-07/-12: Produkt-/Firmenbegriffe. Ein Nachname, der zugleich ein solcher
# Begriff ist ("Gold", "Baer"), sperrt -- ausser der Suchbegriff enthaelt
# mindestens ein weiteres Produktwort, eine ISIN oder ein Ticker-Muster
# ("Gold ETF", "Julius Baer", "GOLD.SW"). Bewusst in Kauf genommen
# (Datenschutz vor Komfort): ein Kunde "Roche" sperrt die Suche "Roche".
PRODUCT_TERMS = frozenset({
    "fund", "fonds", "etf", "index", "core", "global", "world", "swiss", "schweiz", "europe", "europa",
    "gold", "silver", "silber", "bond", "bonds", "equity", "aktien", "obligationen", "immobilien", "real",
    "estate", "income", "growth", "value", "dividend", "dividende", "select", "quality", "small", "large",
    "capital", "invest", "investment", "asset", "management", "bank", "kantonalbank", "trust", "holding",
    "msci", "ftse", "stoxx", "smi", "spi", "ishares", "vanguard", "xtrackers", "amundi", "lyxor", "ubs",
    "credit", "suisse", "pictet", "vontobel", "julius", "baer", "lombard", "odier", "sustainable", "esg",
    "climate", "green", "money", "market", "treasury", "corporate", "emerging", "markets", "america", "usa",
    "japan", "china", "asia", "pacific", "energy", "health", "technology", "tech", "first", "trust",
})


def _fold(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").casefold()
    return [token for token in re.split(r"[^a-z0-9]+", folded) if token]


def normalize_name(text: Any) -> list[str]:
    """Kleinbuchstaben ohne Akzente, nur Buchstaben/Ziffern als Tokens."""
    return _fold(str(text or ""))


def name_variants(text: Any) -> list[list[str]]:
    """Transliterationen: Akzente entfernt (ue -> u) und deutsche Umschrift
    (ue, oe, ae, ss)."""
    raw = str(text or "")
    variants = [_fold(raw), _fold(raw.translate(_GERMAN_TRANSLIT))]
    unique: list[list[str]] = []
    for variant in variants:
        if variant and variant not in unique:
            unique.append(variant)
    return unique


CLIENT_NAME_BLOCK_MESSAGE = (
    "Suche gesperrt: Der Suchbegriff entspricht einem erfassten Kundennamen und wird zum Schutz der "
    "Kundendaten nicht an externe Anbieter gesendet (auch wenn er zugleich ein Produkt- oder Firmenname ist). "
    "Bitte mit ISIN oder Ticker suchen."
)
_ISIN_RE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
_TICKER_RE = re.compile(r"^(?:\^[A-Z0-9]{2,8}|[A-Z0-9]{1,6}\.[A-Z]{1,4})$")


def _product_context(tokens: list[str], raw: str, term: str) -> bool:
    """Steht der Begriff mit einem weiteren Produktwort, einer ISIN oder einem
    Ticker-Muster (mit Boersenkuerzel bzw. Index-Caret) im Suchbegriff?"""
    if any(t in PRODUCT_TERMS and t != term for t in tokens):
        return True
    if _ISIN_RE.search(raw):
        return True
    return any(_TICKER_RE.match(word) for word in raw.split())


def _name_matches(tokens: list[str], first_parts: list[str], last_parts: list[str], raw: str) -> bool:
    parts = [*first_parts, *last_parts]
    joined, compact = f" {' '.join(tokens)} ", "".join(tokens)
    if not last_parts:
        return False
    last = last_parts[-1]
    if f" {' '.join(parts)} " in joined:
        return True
    if len(parts) >= 2 and all(p in tokens for p in parts):
        return True
    for combo in {"".join(parts), "".join(last_parts)}:
        if len(combo) >= 6 and combo in compact:
            return True  # zusammengeschrieben ("HansMueller", "MuellerMeier")
        if len(combo) >= 4 and combo in tokens and combo != last:
            return True  # zusammengeschrieben, kurz ("LiWu")
    if first_parts:
        initial = first_parts[0][0]
        for i in range(len(tokens) - 1):
            if tokens[i] == initial and tokens[i + 1] in last_parts:
                return True  # Initiale + Nachname
    for part in dict.fromkeys([*last_parts]):  # Doppelnamen-Teile einzeln
        if len(part) < 2:
            continue
        if len(part) < 4:
            if tokens == [part]:
                return True  # Kurzname allein, exakter Treffer ("Wu")
            continue
        if part in tokens and (part not in PRODUCT_TERMS or not _product_context(tokens, raw, part)):
            return True  # Nachname(nteil) allein
    return False


def _name_entry(entry: Any) -> tuple[str, str]:
    """Kundenname als (Vorname, Nachname); eine Zeichenkette wird am letzten
    Leerzeichen geteilt."""
    if isinstance(entry, (tuple, list)):
        first = entry[0] if entry else ""
        last = entry[1] if len(entry) > 1 else ""
        return str(first or ""), str(last or "")
    text = str(entry or "").strip()
    if " " not in text:
        return "", text
    first, last = text.rsplit(" ", 1)
    return first, last


def _client_name_hit(text: str) -> bool:
    provider = _STATE.client_name_provider
    if provider is None:
        return False
    term_variants = name_variants(text)
    if not term_variants:
        return False
    for entry in provider():
        first, last = _name_entry(entry)
        # Transliterationen von Vor- und Nachname unabhaengig kombinieren
        for last_parts in name_variants(last):
            for first_parts in name_variants(first) or [[]]:
                if all(len(p) < 2 for p in [*first_parts, *last_parts]):
                    continue
                if any(_name_matches(tokens, first_parts, last_parts, text) for tokens in term_variants):
                    return True
    return False


def _iter_json(node: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value if not isinstance(value, (dict, list)) else None
            yield from _iter_json(value, str(key))
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                yield from _iter_json(value, prefix)
            else:
                yield prefix, value


def _fields_of_body(body: bytes) -> tuple[list[tuple[str, Any]], bool]:
    """(Feld, Wert)-Paare eines Bodys; zweiter Wert: Struktur erkannt."""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return [], True
    if text[:1] in "[{":
        try:
            return [(k, v) for k, v in _iter_json(json.loads(text)) if k], True
        except ValueError:
            return [("", text)], False
    if "=" in text and " " not in text:
        return parse_qsl(text, keep_blank_values=True), True
    return [("", text)], False


def _screen_values(channel: dict[str, Any], pairs: list[tuple[str, Any]], host: str) -> None:
    opaque = set(channel.get("opaque_fields") or [])
    patterns = (_STATE.manifest or {}).get("forbidden_value_patterns") or list(VALUE_PATTERNS)
    field_patterns = channel.get("field_patterns") or {}
    for field, value in pairs:
        if value is None or field in opaque:
            continue
        text = unquote(str(value))
        for name in patterns:
            if VALUE_PATTERNS[name].search(text):
                _block(ReasonCode.EGRESS_VALUE_REJECTED,
                       f"Kanal {channel['id']}: Feld {field or '(Body)'} enthaelt ein {name}-Muster",
                       host=host, channel=channel["id"])
        if channel.get("client_name_screen"):
            try:
                hit = _client_name_hit(text)
            except Exception:  # noqa: BLE001 - Pruefung nicht moeglich -> fail-closed
                hit = True
            if hit:
                _block(ReasonCode.EGRESS_CLIENT_NAME_DENIED,
                       f"Kanal {channel['id']}: {CLIENT_NAME_BLOCK_MESSAGE}",
                       host=host, channel=channel["id"])
        pattern = field_patterns.get(field)
        if pattern and not re.fullmatch(pattern, text):
            _block(ReasonCode.EGRESS_VALUE_REJECTED,
                   f"Kanal {channel['id']}: Feld {field} entspricht nicht dem erlaubten Muster",
                   host=host, channel=channel["id"])


def payload_shape(data: Any) -> dict[str, Any]:
    """Form eines HTTP-Blocks ohne Werte: Methode, Pfadtiefe, Feldnamen."""
    if isinstance(data, memoryview):
        data = data.tobytes()
    if not isinstance(data, (bytes, bytearray)):
        return {"kind": "stream"}
    data = bytes(data)
    match = _REQUEST_LINE.match(data)
    shape: dict[str, Any] = {"kind": "request" if match else "body"}
    body = data
    if match:
        parts = urlsplit(match.group(2).decode("latin-1"))
        shape["method"] = match.group(1).decode()
        shape["path_depth"] = len([s for s in parts.path.split("/") if s])
        shape["query_fields"] = sorted({k for k, _ in parse_qsl(parts.query, keep_blank_values=True)})
        end = data.find(b"\r\n\r\n")
        body = data[end + 4:] if end >= 0 else b""
    pairs, structured = _fields_of_body(body)
    shape["body_fields"] = sorted({k for k, _ in pairs if k}) if structured else ["(unstrukturiert)"] if body else []
    return shape


def payload_schema_hash(shape: dict[str, Any] | None) -> str:
    """Hash ueber die Form (nie Werte); reine Verbindungsversuche ohne Payload
    haben die Form ``connect``."""
    return evidence_hash(shape or {"kind": "connect"}, scheme=SCHEME_V1)


def _count_allowed(channel_id: str) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _STATE.lock:
        key = (day, channel_id)
        _STATE.allowed_counts[key] = _STATE.allowed_counts.get(key, 0) + 1


def check_http_payload(raw_host: Any, data: Any) -> None:
    """Prueft einen ausgehenden HTTP-Datenblock (Request-Zeile + Body)."""
    host = _normalize_host(raw_host)
    shape = payload_shape(data)
    _STATE.local.shape = shape
    try:
        _check_http_payload(host, data)
    finally:
        _STATE.local.shape = None
    if shape.get("kind") == "request":
        channel = resolve_channel(host)
        if channel is not None:
            _count_allowed(channel["id"])


def _check_http_payload(host: str, data: Any) -> None:
    channel = check_host(host)
    if channel is None:
        return
    if isinstance(data, memoryview):
        data = data.tobytes()
    if not isinstance(data, (bytes, bytearray)):
        if channel.get("allowed_fields"):
            _block(ReasonCode.EGRESS_PAYLOAD_UNINSPECTABLE,
                   f"Kanal {channel['id']}: Datenstrom nicht pruefbar", host=host, channel=channel["id"])
        return
    data = bytes(data)
    pairs: list[tuple[str, Any]] = []
    structured = True
    match = _REQUEST_LINE.match(data)
    if match:
        method, target = match.group(1).decode(), match.group(2).decode("latin-1")
        if method == "CONNECT":
            check_host(target.rsplit(":", 1)[0])
            return
        parts = urlsplit(target)
        path = unquote(parts.path or "/")
        path_patterns = channel.get("path_patterns")
        if path_patterns and not any(re.fullmatch(p, path) for p in path_patterns):
            _block(ReasonCode.EGRESS_PATH_REJECTED, f"Kanal {channel['id']}: Pfad nicht erlaubt",
                   host=host, channel=channel["id"])
        pairs.extend(("", segment) for segment in path.split("/") if segment)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        pairs.extend(query_pairs)
        _check_field_names(channel, [k for k, _ in query_pairs], host)
        header_end = data.find(b"\r\n\r\n")
        body = data[header_end + 4:] if header_end >= 0 else b""
    else:
        body = data
    body_pairs, structured = _fields_of_body(body)
    if structured:
        _check_field_names(channel, [k for k, _ in body_pairs if k], host)
    pairs.extend(body_pairs)
    _screen_values(channel, pairs, host)


def _check_field_names(channel: dict[str, Any], names: list[str], host: str) -> None:
    allowed = channel.get("allowed_fields")
    if not allowed or channel.get("field_policy") == FIELD_POLICY_SCREEN_ONLY:
        return
    for name in names:
        if name not in allowed:
            _block(ReasonCode.EGRESS_FIELD_DENIED,
                   f"Kanal {channel['id']}: Feld {name} ist nicht freigegeben", host=host, channel=channel["id"])


def check_url_request(full_url: Any, data: Any, method: Any) -> None:
    """Vollstaendige Pruefung eines urllib-Requests, bevor eine Verbindung
    aufgebaut wird (Audit-Ereignis ``urllib.Request``): bei einer Sperre
    verlaesst kein Byte das System."""
    parts = urlsplit(str(full_url or ""))
    if parts.scheme not in ("http", "https"):
        return
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    head = f"{str(method or 'GET').upper()} {target} HTTP/1.1\r\n\r\n".encode("latin-1", errors="replace")
    body = data if isinstance(data, (bytes, bytearray)) else b""
    check_http_payload(parts.hostname, head + bytes(body))


_WATCHED_EVENTS = frozenset({"socket.getaddrinfo", "socket.connect", "socket.sendto", "socket.sendmsg",
                             "http.client.send", "urllib.Request", "subprocess.Popen", "os.system",
                             "os.posix_spawn", "os.exec", "os.spawn"})


def _audit_hook(event: str, args: tuple) -> None:
    if event not in _WATCHED_EVENTS or not _STATE.active:
        return
    if getattr(_STATE.local, "busy", False):
        return
    _STATE.local.busy = True
    try:
        if event == "socket.getaddrinfo":
            if check_host(args[0] if args else None) is not None:
                _remember_resolution(_normalize_host(args[0]), args[1] if len(args) > 1 else None)
        elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            # N-899-11: UDP (sendto/sendmsg) mit derselben Allowlist wie connect.
            check_connect(args[1] if len(args) > 1 else None)
        elif event == "subprocess.Popen":
            check_subprocess(args[0] if args else None, args[1] if len(args) > 1 else None)
        elif event == "os.system":
            check_shell_command(args[0] if args else None)
        elif event in ("os.posix_spawn", "os.exec"):
            check_subprocess(args[0] if args else None, args[1] if len(args) > 1 else None)
        elif event == "os.spawn":
            check_subprocess(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)
        elif event == "urllib.Request":
            check_url_request(args[0], args[1], args[3] if len(args) > 3 else None)
        else:
            connection, data = args[0], args[1]
            check_http_payload(getattr(connection, "host", None), data)
    finally:
        _STATE.local.busy = False


def activate(settings_obj: Any, *, channel_states: dict[str, dict[str, Any]] | None = None,
             manifest_path: Path | None = None, event_sink: Any = None, client_name_provider: Any = None,
             flush_interval_seconds: float = 5.0, counter_sink: Any = None) -> None:
    """Laufzeitschutz einschalten (idempotent). Fehlt das Manifest oder die
    Freigabe-Information, bleibt jeder nicht-lokale Kanal gesperrt; die App
    startet trotzdem. ``event_sink`` erhaelt blockierte Versuche gesammelt
    (persistentes Protokoll), ``client_name_provider`` liefert die erfassten
    Kundennamen fuer Kanaele mit ``client_name_screen``."""
    with _STATE.lock:
        _STATE.settings = settings_obj
        _STATE.channel_states = channel_states
        _STATE.event_sink = event_sink
        _STATE.counter_sink = counter_sink
        _STATE.client_name_provider = client_name_provider
        try:
            manifest = load_manifest(manifest_path)
            problems = manifest_problems(manifest, check_files=False)
            if problems:
                raise ManifestUnavailable("; ".join(problems))
            _STATE.manifest, _STATE.manifest_error = manifest, None
            _STATE.manifest_sha256 = manifest_hash(manifest)
        except ManifestUnavailable as exc:
            _STATE.manifest, _STATE.manifest_error, _STATE.manifest_sha256 = None, str(exc), None
            logger.critical("Egress-Manifest ungueltig, alle externen Kanaele gesperrt: %s", exc)
        if not _STATE.installed:
            sys.addaudithook(_audit_hook)
            _STATE.installed = True
        _STATE.active = True
        if (event_sink is not None or counter_sink is not None) and _STATE.flusher is None:
            _STATE.stop_flusher.clear()
            _STATE.flusher = threading.Thread(
                target=_flush_loop, args=(flush_interval_seconds,), name="egress-event-flush", daemon=True,
            )
            _STATE.flusher.start()


def update_channel_states(channel_states: dict[str, dict[str, Any]] | None) -> None:
    with _STATE.lock:
        _STATE.channel_states = channel_states


def flush_counts() -> int:
    """Zaehler erlaubter Uebertragungen (je Tag/Kanal, ohne Inhalt) speichern."""
    with _STATE.lock:
        counts, _STATE.allowed_counts = _STATE.allowed_counts, {}
        sink = _STATE.counter_sink
    if not counts or sink is None:
        return 0
    _STATE.local.busy = True
    try:
        sink(counts)
    except Exception:  # noqa: BLE001 - Zaehler duerfen den Schutz nicht stoppen
        logger.exception("Egress-Zaehler konnten nicht gespeichert werden")
        with _STATE.lock:
            for key, value in counts.items():
                _STATE.allowed_counts[key] = _STATE.allowed_counts.get(key, 0) + value
        return 0
    finally:
        _STATE.local.busy = False
    return sum(counts.values())


def flush_events() -> int:
    """Gesammelte Sperren an den Sink geben (persistentes Protokoll)."""
    flush_counts()
    with _STATE.lock:
        batch, _STATE.pending_events = _STATE.pending_events, []
        sink = _STATE.event_sink
    if not batch or sink is None:
        return 0
    _STATE.local.busy = True
    try:
        sink(batch)
    except Exception:  # noqa: BLE001 - Protokoll darf den Schutz nicht stoppen
        logger.exception("Egress-Ereignisse konnten nicht gespeichert werden")
        with _STATE.lock:
            _STATE.pending_events = batch + _STATE.pending_events
        return 0
    finally:
        _STATE.local.busy = False
    return len(batch)


def _flush_loop(interval: float) -> None:
    while not _STATE.stop_flusher.wait(interval):
        flush_events()


def deactivate() -> None:
    flush_events()
    with _STATE.lock:
        _STATE.active = False
        flusher, _STATE.flusher = _STATE.flusher, None
        _STATE.stop_flusher.set()
        _STATE.event_sink = None
        _STATE.counter_sink = None
        _STATE.client_name_provider = None
    if flusher is not None and flusher is not threading.current_thread():
        flusher.join(timeout=2)


def is_active() -> bool:
    return _STATE.active


def recent_blocked() -> list[dict[str, Any]]:
    with _STATE.lock:
        return list(_STATE.recent_blocked)


def runtime_status() -> dict[str, Any]:
    manifest = _STATE.manifest
    channel_rows = []
    for channel in channels(manifest) if manifest else []:
        guarded = channel.get("enforcement") == "python_runtime_guard"
        enabled = guarded and channel_enabled(channel)
        needs_owner = bool(blocking_owner_keys(channel))
        state = (_STATE.channel_states or {}).get(channel["id"]) or {}
        approved = bool(state.get("approval_exempt")) or (
            bool(state.get("approved_sha256")) and state.get("approved_sha256") == state.get("current_sha256"))
        channel_rows.append({
            "id": channel["id"], "class": channel["class"], "enforcement": channel["enforcement"],
            "personal_data": channel["personal_data"], "hosts": channel_hosts(channel) if guarded else [],
            "configured": enabled,
            "approved": approved,
            "allowed_now": bool(_STATE.active and enabled and approved and not state.get("owner_block")),
            "owner_confirmation_required": needs_owner,
            "owner_confirmed": needs_owner and not state.get("owner_block"),
            "owner_block": state.get("owner_block"),
        })
    return {
        "active": _STATE.active,
        "manifest_loaded": manifest is not None,
        "manifest_error": _STATE.manifest_error,
        "channels": channel_rows,
        "recent_blocked": recent_blocked(),
    }
