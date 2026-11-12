"""Point d'entrée de nettoyage des JSON bronze locaux ou présents dans S3."""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import SQLAlchemyError

from la_gazette_des_sorciers.database.stockage_silver import nettoyer_en_base
from la_gazette_des_sorciers.normalisation import normaliser_date
from la_gazette_des_sorciers.preprocess import produire_rapport_par_regle
from la_gazette_des_sorciers.regles_nettoyage import ConfigurationNettoyage
from la_gazette_des_sorciers.stockage_s3 import connecter_bronze, lister_fichiers_s3

logger = logging.getLogger(__name__)


def lire_fichiers(fichiers):
    for fichier in sorted({chemin.resolve() for chemin in fichiers}):
        yield fichier.as_uri(), json.loads(fichier.read_text(encoding="utf-8-sig"))


def lire_s3(prefixe: str):
    client, bucket, _ = connecter_bronze()
    if client is None:
        raise ValueError("Pour lire S3, définir S3_ENABLED=1 ou fournir --fichier")
    cles = sorted(lister_fichiers_s3(client, bucket, prefixe))
    for cle in cles:
        if cle.endswith(".json"):
            with client.get_object(Bucket=bucket, Key=cle)["Body"] as flux:
                yield f"s3://{bucket}/{cle}", json.loads(flux.read())


def ecrire_json(chemin: Path, contenu):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(contenu, ensure_ascii=False, indent=2, default=lambda date: date.isoformat()),
        encoding="utf-8",
    )


def main(argv=None) -> int:
    valeurs_defaut = ConfigurationNettoyage()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fichier", type=Path, action="append", help="JSON bronze local, répétable"
    )
    parser.add_argument("--prefixe", help="Préfixe S3, par défaut json/AAAA-MM-JJ/ du jour UTC")
    parser.add_argument("--rapport", type=Path, help="Fichier JSON du rapport de qualité")
    parser.add_argument("--rapport-regles", type=Path, help="Fichier JSON du rapport par règle")
    parser.add_argument("--version-regles", default=valeurs_defaut.version)
    parser.add_argument("--seuil-doublon", type=float, default=valeurs_defaut.seuil_jaccard)
    parser.add_argument("--taux-rejet-max", type=float, default=valeurs_defaut.taux_rejet_max)
    parser.add_argument(
        "--maintenant", type=normaliser_date, help="Date de référence ISO avec fuseau"
    )
    args = parser.parse_args(argv)
    if args.fichier and args.prefixe:
        parser.error("Choisir --fichier ou --prefixe")

    maintenant = args.maintenant or datetime.now(UTC)
    try:
        configuration = ConfigurationNettoyage(
            version=args.version_regles,
            seuil_jaccard=args.seuil_doublon,
            taux_rejet_max=args.taux_rejet_max,
        )
        prefixe = args.prefixe or f"json/{maintenant:%Y-%m-%d}/"
        documents = lire_fichiers(args.fichier) if args.fichier else lire_s3(prefixe)
        entrees = {chemin.resolve() for chemin in args.fichier or []}
        rapports_configures = [chemin for chemin in (args.rapport, args.rapport_regles) if chemin]
        if args.rapport and not args.rapport_regles:
            rapports_configures.append(
                args.rapport.with_name(f"{args.rapport.stem}-par-regle.json")
            )
        if len({chemin.resolve() for chemin in rapports_configures}) != len(rapports_configures):
            raise ValueError("Les deux rapports doivent avoir des chemins distincts")
        if any(chemin.resolve() in entrees for chemin in rapports_configures):
            raise ValueError("Les rapports doivent être distincts des fichiers bronze")
        resultat = nettoyer_en_base(documents, configuration, maintenant)
        execution_id = resultat.rapport["execution_id"]
        rapport = args.rapport or Path("rapports") / (
            f"qualite-{maintenant:%Y-%m-%d}-execution-{execution_id}.json"
        )
        rapport_regles = args.rapport_regles or rapport.with_name(f"{rapport.stem}-par-regle.json")
    except (BotoCoreError, ClientError, OSError, SQLAlchemyError, ValueError) as erreur:
        logger.error("Nettoyage interrompu : %s", erreur)
        return 1

    try:
        if rapport.resolve() == rapport_regles.resolve():
            raise ValueError("Les deux rapports doivent avoir des chemins distincts")
        if rapport.resolve() in entrees or rapport_regles.resolve() in entrees:
            raise ValueError("Les rapports doivent être distincts des fichiers bronze")
        ecrire_json(rapport, resultat.rapport)
        ecrire_json(rapport_regles, produire_rapport_par_regle(resultat.rapport))
    except (OSError, ValueError) as erreur:
        logger.error(
            "Exécution %s enregistrée dans PostgreSQL, archivage des rapports impossible : %s",
            execution_id,
            erreur,
        )
        return 1
    print(
        f"Entrés={resultat.rapport['entres']} "
        f"gardés={resultat.rapport['gardes']} rejetés={resultat.rapport['rejetes']}"
    )
    print(f"Résultats enregistrés dans PostgreSQL, exécution {execution_id}")
    print(f"Rapport par source dans {rapport}")
    print(f"Rapport par règle dans {rapport_regles}")
    if not resultat.rapport["qualite_validee"]:
        logger.error("Au moins un contrôle de qualité a échoué, consulter le rapport")
        return 2
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
