"""Policy-Daten der Vor-Ort-Signatur (SIGN-001).

Die Policy ist eine versionierte Datendatei (``config/onsite_signature_policy.json``),
keine Code-Konstante. Sie ist nur wirksam, wenn ALLE Bedingungen erfuellt sind:

* ``status == "APPROVED"`` und ``production_activation == "ENABLED"``;
* Freigabe dokumentiert (``approved_by``, ``approved_at``, ``approval_reference``);
* Kundenfaktor-Parameter (Code-Laenge, Ablaufzeit), mindestens ein
  Einwilligungstext, Zeugenerklaerung, Identifikationsmethoden und
  Zeitquellen sind gesetzt.

Sonst liefert :func:`release_problems` die fehlenden Punkte, und jeder Schritt
lehnt mit ``ONSITE_SIGNATURE_NOT_RELEASED`` ab (fail-closed, ehrlich im API).

Dokumentklassen (``document_classes``) bilden ``document_type`` auf
``FORM_REQUIRED_QES_OR_WET_INK``, ``POLICY_REQUIRES_QES`` oder
``EVIDENCE_SIGNATURE_SUFFICIENT`` ab. ``null`` = nicht klassifiziert ->
die Vor-Ort-Signatur dieses Typs ist gesperrt.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

CLASS_FORM_REQUIRED = "FORM_REQUIRED_QES_OR_WET_INK"
CLASS_POLICY_REQUIRES_QES = "POLICY_REQUIRES_QES"
CLASS_EVIDENCE_SUFFICIENT = "EVIDENCE_SIGNATURE_SUFFICIENT"
DOCUMENT_CLASSES = (CLASS_FORM_REQUIRED, CLASS_POLICY_REQUIRES_QES, CLASS_EVIDENCE_SUFFICIENT)
QES_REQUIRED_CLASSES = frozenset({CLASS_FORM_REQUIRED, CLASS_POLICY_REQUIRES_QES})

STATUS_PROPOSED = "PROPOSED"
STATUS_APPROVED = "APPROVED"
STATUS_RETIRED = "RETIRED"
POLICY_STATUSES = (STATUS_PROPOSED, STATUS_APPROVED, STATUS_RETIRED)

ACTIVATION_BLOCKED = "BLOCKED"
ACTIVATION_ENABLED = "ENABLED"

FACTOR_KIND_DOCUMENT_OTP = "document_bound_one_time_code"

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "onsite_signature_policy.json"


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConsentText:
    language: str
    version: str
    text: str

    @property
    def text_hash(self) -> str:
        return text_hash(self.text)


@dataclass(frozen=True)
class WitnessStatement:
    version: str
    text: str

    @property
    def text_hash(self) -> str:
        return text_hash(self.text)


@dataclass(frozen=True)
class OnsiteSignaturePolicy:
    policy_version: str
    status: str
    production_activation: str
    approved_by: str | None = None
    approved_at: str | None = None
    approval_reference: str | None = None
    document_classes: Mapping[str, str | None] = field(default_factory=dict)
    factor_kind: str = FACTOR_KIND_DOCUMENT_OTP
    code_digits: int | None = None
    challenge_ttl_seconds: int | None = None
    consent_texts: Mapping[str, ConsentText] = field(default_factory=dict)
    witness_statement: WitnessStatement | None = None
    accepted_identity_check_methods: tuple[str, ...] = ()
    accepted_time_sources: tuple[str, ...] = ()
    qes_provider: str | None = None
    load_error: str | None = None

    def release_problems(self) -> list[str]:
        """Leere Liste = produktiv freigegeben; sonst die offenen Punkte."""
        if self.load_error:
            return [f"policy_unreadable:{self.load_error}"]
        problems: list[str] = []
        if self.status != STATUS_APPROVED:
            problems.append(f"policy_status:{self.status}")
        if self.production_activation != ACTIVATION_ENABLED:
            problems.append(f"production_activation:{self.production_activation}")
        for name in ("approved_by", "approved_at", "approval_reference"):
            if not getattr(self, name):
                problems.append(f"approval_missing:{name}")
        if self.factor_kind != FACTOR_KIND_DOCUMENT_OTP:
            problems.append(f"customer_factor_kind_unsupported:{self.factor_kind}")
        if not isinstance(self.code_digits, int) or self.code_digits <= 0:
            problems.append("customer_factor_code_digits_missing")
        if not isinstance(self.challenge_ttl_seconds, int) or self.challenge_ttl_seconds <= 0:
            problems.append("customer_factor_ttl_missing")
        if not self.consent_texts:
            problems.append("consent_text_missing")
        if self.witness_statement is None:
            problems.append("witness_statement_missing")
        if not self.accepted_identity_check_methods:
            problems.append("identity_check_methods_missing")
        if not self.accepted_time_sources:
            problems.append("time_sources_missing")
        return problems

    @property
    def released(self) -> bool:
        return not self.release_problems()

    def document_class(self, document_type: str) -> str | None:
        value = self.document_classes.get(str(document_type or ""))
        return value if value in DOCUMENT_CLASSES else None

    def public_view(self) -> dict[str, Any]:
        problems = self.release_problems()
        return {
            "policy_version": self.policy_version,
            "status": self.status,
            "production_activation": self.production_activation,
            "released": not problems,
            "release_problems": problems,
            "document_classes": {
                key: (value if value in DOCUMENT_CLASSES else None)
                for key, value in sorted(self.document_classes.items())
            },
            "qes_provider": self.qes_provider,
        }


def _optional_str(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def policy_from_mapping(data: Mapping[str, Any]) -> OnsiteSignaturePolicy:
    """Strikte Uebersetzung der Datendatei; Formfehler -> ``load_error``."""
    status = str(data.get("status") or "")
    if status not in POLICY_STATUSES:
        raise ValueError(f"unbekannter Policy-Status {status!r}")
    classes_raw = data.get("document_classes") or {}
    if not isinstance(classes_raw, Mapping):
        raise ValueError("document_classes muss ein Objekt sein")
    classes: dict[str, str | None] = {}
    for key, value in classes_raw.items():
        if value is not None and value not in DOCUMENT_CLASSES:
            raise ValueError(f"unbekannte Dokumentklasse {value!r} fuer {key!r}")
        classes[str(key)] = value
    factor = data.get("customer_factor") or {}
    consent: dict[str, ConsentText] = {}
    for language, entry in (data.get("consent_texts") or {}).items():
        version = _optional_str((entry or {}).get("version"))
        text = _optional_str((entry or {}).get("text"))
        if not version or not text:
            raise ValueError(f"Einwilligungstext {language!r} ohne Version oder Text")
        consent[str(language)] = ConsentText(language=str(language), version=version, text=text)
    witness_raw = data.get("witness_statement")
    witness = None
    if witness_raw is not None:
        version = _optional_str(witness_raw.get("version"))
        text = _optional_str(witness_raw.get("text"))
        if not version or not text:
            raise ValueError("Zeugenerklaerung ohne Version oder Text")
        witness = WitnessStatement(version=version, text=text)
    approval = data.get("approval") or {}
    return OnsiteSignaturePolicy(
        policy_version=str(data.get("policy_version") or ""),
        status=status,
        production_activation=str(data.get("production_activation") or ACTIVATION_BLOCKED),
        approved_by=_optional_str(approval.get("approved_by")),
        approved_at=_optional_str(approval.get("approved_at")),
        approval_reference=_optional_str(approval.get("approval_reference")),
        document_classes=classes,
        factor_kind=str(factor.get("kind") or ""),
        code_digits=factor.get("code_digits"),
        challenge_ttl_seconds=factor.get("challenge_ttl_seconds"),
        consent_texts=consent,
        witness_statement=witness,
        accepted_identity_check_methods=tuple(data.get("accepted_identity_check_methods") or ()),
        accepted_time_sources=tuple(data.get("accepted_time_sources") or ()),
        qes_provider=_optional_str((data.get("qes") or {}).get("provider")),
    )


def load_policy(path: Path | None = None) -> OnsiteSignaturePolicy:
    """Laedt die Policy; jeder Lese-/Formfehler ergibt eine gesperrte Policy."""
    target = path or DEFAULT_POLICY_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return policy_from_mapping(data)
    except Exception as exc:  # noqa: BLE001 - fail-closed, Grund wird ausgewiesen
        return OnsiteSignaturePolicy(
            policy_version="",
            status=STATUS_PROPOSED,
            production_activation=ACTIVATION_BLOCKED,
            load_error=type(exc).__name__,
        )
