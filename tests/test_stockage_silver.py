"""Vérifications PostgreSQL, activées avec TEST_DATABASE_URL sur une base de test."""

import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError

from la_gazette_des_sorciers.database import stockage_silver
from la_gazette_des_sorciers.regles_nettoyage import ConfigurationNettoyage

MAINTENANT = datetime(2026, 11, 12, 7, tzinfo=UTC)
REFERENCE = "s3://test-preprocess/json/flux.json"


@pytest.fixture(scope="module")
def moteur_postgres():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Définir TEST_DATABASE_URL pour les tests PostgreSQL")
    moteur = create_engine(url)
    yield moteur
    moteur.dispose()


@pytest.fixture
def bronze_stockage():
    fichier = Path(__file__).parent / "fixtures" / "bronze_preprocess.json"
    return json.loads(fichier.read_text(encoding="utf-8"))


@pytest.fixture
def base_test(moteur_postgres):
    # Les commits du chargeur deviennent des savepoints annulés à la fin du test.
    with moteur_postgres.connect() as connexion:
        transaction = connexion.begin()

        class MoteurTest:
            @contextmanager
            def begin(self):
                with connexion.begin_nested():
                    yield connexion

        yield MoteurTest(), connexion, stockage_silver.charger_tables(connexion)
        transaction.rollback()


def nombre(connexion, table):
    return connexion.scalar(select(func.count()).select_from(table))


def test_enregistrement_complet_et_execution_terminee(base_test, bronze_stockage):
    moteur, connexion, tables = base_test
    resultat = stockage_silver.nettoyer_en_base(
        [(REFERENCE, bronze_stockage)], maintenant=MAINTENANT, moteur=moteur
    )
    assert (len(resultat.articles_propres), len(resultat.rejets)) == (2, 5)
    execution_id = resultat.rapport["execution_id"]
    execution = (
        connexion.execute(
            select(tables["executions_silver"]).where(
                tables["executions_silver"].c.execution_id == execution_id
            )
        )
        .mappings()
        .one()
    )
    assert execution["statut"] == "termine"
    assert execution["fin"] >= execution["debut"]
    assert execution["version_regles"] == "v2"
    assert all(ligne["execution_id"] == execution_id for ligne in resultat.articles_propres)
    assert resultat.rejets[0]["regles_rejet"] == ["R01_publi", "R02_horoscope"]


def test_extrait_complet_enregistre_en_postgresql(base_test, bronze_stockage):
    moteur, connexion, tables = base_test
    extrait = "Un résumé détaillé. " * 80 + "Fin de l'extrait."
    bronze_stockage["content"]["rss"]["channel"]["item"][0]["description"] = f"<p>{extrait}</p>"
    resultat = stockage_silver.nettoyer_en_base(
        [(REFERENCE, bronze_stockage)], maintenant=MAINTENANT, moteur=moteur
    )
    articles = tables["articles_propres"]
    valeur = connexion.scalar(
        select(articles.c.extrait).where(
            articles.c.article_id == resultat.articles_propres[0]["article_id"]
        )
    )
    assert len(valeur) > 500
    assert valeur == extrait


def test_relance_sans_reinsertion_des_articles(base_test, bronze_stockage):
    moteur, connexion, tables = base_test
    premier = stockage_silver.nettoyer_en_base(
        [(REFERENCE, bronze_stockage)], maintenant=MAINTENANT, moteur=moteur
    )
    second = stockage_silver.nettoyer_en_base(
        [(REFERENCE, bronze_stockage)], maintenant=MAINTENANT, moteur=moteur
    )
    assert second.rapport["execution_id"] != premier.rapport["execution_id"]
    assert nombre(connexion, tables["articles_propres"]) == 2
    assert second.rapport["gardes"] == 0
    assert second.rapport["rejetes"] == 7
    assert second.rapport["qualite_validee"] is False


def test_erreur_insertion_annule_tous_les_resultats(base_test, bronze_stockage, monkeypatch):
    moteur, connexion, tables = base_test
    traiter = stockage_silver.traiter_documents

    def resultat_invalide(*args):
        resultat = traiter(*args)
        resultat.articles_propres[1]["titre"] = None
        return resultat

    monkeypatch.setattr(stockage_silver, "traiter_documents", resultat_invalide)
    with pytest.raises(IntegrityError):
        stockage_silver.nettoyer_en_base(
            [(REFERENCE, bronze_stockage)], maintenant=MAINTENANT, moteur=moteur
        )
    assert nombre(connexion, tables["articles_propres"]) == 0
    assert nombre(connexion, tables["rejets"]) == 0
    execution = connexion.execute(select(tables["executions_silver"])).mappings().one()
    assert execution["statut"] == "echec"
    assert execution["fin"] is not None


def test_erreur_bronze_est_tracee_en_echec(base_test):
    moteur, connexion, tables = base_test
    with pytest.raises(ValueError):
        stockage_silver.nettoyer_en_base([(REFERENCE, {})], maintenant=MAINTENANT, moteur=moteur)
    assert nombre(connexion, tables["articles_propres"]) == 0
    assert connexion.scalar(select(tables["executions_silver"].c.statut)) == "echec"


def test_controles_portent_sur_les_donnees_inserees(base_test, bronze_stockage, monkeypatch):
    moteur, _, _ = base_test
    traiter = stockage_silver.traiter_documents

    def resultat_modifie(*args):
        resultat = traiter(*args)
        resultat.articles_propres[0]["date_publication"] = datetime(2027, 1, 1, tzinfo=UTC)
        return resultat

    monkeypatch.setattr(stockage_silver, "traiter_documents", resultat_modifie)
    resultat = stockage_silver.nettoyer_en_base(
        [(REFERENCE, bronze_stockage)], maintenant=MAINTENANT, moteur=moteur
    )
    assert resultat.rapport["controles"]["aucune_date_future"] is False
    assert resultat.rapport["qualite_validee"] is False


def test_deux_chargements_concurrents_ne_dupliquent_pas(moteur_postgres, bronze_stockage):
    document = copy.deepcopy(bronze_stockage)
    identifiant = uuid4().hex
    document["source_id"] = f"concurrence_{identifiant}"
    document["content"]["rss"]["channel"]["item"] = [
        {
            "title": f"Concurrence PostgreSQL {identifiant}",
            "link": f"https://exemple.test/{identifiant}",
            "guid": identifiant,
            "pubDate": "2001-01-01T00:00:00Z",
        }
    ]

    def charger():
        return stockage_silver.nettoyer_en_base(
            [(REFERENCE, document)], ConfigurationNettoyage(), MAINTENANT, moteur=moteur_postgres
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(lambda _: charger(), range(2)))
    execution_ids = [resultat.rapport["execution_id"] for resultat in resultats]
    try:
        assert sorted(resultat.rapport["gardes"] for resultat in resultats) == [0, 1]
        assert sorted(resultat.rapport["rejetes"] for resultat in resultats) == [0, 1]
        with moteur_postgres.connect() as connexion:
            tables = stockage_silver.charger_tables(connexion)
            assert (
                connexion.scalar(
                    select(func.count())
                    .select_from(tables["articles_propres"])
                    .where(tables["articles_propres"].c.source_id == document["source_id"])
                )
                == 1
            )
    finally:
        with moteur_postgres.begin() as connexion:
            tables = stockage_silver.charger_tables(connexion)
            for nom in ("rejets", "articles_propres", "executions_silver"):
                table = tables[nom]
                connexion.execute(delete(table).where(table.c.execution_id.in_(execution_ids)))
