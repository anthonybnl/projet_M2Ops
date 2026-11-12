import copy
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from la_gazette_des_sorciers import nettoyage
from la_gazette_des_sorciers.nettoyage import main
from la_gazette_des_sorciers.preprocess import (
    construire_identifiant,
    extraire_items,
    produire_rapport_par_regle,
    traiter_documents,
)
from la_gazette_des_sorciers.regles_nettoyage import (
    LIBELLES_REGLES,
    ConfigurationNettoyage,
    regles_exclusion,
    similarite_jaccard,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bronze_preprocess.json"
MAINTENANT = datetime(2026, 11, 12, 7, tzinfo=UTC)
REFERENCE = "s3://bronze-test/json/2026-11-12/source.json"


@pytest.fixture
def bronze():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def base_simulee(monkeypatch):
    passages = []

    def enregistrer(documents, configuration, maintenant):
        resultat = traiter_documents(documents, configuration, maintenant)
        resultat.rapport["execution_id"] = 101
        passages.append(resultat)
        return resultat

    monkeypatch.setattr(nettoyage, "nettoyer_en_base", enregistrer)
    return passages


def test_resultats_compatibles_schema_et_bronze_preserve(bronze):
    original = copy.deepcopy(bronze)
    resultat = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)
    assert bronze == original
    assert len(resultat.articles_propres) == 2
    assert len(resultat.rejets) == 5
    article = resultat.articles_propres[0]
    assert article["titre"] == "Une nouvelle liaison ferroviaire"
    assert article["extrait"] == "Le café & les voyageurs."
    assert article["identifiant_article"] == "guid:train-1"
    assert article["position_item"] == 1
    assert article["reference_bronze"] == REFERENCE
    assert article["date_collecte"].tzinfo is UTC
    assert set(article) == {
        "source_id",
        "reference_bronze",
        "position_item",
        "date_collecte",
        "identifiant_article",
        "titre",
        "extrait",
        "lien",
        "date_publication",
        "date_traitement",
    }
    assert set(resultat.rejets[0]) == {
        "source_id",
        "reference_bronze",
        "position_item",
        "date_collecte",
        "regles_rejet",
        "date_traitement",
    }
    assert resultat.articles_propres[1]["identifiant_article"] == (
        "url:https://exemple.test/bibliotheques"
    )


def test_rapport_compte_items_et_regles_separement(bronze):
    resultat = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)
    rapport = resultat.rapport
    assert (rapport["entres"], rapport["gardes"], rapport["rejetes"]) == (7, 2, 5)
    assert sum(rapport["par_regle"].values()) == 6
    assert resultat.rejets[0]["regles_rejet"] == ["R01_publi", "R02_horoscope"]
    assert rapport["par_source"]["source_test"]["rejetes"] == 5
    assert rapport["qualite_validee"] is True


def test_rapport_par_regle_detaille_rejets_et_sources(bronze):
    rapport = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT).rapport
    rapport["execution_id"] = 101
    original = copy.deepcopy(rapport)
    par_regle = produire_rapport_par_regle(rapport)
    assert rapport == original
    assert par_regle["execution_id"] == 101
    assert par_regle["version_regles"] == rapport["version_regles"]
    assert (par_regle["entres"], par_regle["gardes"], par_regle["rejetes"]) == (7, 2, 5)
    assert par_regle["declenchements_regles"] == 6
    assert set(par_regle["par_regle"]) == set(LIBELLES_REGLES)
    regle = par_regle["par_regle"]["R01_publi"]
    assert regle["rejetes"] == 1
    assert regle["taux_sur_entres"] == pytest.approx(1 / 7)
    assert regle["part_des_rejets"] == pytest.approx(1 / 5)
    assert regle["par_source"] == {"source_test": 1}
    assert par_regle["par_regle"]["R03_programme_tv"]["rejetes"] == 0
    assert par_regle["par_regle"]["R03_programme_tv"]["par_source"] == {}


