"""Gemeinsame Werkzeuge des Abnahmenetzes (Laenderpaket-Schritt X0).

Das Abnahmenetz friert das heutige Verhalten als Basiswerte ein, damit jeder
spaetere Umbau in Laenderpakete beweisbar verhaltensneutral ist (G2-G6).

Plattformunabhaengigkeit (Windows == Linux):
* Kanonisches JSON: sortierte Schluessel, ``ensure_ascii``, feste Trenner,
  ``\\n`` als Zeilenende, Floats auf 12 signifikante Stellen (Pythons eigene
  Formatierung, unabhaengig von libc/BLAS-Rundung in der letzten Stelle).
* Volatile Werte (UUIDs, Zeitstempel, Tagesdatum, Hex-Hashes) werden maskiert.
* Basiswerte enthalten fuer Texte nur Digests und Laengen, keine Klartexte:
  sie bleiben damit markenneutral; die Klartexte lassen sich bei Bedarf lokal
  ausgeben (``ACCEPTANCE_NET_DUMP_DIR``), ohne sie einzuchecken.

Basiswerte neu schreiben (nur bei bewusst gewollter Verhaltensaenderung, im PR
begruenden): ``ACCEPTANCE_NET_UPDATE=1 pytest tests/test_acceptance_net_*.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

BASELINE_DIR = Path(__file__).resolve().parent / "fixtures" / "acceptance_net"

UPDATE_ENV = "ACCEPTANCE_NET_UPDATE"
DUMP_ENV = "ACCEPTANCE_NET_DUMP_DIR"

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CH_DATE_RE = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{4}\b")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?Uhr)?\b")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
# Audit-Kurzhash im PDF-Fuss (aus der Mandats-ID abgeleitet).
_AUDIT_RE = re.compile(r"(Audit:\s*)[0-9a-fA-F]{6,}\b")
_WS_RE = re.compile(r"\s+")


def update_mode() -> bool:
    return os.environ.get(UPDATE_ENV, "").strip() == "1"


def mask_text(value: str) -> str:
    """Volatile Teile eines Textes maskieren (Reihenfolge: lang vor kurz)."""
    text = _UUID_RE.sub("<uuid>", value)
    text = _ISO_TS_RE.sub("<ts>", text)
    text = _ISO_DATE_RE.sub("<date>", text)
    text = _CH_DATE_RE.sub("<date>", text)
    text = _TIME_RE.sub("<time>", text)
    text = _AUDIT_RE.sub(r"\1<hex>", text)
    return _HEX_RE.sub("<hex>", text)


def canonical(value: Any, *, mask: bool = True) -> Any:
    """Plattformneutrale, maskierte Normalform fuer JSON-artige Werte."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return float(format(value, ".12g"))
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<bytes:" + hashlib.sha256(bytes(value)).hexdigest()[:16] + ">"
    if isinstance(value, str):
        return mask_text(value) if mask else value
    if isinstance(value, dict):
        return {str(k): canonical(v, mask=mask) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v, mask=mask) for v in value]
    return canonical(str(value), mask=mask)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(value: Any) -> str:
    raw = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def shape(value: Any) -> Any:
    """Typ-Skelett einer JSON-Antwort (Feldmenge und Typen, keine Werte)."""
    if isinstance(value, dict):
        return {str(k): shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        kinds = {canonical_json(shape(item)): shape(item) for item in value}
        return {"list_of": [kinds[key] for key in sorted(kinds)]}
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    return type(value).__name__


def text_fingerprint(text: str) -> dict:
    """Digest eines Textes ohne Leerraum (robust gegen Abstands-Heuristiken
    der Textextraktion) plus Laenge als lesbarer Diagnosewert."""
    compact = _WS_RE.sub("", mask_text(text))
    return {"chars": len(compact), "sha256": hashlib.sha256(compact.encode("utf-8")).hexdigest()}


def baseline_path(name: str) -> Path:
    return BASELINE_DIR / name


def write_baseline_json(name: str, value: Any) -> None:
    path = baseline_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, sort_keys=True, ensure_ascii=True, indent=1) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)


def load_baseline_json(name: str) -> Any:
    path = baseline_path(name)
    if not path.is_file():
        pytest.fail(f"Basiswert {path.name} fehlt; mit {UPDATE_ENV}=1 erzeugen.")
    return json.loads(path.read_text(encoding="utf-8"))


def dump_actual(name: str, content: str) -> None:
    """Klartext lokal ablegen (nur wenn ACCEPTANCE_NET_DUMP_DIR gesetzt ist)."""
    target = os.environ.get(DUMP_ENV, "").strip()
    if not target:
        return
    path = Path(target) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def assert_matches_baseline(name: str, actual: Any) -> None:
    """Vergleich gegen den eingecheckten Basiswert (oder Neuschreiben)."""
    actual = json.loads(canonical_json(actual))
    if update_mode():
        write_baseline_json(name, actual)
        return
    expected = load_baseline_json(name)
    if actual == expected:
        return
    diffs = list(_diff_paths(expected, actual, ""))
    pytest.fail(
        f"Abweichung vom Basiswert {name} ({len(diffs)} Stellen): "
        + "; ".join(diffs[:25])
    )


def _diff_paths(expected: Any, actual: Any, prefix: str):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            path = f"{prefix}/{key}"
            if key not in expected:
                yield f"{path}: neu"
            elif key not in actual:
                yield f"{path}: fehlt"
            else:
                yield from _diff_paths(expected[key], actual[key], path)
        return
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        for idx, (e, a) in enumerate(zip(expected, actual)):
            yield from _diff_paths(e, a, f"{prefix}[{idx}]")
        return
    if expected != actual:
        yield f"{prefix or '/'}: {_short(expected)} -> {_short(actual)}"


def _short(value: Any) -> str:
    text = canonical_json(value)
    return text if len(text) <= 80 else text[:77] + "..."
