"""OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 -- Auslieferungskette.

Warum diese Datei getrennt existiert
------------------------------------
`tests/test_goal_driver_milli_collapse_indistinguishable.py` prueft den
KONVERTER (`_lossless_objective_evidence`) und eine NACHBILDUNG der
Produktionsschleife als reines dict. Gegenprobe gefahren: entfernt man die
beiden Felddeklarationen aus `OptimizerGoalDriverResponse`, bleiben dort
alle 16 Tests gruen -- obwohl dann kein einziger Konsument die verlustfreie
Evidenz mehr erhaelt. Genau dieser Zustand WAR der Befund.

Der Defekt sass also nie im Rechenweg, sondern an der Schema-Grenze: Pydantic
verwirft ein Feld, das der Service setzt und das Response-Modell nicht
deklariert, STILL -- kein Fehler, kein Log, das Feld ist einfach weg. Dieselbe
Fehlerklasse ist in dieser Kontrollrunde fuenfmal aufgetreten
(`requires_resolution`, `evidence_status`, `source_run_status`,
`evidence_frozen` und hier). Ein Test, der die Kette nicht durchlaeuft, kann
sie nicht fangen.

Diese Datei prueft daher die Kette statt der Rechnung:

    Produktions-Dict  ->  Response-Modell  ->  JSON  ->  Monolith-Anzeige

Test 1 ist bewusst GENERISCH gebaut (AST-Abgleich der Schluessel, nicht eine
Liste erwarteter Namen). Ein kuenftiges sechstes Feld, das im Service gesetzt
und im Schema vergessen wird, geht damit rot, ohne dass jemand diesen Test
anfassen muss -- das ist der eigentliche Zweck.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas.allocation import OptimizerGoalDriverResponse  # noqa: E402
from services.portfolio_engine_optimizer_integration import (  # noqa: E402
    _lossless_objective_evidence,
)

# Die Nachbildung aus der Konverter-Datei wird hier GEGEN die Produktion
# geprueft (Test 2) -- sie behauptet von sich, exakt zu replizieren, und diese
# Behauptung soll nicht nur im Docstring stehen.
from test_goal_driver_milli_collapse_indistinguishable import (  # noqa: E402
    _build_drivers_payload_like_production,
    _make_contribution,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
INTEGRATION_PATH = BACKEND_DIR / "services" / "portfolio_engine_optimizer_integration.py"
HTML_PATH = (
    BACKEND_DIR.parent / "ares-desktop" / "frontend" / "ares.html"
)

# Dieselben Werte wie im Audit-Dok: vier materiell verschiedene Zustaende, die
# das Legacy-Milli-Feld alle auf 0 kollabiert.
FULLY_SATISFIED = 0.0
MINIMAL_MISS = 4e-12
SMALL_MATERIAL_SHORTFALL = 4e-5
LARGER_MATERIAL_SHORTFALL = 0.00049


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _production_driver_payload_keys() -> set[str]:
    """Die Schluessel, die die Produktion tatsaechlich in einen Goal-Driver
    schreibt -- aus dem Quelltext von `_build_optimizer_explainability`
    gelesen, nicht hier nachgetippt.

    Per AST statt per Regex, damit Zeilenumbrueche, Kommentare zwischen den
    Eintraegen und mehrzeilige Werte (beides steht dort) die Erkennung nicht
    beeinflussen.
    """
    tree = ast.parse(INTEGRATION_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "_build_optimizer_explainability":
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Dict):
                continue
            keys = {
                k.value for k in inner.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            # Der Goal-Driver-Dict ist der mit goal_id UND rank; andere Dicts
            # in derselben Funktion (Constraints, Meta) haben das nicht.
            if {"goal_id", "rank"} <= keys:
                return keys
        pytest.fail(
            "Goal-Driver-Dict in _build_optimizer_explainability nicht "
            "gefunden -- die Funktion hat ihre Form geaendert, dieser Test "
            "muss nachgezogen werden statt stillschweigend nichts zu pruefen."
        )
    pytest.fail("_build_optimizer_explainability nicht gefunden")


def _publish(payload: dict) -> dict:
    """Schickt ein Produktions-Dict durch das echte Response-Modell und gibt
    zurueck, was tatsaechlich beim Konsumenten ankommt -- einmal um JSON und
    zurueck, damit auch die JSON-Stufe wirklich durchlaufen wird."""
    model = OptimizerGoalDriverResponse(**payload)
    return json.loads(model.model_dump_json())


def _driver_payload(goal_id: str, raw: float) -> dict:
    rows = [_make_contribution(goal_id, raw)]
    return _build_drivers_payload_like_production(rows)[0]


def _require_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")


def _run_node(script: str) -> str:
    """Script ueber eine Datei statt ueber `node -e` fahren und explizit
    utf-8 kodieren/dekodieren.

    Der extrahierte Block enthaelt 'erfuellt' mit Umlaut und einen
    Geviertstrich. Ueber argv und die Windows-Locale-Kodierung wuerden beide
    verstuemmelt, und der Test wuerde an der Kodierung scheitern statt an der
    Sache.
    """
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "render_goal_driver_row.mjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            ["node", str(script_path)],
            capture_output=True, timeout=10, check=False,
        )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8").strip()


def _extract_row_mapper(html: str) -> str:
    """Den echten Zeilen-Renderer der Goal-Driver-Tabelle aus dem Monolithen
    schneiden (Klammer-Matching, wie `_extract_balanced_block` in
    tests/test_cert_cost_publication_001_reproducers.py)."""
    anchor = "dBody.innerHTML=drivers.map(function(d){"
    assert anchor in html, (
        "Anker der Goal-Driver-Tabelle nicht gefunden -- der Monolith hat "
        "diese Stelle umgebaut; Extraktion nachziehen."
    )
    fn_start = html.index(anchor) + len("dBody.innerHTML=drivers.map(")
    i = html.index("{", fn_start)
    depth, j = 1, i + 1
    while depth:
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
        j += 1
    return html[fn_start:j]


# ---------------------------------------------------------------------------
# 1. Die Fehlerklasse generisch: kein Service-Feld darf am Schema verschwinden
# ---------------------------------------------------------------------------


def test_every_production_driver_key_is_declared_on_the_response_model():
    """JEDER Schluessel, den die Produktion in einen Goal-Driver schreibt,
    muss auf `OptimizerGoalDriverResponse` deklariert sein.

    Nicht deklariert heisst bei Pydantic nicht "Fehler", sondern "lautlos
    verworfen". Dieser Test ist der Grund, warum die Datei existiert: er
    nennt keine Feldnamen und faengt damit auch das naechste vergessene Feld.
    """
    production_keys = _production_driver_payload_keys()
    declared = set(OptimizerGoalDriverResponse.model_fields)

    # Sanity: die Extraktion hat wirklich den Goal-Driver-Dict erwischt und
    # nicht einen leeren oder fremden. Ohne diese Zeile koennte der Test
    # gruen sein, weil er nichts geprueft hat.
    assert len(production_keys) >= 7, production_keys

    missing = production_keys - declared
    assert not missing, (
        "Diese Felder setzt der Service, das Response-Modell deklariert sie "
        f"NICHT -- Pydantic verwirft sie still: {sorted(missing)}"
    )


def test_replica_helper_in_sibling_test_matches_production_keys():
    """Die Nachbildung in der Konverter-Testdatei muss dieselben Schluessel
    liefern wie die Produktion.

    Sonst prueft jene Datei eine Produktion, die es nicht gibt -- genau das
    war vor dem Fix der Fall, als sie nur das Milli-Feld nachbildete.
    """
    replica_keys = set(_driver_payload("g", LARGER_MATERIAL_SHORTFALL))
    assert replica_keys == _production_driver_payload_keys(), (
        "Nachbildung und Produktion sind auseinandergelaufen: "
        f"nur in der Nachbildung {sorted(replica_keys - _production_driver_payload_keys())}, "
        f"nur in der Produktion {sorted(_production_driver_payload_keys() - replica_keys)}"
    )


# ---------------------------------------------------------------------------
# 2. Die Schema-Grenze konkret
# ---------------------------------------------------------------------------


def test_lossless_pair_survives_the_response_model():
    """Das verlustfreie Paar muss die Serialisierung ueberleben -- wertgleich,
    nicht nur namentlich vorhanden."""
    payload = _driver_payload("small", SMALL_MATERIAL_SHORTFALL)
    published = _publish(payload)

    assert "weighted_objective_contribution_decimal" in published, (
        "Der Dezimalwert kommt beim Konsumenten nicht an."
    )
    assert "weighted_objective_contribution_binary64_hex" in published, (
        "Die bit-exakte Darstellung kommt beim Konsumenten nicht an."
    )
    expected_decimal, expected_hex = _lossless_objective_evidence(
        SMALL_MATERIAL_SHORTFALL
    )
    assert published["weighted_objective_contribution_decimal"] == expected_decimal
    assert published["weighted_objective_contribution_binary64_hex"] == expected_hex

    # Und der Rohwert ist aus dem PUBLIZIERTEN Feld exakt zurueckzulesen --
    # das ist der eigentliche Zweck, nicht die Anwesenheit eines Strings.
    assert float(published["weighted_objective_contribution_decimal"]) == (
        SMALL_MATERIAL_SHORTFALL
    )
    assert float.fromhex(
        published["weighted_objective_contribution_binary64_hex"]
    ) == SMALL_MATERIAL_SHORTFALL


def test_published_states_stay_apart_after_the_response_model():
    """Die vier Audit-Zustaende muessen NACH der Serialisierung unterscheidbar
    sein -- und das Legacy-Feld muss sie weiterhin kollabieren.

    Die zweite Haelfte ist der Beleg, dass die Unterscheidbarkeit aus dem
    neuen Paar kommt und nicht daher, dass jemand das Milli-Feld
    stillschweigend umskaliert hat (das waere ein Bruch fuer jeden
    bestehenden Konsumenten).
    """
    raws = [
        FULLY_SATISFIED,
        MINIMAL_MISS,
        SMALL_MATERIAL_SHORTFALL,
        LARGER_MATERIAL_SHORTFALL,
    ]
    published = [_publish(_driver_payload(f"g{i}", raw)) for i, raw in enumerate(raws)]

    decimals = [p["weighted_objective_contribution_decimal"] for p in published]
    hexes = [p["weighted_objective_contribution_binary64_hex"] for p in published]
    assert len(set(decimals)) == 4, decimals
    assert len(set(hexes)) == 4, hexes
    assert [float(d) for d in decimals] == raws

    millis = {p["weighted_objective_contribution_milli"] for p in published}
    assert millis == {0}, (
        "Das Legacy-Milli-Feld wurde umskaliert -- Zielvertrag Punkt 7 "
        f"verlangt es unveraendert: {millis}"
    )


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf")])
def test_unavailable_publishes_as_null_not_zero(raw):
    """Nicht endliche Werte muessen als JSON `null` ankommen, nicht als 0.

    "Nicht verfuegbar" und "Ziel vollstaendig erfuellt" sind verschiedene
    Aussagen; sie auf 0 zusammenzuziehen waere derselbe Fehler wie der
    Milli-Kollaps, nur eine Stufe spaeter. Geprueft wird am JSON-TEXT, weil
    nur dort `null` von `0` sicher zu unterscheiden ist.
    """
    payload = _driver_payload("unavailable", raw)
    raw_json = OptimizerGoalDriverResponse(**payload).model_dump_json()
    published = json.loads(raw_json)

    assert published["weighted_objective_contribution_decimal"] is None
    assert published["weighted_objective_contribution_binary64_hex"] is None
    assert re.search(
        r'"weighted_objective_contribution_decimal"\s*:\s*null', raw_json
    ), raw_json

    # Gegenprobe: der echte Nullwert ist NICHT null, sondern "0.0".
    zero_published = _publish(_driver_payload("zero", FULLY_SATISFIED))
    assert zero_published["weighted_objective_contribution_decimal"] is not None
    assert float(zero_published["weighted_objective_contribution_decimal"]) == 0.0


# ---------------------------------------------------------------------------
# 3. Das letzte Glied: was der Berater wirklich liest
# ---------------------------------------------------------------------------


def test_monolith_row_renders_the_lossless_value_in_three_distinct_states():
    """Der echte Zeilen-Renderer des Monolithen, aus dem HTML geschnitten und
    unter Node ausgefuehrt.

    Dass das Feld im Payload steht, hilft niemandem, wenn die Maske weiter
    das Milli-Feld anzeigt -- das war vor dem Fix genau so. Jedes
    Eingangs-Objekt traegt daher ein absichtlich kollabiertes
    `*_milli: 0`: zeigt die Maske noch das Legacy-Feld, stehen hier drei
    identische "0" und der Test geht rot.
    """
    _require_node()
    mapper_src = _extract_row_mapper(HTML_PATH.read_text(encoding="utf-8"))
    assert "weighted_objective_contribution_decimal" in mapper_src, (
        "Sanity: der extrahierte Renderer liest das verlustfreie Feld nicht "
        "-- Extraktion zeigt auf die falsche Stelle."
    )

    rows = [
        {"rank": 1, "label": "Grosser Shortfall", "hardness_key": "hart",
         "weight_bps": 5000, "weighted_objective_contribution_milli": 0,
         "weighted_objective_contribution_decimal":
             _lossless_objective_evidence(LARGER_MATERIAL_SHORTFALL)[0]},
        {"rank": 2, "label": "Minimale Verfehlung", "hardness_key": "hart",
         "weight_bps": 5000, "weighted_objective_contribution_milli": 0,
         "weighted_objective_contribution_decimal":
             _lossless_objective_evidence(MINIMAL_MISS)[0]},
        {"rank": 3, "label": "Erfuellt", "hardness_key": "hart",
         "weight_bps": 5000, "weighted_objective_contribution_milli": 0,
         "weighted_objective_contribution_decimal":
             _lossless_objective_evidence(FULLY_SATISFIED)[0]},
        {"rank": 4, "label": "Nicht verfuegbar", "hardness_key": "hart",
         "weight_bps": 5000, "weighted_objective_contribution_milli": 0,
         "weighted_objective_contribution_decimal": None},
    ]

    script = (
        "function escapeHtml(s){return String(s);}\n"
        "function formatBpsPercent(b){return String(Number(b)/100)+'%';}\n"
        "const renderRow = " + mapper_src + ";\n"
        "const rows = " + json.dumps(rows) + ";\n"
        "console.log(JSON.stringify(rows.map(function(r){"
        "return renderRow(r);})));\n"
    )
    rendered = json.loads(_run_node(script))
    assert len(rendered) == 4, rendered

    def _contribution_cell(row_html: str) -> str:
        cells = re.findall(r"<td>(.*?)</td>", row_html, flags=re.S)
        assert len(cells) == 5, row_html
        return cells[4]

    cells = [_contribution_cell(r) for r in rendered]

    # Der Kern: vier Zeilen, die im Legacy-Feld alle "0" waeren, ergeben hier
    # vier verschiedene Anzeigen.
    assert len(set(cells)) == 4, (
        f"Die Maske zeigt materiell verschiedene Beitraege gleich an: {cells}"
    )

    larger, minimal, satisfied, unavailable = cells
    assert float(larger) == LARGER_MATERIAL_SHORTFALL, larger
    assert float(minimal) == MINIMAL_MISS, minimal
    assert "erf" in satisfied and satisfied.startswith("0"), satisfied
    assert "nicht verf" in unavailable, unavailable
    assert unavailable != satisfied, (
        "'nicht verfuegbar' und 'erfuellt' sind in der Maske dieselbe "
        "Anzeige -- der Unterschied, auf dem Zielvertrag Punkt 4 besteht, "
        "kommt beim Berater nicht an."
    )


def test_monolith_does_not_round_the_displayed_contribution():
    """Keine Anzeige-Rundung auf dem Beitragswert.

    Eine Rundung in der Maske wuerde den Kollaps genau dort wieder
    einfuehren, wo er behoben werden sollte -- der Payload waere verlustfrei
    und der Berater saehe trotzdem "0". Deshalb ist der Renderer bewusst
    ungerundet, und das wird hier festgehalten.
    """
    mapper_src = _extract_row_mapper(HTML_PATH.read_text(encoding="utf-8"))
    contribution_part = mapper_src[
        mapper_src.index("weighted_objective_contribution_decimal"):
    ]
    for rounder in ("toFixed", "Math.round", "formatBpsPercent(dec", "toPrecision"):
        assert rounder not in contribution_part, (
            f"Der Beitragswert wird in der Maske mit {rounder} gerundet -- "
            "das macht den Praezisions-Fix wirkungslos."
        )
