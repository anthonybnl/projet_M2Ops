import csv
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("collecte_xml")

USER_AGENT = "Mozilla/5.0 (la_gazette_des_sorciers)"
TIMEOUT_S = 30

SOURCES_FILE = Path(os.environ["SOURCES_FILE"]).resolve()
DATA_DIR = Path(os.environ["DATA_DIR"]).resolve()

XML_DATA_DIR = DATA_DIR / "xml"


def read_sources(path: str | Path) -> list[dict]:
    sources, seen = [], set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("acces") or "").split("|")[0]
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "id": row["id"],
                    "nom": row["nom"],
                    "type": row["type"],
                    "region": row["region"],
                    "url": url,
                }
            )
    return sources


def fetch(url: str) -> tuple[bytes, int]:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.content, resp.status_code


def stocker(xml_data, source_id: str, source_url: str, fetched_at: datetime, status_code: int):

    # 1 dossier par jour
    PATH = XML_DATA_DIR / fetched_at.strftime("%Y-%m-%d")
    PATH.mkdir(parents=True, exist_ok=True)

    fetched_at_str = fetched_at.isoformat()

    # base_filename = f"{fetched_at_str}_{source_id}"
    base_filename = f"{fetched_at.strftime('%Y%m%dT%H%M%S%fZ')}_{source_id}"

    # on écrit le fichier XML
    xml_filepath = PATH / f"{base_filename}.xml"
    with open(xml_filepath, "wb") as f:
        f.write(xml_data)

    # on écrit le fichier des métadonnées JSON
    metadata = {
        "source_id": source_id,
        "source_url": source_url,
        "fetched_at": fetched_at_str,
        "http_status": status_code,
        "filepath": str(xml_filepath),
    }
    metadata_filepath = PATH / f"{base_filename}.json"

    with open(metadata_filepath, "w", encoding="utf-8") as f:
        json.dump(
            metadata,
            f,
            ensure_ascii=False,
            indent=4,
        )


def collecter_flux(source: dict) -> None:

    # métadonnées
    fetched_at = datetime.now(UTC)
    source_id = source["id"]
    source_url = source["url"]

    # data
    xml, status_code = fetch(source_url)

    stocker(
        xml,
        source_id,
        source_url,
        fetched_at,
        status_code,
    )


def main():
    logger.info("XML data directory: %s", XML_DATA_DIR)
    sources = read_sources(SOURCES_FILE)

    for source in sources:
        logger.info("Collecte du flux: %s", source["id"])
        collecter_flux(source)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
