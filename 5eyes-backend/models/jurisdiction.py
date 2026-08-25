"""WP1 (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Schema-Grundlage fuer Nicht-CH-Jurisdiktionen.

# Kontext
Bisher kennt der Code genau eine implizite Jurisdiktion (Schweiz, "CH"),
signalisiert durch NULL in Mandate.jurisdiction (siehe models/mandates.py).
Dieses Arbeitspaket legt die additiven Schema-Bausteine, damit weitere
Jurisdiktionen (z.B. "DE") in spaeteren Arbeitspaketen (Router/Services,
NICHT hier) verwaltet werden koennen -- ohne den CH-Pfad zu veraendern.

# Zwei neue Tabellen
- JurisdictionProfile: Stammdaten-Zeile pro Jurisdiktion (Code, Waehrung,
  Freigabe-Status). Genau eine Zeile pro Jurisdiktions-Code.
- JurisdictionHomeBiasDefault: parametrisierte Home-Bias-Praeferenzen pro
  Jurisdiktion (z.B. "in DE bevorzugen wir DAX/Euro-Bunds als Heimmarkt-
  Anteil analog zur CH-SPI/CHF-Praeferenz") -- Datenzeilen, KEINE Logik.
  Die tatsaechliche Anwendung dieser Defaults in der Engine ist bewusst
  NICHT Teil dieses Arbeitspakets (spaeteres WP).

# Status-Governance (harte Vorgabe, siehe CapitalMarketAssumption.status)
Kapitalmarkt-Zahlen fuer Nicht-CH-Jurisdiktionen (siehe models/allocation.py
CapitalMarketAssumption additive Spalten) duerfen NUR nach IC-Freigabe in
Kundendokumente einfliessen. is_provisional auf beiden Tabellen hier ist
das analoge Signal fuer Home-Bias-Zeilen: 1 = noch nicht IC-geprueft.

# Backwards-Compat
Komplett neue Tabellen -- Base.metadata.create_all() legt sie automatisch
an (kein ensure_runtime_columns()-Eintrag notwendig, analog zu
ProductUniverseEntry in models/review.py). Existiert (noch) keine Zeile
fuer eine Jurisdiktion, aendert sich am CH-Verhalten nichts (diese Tabellen
werden von der bestehenden Engine schlicht nicht gelesen).
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, Integer, String

from database import Base


class JurisdictionProfile(Base):
    """Stammdaten-Zeile pro Jurisdiktion (z.B. "CH", "DE").

    status (Lifecycle der Jurisdiktion selbst, NICHT zu verwechseln mit
    CapitalMarketAssumption.status): "draft" | "pending_ic_review" |
    "approved" | "retired". Nur "approved"-Jurisdiktionen sind fuer
    Berater in spaeteren Arbeitspaketen (Router/UI) waehlbar -- diese
    Durchsetzung ist bewusst NICHT Teil dieses Arbeitspakets.
    """

    __tablename__ = "jurisdiction_profiles"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False, unique=True)  # z.B. "CH", "DE"
    display_name = Column(String, nullable=False)
    home_currency = Column(String(3), nullable=False)  # z.B. "CHF", "EUR"
    is_active = Column(Integer, nullable=False, default=1)
    # 1 = Zahlen/Konfiguration fuer diese Jurisdiktion noch nicht vom
    # Investment Committee geprueft -- siehe Modul-Docstring.
    is_provisional = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="draft")
    notes = Column(String)
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)


class JurisdictionHomeBiasDefault(Base):
    """Parametrisierte Home-Bias-Praeferenz-Zeile pro Jurisdiktion.

    Eine Zeile beschreibt EINE Praeferenz (preference_key/preference_value)
    fuer EINE Sub-Anlageklasse innerhalb einer Jurisdiktion, z.B.
    (jurisdiction_code="DE", preference_key="equity_home_market",
    preference_value="DAX", sub_asset_class="Aktien Heimmarkt",
    split_bps=3000). Reine Datenzeile -- die Anwendung in der Engine ist
    NICHT Teil dieses Arbeitspakets.
    """

    __tablename__ = "jurisdiction_home_bias_defaults"
    __table_args__ = (
        Index(
            "ix_jurisdiction_home_bias_lookup",
            "jurisdiction_code", "preference_key", "preference_value", "sub_asset_class",
        ),
    )

    id = Column(String, primary_key=True)
    jurisdiction_code = Column(String, ForeignKey("jurisdiction_profiles.code"), nullable=False)
    preference_key = Column(String, nullable=False)
    preference_value = Column(String, nullable=False)
    sub_asset_class = Column(String, nullable=False)
    split_bps = Column(Integer, nullable=False)
    rationale_text = Column(String)
    # 1 = noch nicht IC-geprueft, siehe Modul-Docstring.
    is_provisional = Column(Integer, nullable=False, default=0)
    sort_order = Column(Integer)
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)
