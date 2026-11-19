"""KN4-B / E2E4-03: Kundentexte fuer dokumentierte Anlagepraeferenzen (reines
Blatt, nur Standardbibliothek).

Das Kunden-PDF «Vertragsunterzeichnung» druckte die Praeferenzen als
Rohschluessel und Python-Werte («homeBias: ch_focus; altsGold: True ...»).
Jetzt laufen sie ueber diese abschliessende Label-Liste (Vokabular wie
schemas/allocation.py und das Anlagestrategie-PDF). Ein unbekannter Schluessel
oder Wert wird weggelassen -- nie roh gedruckt. ESG laeuft wie bisher ueber das
gepruefte Kriterium (``_customer_esg_orientation_label`` in routers/pdf_reports.py).
"""
from __future__ import annotations

# Auswahlwerte je (Bereich, Schluessel).
CHOICE_LABELS = {
    ("policy", "universe"): {
        "standard": "Anlageuniversum Standard",
        "extended": "Anlageuniversum erweitert",
        "funds_only": "Nur Fonds/ETFs",
        "listed_only": "Nur kotierte Instrumente",
    },
    ("policy", "homeBias"): {
        "none": "Kein Heimmarkt-Schwerpunkt",
        "ch_focus": "Heimmarkt Schweiz bevorzugt",
        "europe_focus": "Europa-Schwerpunkt",
        "global": "Global ausgewogen",
    },
    ("policy", "hedging"): {
        "none": "Keine Vorgabe zur Währungsabsicherung",
        "hedged": "Währungsgesicherte Anlagen bevorzugt",
        "chf_only": "Nur Anlagen in CHF",
        "risk_budget": "Fremdwährungen innerhalb des Risikobudgets",
    },
    ("assetClasses", "equitiesGeo"): {
        "Schweiz Fokus": "Aktien mit Schweiz-Schwerpunkt",
        "Deutschland Fokus": "Aktien mit Deutschland-Schwerpunkt",
        "Global": "Aktien global",
        "Europa": "Aktien mit Europa-Schwerpunkt",
        "Schwellenländer": "Aktien mit Schwerpunkt Schwellenländer",
        "Schwellenlaender": "Aktien mit Schwerpunkt Schwellenländer",
    },
    ("assetClasses", "bondsDuration"): {
        "Langfristig": "Obligationen mit langer Laufzeit",
        "Kurzfristig": "Obligationen mit kurzer Laufzeit",
        "Gemischt": "Obligationen mit gemischten Laufzeiten",
    },
    ("assetClasses", "realestateMarket"): {
        "Schweiz": "Immobilien Schweiz",
        "Deutschland": "Immobilien Deutschland",
        "Ausland": "Immobilien Ausland",
        "Gemischt": "Immobilien gemischt",
    },
    ("assetClasses", "liquidityInstrument"): {
        "Geldmarktfonds": "Liquidität in Geldmarktfonds",
        "Kontoguthaben": "Liquidität als Kontoguthaben",
        "Festgeld": "Liquidität als Festgeld",
    },
}

# Ja/Nein-Schalter je (Bereich, Schluessel): nur "ja" wird gedruckt.
FLAG_LABELS = {
    ("assetClasses", "equitiesLargeCap"): "Aktien grosser Unternehmen",
    ("assetClasses", "equitiesSmid"): "Aktien kleiner und mittlerer Unternehmen",
    ("assetClasses", "bondsInvestmentGrade"): "Obligationen guter Bonität",
    ("assetClasses", "bondsHighYield"): "Hochzinsanleihen",
    ("assetClasses", "bondsEmerging"): "Anleihen aus Schwellenländern",
    ("assetClasses", "realestateFunds"): "Immobilienfonds",
    ("assetClasses", "realestateDirect"): "Direkte Immobilienanlagen",
    ("assetClasses", "altsGold"): "Gold und Rohstoffe",
    ("assetClasses", "altsLiquidAlts"): "Liquide alternative Anlagen",
    ("assetClasses", "altsHedge"): "Hedge-Fonds",
    ("assetClasses", "altsPe"): "Private Equity",
    ("assetClasses", "altsCrypto"): "Kryptowährungen",
    ("product", "noDerivatives"): "Keine Derivate",
    ("product", "noLeverage"): "Keine Hebelprodukte",
    ("product", "noStructured"): "Keine strukturierten Produkte",
    ("product", "listedOnly"): "Nur kotierte Titel",
    ("product", "fundsOnly"): "Nur Fonds/ETFs",
    ("geo", "chFocus"): "Schweiz-Schwerpunkt",
    ("geo", "noEm"): "Keine Schwellenländer",
    ("geo", "hedgingRequired"): "Währungsabsicherung verlangt",
    ("geo", "chfOnly"): "Nur Anlagen in CHF",
    ("geo", "noUsd"): "Keine Anlagen in USD",
}


def preference_label(section: str, key: str, value):
    """Kundentext fuer einen Praeferenzwert oder ``None`` (weglassen)."""
    flag = FLAG_LABELS.get((section, key))
    if flag is not None:
        return flag if value is True else None
    choices = CHOICE_LABELS.get((section, key))
    if choices is not None and isinstance(value, str):
        return choices.get(value)
    return None
