import json
import logging
import os
from datetime import datetime
from pathlib import Path

import xmltodict
from dotenv import find_dotenv, load_dotenv

if __package__:
    from .stockage_s3 import assurer_bucket, connecter_bronze, deposer_contenu
else:
    from stockage_s3 import assurer_bucket, connecter_bronze, deposer_contenu

ENV_FILE = find_dotenv(usecwd=True)
load_dotenv(ENV_FILE)
BASE_DIR = Path(ENV_FILE).parent if ENV_FILE else Path.cwd()

logger = logging.getLogger("collecte_json")

DATA_DIR = (BASE_DIR / os.getenv("DATA_DIR", "./data")).resolve()

XML_DATA_DIR = DATA_DIR / "xml"
JSON_DATA_DIR = DATA_DIR / "json"


def recuperer_fichiers_metadonnees(client=None, bucket: str | None = None) -> list[Path | str]:
    if client is not None:
        cles = []
        continuation = None
        while True:
            parametres = {"Bucket": bucket, "Prefix": "xml/"}
            if continuation:
                parametres["ContinuationToken"] = continuation
            page = client.list_objects_v2(**parametres)
            for objet in page.get("Contents", []):
                cle = objet["Key"]
                if len(cle.split("/")) == 3 and cle.endswith(".json"):
                    cles.append(cle)
            if not page.get("IsTruncated"):
                return cles
            continuation = page["NextContinuationToken"]

    fichiers = []
    for root, _, files in os.walk(XML_DATA_DIR):
        for file in files:
            if file.endswith(".json"):
                fichiers.append(Path(root) / file)
    return fichiers


def stocker_json(data: dict, client, bucket: str, region: str):

    fetched_at_str = data["fetched_at"]

    fetched_at = datetime.fromisoformat(fetched_at_str)

    jour = fetched_at.strftime("%Y-%m-%d")
    filename = f"{fetched_at_str.replace(':', '-')}_{data['source_id']}.json"
    contenu = json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8")

    if client is not None:
        cle = f"json/{jour}/{filename}"
        deposer_contenu(client, bucket, cle, contenu, "application/json")
    else:
        dossier_local = JSON_DATA_DIR / jour
        dossier_local.mkdir(parents=True, exist_ok=True)
        (dossier_local / filename).write_bytes(contenu)


def lire_objet_s3(client, bucket: str, cle: str) -> bytes:
    flux = client.get_object(Bucket=bucket, Key=cle)["Body"]
    try:
        return flux.read()
    finally:
        flux.close()


def traiter_fichier(fichier_metadonnees: Path | str, client, bucket: str, region: str):
    if client is not None:
        metadata = json.loads(lire_objet_s3(client, bucket, fichier_metadonnees))
        xml_cle = metadata.get("s3_key") or fichier_metadonnees.removesuffix(".json") + ".xml"
        xml_content = lire_objet_s3(client, bucket, xml_cle)
        metadata.pop("filepath", None)
        metadata["s3_key"] = xml_cle
    else:
        with open(fichier_metadonnees, encoding="utf-8") as f:
            metadata = json.load(f)
        with open(metadata["filepath"], "rb") as f:
            xml_content = f.read()

    final_dict = {**metadata}

    logger.info("Traitement de %s, %s", metadata["fetched_at"], metadata["source_id"])

    # conversion du XML en JSON avec xmltodict
    xml_dict = xmltodict.parse(xml_content)
    final_dict["content"] = xml_dict

    stocker_json(final_dict, client, bucket, region)


def main():
    client, bucket, region = connecter_bronze()
    if client is not None:
        assurer_bucket(client, bucket, region)
    fichiers = recuperer_fichiers_metadonnees(client, bucket)
    for fichier in fichiers:
        traiter_fichier(fichier, client, bucket, region)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
