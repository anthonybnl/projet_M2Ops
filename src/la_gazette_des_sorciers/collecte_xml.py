import csv
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import find_dotenv, load_dotenv

if __package__:
    from .stockage_s3 import assurer_bucket, connecter_bronze, deposer_contenu
else:
    from stockage_s3 import assurer_bucket, connecter_bronze, deposer_contenu

ENV_FILE = find_dotenv(usecwd=True)
load_dotenv(ENV_FILE)
BASE_DIR = Path(ENV_FILE).parent if ENV_FILE else Path.cwd()

logger = logging.getLogger("collecte_xml")

USER_AGENT = "Mozilla/5.0 (la_gazette_des_sorciers)"
TIMEOUT_S = 30

SOURCES_FILE = (BASE_DIR / os.environ["SOURCES_FILE"]).resolve()
DATA_DIR = (BASE_DIR / os.getenv("DATA_DIR", "./data")).resolve()

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


def stocker(
    xml_data: bytes,
    source_id: str,
    source_url: str,
    fetched_at: datetime,
    status_code: int,
    client,
    bucket: str,
    region: str,
):

    jour = fetched_at.strftime("%Y-%m-%d")
    dossier_local = XML_DATA_DIR / jour
    fetched_at_str = fetched_at.isoformat()
    base_filename = f"{fetched_at_str.replace(':', '-')}_{source_id}"
    xml_filepath = dossier_local / f"{base_filename}.xml"
    metadata_filepath = dossier_local / f"{base_filename}.json"
    xml_cle = f"xml/{jour}/{base_filename}.xml"
    metadata_cle = f"xml/{jour}/{base_filename}.json"
    metadata = {
        "source_id": source_id,
        "source_url": source_url,
        "fetched_at": fetched_at_str,
        "http_status": status_code,
    }

    if client is not None:
        metadata["s3_key"] = xml_cle
        metadata_contenu = json.dumps(metadata, ensure_ascii=False, indent=4).encode("utf-8")
        assurer_bucket(client, bucket, region)
        deposer_contenu(client, bucket, xml_cle, xml_data, "application/xml")
        deposer_contenu(client, bucket, metadata_cle, metadata_contenu, "application/json")
    else:
        metadata["filepath"] = str(xml_filepath)
        metadata_contenu = json.dumps(metadata, ensure_ascii=False, indent=4).encode("utf-8")
        dossier_local.mkdir(parents=True, exist_ok=True)
        xml_filepath.write_bytes(xml_data)
        metadata_filepath.write_bytes(metadata_contenu)


def collecter_flux(source: dict, client, bucket: str, region: str) -> None:

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
        client,
        bucket,
        region,
    )


def main():
    sources = read_sources(SOURCES_FILE)
    client, bucket, region = connecter_bronze()

    for source in sources:
        logger.info("Collecte du flux: %s", source["id"])
        collecter_flux(source, client, bucket, region)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
