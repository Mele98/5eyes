"""PREF-CONTEXT-001: der Praeferenz-Snapshot der Soll-Allokation ist die
einzige Praeferenzquelle fuer die Produktselektion.

Befund (ESG-Architektur-Review 18.10.2026, C1/I): ``generate_recommendation_run``
normalisierte bisher die REQUEST-Praeferenzen und nutzte sie fuer Matcher,
Score, ESG-Gap-Hinweis, Themen-Offenlegung und Konzentrationslimits, waehrend
der TA-Rebuild den gespeicherten Snapshot (``TargetAllocation.preferences_json``,
im ``allocation_context_hash`` gebunden) las. Eine TA mit ``policy.esg=impact``
plus Recommendation ohne Request-Praeferenzen erzeugte so Produkte OHNE
ESG-Filter, das PDF zeigte trotzdem das Kriterium aus dem Snapshot.

Vertrag (CIO-Entscheid 2026-10-18):

* Aktuelle TA MIT Snapshot -> der Snapshot ist die einzige Quelle.
  ``preferences=None`` -> Snapshot. Ein mitgesendeter Request, der kanonisch
  (``_normalize_preferences`` + Mandats-Building-Block-Defaults,
  schluesselreihenfolge-unabhaengig) vom Snapshot abweicht ->
  :class:`PreferenceSnapshotMismatchError` (Reason-Code
  ``PREFERENCE_SNAPSHOT_MISMATCH``, HTTP 409, kein Run, keine Position).
* Legacy-TA OHNE Snapshot (``preferences_json IS NULL``) -> bisheriges
  Verhalten (Request bzw. Defaults), aber mit sichtbarer Run-Warnung
  ``PREFERENCE_SNAPSHOT_LEGACY``.
* TA-Neuberechnung mit ``preferences=None`` (React ``generateAllocation``
  sendet ``{preferences: null}``) uebernimmt die Praeferenzen der aktuellen
  TA statt sie still durch Defaults zu ersetzen ("Neuberechnung = gleiche
  Praeferenzen"). Wer bewusst auf Defaults zuruecksetzen will, sendet
  explizit ``{}``.

Bewusst ohne Schema-/Migrationsaenderung; Run-Hashes folgen separat (PR-E).
"""
from __future__ import annotations

import json

PREFERENCE_SNAPSHOT_MISMATCH = "PREFERENCE_SNAPSHOT_MISMATCH"
PREFERENCE_SNAPSHOT_LEGACY = "PREFERENCE_SNAPSHOT_LEGACY"

LEGACY_SNAPSHOT_WARNING = (
    f"{PREFERENCE_SNAPSHOT_LEGACY}: Die Soll-Allokation stammt aus einer Phase "
    "ohne gespeicherten Praeferenz-Snapshot. Die Produktselektion nutzt die mit "
    "dieser Anfrage gesendeten Praeferenzen (bzw. Standardwerte) und ist nicht "
    "an die Strategie gebunden. Bitte Strategie neu berechnen."
)
INHERITED_PREFERENCES_NOTE = (
    "Neuberechnung ohne mitgesendete Praeferenzen: die festgehaltenen "
    "Praeferenzen der bisherigen Soll-Allokation (inkl. ESG-Vorgaben) wurden "
    "unveraendert uebernommen."
)


# ESG-P0-3/P0-5 (CIO-Entscheid 2026-10-18): weitere stabile Reason-Codes.
PREFERENCE_CONSTRAINT_VIOLATION = "PREFERENCE_CONSTRAINT_VIOLATION"
THEME_CLASSIFICATION_MISSING = "THEME_CLASSIFICATION_MISSING"


class ReasonCodedConflictError(ValueError):
    """Basisklasse fuer fail-closed 409-Konflikte mit stabilem Reason-Code.
    Router mappen sie auf ``HTTPException(409, detail=exc.http_detail())``;
    ``str(exc)`` beginnt immer mit dem Reason-Code (Logs, Altaufrufer)."""

    reason_code = "CONFLICT"
    message = ""

    def http_detail(self) -> dict:
        return {"reason_code": self.reason_code, "message": self.message}