def test_rapport_par_regle_sans_entrees():
    rapport = traiter_documents([], maintenant=MAINTENANT).rapport
    par_regle = produire_rapport_par_regle(rapport)
    assert par_regle["declenchements_regles"] == 0
    for regle in par_regle["par_regle"].values():
        assert regle["rejetes"] == 0
        assert regle["taux_sur_entres"] == 0.0
        assert regle["part_des_rejets"] == 0.0


def test_rapport_par_regle_conserve_regles_historiques_et_plusieurs_sources(bronze):
    rapport = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT).rapport
    rapport["par_regle"]["ancienne_regle"] = 3
    rapport["par_source"]["source_test"]["par_regle"]["ancienne_regle"] = 1
    rapport["par_source"]["autre_source"] = {"par_regle": {"ancienne_regle": 2}}
    regle = produire_rapport_par_regle(rapport)["par_regle"]["ancienne_regle"]
    assert regle["rejetes"] == 3
    assert regle["par_source"] == {"autre_source": 2, "source_test": 1}


@pytest.mark.parametrize(
    "titre,regle",
    [
        ("Contenu partenaire : actualité", "R01_publi"),
        ("Horoscope du jeudi", "R02_horoscope"),
        ("Les programmes TV de ce soir", "R03_programme_tv"),
        ("Jeu concours du mois", "R04_jeux_concours"),
    ],
)
def test_regles_exclusion(titre, regle):
    assert regle in regles_exclusion(titre, "")


def test_mention_jeux_dans_extrait_ne_suffit_pas():
    assert regles_exclusion("Une réforme de l'éducation", "Une étude des jeux concours") == []


def test_date_absente_et_future_sont_rejetees(bronze):
    resultat = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)
    par_position = {rejet["position_item"]: rejet["regles_rejet"] for rejet in resultat.rejets}
    assert par_position[5] == ["R06_date_invalide"]
    assert par_position[6] == ["R07_date_future"]
    assert par_position[7] == ["R05_titre_vide"]


@pytest.mark.parametrize(
    "champ,valeur,regle",
    [
        ("title", "<b> </b>", "R05_titre_vide"),
        ("link", "javascript:alert(1)", "R08_lien_invalide"),
        ("title", "Actualit\ufffd du jour", "R11_encodage"),
    ],
)
def test_item_inexploitable_est_classe_comme_rejet(bronze, champ, valeur, regle):
    item = bronze["content"]["rss"]["channel"]["item"][0]
    item[champ] = valeur
    bronze["content"]["rss"]["channel"]["item"] = [item]
    resultat = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)
    assert resultat.articles_propres == []
    assert regle in resultat.rejets[0]["regles_rejet"]


def test_doublon_approximatif_et_inter_sources(bronze):
    premiere = bronze["content"]["rss"]["channel"]["item"][0]
    premiere["title"] = "Le gouvernement annonce une nouvelle mesure pour les transports"
    bronze["content"]["rss"]["channel"]["item"] = [premiere]
    autre = copy.deepcopy(bronze)
    autre["source_id"] = "autre_source"
    item = autre["content"]["rss"]["channel"]["item"][0]
    item["title"] += " publics"
    item["guid"] = "autre-article"
    item["link"] = "https://autre.test/article"
    assert similarite_jaccard(premiere["title"], item["title"]) > 0.85
    resultat = traiter_documents(
        [(REFERENCE, bronze), (REFERENCE + "-2", autre)], maintenant=MAINTENANT
    )
    assert len(resultat.articles_propres) == 1
    assert resultat.rejets[0]["regles_rejet"] == ["R10_doublon_proche"]


def test_identite_deja_connue_dans_une_execution_precedente(bronze):
    premier = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)
    second = traiter_documents(
        [(REFERENCE, bronze)], maintenant=MAINTENANT, articles_existants=premier.articles_propres
    )
    assert second.articles_propres == []
    assert sum("R09_doublon_exact" in rejet["regles_rejet"] for rejet in second.rejets) == 3


