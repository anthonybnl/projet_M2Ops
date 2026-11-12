"""Dépose les fichiers de collecte bronze dans un stockage compatible S3."""

import argparse
import logging
import os
from datetime import date
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CONTENT_TYPES = {".xml": "application/xml", ".json": "application/json"}
BRONZE_DIRECTORIES = {"xml": {".xml", ".json"}, "json": {".json"}}


def fichiers_bronze(data_dir: Path, jour: date | None = None) -> list[tuple[Path, str]]:
    """Retourne les fichiers bronze et leurs clés S3, sans chemin absolu local."""
    fichiers = []
    for repertoire, extensions in BRONZE_DIRECTORIES.items():
        racine = data_dir / repertoire
        if not racine.is_dir():
            continue
        for fichier in sorted(racine.rglob("*")):
            if not fichier.is_file() or fichier.suffix.lower() not in extensions:
                continue
            chemin_relatif = fichier.relative_to(data_dir)
            if len(chemin_relatif.parts) != 3:
                continue
            if jour is not None and chemin_relatif.parts[1] != jour.isoformat():
                continue
            fichiers.append((fichier, chemin_relatif.as_posix()))
    return fichiers


def creer_client(endpoint: str, region: str):
    """Crée un client S3 avec l'adressage par chemin requis par RustFS."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def assurer_bucket(client, bucket: str, region: str) -> None:
    """Crée le bucket uniquement s'il n'existe pas déjà."""
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise

    arguments = {"Bucket": bucket}
    if region != "us-east-1":
        arguments["CreateBucketConfiguration"] = {"LocationConstraint": region}
    client.create_bucket(**arguments)
    logger.info("Bucket créé : %s", bucket)


def connecter_bronze():
    """Prépare le client bronze à partir de l'environnement ou de .env."""

    S3_ENABLED = os.getenv("S3_ENABLED", "0") == "1"
    if not S3_ENABLED:
        logger.error("S3 n'est pas activé")
        return None, None, None

    variables = ("S3_ENDPOINT_URL", "S3_BUCKET")
    manquantes = [nom for nom in variables if not os.getenv(nom)]
    if manquantes:
        raise ValueError(f"Variables manquantes : {', '.join(manquantes)}")

    bucket = os.environ["S3_BUCKET"]
    region = os.getenv("S3_REGION", "")
    client = creer_client(os.environ["S3_ENDPOINT_URL"], region)

    return client, bucket, region


def deposer_contenu(client, bucket: str, cle: str, contenu: bytes, content_type: str) -> None:
    """Envoie des octets produits par un collecteur directement vers S3."""
    client.put_object(Bucket=bucket, Key=cle, Body=contenu, ContentType=content_type)
    logger.info("Déposé : s3://%s/%s", bucket, cle)


def deposer_fichier(data_dir: Path, fichier: Path, client, bucket: str) -> str:
    """Dépose un fichier local en conservant son chemin relatif sous DATA_DIR."""
    cle = fichier.relative_to(data_dir).as_posix()
    client.upload_file(
        str(fichier),
        bucket,
        cle,
        ExtraArgs={"ContentType": CONTENT_TYPES[fichier.suffix.lower()]},
    )
    logger.info("Déposé : s3://%s/%s", bucket, cle)
    return cle


def deposer_fichier_avec_clef(client, bucket: str, cle: str, fichier: Path, content_type: str):
    client.upload_file(
        str(fichier),
        bucket,
        cle,
        ExtraArgs={"ContentType": content_type},
    )
    logger.info("Déposé : s3://%s/%s", bucket, cle)


def deposer_bronze(
    data_dir: Path, client, bucket: str, region: str = "", jour: date | None = None
) -> int:
    """Envoie les XML, leurs métadonnées et les JSON convertis vers S3."""
    fichiers = fichiers_bronze(data_dir, jour)
    if not fichiers:
        raise FileNotFoundError(f"Aucun fichier bronze trouvé dans {data_dir}")

    assurer_bucket(client, bucket, region)
    for fichier, _ in fichiers:
        deposer_fichier(data_dir, fichier, client, bucket)
    return len(fichiers)


def lister_fichiers_s3(client, bucket: str, prefix: str) -> list[str]:
    liste_fichiers = []
    continuation_token = None
    while True:
        if continuation_token is None:
            objects = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        else:
            objects = client.list_objects_v2(
                Bucket=bucket, Prefix=prefix, ContinuationToken=continuation_token
            )
        liste_fichiers += [obj["Key"] for obj in objects.get("Contents", [])]
        if objects.get("IsTruncated"):
            continuation_token = objects.get("NextContinuationToken")
        else:
            break
    return liste_fichiers

def recuperer_contenu(client, bucket: str, cle: str) -> bytes:
    """Récupère le contenu d'un fichier depuis S3."""
    response = client.get_object(Bucket=bucket, Key=cle)
    return response["Body"].read()