class PreferenceSnapshotMismatchError(ReasonCodedConflictError):
    """Request-Praeferenzen weichen vom verifizierten TA-Snapshot ab."""

    reason_code = PREFERENCE_SNAPSHOT_MISMATCH

    def __init__(self, differing_sections: list[str]):
        self.differing_sections = list(differing_sections)
        sections = ", ".join(self.differing_sections) or "unbekannt"
        self.message = (
            "Die gesendeten Anlagepraeferenzen weichen von den in der aktuellen "
            f"Soll-Allokation festgehaltenen Praeferenzen ab (Abschnitte: {sections}). "
            "Eine Empfehlung wird nur aus den Praeferenzen der Strategie erzeugt; "
            "bitte zuerst die Strategie mit den neuen Praeferenzen neu berechnen."
        )
        super().__init__(f"{PREFERENCE_SNAPSHOT_MISMATCH}: {self.message}")

    def http_detail(self) -> dict:
        return {
            "reason_code": self.reason_code,
            "message": self.message,
            "differing_sections": self.differing_sections,
        }


def effective_preferences(preferences: dict | None, mandate) -> dict:
    """Kanonische, wirksame Praeferenzen: Vokabular-Validierung plus
    Mandats-Building-Block-Defaults -- exakt die Form, die
    ``generate_target_allocation`` als Snapshot persistiert."""
    from services.portfolio_engine import (
        _merge_mandate_defaults_into_prefs,
        _normalize_preferences,
    )

    return _merge_mandate_defaults_into_prefs(_normalize_preferences(preferences), mandate)


def _canonical(prefs: dict) -> str:
    return json.dumps(prefs, sort_keys=True, default=str)


def resolve_recommendation_preferences(
    allocation, request_preferences: dict | None, mandate,
) -> tuple[dict | None, str | None]:
    """Liefert ``(rohe Praeferenzen fuer Produktselektion + TA-Rebuild,
    optionale Legacy-Warnung)``. Wirft :class:`PreferenceSnapshotMismatchError`
    bei kanonischer Abweichung des Requests vom Snapshot."""
    from services.portfolio_engine import _allocation_snapshot_preferences

    snapshot = _allocation_snapshot_preferences(allocation)
    if snapshot is None:
        return request_preferences, LEGACY_SNAPSHOT_WARNING
    if request_preferences is not None:
        stored = effective_preferences(snapshot, mandate)
        sent = effective_preferences(request_preferences, mandate)
        if _canonical(stored) != _canonical(sent):
            differing = sorted(
                key for key in set(stored) | set(sent)
                if _canonical({"v": stored.get(key)}) != _canonical({"v": sent.get(key)})
            )
            raise PreferenceSnapshotMismatchError(differing)
    return snapshot, None


def inherit_current_allocation_preferences(
    db, mandate, preferences: dict | None,
) -> tuple[dict | None, bool]:
    """TA-Neuberechnung: ``None`` -> Praeferenzen der aktuellen TA (falls ein
    Snapshot existiert). Liefert ``(Praeferenzen, uebernommen?)``."""
    if preferences is not None:
        return preferences, False
    from services.portfolio_engine import (
        _allocation_snapshot_preferences,
        _current_target_allocation_or_none,
    )

    snapshot = _allocation_snapshot_preferences(
        _current_target_allocation_or_none(db, mandate.id)
    )
    if snapshot is None:
        return None, False
    return snapshot, True


# ---------------------------------------------------------------------------
# ESG-P0-3 PREF-MANUAL-001 / PREF-FINAL-001 (CIO-Entscheid 2026-10-18)
# ---------------------------------------------------------------------------
# Manuelles Hinzufuegen einer Position und die Finalisierung eines Runs
# pruefen gegen den Praeferenz-Snapshot der TA -- mit DEMSELBEN Matcher wie
# die Auto-Selektion (portfolio_engine_payload._product_matches_constraints),
# kein zweiter Matcher. Die "hints" erklaeren nur (aus den bestehenden
# Erklaer-Helfern); entschieden wird ausschliesslich durch den Matcher.