def test_doublon_exact_prioritaire_sur_un_titre_proche(bronze):
    item = bronze["content"]["rss"]["channel"]["item"][0]
    item["title"] = "Le gouvernement annonce une nouvelle mesure pour les transports"
    bronze["content"]["rss"]["channel"]["item"] = [item]
    article = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT).articles_propres[0]
    proche = dict(article, source_id="autre", titre=article["titre"] + " publics")
    exact = dict(article, titre="Ancien titre de cet article")
    resultat = traiter_documents(
        [(REFERENCE, bronze)], maintenant=MAINTENANT, articles_existants=[proche, exact]
    )
    assert resultat.rejets[0]["regles_rejet"] == ["R09_doublon_exact"]


def test_item_unique_et_flux_vide(bronze):
    item = bronze["content"]["rss"]["channel"]["item"][0]
    bronze["content"]["rss"]["channel"]["item"] = item
    assert extraire_items(bronze) == [item]
    bronze["content"]["rss"]["channel"].pop("item")
    resultat = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)
    assert resultat.rapport["entres"] == 0
    assert resultat.rapport["controles"]["volumes_non_vides"] is False


def test_metadonnees_invalides_echouent_explicitement(bronze):
    bronze.pop("source_id")
    with pytest.raises(ValueError, match="source_id"):
        traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)


def test_taux_de_rejet_declenche_un_controle(bronze):
    resultat = traiter_documents(
        [(REFERENCE, bronze)], ConfigurationNettoyage(taux_rejet_max=0.5), MAINTENANT
    )
    assert resultat.rapport["qualite_validee"] is False
    assert resultat.rapport["controles"]["taux_rejet_par_source"] is False


def test_identifiant_sans_guid_et_guid_url():
    assert construire_identifiant({}, "https://exemple.test/a") == "url:https://exemple.test/a"
    assert (
        construire_identifiant(
            {"guid": {"#text": "https://exemple.test/a?utm_source=rss"}}, "https://exemple.test/a"
        )
        == "guid:https://exemple.test/a"
    )


def test_cli_enregistre_en_base_et_archive_les_deux_rapports(tmp_path, base_simulee):
    rapport = tmp_path / "qualite.json"
    arguments = [
        "--fichier",
        str(FIXTURE),
        "--maintenant",
        MAINTENANT.isoformat(),
        "--rapport",
        str(rapport),
    ]
    assert main(arguments) == 0
    assert len(base_simulee[0].articles_propres) == 2
    assert len(base_simulee[0].rejets) == 5
    rapport_regles = tmp_path / "qualite-par-regle.json"
    assert set(tmp_path.iterdir()) == {rapport, rapport_regles}
    assert json.loads(rapport.read_text(encoding="utf-8"))["entres"] == 7
    assert json.loads(rapport.read_text(encoding="utf-8"))["execution_id"] == 101
    contenu_regles = json.loads(rapport_regles.read_text(encoding="utf-8"))
    assert contenu_regles["execution_id"] == 101
    assert contenu_regles["par_regle"]["R06_date_invalide"]["par_source"] == {"source_test": 1}
    assert main([*arguments, "--taux-rejet-max", "0.1"]) == 2


