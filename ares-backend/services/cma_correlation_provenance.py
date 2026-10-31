"""Herkunft der Bucket-Korrelationsmatrix im Nachweis sichtbar machen.

CMA-CORRELATION-JURISDICTION-PROVENANCE-001
===========================================

**Befund.** Returns und Volatilitaeten einer CMA-Zeile sind
jurisdiktionsbewusst und fail-closed: ``validate_runtime_cma_completeness()``
verlangt fuer CH die ``*_ch_*``/``*_chf_*``-Felder und fuer jede andere
Jurisdiktion die ``*_home_*``-Felder, und ein fehlender Wert ist ein
``CMAValidationError`` -- nie ein Fallback.

Die 5x5-Korrelationsmatrix bekam diese Behandlung nie. Fehlt der Payload,
setzt ``parse_correlation_matrix_json()`` den Default ein -- und das ist, wie
der Docstring von ``_correlation_factor_from_cma`` selbst sagt, der
"canonical **Swiss-market** default", **unabhaengig von
``cma.jurisdiction``**. Ein DE-Mandat rechnet seine Risikozahlen damit auf
schweizerischen Abhaengigkeiten: die Aktien/Obligationen-Korrelation von -0.2
traegt die Safe-Haven-Eigenschaft des CHF, die der EUR-Raum nicht hat, und
"Immobilien" meint den schweizerischen Markt.

Die Korrelationsmatrix ist dabei kein Randparameter -- sie ist neben den
Volatilitaeten der erste Treiber jeder Risikokennzahl (VaR, CVaR, Drawdown,
Zielerreichungswahrscheinlichkeit).

**Was schon gedeckt ist.** Der Sensitivitaets-Hash bindet die GANZE CMA-Zeile
(``cma_snapshot`` ueber alle Spalten), also Matrix UND Jurisdiktion; und der
MC-Seed enthaelt ``correlation_matrix_json``. Zwei Laeufe mit verschiedenen
Matrizen liefern also verschiedene Zahlen und verschiedene Hashes -- das ist
in Ordnung.

**Was fehlte.** Der Modell-Basis-Block, der die verwendete Methodik
ausdruecklich ausweist (und ueber den JSON-Aggregator und das PDF beim Kunden
landet), sagte zur Bucket-Korrelation gar nichts. Er fuehrt
``sub_class_intra_correlation_x100`` (die Intra-Sub-Asset-Class-Annahme), aber
keinen Satz darueber, welche Bucket-Korrelationsstruktur gerechnet wurde und
ob sie zur Jurisdiktion des Mandats passt. Ein DE-Bericht offenbarte also
nirgends, dass schweizerische Korrelationen seine Risikozahlen treiben.

Dieses Modul schliesst genau diese Luecke: es benennt die Herkunft, statt sie
zu ersetzen.

Was dieses Modul NICHT tut
--------------------------

Es **erfindet keine Korrelationsmatrix** fuer eine andere Jurisdiktion. Eine
plausibel aussehende DE- oder US-Matrix zu hinterlegen waere schlimmer als der
heutige Zustand: aus einem benennbaren Fremdmarkt-Fallback wuerde eine Zahl
ohne Quelle, die niemand mehr als Luecke erkennt. Dieselbe Linie wie bei
HEDGED-ALKOHOL-GAP-001.

``JURISDICTION_DEFAULT_CORRELATION_SOURCES`` ist deshalb als Registry
ausgelegt, in der heute nur CH einen Default hat. Liefert das
Investment Committee eine Matrix fuer eine weitere Jurisdiktion, ist das ein
Eintrag hier plus der Datensatz -- kein Umbau. Bis dahin weist
``jurisdiction_matched = False`` die Fremdmarkt-Verwendung ausdruecklich aus.

CMA-001 / CMA-CORR-001 (Entscheidungsdokument 2026-10-27): eine
Nicht-CH-Jurisdiktion OHNE eigene Matrix rechnet nicht mehr live -- die
Runtime-Validierung ist dort fail-closed wie bei Returns/Volatilitaeten.
Fuer CH wird der bestehende Default nur noch als benannte, versionierte
Policy (``JURISDICTION_DEFAULT_CORRELATION_POLICIES``) eingesetzt
(``resolve_bucket_correlation_matrix``), nicht durch blosse Abwesenheit des
Payloads. Der Nachweis-Block oben bleibt unveraendert, damit gespeicherte
Evidenz-Hashes stabil bleiben.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from services.cma_validation import (
    CORRELATION_DIMENSION,
    CMAValidationError,
    parse_correlation_matrix_json,
    validate_correlation_matrix,
)

# Herkunftskennungen. Stabil halten -- sie landen im persistierten Nachweis.
EXPLICIT_CMA_SOURCE = "cma:correlation_matrix_json"
SWISS_MARKET_DEFAULT_SOURCE = "default:swiss_market_correlation_v1"
UNRESOLVED_SOURCE = "unresolved:invalid_payload"
UNKNOWN_SOURCE = "unknown:no_cma_in_scope"

# Jurisdiktionen mit einer hinterlegten Default-Korrelationsmatrix.
# Bewusst genau eine: fuer alles andere gibt es keine freigegebene Matrix, und
# eine erfundene waere schlechter als ein benannter Fallback (siehe
# Modul-Docstring).
JURISDICTION_DEFAULT_CORRELATION_SOURCES: dict[str, str] = {
    "CH": SWISS_MARKET_DEFAULT_SOURCE,
}

#: CMA-CORR-001 (Entscheidungsdokument 2026-10-27, Abschnitt 5): die
#: Korrelationsannahme hat eine eigene Entscheidungs-ID -- sie ist NICHT
#: ADR-12a (KGV). Ein fachlicher Default darf nie durch blosse Abwesenheit
#: eines Payloads aktiv werden, sondern nur als benannte, versionierte,
#: offengelegte Policy je Jurisdiktion. Heute existiert genau eine: der
#: bestehende Schweizer Default (keine neue Zahl), Ausschussfreigabe offen.
#: Fuer jede andere Jurisdiktion ohne eigenen Payload ist der Lauf
#: fail-closed (``services/cma_validation.py::validate_runtime_cma_completeness``).
CORRELATION_DECISION_ID = "CMA-CORR-001"
JURISDICTION_DEFAULT_CORRELATION_POLICIES: dict[str, dict[str, str]] = {
    "CH": {
        "decision_id": CORRELATION_DECISION_ID,
        "policy_name": "ch_bucket_correlation_default",
        "version": "v1",
        "source": SWISS_MARKET_DEFAULT_SOURCE,
        "scope": "CH",
        "approval_status": "pending_committee_approval",
        "matrix_location": "services/portfolio_engine.py::_DEFAULT_CORRELATION_MATRIX",
    },
}


def jurisdiction_default_correlation_policy(cma: Any) -> dict[str, str] | None:
    """Benannte Default-Policy der Jurisdiktion oder ``None`` (= keine)."""
    policy = JURISDICTION_DEFAULT_CORRELATION_POLICIES.get(normalized_jurisdiction(cma))
    return dict(policy) if policy is not None else None


def resolve_bucket_correlation_matrix(
    cma: Any,
    *,
    default_matrix: Any,
    dimension: int = CORRELATION_DIMENSION,
) -> tuple[tuple[float, ...], ...]:
    """Die fuer ``cma`` zu rechnende Bucket-Korrelationsmatrix.

    Payload vorhanden -> genau dieser (fail-closed validiert). Payload
    fehlt -> nur ueber die benannte Default-Policy der Jurisdiktion; ohne
    eine solche ``CMAValidationError`` statt eines Fremdmarkt-Ersatzes.
    """
    raw_payload = getattr(cma, "correlation_matrix_json", None)
    if raw_payload:
        matrix = parse_correlation_matrix_json(raw_payload, dimension=dimension)
        assert matrix is not None
        return matrix
    if jurisdiction_default_correlation_policy(cma) is None:
        raise CMAValidationError(
            "Keine Korrelationsmatrix fuer Jurisdiktion "
            f"{normalized_jurisdiction(cma)}: die CMA hat keinen "
            "correlation_matrix_json und es gibt keine genehmigte Default-"
            f"Policy ({CORRELATION_DECISION_ID}). Ein Fremdmarkt-Default wird "
            "nicht eingesetzt."
        )
    return validate_correlation_matrix(default_matrix, dimension=dimension)


def normalized_jurisdiction(cma: Any) -> str:
    """CMA-Jurisdiktion in der Normalform der Engine (leer/None -> "CH").

    Gleiche Konvention wie ``validate_runtime_cma_completeness()``, damit
    Nachweis und Validierung nicht auseinanderlaufen koennen.
    """
    return str(getattr(cma, "jurisdiction", None) or "CH").strip().upper()


def correlation_matrix_digest(
    matrix: Any, *, dimension: int = CORRELATION_DIMENSION
) -> str:
    """Stabiler Digest der VALIDIERTEN Matrix.

    Ueber die normalisierten Zahlen, nicht ueber den Rohtext: unterschiedliche
    Formatierung derselben Matrix ergibt denselben Digest, und eine
    tatsaechlich andere Matrix einen anderen.
    """
    rows = [[float(value) for value in row] for row in matrix]
    payload = json.dumps(rows, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def bucket_correlation_provenance(
    cma: Any,
    *,
    default_matrix: Any = None,
    dimension: int = CORRELATION_DIMENSION,
) -> dict[str, Any]:
    """Beschreibt, WELCHE Bucket-Korrelationsstruktur ein Lauf verwendet hat.

    Liefert einen Nachweis-Block, nie eine Exception: der Modell-Basis-Block
    wird auch fuer Legacy- und Fallback-Laeufe gebaut, und eine Kennzahl darf
    nicht an ihrer eigenen Herkunftsbeschreibung scheitern. Eine ungueltige
    Matrix haette den Lauf vorher schon abgebrochen
    (``parse_correlation_matrix_json`` ist fail-closed); sie wird hier als
    ``UNRESOLVED_SOURCE`` ausgewiesen statt verschwiegen.

    ``jurisdiction_matched`` ist die eigentliche Aussage:
      * ``True``  -- die Matrix stammt von der CMA-Zeile selbst, oder der
        Default der Jurisdiktion wurde fuer genau diese Jurisdiktion verwendet.
      * ``False`` -- es wurde die Matrix eines FREMDEN Marktes verwendet, weil
        fuer diese Jurisdiktion keine hinterlegt ist.
    """
    if cma is None:
        # Ohne CMA-Zeile im Scope ist die Herkunft nicht feststellbar. Das wird
        # ausgewiesen und nicht als "Schweizer Default" geraten -- sonst
        # behauptet der Nachweis etwas, was niemand geprueft hat.
        return {
            "source": UNKNOWN_SOURCE,
            "jurisdiction": None,
            "jurisdiction_matched": False,
            "matrix_digest": None,
            "dimension": int(dimension),
        }

    if default_matrix is None:
        # Lazy Import: portfolio_engine importiert dieses Modul, nicht umgekehrt.
        from services.portfolio_engine import _DEFAULT_CORRELATION_MATRIX

        default_matrix = _DEFAULT_CORRELATION_MATRIX

    jurisdiction = normalized_jurisdiction(cma)
    raw_payload = getattr(cma, "correlation_matrix_json", None)
    has_explicit_payload = bool(raw_payload)

    try:
        matrix = parse_correlation_matrix_json(
            raw_payload,
            default_matrix=default_matrix,
            dimension=dimension,
        )
    except CMAValidationError:
        return {
            "source": UNRESOLVED_SOURCE,
            "jurisdiction": jurisdiction,
            "jurisdiction_matched": False,
            "matrix_digest": None,
            "dimension": int(dimension),
        }

    if has_explicit_payload:
        source = EXPLICIT_CMA_SOURCE
        matched = True
    else:
        source = JURISDICTION_DEFAULT_CORRELATION_SOURCES.get(
            jurisdiction, SWISS_MARKET_DEFAULT_SOURCE
        )
        matched = jurisdiction in JURISDICTION_DEFAULT_CORRELATION_SOURCES

    return {
        "source": source,
        "jurisdiction": jurisdiction,
        "jurisdiction_matched": bool(matched),
        "matrix_digest": (
            correlation_matrix_digest(matrix, dimension=dimension)
            if matrix is not None
            else None
        ),
        "dimension": int(dimension),
    }
