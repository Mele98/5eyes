"""Produktgebundene Retrozessions-Offenlegung im Ex-ante-Kostenausweis.

Audit 2026-11, Paket P1 (Luecke L1, Bericht 02/PO-12).
Rechtsgrundlage: Art. 26 FIDLEG (Entschaedigungen Dritter), Art. 400 OR,
BGE 132 III 460 (Herausgabepflicht), BGE 137 III 393 (Verzicht nur bei
Kenntnis von Umfang und Berechnungsparametern).

Bisher kannte der Kostenausweis Retrozessionen nur, wenn der Berater sie
pro Mandat manuell als Interessenkonflikt erfasste (Retrozessions-Feature
2026-07-27). Ein empfohlenes Produkt mit Retrozession konnte deshalb ohne
Offenlegungszeile im Kundendokument stehen. Diese Komponente bindet die
Offenlegung an das PRODUKT:

* Satz > 0  -> Offenlegungszeile mit geschaetztem Jahresbetrag (Satz x
  investiertes Volumen des Produkts) und der Behandlung gemaess Mandat
  (Weitergabe an den Kunden / dokumentierter Verzicht / nicht geregelt).
* Satz NULL -> Pflichtwarnung an den Berater und Kennzeichnung im Dokument.
  Das Produkt gilt NIE still als retrozessionsfrei.
* Satz 0    -> ausdruecklich retrozessionsfrei (mit Quelle erfasst).

Zusammenfuehrung mit der manuellen Erfassung pro Mandat (kein doppelter
Ausweis): Eine manuelle Retrozessions-Zeile des Mandats, deren Anbieter dem
Anbieter des Produkts entspricht (Vergleich ohne Gross-/Kleinschreibung und
Leerraum), IST die Offenlegungszeile dieses Produkts. Ihre Behandlung
(rueckerstattet / Verzicht belegt / nicht belegt) gilt fuer das Produkt;
eine zweite Kostenzeile entsteht nicht. Nur ein Produkt ohne passende
Mandatszeile bekommt eine eigene Kostenzeile -- stets AUSSERHALB des Totals
(die Retrozession ist Teil der TER, Addieren waere Doppelzaehlung) und mit
``requires_resolution``, weil weder Verzicht noch Weitergabe erfasst ist.

Bewusst eine eigene, abgegrenzte Komponente: ``services/cost_disclosure.py``
ruft nur ``apply_product_retrocessions()`` auf. Die Auswahl- und
Scoring-Logik der Engine bleibt unberuehrt.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

TREATMENT_REIMBURSED = "reimbursed"
TREATMENT_WAIVER_DOCUMENTED = "waiver_documented"
TREATMENT_UNRESOLVED = "unresolved"
TREATMENT_NOT_APPLICABLE = "not_applicable"
TREATMENT_UNKNOWN = "unknown"

TREATMENT_LABELS = {
    TREATMENT_REIMBURSED: "Weitergabe an den Kunden gemäss Mandat",
    TREATMENT_WAIVER_DOCUMENTED: "Verzicht des Kunden dokumentiert",
    TREATMENT_UNRESOLVED: "Weder Verzicht noch Weitergabe belegt – Klärung erforderlich",
    TREATMENT_NOT_APPLICABLE: "Keine Retrozession",
    TREATMENT_UNKNOWN: "Satz nicht erfasst – gilt nicht als retrozessionsfrei",
}

COST_ITEM_KEY = "retrocession_product"
DISCLOSURE_SCHEMA_VERSION = 1


def _norm_provider(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _format_amount(rappen: int, currency: str) -> str:
    whole, cents = divmod(abs(int(rappen)), 100)
    grouped = f"{whole:,}".replace(",", "'")
    sign = "-" if rappen < 0 else ""
    return f"{currency} {sign}{grouped}.{cents:02d}"


def _rate(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        rate = int(value)
    except (TypeError, ValueError):
        return None
    return rate if rate >= 0 else None


def _mandate_treatment(entry: Mapping[str, Any], has_documented_waiver) -> str:
    if bool(entry.get("reimbursed_to_client")):
        return TREATMENT_REIMBURSED
    if has_documented_waiver(entry):
        return TREATMENT_WAIVER_DOCUMENTED
    return TREATMENT_UNRESOLVED


def build_product_retrocession_lines(
    products: Iterable[Mapping[str, Any]],
    inducements: Iterable[Mapping[str, Any]] | None,
    *,
    has_documented_waiver,
) -> list[dict[str, Any]]:
    """Eine Zeile je empfohlenem Produkt (Positionen desselben Produkts
    zusammengefasst), stabil nach Produktname sortiert."""
    by_provider: dict[str, Mapping[str, Any]] = {}
    for entry in inducements or []:
        # Nur Zeilen, die im Kostenausweis tatsaechlich erscheinen (Betrag
        # > 0, siehe calculate_cost_disclosure) koennen eine Produkt-
        # Retrozession abdecken -- sonst verschwaende die Offenlegung.
        try:
            entry_amount = int(entry.get("amount_rappen") or 0)
        except (TypeError, ValueError):
            entry_amount = 0
        if entry_amount <= 0:
            continue
        key = _norm_provider(entry.get("provider"))
        if key and key not in by_provider:
            by_provider[key] = entry

    merged: dict[str, dict[str, Any]] = {}
    for item in products:
        product_id = str(item.get("product_id") or "")
        line = merged.get(product_id)
        amount = max(0, int(item.get("amount_rappen") or 0))
        if line is None:
            merged[product_id] = {
                "product_id": product_id or None,
                "product_name": str(item.get("product_name") or "Produkt"),
                "isin": item.get("isin") or None,
                "provider": item.get("provider") or None,
                "amount_rappen": amount,
                "rate_bps": _rate(item.get("retrocession_bps")),
                "source": item.get("retrocession_source") or None,
            }
        else:
            line["amount_rappen"] += amount

    lines: list[dict[str, Any]] = []
    for line in merged.values():
        rate = line["rate_bps"]
        if rate is None:
            status, treatment, estimate = "unknown", TREATMENT_UNKNOWN, None
            covered = False
        elif rate == 0:
            status, treatment, estimate = "none", TREATMENT_NOT_APPLICABLE, 0
            covered = False
        else:
            status = "present"
            estimate = int(round(line["amount_rappen"] * rate / 10000))
            entry = by_provider.get(_norm_provider(line["provider"]))
            covered = entry is not None
            treatment = (
                _mandate_treatment(entry, has_documented_waiver)
                if entry is not None
                else TREATMENT_UNRESOLVED
            )
        lines.append({
            **line,
            "status": status,
            "estimated_annual_rappen": estimate,
            "treatment": treatment,
            "treatment_label": TREATMENT_LABELS[treatment],
            # True = die manuelle Retrozessions-Zeile des Mandats (gleicher
            # Anbieter) ist die Offenlegungszeile; keine zweite Kostenzeile.
            "covered_by_mandate_entry": covered,
            "requires_resolution": status == "present" and treatment == TREATMENT_UNRESOLVED,
        })
    lines.sort(key=lambda row: (row["product_name"].casefold(), str(row["product_id"] or "")))
    return lines


def apply_product_retrocessions(
    *,
    products: Iterable[Mapping[str, Any]] | None,
    inducements: Iterable[Mapping[str, Any]] | None,
    has_documented_waiver,
    currency: str,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    """Zusaetzliche Kostenzeilen, Warnungen und die Offenlegungs-Uebersicht.

    ``products`` None = der Aufrufer kennt die Produkte nicht (z.B. eine
    reine Rechnung ohne Lauf) -> keine Aussage, Uebersicht None.
    """
    if products is None:
        return [], [], None
    lines = build_product_retrocession_lines(
        products, inducements, has_documented_waiver=has_documented_waiver,
    )
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    for line in lines:
        if line["status"] != "present" or line["covered_by_mandate_entry"]:
            continue
        source = line["source"] or "nicht angegeben"
        items.append({
            "key": COST_ITEM_KEY,
            "label": (
                f"Vergütung von Dritten: {line['product_name']} "
                f"({line['rate_bps']} bps p.a., Schätzung)"
            ),
            "category": "Vergütungen von Dritten",
            "frequency": "jährlich",
            "rate_bps": line["rate_bps"],
            "amount_rappen": line["estimated_annual_rappen"],
            "basis_rappen": line["amount_rappen"],
            "basis_label": "Investiertes Volumen des Produkts",
            "source": f"Produkt-Stammdaten (Retrozessionssatz; Quelle: {source})",
            "is_estimate": True,
            # Teil der TER -- addieren waere Doppelzaehlung, abziehen wuerde
            # eine Rueckerstattung behaupten, die nicht erfasst ist.
            "included_in_total": False,
            "requires_resolution": True,
        })
        warnings.append(
            f"Das empfohlene Produkt {line['product_name']} zahlt eine Retrozession "
            f"({line['rate_bps']} bps p.a., geschätzt "
            f"{_format_amount(line['estimated_annual_rappen'], currency)} pro Jahr). Im Mandat "
            "ist weder ein Verzicht des Kunden noch die Weitergabe erfasst. Interessenkonflikt "
            "«Retrozession / Inducement» für diesen Anbieter erfassen und Verzicht oder "
            "Rückerstattung dokumentieren (Art. 26 FIDLEG; BGE 132 III 460 / 137 III 393)."
        )

    unknown = [line["product_name"] for line in lines if line["status"] == "unknown"]
    if unknown:
        listed = ", ".join(unknown[:6]) + (f" und {len(unknown) - 6} weitere" if len(unknown) > 6 else "")
        warnings.append(
            f"Retrozession unbekannt für {len(unknown)} empfohlene"
            f"{'s Produkt' if len(unknown) == 1 else ' Produkte'} ({listed}). Diese Produkte "
            "gelten NICHT als retrozessionsfrei. Satz und Quelle im Fondsuniversum erfassen, "
            "bevor das Dokument dem Kunden abgegeben wird (Art. 26 FIDLEG)."
        )

    summary = {
        "schema_version": DISCLOSURE_SCHEMA_VERSION,
        "lines": lines,
        "unknown_count": len(unknown),
        "present_count": sum(1 for line in lines if line["status"] == "present"),
        "unresolved_count": sum(1 for line in lines if line["requires_resolution"]),
        # Vollstaendig = jeder Satz bekannt UND jede Retrozession geregelt.
        "complete": not unknown and not any(line["requires_resolution"] for line in lines),
        "legal_basis": "Art. 26 FIDLEG; Art. 400 OR; BGE 132 III 460; BGE 137 III 393",
    }
    return items, warnings, summary