class PreferenceConstraintViolationError(ReasonCodedConflictError):
    """Mindestens eine Position verletzt die Praeferenzen der Strategie."""

    reason_code = PREFERENCE_CONSTRAINT_VIOLATION

    def __init__(self, positions: list[dict], *, context: str):
        self.positions = list(positions)
        self.context = context
        names = ", ".join(str(item.get("product_name") or item.get("product_id")) for item in self.positions)
        action = (
            "Die Position wird nicht hinzugefuegt"
            if context == "manual_position"
            else "Die Empfehlung kann nicht freigegeben werden"
        )
        self.message = (
            "Produkt(e) erfuellen die in der Soll-Allokation festgehaltenen "
            f"Anlagepraeferenzen nicht: {names}. {action}; bitte ein passendes "
            "Produkt waehlen oder die Strategie mit geaenderten Praeferenzen neu berechnen."
        )
        super().__init__(f"{PREFERENCE_CONSTRAINT_VIOLATION}: {self.message}")

    def http_detail(self) -> dict:
        return {
            "reason_code": self.reason_code,
            "message": self.message,
            "context": self.context,
            "positions": self.positions,
        }


class ThemeClassificationMissingError(ReasonCodedConflictError):
    """ESG-P0-5: ein Baustein ist nur deshalb unumsetzbar, weil Produkten die
    Themenklassifikation fehlt, waehrend der Kunde ein Thema ausschliesst."""

    reason_code = THEME_CLASSIFICATION_MISSING

    def __init__(self, building_blocks: list[dict], base_message: str):
        self.building_blocks = list(building_blocks)
        self.message = base_message
        super().__init__(f"{THEME_CLASSIFICATION_MISSING}: {self.message}")

    def http_detail(self) -> dict:
        return {
            "reason_code": self.reason_code,
            "message": self.message,
            "building_blocks": self.building_blocks,
        }


def _violation_hints(product, prefs: dict) -> list[str]:
    """Erklaerung (nicht Entscheidung) aus den bestehenden Helfern."""
    from services.portfolio_engine import _norm_text
    from services.portfolio_engine_payload import (
        ESG_POLICY_EXEMPT_ASSET_CLASS,
        THEME_DISPLAY_NAMES,
        effective_theme_screening,
        esg_policy_criterion_label,
        product_meets_esg_policy,
        product_theme_classification_missing,
        product_theme_keys,
    )

    hints: list[str] = []
    screened = effective_theme_screening(prefs)
    hit = [key for key in screened if key in product_theme_keys(product)]
    if hit:
        hints.append(
            "Themen-Ausschluss: " + ", ".join(THEME_DISPLAY_NAMES[key] for key in hit)
        )
    elif screened and product_theme_classification_missing(product, screened):
        hints.append(
            "Themen-Ausschluss aktiv, Produkt ohne Themen-Zuordnung "
            f"({THEME_CLASSIFICATION_MISSING})"
        )
    policy = (prefs.get("policy") or {}).get("esg")
    if (
        _norm_text(getattr(product, "asset_class", None)) != ESG_POLICY_EXEMPT_ASSET_CLASS
        and not product_meets_esg_policy(product, policy)
    ):
        hints.append(f"ESG-Kriterium nicht erfuellt: {esg_policy_criterion_label(policy)}")
    if not hints:
        hints.append("Anlagepraeferenz (Universum, Waehrung, Struktur/Derivate) nicht erfuellt")
    return hints


