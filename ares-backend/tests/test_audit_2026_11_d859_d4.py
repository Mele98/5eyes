"""Delta-Pruefung #859 (Dok. 86): D-4 (gemeinsamer Kontext siehe unten).

D-1: Einzelziel-Kappung im Hausmatrix-Modus (Aktien-Ziel 75 % + Berater-
Minimum Obligationen 20 %): die Liquiditaet sinkt von 2 % auf 0 %, das
Reasoning sagte aber zugleich "Die SAA-Liquiditaet bleibt auf 2.0%." (Satz
der Reserve-Berechnung VOR der Projektion). Im Hausmatrix-Modus gilt die
Liquiditaets-Untergrenze der Hausmatrix (hier 0 %), nicht die globale
2-%-Untergrenze des stochastischen Modells -- das wird jetzt ausgewiesen.

D-2: systembedingte Erweiterung des Liquiditaetsbands ueber das
Hausmatrix-Maximum (M2) wird als Reasoning-Satz und Info-Meldung
ausgewiesen.

D-4: H-859-1 ohne Fallback -- gekapptes Einzelziel, Warnung und
body_client nennen die gespeicherte Quote, in beiden Modi.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

SINGLE_CAPPED = {"bands": {"equities": {"target_bps": 7500}, "bonds": {"min_bps": 2000}}}


def _generate(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        return result


@pytest.mark.parametrize("mode", ["house_matrix", "stochastic"])
def test_d4_capped_single_target_warning_names_persisted_quote(session_factory, monkeypatch, mode):
    """Ohne Fallback, gekapptes Einzelziel (Aktien 75 % bei Obligationen-
    Minimum 20 %). Im stochastischen Modus haelt der echte Optimierer den
    Anker hier exakt; damit der Test zwischen Anker und gespeicherter Quote
    unterscheidet, verschiebt ein Wrapper den (konvergierten) Optimierer-
    Output konsistent um 5 bps (Aktien -> Obligationen). Im Hausmatrix-Modus
    folgt nach dem Anker keine Rechnung mehr; dort prueft der Fall die
    Konsistenz der Meldung mit der gespeicherten Quote."""
    from dataclasses import replace as _replace  # noqa: F401

    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    if mode == "stochastic":
        original = pe._run_stochastic_optimizer_pass

        def _shifted(**kwargs):
            result = original(**kwargs)
            if result is not None and kwargs.get("apply_targets"):
                weights = dict(result.weights_bps)
                weights["equities"] -= 5
                weights["bonds"] += 5
                object.__setattr__(result, "weights_bps", weights)
                for bucket, bps in weights.items():
                    kwargs["targets"][bucket] = int(bps)
            return result

        monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", _shifted)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"d4{mode[:3]}")
    result = _generate(session_factory, mid, adv, SINGLE_CAPPED)
    ta = result["target_allocation"]
    assert "WARN_FALLBACK" not in [w.get("code") for w in result["warnings"]]
    assert int(ta.target_equities_bps) < 7500
    adjusted = [w for w in result["warnings"] if w.get("code") == "WARN_TARGET_ADJUSTED"]
    assert len(adjusted) == 1, result["warnings"]
    persisted = f"{int(ta.target_equities_bps) / 100:.2f} %"
    assert persisted in adjusted[0]["body_client"], (persisted, adjusted[0]["body_client"])
    assert persisted in adjusted[0]["body_advisor"]
