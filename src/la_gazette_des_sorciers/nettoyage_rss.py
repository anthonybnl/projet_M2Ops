import html
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("nettoyage_rss")

MAX_AGE = timedelta(hours=24)
PARIS = ZoneInfo("Europe/Paris")
# Le Parisien : pas de pubDate, mais le lien finit par -jj-mm-aaaa-IDENTIFIANT.php
DATE_DANS_URL = re.compile(r"-(\d{2})-(\d{2})-(\d{4})-[A-Za-z0-9]+\.php$")


def en_liste(valeur) -> list:
    # xmltodict renvoie un dict s'il y a 1 seul <item>, une liste sinon
    if valeur is None:
        return []
    return valeur if isinstance(valeur, list) else [valeur]


def texte(valeur) -> str:
    # une balise avec attributs devient {"@attr": ..., "#text": ...}
    if isinstance(valeur, dict):
        valeur = valeur.get("#text")
    if not valeur:
        return ""
    return str(valeur).strip()


def nettoyer_texte(valeur) -> str:
    brut = html.unescape(re.sub(r"<[^>]+>", " ", texte(valeur)))
    return re.sub(r"\s+", " ", brut).strip()


def parser_date(valeur) -> datetime | None:
    brut = texte(valeur)
    if not brut:
        return None
    try:
        date = parsedate_to_datetime(brut)
    except (TypeError, ValueError):
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return date.astimezone(UTC)


def date_depuis_url(url: str) -> datetime | None:
    # le lien ne donne que le jour : on prend minuit, heure de Paris
    m = DATE_DANS_URL.search(url)
    if not m:
        return None
    jour, mois, annee = (int(g) for g in m.groups())
    try:
        return datetime(annee, mois, jour, tzinfo=PARIS).astimezone(UTC)
    except ValueError:
        return None


def choisir_date(item: dict, url: str, fetched_at: datetime) -> tuple[datetime, str]:
    # pubDate, sinon date dans le lien, sinon date de collecte
    if date := parser_date(item.get("pubDate")):
        return date, "pubDate"
    if date := date_depuis_url(url):
        return date, "url"
    return fetched_at, "collecte"


def nettoyer_item(item: dict, source_id: str, fetched_at: datetime) -> dict | None:
    titre = nettoyer_texte(item.get("title"))
    url = texte(item.get("link"))
    if not titre or not url:
        return None
    publie, date_source = choisir_date(item, url, fetched_at)
    return {
        "source_id": source_id,
        "title": titre,
        "url": url,
        "guid": texte(item.get("guid")) or url,
        "published_at": publie.isoformat(),
        "date_source": date_source,
        "description": nettoyer_texte(item.get("description")),
    }


def nettoyer_flux(data: dict) -> tuple[list[dict], dict]:
    source_id = data["source_id"]
    fetched_at = datetime.fromisoformat(data["fetched_at"])
    contenu = data.get("content") or {}
    if "rss" not in contenu:
        logger.warning("source=%s format non géré (racine: %s)", source_id, list(contenu))
    items = en_liste((contenu.get("rss") or {}).get("channel", {}).get("item"))

    articles = []
    stats = {
        "total": len(items),
        "invalides": 0,
        "trop_vieux": 0,
        "date_url": 0,
        "date_collecte": 0,
    }
    for item in items:
        article = nettoyer_item(item, source_id, fetched_at)
        if article is None:
            stats["invalides"] += 1
            continue
        if fetched_at - datetime.fromisoformat(article["published_at"]) > MAX_AGE:
            stats["trop_vieux"] += 1
            continue
        if article["date_source"] != "pubDate":
            stats[f"date_{article['date_source']}"] += 1
        articles.append(article)
    return articles, stats


def stocker_propre(articles: list[dict], data: dict, clean_dir: Path) -> Path:
    fetched_at_str = data["fetched_at"]
    dossier = clean_dir / datetime.fromisoformat(fetched_at_str).strftime("%Y-%m-%d")
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{fetched_at_str}_{data['source_id']}.json"
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=4)
    return chemin


def main():
    data_dir = Path(os.environ["DATA_DIR"]).resolve()
    json_dir, clean_dir = data_dir / "json", data_dir / "clean"

    for fichier in sorted(json_dir.rglob("*.json")):
        with open(fichier, encoding="utf-8") as f:
            data = json.load(f)
        articles, stats = nettoyer_flux(data)
        stocker_propre(articles, data, clean_dir)
        logger.info(
            "source=%s gardes=%d total=%d invalides=%d trop_vieux=%d date_url=%d date_collecte=%d",
            data["source_id"],
            len(articles),
            stats["total"],
            stats["invalides"],
            stats["trop_vieux"],
            stats["date_url"],
            stats["date_collecte"],
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
