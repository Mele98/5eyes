"""Laenderpakete (Jurisdiction Packs), Schritt X1: Geruest und Registry.

Aufbau (Design 80, Abschnitt 2.3):

- ``api.py``      -- Datentypen (``JurisdictionPack``, ``ResolvedPack``,
  ``NotProvided``) und die Protocols der Pack-Bereiche.
- ``registry.py`` -- ``PackRegistry`` (Duplikat = Fehler) und das Laden der
  eingebauten Packs aus ``<code>/pack.yaml``.
- ``resolve.py``  -- ``resolve_pack(...)``: die eine Aufloesung des
  Laendercodes eines Mandats.
- ``ch/``         -- CH-Pack. ``pack.yaml`` ist reine Daten;
  ``ch/references.py`` referenziert die bestehenden CH-Konstanten per Import
  und verschiebt nichts.

Abgrenzung: ``services/jurisdiction/`` (CMA-/Building-Block-Resolver,
Provisional-Gate) und ``services/tax/jurisdictions/`` (Steuer-Schaetz-API)
bleiben unveraendert. ``api``, ``registry`` und ``resolve`` importieren
bewusst kein Backend-Modul ausserhalb dieses Pakets, damit spaetere
Konsumenten in ``services``/``routers`` keinen Importzyklus erzeugen.

Dieses ``__init__`` importiert absichtlich nichts.
"""
