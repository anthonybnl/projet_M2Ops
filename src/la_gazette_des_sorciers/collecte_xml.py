import json
import logging
import os
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from la_gazette_des_sorciers.database.crud_sources import list_sources
from la_gazette_des_sorciers.database.db import SessionLocal
from la_gazette_des_sorciers.database.db_models import Sources

load_dotenv()

logger = logging.getLogger("collecte_xml")

USER_AGENT = "Mozilla/5.0 (la_gazette_des_sorciers)"
TIMEOUT_S = 30

DATA_DIR = Path(os.environ["DATA_DIR"]).resolve()

XML_DATA_DIR = DATA_DIR / "xml"


def recuperer_sources() -> list[Sources]:
    with SessionLocal() as session:
        data = list_sources(session, actif=True)
    return data


def mettre_a_jour_source(source_id, etag=None, last_modified=None, derniere_reussite=None):
    with SessionLocal() as session:
        # on cherche une source par son id
        source_bdd = session.query(Sources).filter(Sources.id == source_id).first()
        if source_bdd:
            if etag:
                source_bdd.etag = etag
            if last_modified:
                source_bdd.last_modified = last_modified
            if derniere_reussite:
                source_bdd.derniere_reussite = derniere_reussite
            session.commit()


def fetch(source: Sources) -> tuple[bytes, int]:
    headers = {"User-Agent": USER_AGENT}

    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        # la date est déja en UTC il faut juste ajouter le tz
        last_modified_utc = source.last_modified.replace(tzinfo=UTC)
        headers["If-Modified-Since"] = format_datetime(last_modified_utc, usegmt=True)

    resp = requests.get(source.url_flux, headers=headers, timeout=TIMEOUT_S)
    resp.raise_for_status()

    headers = resp.headers
    etag = headers.get("etag")  # Récupération de l'en-tête ETag si présent
    last_modified = headers.get(
        "last-modified"
    )  # Récupération de l'en-tête Last-Modified si présent

    # on met à jour Etag, last-modified et la dernière réussite en BDD
    mettre_a_jour_source(
        source.id, etag=etag, last_modified=last_modified, derniere_reussite=datetime.now(UTC)
    )

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


def collecter_flux(source: Sources) -> None:

    # métadonnées
    fetched_at = datetime.now(UTC)
    source_id = source.id
    source_url = source.url_flux

    # data
    xml, status_code = fetch(source)

    # si code 304 (Not Modified), on ne stocke pas le fichier
    if status_code == 304:
        logger.info("Flux non modifié: %s", source.id)
    else:
        stocker(
            xml,
            source_id,
            source_url,
            fetched_at,
            status_code,
        )
        logger.info("Flux collecté: %s", source.id)


def main():
    logger.info("XML data directory: %s", XML_DATA_DIR)
    sources = recuperer_sources()

    for source in sources:
        collecter_flux(source)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
