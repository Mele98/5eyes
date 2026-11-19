"""K2 / N-915-03: Seed-Katalog mit neutralen Musterbezeichnungen.

Der automatische CH-Katalog (services/portfolio_engine.py::DEFAULT_CATALOG_PRODUCTS)
traegt keine Emittenten- oder Produktnamen mehr: TER und Ratings des Seeds sind
nicht belegt, reale Namen waeren irrefuehrend. Echte Produkte kommen nur ueber den
Product-Evidence-Pfad bzw. das Fonds-Universum.

Bestehende Installationen behalten ihre frueher geseedeten Zeilen unveraendert (keine
stille Datenmigration: Produktnamen gehen in versiegelte Empfehlungsstaende ein).
Damit Marktprofil, ESG-Seed-Status und der Backfill der abgesicherten Varianten sie
weiter erkennen, ordnet diese Tabelle den SHA-256 des frueheren Seed-Namens dem
neuen Musternamen zu -- ohne die Altnamen im Klartext zu fuehren.
"""
from __future__ import annotations

import hashlib

LEGACY_SEED_NAME_SHA256: dict[str, str] = {
    "28c190a5dfbf19dd88d8ec101288100506ca5f6a34160db5507c4d9006ce012b": "Musterprodukt Aktien Europa",
    "2428033322364eafd3da03db9d177715eb06d198e93865f282dd2b36aac00624": "Musterprodukt Aktien Europa CHF-abgesichert",
    "ca1350d9fb820af9229c1ecc4fa23dbbbe2e3e8613cb5e15da2e9d1d76f17d02": "Musterprodukt Aktien Global",
    "4eff628c3ab0e2fae7866418f3b83eed48988db6a6088c998f50561a02cd04ae": "Musterprodukt Aktien Global CHF-abgesichert",
    "9083e820d2d48e0d562c16fd6ff7d2aa10ccbe0278f49beac125d03f2ad2151f": "Musterprodukt Aktien Schweiz",
    "2b949cf28d7fb4f28078e0b349aa0f50fdb319e6188a2ee5d2298c526acb54cc": "Musterprodukt Aktien Schweiz Small/Mid",
    "592aa7d474b22c513a46073014abc6c2a94d5d9a0e761845a7b47b1254d200b6": "Musterprodukt Aktien Schwellenlaender",
    "d3a7dd826b60e7f328d1e934dc27aa17eb25f64db6f61a089ffbeeab71639c26": "Musterprodukt Aktien Schwellenlaender CHF-abgesichert",
    "2a49fcffecd90d798c74ce03e1da29dc3e693b27597e58ae44273463832e2b4e": "Musterprodukt Geldmarktfonds",
    "e4026fbff4081e1f7695e26f75136d146bf8c7fe348a5e29a924aba9d45aaab1": "Musterprodukt Gold / Rohstoffe",
    "61d8d02b4592a41e8fcae25515325babecfdca82484488d510181378196f2a65": "Musterprodukt Hedge Funds",
    "c5a75675860739208327f88b6ed2961b2e144dbc5fbf3d8f4acc46720ecf031e": "Musterprodukt Immobilien Global",
    "3c7463f63f7192d062075b9ad1ebeabe539d3cb7edba583d44250fec298dbcb0": "Musterprodukt Immobilien Global CHF-abgesichert",
    "b08ff1c460378330261c79a097dd2951794b58217daa455a754c0f34003bef44": "Musterprodukt Immobilien Schweiz",
    "844199e38d67860c53e42176da09211a408f42ca663f563d4b87e3b1f3d0441c": "Musterprodukt Krypto",
    "347e3ba47f84346e26dfdf74cc198e9c19e08716d37fe2469ae2affafaaba3ec": "Musterprodukt Liquid Alternatives",
    "73b8bdc8418a25bf482b426aebf6188df644ab816f1a58914261c8f0e12c767c": "Musterprodukt Obligationen CHF IG",
    "e1838174501a812fd7fc8db22d477dd2df52d9cd4db9f983bdc9c717e54b7bae": "Musterprodukt Obligationen Emerging",
    "365d63ec31ece07c78b24101e60a204877e45ccf47093b296bfce0629f330107": "Musterprodukt Obligationen Emerging CHF-abgesichert",
    "e6179a149822100a6473c9a952197413ba1a6bad499fb49832e87506b4631b97": "Musterprodukt Obligationen Global Hedged",
    "ad700ff0be05ea47ec35d3e98cd5a20c88109aac68d870de535d5af5dc6b1fc2": "Musterprodukt Obligationen High Yield",
    "54ab75731953b0e0e6619a55e80a714b9100b79fe368f79719edde29b23cdd39": "Musterprodukt Private Equity",
    "65ea5074a703d4cf4ad88758e082f72d3ba877f743de56310a76aa3e4b792112": "Musterprodukt Thema Alkohol",
    "9cac90e64d061ac95abd615d6dfd6576fca024c32cc6a1f0620de4960de4acfd": "Musterprodukt Thema Fossile Energie",
    "b04a7b354b5923fdf9877dc807c6670fd6ed8dc4bfaf673b891f4e79a4e157ed": "Musterprodukt Thema Fossile Energie CHF-abgesichert",
    "6b10fbfe622d5b8ab44275b9609704db350b122cf3d9f2425aa5599fd02f2527": "Musterprodukt Thema Gluecksspiel",
    "5c7872cb538349fb596a419e6184114899cdbc8fd90100f0d20dc75548c71007": "Musterprodukt Thema Gluecksspiel CHF-abgesichert",
    "27e50be894174b8f5727045faa6a265de9273b7ddc07458dd61e5bbaa93e1e73": "Musterprodukt Thema Kernenergie",
    "04c9425f2774942730d198d610925062f4be86b11ac012496400482608b53a6a": "Musterprodukt Thema Kernenergie CHF-abgesichert",
    "ff605ee8ef29c9dfac6edab5de65701e264f86db674d8f85741c99280d6bbee1": "Musterprodukt Thema Tabak",
    "2ad138efc7fb402a6fe1e08fc03f638093195522e80bcf63897e17c9a4ec0e01": "Musterprodukt Thema Tabak CHF-abgesichert",
    "080a8ea3a4b7bf8b93b8236e9f2a92b48fc4d3378767c37ff08bbcb415f4b782": "Musterprodukt Thema Verteidigung",
    "490256717fd6e9407e8bb75acc8823194f8f1e4cc57ba33057b30b664abb7dff": "Musterprodukt Thema Verteidigung CHF-abgesichert",
}


def canonical_seed_name(name: object) -> str:
    """Musterbezeichnung eines (auch frueher geseedeten) Katalognamens; sonst unveraendert."""
    key = str(name or "").strip()
    return LEGACY_SEED_NAME_SHA256.get(hashlib.sha256(key.encode("utf-8")).hexdigest(), key)
