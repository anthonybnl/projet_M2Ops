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

def decode_nfkd(texte: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", texte)


def traiter_flux(data):
    articles = []
    for item in data["content"]["rss"]["channel"]["item"]:
        # gestion de la date
        date_article = item.get("pubDate")
        # date au format : Thu, 12 Nov 2026 12:56:41 GMT / Thu, 12 Nov 2026 12:56:41 +01:00
        # conversion en objet datetime
        if date_article:
            try:
                date_article = datetime.strptime(date_article, "%a, %d %b %Y %H:%M:%S %Z")
            except ValueError:
                date_article = datetime.strptime(date_article, "%a, %d %b %Y %H:%M:%S %z") # Atom 2

        extrait = item.get("description")
        if not extrait:
            print("Description manquante pour l'article")
            # on passe au suivant
            continue

        new_data = {
            "titre": decode_nfkd(item.get("title")),
            "extrait": decode_nfkd(extrait),
            "lien": item.get("link"),
            "date_publication": date_article,
        }
        articles.append(new_data)
    return articles


def main():
    client, bucket, region = connecter_bronze()
    clefs = lister_fichiers_s3(client, bucket, prefix="json/")

    all_articles = []
    for i, clef in enumerate(clefs[0:10]):
        print(f"====== {i} Processing file: {clef}")

        b = recuperer_contenu(client, bucket, clef)
        data = json.loads(b)

        # with open(f"tmp/data_{i}.json", "w", encoding="utf-8") as f:
        #     json.dump(data, f, ensure_ascii=False, indent=4)

        articles = traiter_flux(data)

        if len(articles) == 0:
            print(f"Aucun article trouvé ou valide dans le fichier {clef}")
        else:
            all_articles.extend(articles)

            # with open(f"tmp/articles_{i}.json", "w", encoding="utf-8") as f:
            #     json.dump(
            #         [{**a, "date_publication": a["date_publication"].isoformat()} for a in articles],
            #         f,
            #         ensure_ascii=False,
            #         indent=4,
            #     )

    print(f"Total articles collected: {len(all_articles)}")
    with open(f"tmp/articles_all.json", "w", encoding="utf-8") as f:
        json.dump(
            [{**a, "date_publication": a["date_publication"].isoformat()} for a in all_articles],
            f,
            ensure_ascii=False,
            indent=4,
        )

if __name__ == "__main__":
    main()
