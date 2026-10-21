"""Nettoyage : JSON bruts -> articles normalisés des dernières 24 h."""

import argparse
import hashlib
import html
import json
import logging
import re
import sys
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from la_gazette_des_sorciers.storage import LocalStorage

log = logging.getLogger("nettoyage")


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def text(value) -> str:
    """Valeur xmltodict -> chaîne (gère les éléments à attributs : {'#text': ...})."""
    if isinstance(value, dict):
        value = value.get("#text", "")
    return value.strip() if isinstance(value, str) else ""


def strip_html(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(UTC)


def atom_link(links) -> str:
    for link in as_list(links):
        if isinstance(link, dict) and link.get("@rel", "alternate") == "alternate":
            return link.get("@href", "")
    return ""


def raw_items(feed: dict) -> list[dict]:
    if "rss" in feed:
        return as_list((feed["rss"].get("channel") or {}).get("item"))
    if "feed" in feed:
        return as_list(feed["feed"].get("entry"))
    return []


def clean_item(item: dict, source: dict) -> dict | None:
    """Ne garde que titre, résumé, lien et date (ni auteurs, ni images, ni corps complet)."""
    link = text(item.get("link")) or atom_link(item.get("link")) or text(item.get("guid"))
    title = strip_html(text(item.get("title")))
    if not link or not title:
        return None
    summary = strip_html(text(item.get("description")) or text(item.get("summary")))
    published = parse_date(
        text(item.get("pubDate"))
        or text(item.get("dc:date"))
        or text(item.get("published"))
        or text(item.get("updated"))
    )
    return {
        "id": hashlib.sha1(link.encode()).hexdigest()[:16],
        "source": source["nom"],
        "type": source["type"],
        "region": source["region"],
        "title": title,
        "summary": summary,
        "link": link,
        "published": published,
    }


def clean_document(document: dict, window: timedelta) -> list[dict]:
    """Articles publiés dans la fenêtre précédant la collecte (articles sans date écartés)."""
    reference = datetime.fromisoformat(document["fetched_at"])
    articles = []
    for item in raw_items(document["feed"]):
        article = clean_item(item, document["source"])
        if article is None or article["published"] is None:
            continue
        if article["published"] < reference - window or article["published"] > reference:
            continue
        article["published"] = article["published"].isoformat()
        articles.append(article)
    return articles


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,  # sur stderr, Kestra afficherait tous les logs en ERROR
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(datetime.UTC).strftime("%Y-%m-%d"))
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    storage = LocalStorage()
    keys = storage.list(f"raw/json/{args.date}")
    if not keys:
        log.error("Aucun JSON brut pour le %s", args.date)
        return 1

    articles, seen = [], set()
    for key in keys:
        document = json.loads(storage.get(key))
        kept = [
            a
            for a in clean_document(document, timedelta(hours=args.hours))
            if a["link"] not in seen
        ]
        seen.update(a["link"] for a in kept)
        articles.extend(kept)
        log.info("%-35s %d articles", document["source"]["nom"], len(kept))

    articles.sort(key=lambda a: a["published"], reverse=True)
    out = storage.put(
        f"clean/{args.date}/articles.json",
        json.dumps(articles, ensure_ascii=False, indent=2).encode(),
    )
    log.info("%d articles écrits dans %s", len(articles), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
