import json
import logging
import shutil
import os
from datetime import datetime
from pathlib import Path

import xmltodict
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer

from la_gazette_des_sorciers.stockage_s3 import (
    connecter_bronze,
    deposer_contenu,
    lister_fichiers_s3,
    recuperer_contenu,
)

import numpy as np

load_dotenv()

CACHE_FOLDER = Path(__file__).parents[2] / "model_cache"

MODEL = os.environ["MODEL"]
MODEL_FOLDER = Path(os.getenv("MODEL_FOLDER", "model")).resolve()
SAVE_MODEL = os.getenv("SAVE_MODEL", "0") == "1"

PREFIX = "query: "


def charger_model(model_name: str):
    print(f"Chargement du modèle {model_name} ...")

    # on vérifie si le dossier MODEL_FOLDER existe et contient le modèle
    can_load_from_folder = MODEL_FOLDER.exists() and any(MODEL_FOLDER.iterdir())

    if can_load_from_folder:
        print(f"Chargement du modèle depuis {MODEL_FOLDER} ...")
        model = SentenceTransformer(str(MODEL_FOLDER))
    else:
        print(f"Le dossier {MODEL_FOLDER} n'existe pas ou est vide.")
        print("Téléchargement du modèle ou utilisation du cache ...")
        print(f"Le dossier du cache est {CACHE_FOLDER}")
        model = SentenceTransformer(model_name, cache_folder=str(CACHE_FOLDER))

        # sauvegarde du modèle si nécessaire (et suppression du cache)
        if SAVE_MODEL:
            print(f"Sauvegarde du modèle dans {MODEL_FOLDER} ...")
            model.save(str(MODEL_FOLDER))
            # on supprime le cache du modèle avec shutil
            if CACHE_FOLDER.exists():
                shutil.rmtree(CACHE_FOLDER)

    return model


def main():

    model = charger_model(MODEL)

    with open("tmp/articles_all.json", encoding="utf-8") as f:
        raw_data = json.load(f)

    # mécanique dumb pour enlever les doublons basés sur le titre
    data_sans_doublons = []
    seen_ids = set()
    for article in raw_data:
        if article["titre"] not in seen_ids:
            data_sans_doublons.append(article)
            seen_ids.add(article["titre"])
    data = data_sans_doublons

    print(len(data_sans_doublons))

    textes = []
    ids = [article["titre"] for article in data_sans_doublons]

    # si doublon dans les ids -> exception
    if len(ids) != len(set(ids)):
        # on trouve le doublon :
        doublons = [id for id in ids if ids.count(id) > 1]
        raise ValueError(f"Doublon détecté dans les ids des articles : {doublons}")

    for article in data_sans_doublons:
        textes.append(PREFIX + article["titre"] + " : " + article["extrait"])


    print("Encodage des textes ...")
    embeddings = model.encode(textes, batch_size=32, show_progress_bar=True)

    print(embeddings.shape)
    print(embeddings.dtype)

    # sauvegarde temp
    sortie = "tmp/embeddings"
    np.save(f"{sortie}.npy", embeddings.astype(np.float32))
    Path(f"{sortie}_ids.json").write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