def check_products_against_allocation_snapshot(
    db, mandate, allocation, items: list[tuple[str | None, object]], *, score_bucket: int,
) -> tuple[list[dict], str | None]:
    """Prueft ``items`` = [(position_id|None, Product)] gegen den Snapshot von
    ``allocation``. Liefert ``(Verstoesse, Legacy-Warnung)``. Ohne Snapshot
    (Legacy) wird nichts geprueft -- bisheriges Verhalten + Warnung."""
    import services.portfolio_engine_payload as payload
    from services.jurisdiction.resolve import resolve_mandate_jurisdiction
    from services.portfolio_engine import (
        _allocation_snapshot_preferences,
        _normalize_preferences,
        _resolve_jurisdiction_context,
    )

    snapshot = _allocation_snapshot_preferences(allocation)
    if snapshot is None:
        return [], LEGACY_SNAPSHOT_WARNING

    prefs = _normalize_preferences(snapshot)
    jurisdiction_ctx = _resolve_jurisdiction_context(db, mandate, resolve_mandate_jurisdiction(mandate))
    violations = []
    for position_id, product in items:
        if payload._product_matches_constraints(
            product, prefs, score_bucket, jurisdiction_ctx=jurisdiction_ctx,
        ):
            continue
        violations.append({
            "position_id": position_id,
            "product_id": getattr(product, "id", None),
            "product_name": getattr(product, "product_name", None),
            "hints": _violation_hints(product, prefs),
        })
    return violations, None


def enforce_products_against_allocation_snapshot(
    db, mandate, allocation, items, *, score_bucket: int, context: str,
) -> str | None:
    """Wie :func:`check_products_against_allocation_snapshot`, wirft aber
    :class:`PreferenceConstraintViolationError` bei Verstoss (fail-closed).
    Rueckgabe: optionale Legacy-Warnung."""
    violations, legacy_warning = check_products_against_allocation_snapshot(
        db, mandate, allocation, items, score_bucket=score_bucket,
    )
    if violations:
        raise PreferenceConstraintViolationError(violations, context=context)
    return legacy_warning


class ThemeGapDiagnosis:
    """THEME-MISSINGNESS-001 (aus generate_recommendation_run ausgelagert):
    Diagnose-Pool = eignungs-zulaessige Produkte, nur bei aktivem
    Themen-Screening (einmal pro Lauf). ``hint(sub)`` benennt, ob ein leerer
    Baustein NUR an fehlender Themen-Zuordnung scheitert;
    ``raise_if_blocked`` -> 409 THEME_CLASSIFICATION_MISSING, auch unterhalb
    der 50-bps-Toleranz (keine stille Lockerung)."""

    def __init__(self, db, products, prefs, score_bucket, *, service_mode, jurisdiction, jurisdiction_ctx):
        from services.portfolio_engine_payload import effective_theme_screening
        from services.product_eligibility import is_eligible_candidate

        self.prefs = prefs
        self.score_bucket = score_bucket
        self.jurisdiction_ctx = jurisdiction_ctx
        self.pool = [
            product for product in products
            if is_eligible_candidate(db, product, service_mode=service_mode, score_bucket=score_bucket, jurisdiction=jurisdiction)
        ] if effective_theme_screening(prefs) else []

    def hint(self, sub: dict) -> str | None:
        from services.portfolio_engine_payload import theme_classification_gap_hint

        return theme_classification_gap_hint(
            self.pool, sub["sub_asset_class"], sub["asset_class"], self.prefs, self.score_bucket,
            jurisdiction_ctx=self.jurisdiction_ctx,
        )

    @staticmethod
    def raise_if_blocked(missing_sub_classes: list[dict]) -> None:
        theme_blocked = [item for item in missing_sub_classes if item.get("theme_gap_hint")]
        if theme_blocked:
            raise ThemeClassificationMissingError(theme_blocked, "Produktselektion unvollstaendig: " + "; ".join(
                f"{item['sub_asset_class']} ({item['target_weight_bps']/100:.1f}%): {item['theme_gap_hint']}"
                for item in theme_blocked
            ) + ". Themen-Zuordnung im Produktkatalog pflegen oder ein klassifiziertes Produkt erfassen.")
