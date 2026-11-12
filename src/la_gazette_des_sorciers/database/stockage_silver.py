"""Chargement transactionnel du nettoyage dans les tables PostgreSQL silver."""

import logging
from datetime import UTC, datetime

from sqlalchemy import MetaData, Table, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from la_gazette_des_sorciers.normalisation import normaliser_date
from la_gazette_des_sorciers.preprocess import (
    ResultatNettoyage,
    produire_rapport,
    traiter_documents,
)
from la_gazette_des_sorciers.regles_nettoyage import ConfigurationNettoyage

logger = logging.getLogger(__name__)

# Sérialise les chargements de ce pipeline entre la lecture des doublons et l'insertion.
VERROU_CHARGEMENT_SILVER = 748021104


def charger_tables(connexion):
    metadata = MetaData(schema="silver")
    return {
        nom: Table(nom, metadata, autoload_with=connexion)
        for nom in ("executions_silver", "articles_propres", "rejets")
    }


def nettoyer_en_base(
    documents,
    configuration: ConfigurationNettoyage | None = None,
    maintenant: datetime | None = None,
    *,
    moteur=None,
) -> ResultatNettoyage:
    """Enregistre un passage, puis valide ou annule l'ensemble de ses résultats."""
    if moteur is None:
        try:
            from la_gazette_des_sorciers.database.db import engine
        except KeyError as erreur:
            raise ValueError("DATABASE_URL doit être renseigné dans .env") from erreur
        moteur = engine
    configuration = configuration or ConfigurationNettoyage()
    maintenant = normaliser_date(maintenant or datetime.now(UTC))

    with moteur.begin() as connexion:
        tables = charger_tables(connexion)
        executions = tables["executions_silver"]
        execution_id = connexion.execute(
            executions.insert()
            .values(debut=datetime.now(UTC), version_regles=configuration.version)
            .returning(executions.c.execution_id)
        ).scalar_one()

    try:
        with moteur.begin() as connexion:
            connexion.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            connexion.execute(
                text("SELECT pg_advisory_xact_lock(:cle)"),
                {
                    "cle": VERROU_CHARGEMENT_SILVER,
                },
            )
            articles = tables["articles_propres"]
            rejets = tables["rejets"]
            precedents = list(
                connexion.execute(
                    select(
                        articles.c.source_id,
                        articles.c.identifiant_article,
                        articles.c.lien,
                        articles.c.titre,
                        articles.c.date_publication,
                    )
                ).mappings()
            )
            resultat = traiter_documents(documents, configuration, maintenant, precedents)

            for table, lignes in (
                (articles, resultat.articles_propres),
                (rejets, resultat.rejets),
            ):
                if lignes:
                    connexion.execute(
                        table.insert(),
                        [{**ligne, "execution_id": execution_id} for ligne in lignes],
                    )

            # Les contrôles et les compteurs sont recalculés sur les lignes réellement insérées.
            articles_stockes = [
                dict(ligne)
                for ligne in connexion.execute(
                    select(articles).where(articles.c.execution_id == execution_id)
                ).mappings()
            ]
            rejets_stockes = [
                dict(ligne)
                for ligne in connexion.execute(
                    select(rejets).where(rejets.c.execution_id == execution_id)
                ).mappings()
            ]
            volumes = {
                source: chiffres["entres"]
                for source, chiffres in resultat.rapport["par_source"].items()
            }
            rapport = produire_rapport(
                articles_stockes, rejets_stockes, volumes, maintenant, configuration
            )
            rapport["execution_id"] = execution_id
            connexion.execute(
                update(executions)
                .where(executions.c.execution_id == execution_id)
                .values(statut="termine", fin=datetime.now(UTC))
            )

        return ResultatNettoyage(articles_stockes, rejets_stockes, rapport)
    except Exception:
        # La transaction des articles et rejets a été annulée. L'exécution reste traçable.
        try:
            with moteur.begin() as connexion:
                connexion.execute(
                    update(executions)
                    .where(executions.c.execution_id == execution_id)
                    .values(statut="echec", fin=datetime.now(UTC))
                )
        except SQLAlchemyError:
            logger.exception("Impossible de marquer l'exécution %s en échec", execution_id)
        raise
