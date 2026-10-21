import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import xmltodict
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("collecte_json")

SOURCES_FILE = Path(os.environ["SOURCES_FILE"]).resolve()
DATA_DIR = Path(os.environ["DATA_DIR"]).resolve()

XML_DATA_DIR = DATA_DIR / "xml"
JSON_DATA_DIR = DATA_DIR / "json"


def recuperer_fichiers_metadonnees() -> list[Path]:
    fichiers = []
    for root, _, files in os.walk(XML_DATA_DIR):
        for file in files:
            if file.endswith(".json"):
                fichiers.append(Path(root) / file)
    return fichiers


def stocker_json(data: dict):

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


def traiter_fichier(fichier_metadonnees: Path):
    with open(fichier_metadonnees, encoding="utf-8") as f:
        metadata = json.load(f)

    final_dict = {**metadata}

    logger.info("Traitement de %s, %s", metadata["fetched_at"], metadata["source_id"])

    xml_file_path = DATA_DIR / metadata["filepath"]
    # on lit le fichier XML associé
    with open(xml_file_path, encoding="utf-8") as f:
        xml_content = f.read()

    # conversion du XML en JSON avec xmltodict
    xml_dict = xmltodict.parse(xml_content)
    final_dict["content"] = xml_dict

    stocker_json(final_dict)


def main():
    logger.info("JSON data directory: %s", JSON_DATA_DIR)
    fichiers = recuperer_fichiers_metadonnees()
    for fichier in fichiers:
        traiter_fichier(fichier)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,  # par default python est en stderr, Kestra afficherait tous sortie stderr en logs ERROR, donc on le passe en stdout
    )
    main()
