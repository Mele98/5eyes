"""RFC-6266-konforme `Content-Disposition`-Header fuer Dokument-Downloads.

Befund 2026-10-12 (Ende-zu-Ende-Durchlauf Mock-Mandant "Thierry Gössi")
-----------------------------------------------------------------------
Alle Dokument-Endpunkte bauten ihren Dateinamen so:

    safe_name = "".join(c if c.isalnum() else "_" for c in ctx.mandate_name)[:40]
    headers={"Content-Disposition": f'inline; filename="{safe_name}.pdf"'}

Die Absicht war ein ASCII-sicherer Name. `str.isalnum()` ist in Python aber
UNICODE-bewusst: `"ö".isalnum()` ist `True`. Der Sanitizer liess also jeden
Unicode-Buchstaben durch, und der Name landete unverarbeitet im Header.

Gemessene Folgen, zwei Schweregrade:

    "Gössi"   -> Starlette kodiert Header als Latin-1; der Byte 0xF6 geht
                 roh raus. HTTP-Header-Werte sind nach RFC 7230 ASCII --
                 Browser zeigen den Namen verstuemmelt, und ein HTTP-Client
                 der strikt UTF-8 dekodiert bricht ab (im Durchlauf genau
                 so: UnicodeDecodeError im TestClient).

    "Łukasz"  -> `"Ł".encode("latin-1")` WIRFT. Die Exception entsteht in
    "Şahin"      `Response.__init__`, also nach dem Rendern des PDFs und
    "李明"        ausserhalb jedes try/except des Endpunkts: HTTP 500. Fuer
                 solche Mandanten ist das FIDLEG-Pflichtdokument UEBERHAUPT
                 NICHT herunterladbar.

Umlaute sind in Schweizer Namen der Normalfall, nicht die Ausnahme; nicht in
Latin-1 darstellbare Namen sind bei internationaler Kundschaft gewoehnlich.

Loesung
-------
RFC 6266 sieht fuer genau diesen Fall zwei Parameter vor:

    filename="<ASCII-Rueckfall>"; filename*=UTF-8''<prozentkodiert>

Jeder Client bekommt einen funktionierenden Namen, moderne Clients den
exakten. Das ist der Standardweg, kein Flicken: der ASCII-Rueckfall ist
nicht "der Name, nur kaputt", sondern der vom Standard vorgesehene
Ersatzwert.
"""
from __future__ import annotations

import unicodedata
from urllib.parse import quote

# Deutschsprachige Umschrift ZUERST. Ohne sie wuerde die
# Unicode-Zerlegung weiter unten aus "Gössi" ein "Gossi" machen -- im
# deutschen Sprachraum ist "Goessi" die uebliche und besser lesbare
# Umschrift, und der Dateiname ist das, was der Berater im Download-Ordner
# wiederfinden muss.
_TRANSLITERATION = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
    # Nicht deutsch, aber im CH-Umfeld haeufig und nicht ueber die
    # Unicode-Zerlegung erreichbar:
    "æ": "ae", "Æ": "Ae", "ø": "oe", "Ø": "Oe", "å": "aa", "Å": "Aa",
    "đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "þ": "th", "Þ": "Th",
}


def ascii_filename_component(value: str, *, max_length: int = 40, fallback: str = "dokument") -> str:
    """Ein ASCII-sicherer, header-taugliches Namensfragment.

    Reihenfolge mit Absicht:

    1. Umschrift der haeufigen Sonderzeichen (siehe `_TRANSLITERATION`) --
       muss VOR Schritt 2 laufen, weil die Unicode-Zerlegung "ö" zu "o"
       verkuerzen wuerde.
    2. NFKD-Zerlegung und Verwerfen aller nicht-ASCII-Reste. Damit fallen
       auch Zeichen weg, fuer die es keine sinnvolle Umschrift gibt (etwa
       chinesische Schrift) -- der genaue Name bleibt im
       `filename*`-Parameter erhalten.
    3. Alles, was danach nicht `[A-Za-z0-9_-]` ist, wird `_`. Das haelt
       Anfuehrungszeichen, Semikolon, CR und LF draussen -- genau die
       Zeichen, mit denen sich ueber einen Kundennamen ein Header
       einschmuggeln liesse. Bindestrich und Unterstrich bleiben, damit
       "kostenausweis-Goessi" nicht zu "kostenausweis_Goessi" wird.
    4. Rueckfall, wenn nichts Brauchbares uebrig bleibt (ein Name
       ausschliesslich aus nicht-lateinischer Schrift ergibt sonst einen
       leeren Dateinamen).
    """
    text = str(value or "")
    for source, target in _TRANSLITERATION.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = "".join(
        c if ("a" <= c <= "z" or "A" <= c <= "Z" or ("0" <= c <= "9") or c in "-_") else "_"
        for c in text
    )
    text = text.strip("_")[:max_length].strip("_")
    return text or fallback


def content_disposition(filename: str, *, disposition: str = "inline") -> str:
    """Vollstaendiger Header-Wert mit ASCII-Rueckfall UND exaktem Namen.

    `filename` ist der GEWUENSCHTE Name (darf Unicode enthalten); der
    Rueckfall wird daraus abgeleitet. Erzeugt z.B.

        inline; filename="kostenausweis-Goessi.pdf";
            filename*=UTF-8''kostenausweis-G%C3%B6ssi.pdf

    Der `filename*`-Wert ist prozentkodiert, enthaelt also nur ASCII -- der
    gesamte Header-Wert ist damit garantiert ASCII und kann Starlettes
    Latin-1-Kodierung nicht mehr zum Werfen bringen.
    """
    name = str(filename or "").strip() or "dokument"

    stem, dot, suffix = name.rpartition(".")
    if dot:
        ascii_name = f"{ascii_filename_component(stem, max_length=120)}.{ascii_filename_component(suffix, max_length=8, fallback='bin')}"
    else:
        ascii_name = ascii_filename_component(name)

    header = f'{disposition}; filename="{ascii_name}"'
    if ascii_name != name:
        # Nur anhaengen, wenn er etwas Neues sagt. `quote` laesst
        # RFC-5987-"attr-char" stehen und kodiert alles andere.
        header += f"; filename*=UTF-8''{quote(name, safe='')}"

    assert header.isascii(), f"Header-Wert ist nicht ASCII: {header!r}"
    return header
