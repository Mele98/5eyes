"""Sprint 14: Statische Erklaerungstexte fuer Anlagestrategie-PDF.

Laenderpaket X3: Die Texte liegen als Daten im DocumentSet des Packs
(``jurisdictions/ch/documents/de-CH/strategy_report.yaml`` und
``legal.yaml``) und werden hier byte-gleich unter den bisherigen Namen
bereitgestellt (gleiche Typen: Text, Liste von Texten, Liste von Paaren).
Nachweis: tests/test_jurisdiction_document_set.py.

KEINE Marken-Eigennamen von Dritt-Firmen oder externen Produkten — alle
Texte sind eigenstaendig mit neutralen Formulierungen verfasst
('wir', 'der Vermoegensverwalter',
'Sie als Kunde').
"""
from __future__ import annotations

from jurisdictions.documents import default_documents

_DOCUMENTS = default_documents()

INVESTITIONSANSATZ_TITLE = _DOCUMENTS.text("strategy_report.investment_approach.title")
INVESTITIONSANSATZ_TEXT = list(_DOCUMENTS.paragraphs("strategy_report.investment_approach.paragraphs"))


ANLAGEUNIVERSUM_TITLE = _DOCUMENTS.text("strategy_report.investment_universe.title")
ANLAGEUNIVERSUM_INTRO = _DOCUMENTS.text("strategy_report.investment_universe.intro")
ANLAGEUNIVERSUM_BULLETS = list(_DOCUMENTS.paragraphs("strategy_report.investment_universe.bullets"))
ANLAGEUNIVERSUM_OUTRO = list(_DOCUMENTS.paragraphs("strategy_report.investment_universe.outro"))


ZUSAMMENFASSUNG_TITLE = _DOCUMENTS.text("strategy_report.summary.title")
ZUSAMMENFASSUNG_TEXT = list(_DOCUMENTS.paragraphs("strategy_report.summary.paragraphs"))


KENNZAHLEN_TITLE = _DOCUMENTS.text("strategy_report.metrics.title")
KENNZAHLEN_DEFINITIONS = [tuple(pair) for pair in _DOCUMENTS.pairs("strategy_report.metrics.definitions")]


DISCLAIMER_TITLE = _DOCUMENTS.text("legal.disclaimer.title")
DISCLAIMER_TEXT = list(_DOCUMENTS.paragraphs("legal.disclaimer.paragraphs"))


COVER_TAGLINE = _DOCUMENTS.text("strategy_report.cover.tagline")


# Neutrale Default-Berater-Kontaktdaten (Berater-Profil ueberschreibt im
# PDFContext). KEINE Marken-Eigennamen — der Berater pflegt seine eigene
# Org-Adresse in seinem Profil.
DEFAULT_ADVISOR_ORG = ""
DEFAULT_ADVISOR_STREET = ""
DEFAULT_ADVISOR_POSTAL = ""
DEFAULT_ADVISOR_PHONE = ""
DEFAULT_ADVISOR_EMAIL = ""
DEFAULT_ADVISOR_WEBSITE = ""