def test_cli_chemins_rapports_par_defaut(tmp_path, base_simulee, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--fichier", str(FIXTURE), "--maintenant", MAINTENANT.isoformat()]) == 0
    assert {chemin.name for chemin in (tmp_path / "rapports").iterdir()} == {
        "qualite-2026-11-12-execution-101.json",
        "qualite-2026-11-12-execution-101-par-regle.json",
    }


def test_cli_chemin_personnalise_rapport_regles(tmp_path, base_simulee):
    rapport_regles = tmp_path / "regles" / "bilan.json"
    assert (
        main(
            [
                "--fichier",
                str(FIXTURE),
                "--maintenant",
                MAINTENANT.isoformat(),
                "--rapport",
                str(tmp_path / "sources.json"),
                "--rapport-regles",
                str(rapport_regles),
            ]
        )
        == 0
    )
    assert json.loads(rapport_regles.read_text(encoding="utf-8"))["execution_id"] == 101


@pytest.mark.parametrize("collision", ["rapports", "bronze", "derive"])
def test_cli_refuse_collisions_rapport_regles_avant_stockage(tmp_path, base_simulee, collision):
    bronze = tmp_path / "qualite-par-regle.json"
    contenu = FIXTURE.read_bytes()
    bronze.write_bytes(contenu)
    rapport = tmp_path / "qualite.json"
    arguments = ["--fichier", str(bronze), "--rapport", str(rapport)]
    if collision == "rapports":
        arguments.extend(["--rapport-regles", str(rapport)])
    elif collision == "bronze":
        arguments.extend(["--rapport-regles", str(bronze)])
    assert main(arguments) == 1
    assert base_simulee == []
    assert bronze.read_bytes() == contenu
    assert not rapport.exists()


def test_cli_fichier_absent_ne_produit_pas_de_rapport(tmp_path, base_simulee):
    rapport = tmp_path / "qualite.json"
    assert main(["--fichier", str(tmp_path / "absent.json"), "--rapport", str(rapport)]) == 1
    assert not rapport.exists()
    assert base_simulee == []


def test_cli_preserve_le_fichier_bronze(tmp_path):
    fichier = tmp_path / "bronze.json"
    contenu = FIXTURE.read_bytes()
    fichier.write_bytes(contenu)
    assert main(["--fichier", str(fichier), "--rapport", str(fichier)]) == 1
    assert fichier.read_bytes() == contenu


def test_cli_signale_un_rapport_impossible_apres_enregistrement(tmp_path, base_simulee):
    assert (
        main(
            [
                "--fichier",
                str(FIXTURE),
                "--maintenant",
                MAINTENANT.isoformat(),
                "--rapport",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert len(base_simulee) == 1


def test_lecture_s3_trace_objet_et_ferme_flux(monkeypatch, bronze):
    flux = io.BytesIO(json.dumps(bronze).encode("utf-8"))

    class ClientS3:
        def get_object(self, Bucket, Key):
            assert (Bucket, Key) == ("bronze-test", "json/flux.json")
            return {"Body": flux}

    monkeypatch.setattr(nettoyage, "connecter_bronze", lambda: (ClientS3(), "bronze-test", ""))
    monkeypatch.setattr(
        nettoyage, "lister_fichiers_s3", lambda *_: ["json/flux.json", "json/autre.txt"]
    )
    documents = list(nettoyage.lire_s3("json/"))
    assert documents == [("s3://bronze-test/json/flux.json", bronze)]
    assert flux.closed


def test_guid_url_invalide_utilise_le_lien():
    assert construire_identifiant({"guid": "http://"}, "https://exemple.test/a") == (
        "url:https://exemple.test/a"
    )


def test_parametres_effectifs_dans_rapport(bronze):
    configuration = ConfigurationNettoyage(version="v2", seuil_jaccard=0.95)
    resultat = traiter_documents([(REFERENCE, bronze)], configuration, MAINTENANT)
    assert resultat.rapport["version_regles"] == "v2"
    assert resultat.rapport["parametres"]["seuil_jaccard"] == 0.95


def test_extrait_complet_conserve_au_dela_de_500_caracteres(bronze):
    extrait = "Un résumé détaillé. " * 80 + "Fin de l'extrait."
    item = bronze["content"]["rss"]["channel"]["item"][0]
    item["description"] = f"<p>{extrait}</p>"
    bronze["content"]["rss"]["channel"]["item"] = [item]
    resultat = traiter_documents([(REFERENCE, bronze)], maintenant=MAINTENANT)
    assert len(resultat.articles_propres[0]["extrait"]) > 500
    assert resultat.articles_propres[0]["extrait"] == extrait
