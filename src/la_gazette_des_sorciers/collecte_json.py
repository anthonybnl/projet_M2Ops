import json
import logging
import os
from datetime import datetime
from pathlib import Path

import xmltodict
from dotenv import load_dotenv

from la_gazette_des_sorciers.stockage_s3 import (
    connecter_bronze,
    deposer_contenu,
    lister_fichiers_s3,
    recuperer_contenu,
)

load_dotenv()

logger = logging.getLogger("collecte_json")

SOURCES_FILE = Path(os.environ["SOURCES_FILE"]).resolve()
DATA_DIR = Path(os.environ["DATA_DIR"]).resolve()

XML_DATA_DIR = DATA_DIR / "xml"
JSON_DATA_DIR = DATA_DIR / "json"


def recuperer_fichiers_metadonnees_local() -> list[Path]:
    fichiers = []
    for root, _, files in os.walk(XML_DATA_DIR):
        for file in files:
            if file.endswith(".json"):
                fichiers.append(Path(root) / file)
    return fichiers


def stocker_json_local(data: dict):

    fetched_at_str = data["fetched_at"]

    fetched_at = datetime.fromisoformat(fetched_at_str)

    # 1 dossier par jour
    PATH = JSON_DATA_DIR / fetched_at.strftime("%Y-%m-%d")
    PATH.mkdir(parents=True, exist_ok=True)

    filename = f"{fetched_at.strftime('%Y%m%dT%H%M%S%fZ')}_{data['source_id']}.json"

    with open(PATH / filename, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=4,
        )


def constituer_final_dict(metadata: dict, xml_content: str) -> dict:
    xml_dict = xmltodict.parse(xml_content)
    final_dict = {**metadata}
    final_dict["content"] = xml_dict
    return final_dict


def traiter_fichier_local(fichier_metadonnees: Path):
    with open(fichier_metadonnees, encoding="utf-8") as f:
        metadata = json.load(f)

    logger.info("Traitement de %s, %s", metadata["fetched_at"], metadata["source_id"])

    xml_file_path = metadata["filepath"]
    # on lit le fichier XML associé
    with open(xml_file_path, encoding="utf-8") as f:
        xml_content = f.read()

    final_dict = constituer_final_dict(metadata, xml_content)

    stocker_json_local(final_dict)


def traiter_clef_s3(client, bucket: str, metadata_cle: str):
    contenu = recuperer_contenu(client, bucket, metadata_cle)
    metadata = json.loads(contenu)

    # on récupère le fichier XML
    xml_clef = metadata["s3_file_key"]
    xml_contenu = recuperer_contenu(client, bucket, xml_clef)

    final_dict = constituer_final_dict(metadata, xml_contenu)

    json_clef = metadata_cle.replace("metadata/", "json/")

    deposer_contenu(
        client, bucket, json_clef, json.dumps(final_dict, ensure_ascii=False), "application/json"
    )


def main():

    client, bucket, _ = connecter_bronze()
    clefs = lister_fichiers_s3(client, bucket, prefix="metadata/")

    for clef in clefs:
        logger.info("Traitement de la clé S3: %s", clef)
        traiter_clef_s3(client, bucket, clef)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
