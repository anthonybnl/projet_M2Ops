import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parents[2] / "data"
DATA_XML_DIR = DATA_DIR / "xml"
DATA_JSON_DIR = DATA_DIR / "json"

FEED_URL = "https://www.la-croix.com/feeds/rss/site.xml"
HEADERS = {"Accept": "application/xml", "User-Agent": "LaGazetteM2Ops/0.1"}


@dataclass
class Article:
    guid: str
    title: str
    link: str
    description: str
    published: datetime | None


def fetch_feed(url: str) -> bytes:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    # on sauvegarde le XML brut
    DATA_XML_DIR.mkdir(parents=True, exist_ok=True)

    # nom du fichier avec la datetime
    xml_file_path = DATA_XML_DIR / f"lacroix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
    with open(xml_file_path, "wb") as f:
        f.write(response.content)

    return response.content


def parse_feed(content: bytes) -> list[Article]:
    root = ET.fromstring(content)
    articles = []
    for item in root.findall("./channel/item"):
        pub_date = item.findtext("pubDate", default="").strip()
        articles.append(
            Article(
                guid=item.findtext("guid", default="").strip(),
                title=item.findtext("title", default="").strip(),
                link=item.findtext("link", default="").strip(),
                description=item.findtext("description", default="").strip(),
                published=parsedate_to_datetime(pub_date) if pub_date else None,
            )
        )
    return articles


def collect() -> list[Article]:
    return parse_feed(fetch_feed(FEED_URL))


def save_articles_to_json(articles: list[Article], file_path: Path) -> None:

    new_list_articles = []
    for article in articles:
        new_list_articles.append(
            {
                "guid": article.guid,
                "title": article.title,
                "link": article.link,
                "description": article.description,
                "published": article.published.isoformat() if article.published else None,
            }
        )

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    **article.__dict__,
                    "published": article.published.isoformat() if article.published else None,
                }
                for article in articles
            ],
            f,
            ensure_ascii=False,
            indent=4,
        )


def main():
    articles = collect()

    # écriture du JSON en local

    save_articles_to_json(
        articles, DATA_JSON_DIR / f"lacroix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )


if __name__ == "__main__":
    main()
