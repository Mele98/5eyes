"""G7: Klassifikation jedes Treffers des Rundungsstellen-Inventars.

Das Inventar selbst ist eine unveraenderte Kopie des Codex-Sweeps
(``scripts/inventory_2026_11_11_rounding_sites.py``, SHA-256 dde6e323...). Dieses
Skript ordnet jede gefundene Datei:Zeile genau einer Klasse zu:

* ``MIGRATE``          -- Anzeigeformatierung, laeuft ueber den gemeinsamen
                          Formatter (Policy ares-rounding/1); ``status=done``.
                          ``status=open`` (eigene Rundung) ist nicht zulaessig.
* ``COMPUTATION_KEEP`` -- rechnende Rundung (bps/Rappen-Ableitung, Eingabe ->
                          Integer, Geometrie/Pixel, Achsen-Ticks); bleibt bewusst.
* ``FALSE_POSITIVE``   -- Treffer ohne Rundung (Import, Definition/Implementierung
                          des Formatters, Kommentar, Name enthaelt nur das Muster).

Die Regeln werden in Reihenfolge geprueft; die erste passende gewinnt. Ein Treffer
ohne passende Regel ist ``UNCLASSIFIED`` -- der Test
``tests/test_rounding_site_classification.py`` ist dann rot.

Aufruf: ``python scripts/classify_rounding_sites.py [--write OUT.json]``
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory_2026_11_11_rounding_sites as inventory_mod  # noqa: E402

# Gemeinsame Formatter (Aufrufe = migriert).
_FORMATTER_CALLS = (
    r"\b(?:fmtPct|fmtNumber|fmtSignedPct|fmtProbPct|fmtSharpe|fmtCHF|formatRappen|formatSignedRappen|"
    r"formatCompactCHF|formatCompactCHFAmount|formatBpsPercent|formatSignedBpsPercent|formatRiskLossBps|"
    r"formatProbabilityPct|formatBpsAsPct|formatBpsSignedPct|formatChfRappen|formatChfFromRappen|"
    r"fmtChfCompact|fmtChfCompactAmount|formatMoneyRappen|formatMoneyMinor|formatPercentBps|formatDecimal|"
    r"formatCompactAmount|formatApportionedPercentBps|formatProbabilityPct|format_bps_as_pct|"
    r"format_bps_signed_pct|format_chf_rappen|format_amount_minor|format_pct_value|format_minor_number|"
    r"format_number|aaChartPctText|aaChartChf|dcFmtPct|btFormatPctBps|btSignedPctBps|formatCostRate|_formatRappenChf)\s*\(|=\s*formatRappen;"
)

# (Klasse, Status, Begruendung, Kanal-Regex fuer Datei, Regex fuer Quelltext)
RULES: list[tuple[str, str, str, str, str]] = [
    ("FALSE_POSITIVE", "", "Implementierung des gemeinsamen Formatters (Policy ares-rounding/1)",
     r"presentationRounding\.ts$|presentation-rounding\.js$|presentation_rounding\.py$", r"."),
    ("FALSE_POSITIVE", "", "Import/Export eines Formatters", r".", r"^\s*(?:import\b|export\s*\{|from\s+\S+\s+import\b|[A-Za-z_,\s]+\}\s*from\s)"),
    ("FALSE_POSITIVE", "", "Import-Liste (Name)", r"\.tsx?$|\.py$", r"^\s*[A-Za-z_]+,\s*$"),
    ("FALSE_POSITIVE", "", "Kommentar/Doku", r".", r"^\s*(?://|\*|/\*|#)"),
    ("FALSE_POSITIVE", "", "Funktionsdefinition delegiert an den gemeinsamen Formatter",
     r".", r"^\s*(?:export\s+)?function\s+(?:fmt|format)[A-Za-z_]*\s*\(|^\s*def\s+_?(?:fmt|format)[A-Za-z_]*\s*\(|^\s*function\s+formatRappen|^\s*function\s+_formatRappenChf"),
    # Geometrie, Layout, Achsen -- keine Kundenzahl.
    ("COMPUTATION_KEEP", "", "Geometrie/Layout (Pixel, CSS-Breite/Position, Farbe)", r".",
     r"style=|\bwidth\b|\bleft\b|height|pillW|\bx\b\s*=|\by\b\s*=|radius|Math\.round\(\s*(?:v|m|idx)\b|color-mix|toString\(16\)|"
     r"\bpx\b|canvas|\bctx\b|offset|fontSize|scale\(|Math\.round\(\(1-t\)|Math\.round\(idx"),
    ("COMPUTATION_KEEP", "", "Achsen-/Tick-Raster (Skalenberechnung)", r".",
     r"[Ss]tep|tick|Tick|y_tick|niceStep|k \* step"),
    ("COMPUTATION_KEEP", "", "Eingabe -> Integer-bps/Rappen (Persistenzwert, keine Anzeige)", r".",
     r"Math\.round\([^)]*\*\s*100\b|Math\.round\([^)]*\*\s*10000|Math\.round\(\s*(?:amount|value|v|n|num|chf|pct|parsed|x)\s*\*\s*100|"
     r"_rappen\s*[:=]\s*Math\.round|amount_rappen: Math\.round|_bps\s*[:=]\s*Math\.round|\*\s*100\)\s*:|parseCHF|parseBps|"
     r"Number\(\s*\w+\.toFixed\(4\)\)|toFixed\(4\)"),
    ("COMPUTATION_KEEP", "", "Rechnende Rundung (Ableitung bps/Rappen/Jahre, keine Anzeige)", r"\.py$",
     r"int\(round\(|=\s*round\(|round\(\s*\w+\s*\*|\bround\(k \*|sorted\(\{round"),
    ("COMPUTATION_KEEP", "", "Rechnende Rundung im Frontend (Zwischenwert/Vergleich, keine Anzeige)", r".",
     r"Math\.round\((?:Number\()?\(?[A-Za-z_.\[\]]+\s*[/*]\s*[A-Za-z0-9_.()]+\)?\)?\s*[;,)]|=\s*Math\.round\(|"
     r"Math\.round\(Number\([^)]*\)\)|Math\.max\(0,\s*Math\.round|Math\.abs\([^)]*Math\.round|"
     r"Math\.round\(canonical|return\s+Math\.round\(|Math\.round\(\w+\)\s*[!=<>]|isFinite\(n\)\s*\?\s*Math\.round"),
    ("COMPUTATION_KEEP", "", "Eingabefeld-Wert (Roundtrip eines Editierfelds, keine Kundenevidenz)", r".",
     r"setInputValue\(|formatInput(?:CHF|Percent)\(|horizonInput\.value|function formatInput|formatBandPercent\(|"
     r"parseBandPercentInput|adminBpsToPercentValue|\.value\s*=\s*String\("),
    ("COMPUTATION_KEEP", "", "Ganzzahlige Skala (Risikoscore x10, Jahre, Inflationsmittel) -- kein Policy-Grenzfall", r".",
     r"[Ss]core|_x10|avgInflation|years\)\)"),
    ("COMPUTATION_KEEP", "", "Datum/Zeit-Formatierung (keine Zahl der Kundenevidenz)", r".", r"new Date\("),
    ("COMPUTATION_KEEP", "", "Projektions-/Reihenberechnung (Rappen, keine Anzeige)", r".",
     r"[Ss]eries|push\(Math\.round|Sockel|startK|startRappen|partialSaleChf|bps:Math\.round|chf:Math\.round|"
     r"chfTarget:Math\.round|isFinite\(n\)\?Math\.max"),
    # Anzeige ueber den gemeinsamen Formatter.
    ("MIGRATE", "done", "Anzeige ueber gemeinsamen Formatter", r".", _FORMATTER_CALLS),
    ("MIGRATE", "done", "Anzeige ueber gemeinsamen Formatter (AresRounding)", r".", r"AresRounding\."),
]


# Rohe Rundung im Quelltext (nicht ueber den gemeinsamen Formatter).
RAW = re.compile(r"\.toFixed\(|Intl\.NumberFormat|toLocaleString\(|Math\.round\(|\bround\(|\.quantize\(|ROUND_HALF|:\.[0-9]+[f%]")


# Anzeige-Senken: eine rohe Rundung auf einer solchen Zeile ist nie "rechnend" per Regel.
SINK = re.compile(r"textContent|innerHTML|setText\(|aria-label|title=|Error\(|return\s+'|\+\s*'[^']*%|\.label\b|label:\s*function|tipFormat|<td|<span|<div")


def _classify_one(site: dict) -> tuple[str, str, str]:
    """N-894-03: COMPUTATION_KEEP nur per Einzelentscheid (Overrides-Datei = die
    Ausnahme-Annotation je Stelle, mit Datenfluss-Begruendung). Regeln liefern fuer
    rohe Rundung hoechstens einen Vorschlag; ohne Einzelentscheid ist die Stelle
    UNCLASSIFIED (Test rot). FALSE_POSITIVE und MIGRATE/done (Formatter-Aufruf ohne
    rohe Rundung) bleiben regelbasiert."""
    src = site["source"]
    override = OVERRIDES.get(_key(site))
    if override:
        return override
    for c, st, why, file_re, src_re in RULES:
        if c != "FALSE_POSITIVE":
            continue
        if re.search(file_re, site["file"]) and re.search(src_re, src):
            return c, st, why
    if RAW.search(src):
        for c, st, why, file_re, src_re in RULES:
            if c == "COMPUTATION_KEEP" and re.search(file_re, site["file"]) and re.search(src_re, src):
                hint = "Anzeige-Senke! " if SINK.search(src) else ""
                return "UNCLASSIFIED", "", "Vorschlag (Einzelentscheid noetig): " + hint + why
        return "UNCLASSIFIED", "", ""
    for c, st, why, file_re, src_re in RULES:
        if (c, st) == ("MIGRATE", "done") and re.search(file_re, site["file"]) and re.search(src_re, src):
            return c, st, why
    for c, st, why, file_re, src_re in RULES:
        if c == "COMPUTATION_KEEP" and why.startswith("Eingabefeld") and re.search(file_re, site["file"]) and re.search(src_re, src):
            return "UNCLASSIFIED", "", "Vorschlag (Einzelentscheid noetig): " + why
    return "UNCLASSIFIED", "", ""


def _git_head(root: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def classic_modules() -> list[str]:
    """N-894-13: alle ausgelagerten bzw. eigenstaendigen Classic-Module, generiert aus
    scripts/audit_html_monolith.py (EXTRACTED_MONOLITH_PARTS + STANDALONE_FRONTEND_MODULES)."""
    from audit_html_monolith import EXTRACTED_MONOLITH_PARTS, STANDALONE_FRONTEND_MODULES

    names = {name for name, kind in EXTRACTED_MONOLITH_PARTS if kind == "js"}
    names |= {name for name in STANDALONE_FRONTEND_MODULES if name.endswith(".js")}
    return sorted(names)


def _classic_module_sites(root: Path) -> list[dict]:
    """Gleiches Muster wie das (unveraenderte) Codex-Inventar, angewandt auf die Module."""
    rows: list[dict] = []
    for name in classic_modules():
        path = root / "ares-desktop" / "frontend" / name
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if inventory_mod.PATTERN.search(line):
                rows.append({"file": path.relative_to(root).as_posix(), "line": number, "source": line.strip()[:240]})
    return rows


def classify(root: Path = REPO_ROOT) -> dict:
    data = inventory_mod.inventory(root)
    # N-894-13: das Codex-Inventar deckt fuer Classic nur ares.html ab; die Module
    # (goal-review-runtime.js, product-master-data.js, aa-chart.js, ...) gehoeren dazu.
    data["classic"] = list(data["classic"]) + _classic_module_sites(root)
    rows = []
    texts: dict[str, list[str]] = {}
    for channel, sites in data.items():
        for site in sites:
            if site["file"] not in texts:
                texts[site["file"]] = (root / site["file"]).read_text(encoding="utf-8").splitlines()
            # Das Inventar kuerzt den Quelltext auf 240 Zeichen; klassifiziert wird die volle Zeile.
            full = {**site, "source": texts[site["file"]][site["line"] - 1].strip()}
            cls, status, reason = _classify_one(full)
            rows.append({**site, "channel": channel, "class": cls, "status": status, "reason": reason})
    counts: dict[str, int] = {}
    for row in rows:
        k = row["class"] + (f":{row['status']}" if row["status"] else "")
        counts[k] = counts.get(k, 0) + 1
    return {"schema_version": 1, "policy_version": "ares-rounding/1", "counts": counts, "sites": rows}


def _key(site: dict) -> str:
    return site["file"] + "::" + site["source"][:240]


# Einzelentscheide fuer Treffer, die keine allgemeine Regel trifft (Quelltext-genau).
OVERRIDES: dict[str, tuple[str, str, str]] = {}
_OVERRIDES_PATH = REPO_ROOT / "docs" / "audits" / "2026-11-11-g7-rounding-site-overrides.json"
if _OVERRIDES_PATH.is_file():
    for entry in json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))["overrides"]:
        OVERRIDES[entry["file"] + "::" + entry["source"]] = (entry["class"], entry.get("status", ""), entry["reason"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()
    result = classify(REPO_ROOT)
    result["head_sha_parent"] = _git_head(REPO_ROOT)
    if args.write:
        args.write.write_text(json.dumps(result, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], sort_keys=True))
    return 0 if "UNCLASSIFIED" not in result["counts"] else 1


if __name__ == "__main__":
    sys.exit(main())
