"""Transformations pures des valeurs RSS avant leur stockage en silver."""

import re
import unicodedata
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


def extraire_texte(valeur) -> str:
    """Accepte le texte RSS et les valeurs xmltodict contenant une clé #text."""
    if valeur is None:
        return ""
    if isinstance(valeur, dict):
        return extraire_texte(valeur.get("#text"))
    if isinstance(valeur, list):
        return " ".join(extraire_texte(element) for element in valeur)
    if not isinstance(valeur, str):
        return ""
    return valeur


def reparer_encodage(texte: str) -> str:
    """Répare les mots UTF-8 interprétés en latin-1 ou Windows-1252."""
    marqueurs = ("Ã", "Â", "â€", "ðŸ")

    def score(mot):
        return sum(mot.count(marqueur) for marqueur in marqueurs)

    def reparer_mot(match):
        mot = match.group()
        for _ in range(3):
            candidats = [mot]
            for encodage in ("cp1252", "latin1"):
                try:
                    decode = mot.encode(encodage).decode("utf-8", errors="surrogateescape")
                    # Préserve les accents déjà corrects dans un mot partiellement altéré.
                    candidat = "".join(
                        bytes([ord(caractere) - 0xDC00]).decode(encodage)
                        if 0xDC80 <= ord(caractere) <= 0xDCFF
                        else caractere
                        for caractere in decode
                    )
                    candidats.append(candidat)
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
            meilleur = min(candidats, key=score)
            if score(meilleur) >= score(mot):
                break
            mot = meilleur
        return mot

    return re.sub(r"\S+", reparer_mot, texte)


class _TexteHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.morceaux = []
        self.profondeur_ignoree = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.profondeur_ignoree += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.morceaux.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.profondeur_ignoree = max(0, self.profondeur_ignoree - 1)
        if tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.morceaux.append(" ")

    def handle_data(self, data):
        if self.profondeur_ignoree == 0:
            self.morceaux.append(data)


def supprimer_html(texte: str) -> str:
    parseur = _TexteHTML()
    parseur.feed(texte)
    parseur.close()
    return "".join(parseur.morceaux)


def normaliser_espaces(texte: str) -> str:
    return " ".join(texte.replace("\u200b", "").replace("\ufeff", "").split())


def normaliser_texte(valeur) -> str:
    texte = extraire_texte(valeur)
    for _ in range(2):
        texte = unescape(texte)
    texte = reparer_encodage(texte)
    return normaliser_espaces(unicodedata.normalize("NFC", supprimer_html(texte)))


def normaliser_date(valeur: str | datetime) -> datetime:
    """Accepte ISO 8601 et les dates RSS, avec un fuseau horaire explicite."""
    if isinstance(valeur, datetime):
        date = valeur
    else:
        texte = extraire_texte(valeur).strip()
        if not texte:
            raise ValueError("Date absente")
        try:
            date = datetime.fromisoformat(texte)
        except ValueError:
            try:
                date = parsedate_to_datetime(texte)
            except (ValueError, TypeError, OverflowError) as erreur:
                raise ValueError("Date illisible") from erreur
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError("Fuseau horaire absent")
    try:
        return date.astimezone(UTC)
    except (ValueError, OverflowError) as erreur:
        raise ValueError("Date hors limites en UTC") from erreur


PARAMETRES_SUIVI = {"fbclid", "gclid", "mc_cid", "mc_eid", "xtor", "at_medium", "at_campaign"}


def normaliser_url(valeur, url_source: str = "") -> str:
    texte = extraire_texte(valeur).strip()
    if not texte:
        raise ValueError("Lien absent")
    url = urlsplit(urljoin(url_source, unescape(texte)))
    if url.scheme.lower() not in {"http", "https"} or not url.hostname:
        raise ValueError("Lien HTTP ou HTTPS attendu")
    if url.username or url.password or any(caractere.isspace() for caractere in url.geturl()):
        raise ValueError("Lien invalide")
    domaine = url.hostname.lower()
    if ":" in domaine:
        domaine = f"[{domaine}]"
    port = url.port
    if port and (url.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
        domaine = f"{domaine}:{port}"
    parametres = [
        (cle, valeur)
        for cle, valeur in parse_qsl(url.query, keep_blank_values=True)
        if not cle.lower().startswith("utm_") and cle.lower() not in PARAMETRES_SUIVI
    ]
    return urlunsplit((url.scheme.lower(), domaine, url.path or "/", urlencode(parametres), ""))


def normaliser_titre_comparaison(titre: str) -> str:
    texte = unicodedata.normalize("NFKD", titre.casefold())
    texte = "".join(caractere for caractere in texte if not unicodedata.combining(caractere))
    return " ".join(re.findall(r"[^\W_]+", texte))
