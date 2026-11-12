"""Nettoie les items bronze et prépare les lignes des tables silver."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from la_gazette_des_sorciers.normalisation import (
    extraire_texte,
    normaliser_date,
    normaliser_texte,
    normaliser_titre_comparaison,
    normaliser_url,
)
from la_gazette_des_sorciers.regles_nettoyage import (
    LIBELLES_REGLES,
    ConfigurationNettoyage,
    regles_exclusion,
    similarite_jaccard,
)


@dataclass
class ResultatNettoyage:
    articles_propres: list[dict]
    rejets: list[dict]
    rapport: dict


def extraire_items(document: dict) -> list[dict]:
    """Gère les flux RSS contenant zéro, une ou plusieurs entrées xmltodict."""
    try:
        canal = document["content"]["rss"]["channel"]
    except (KeyError, TypeError) as erreur:
        raise ValueError("Le document bronze ne contient pas de canal RSS") from erreur
    if not isinstance(canal, dict):
        raise ValueError("Le canal RSS doit être un objet")
    items = canal.get("item") or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Les entrées RSS doivent être des objets")
    return items


def construire_identifiant(item: dict, lien: str) -> str:
    guid = extraire_texte(item.get("guid")).strip()
    if guid:
        if guid.lower().startswith(("https://", "http://")):
            try:
                guid = normaliser_url(guid)
            except ValueError:
                return f"url:{lien}"
        return f"guid:{guid}"
    return f"url:{lien}"


def normaliser_item(item: dict, trace: dict, maintenant: datetime, url_source=""):
    titre = normaliser_texte(item.get("title"))
    extrait = normaliser_texte(item.get("description"))
    categories = normaliser_texte(item.get("category"))
    regles = regles_exclusion(titre, extrait, categories)
    if not titre:
        regles.append("R05_titre_vide")
    if "\ufffd" in titre or "\ufffd" in extrait:
        regles.append("R11_encodage")

    publication = None
    try:
        publication = normaliser_date(item.get("pubDate") or item.get("dc:date"))
    except ValueError:
        regles.append("R06_date_invalide")
    if publication and publication > maintenant:
        regles.append("R07_date_future")

    lien = ""
    try:
        lien = normaliser_url(item.get("link"), url_source)
    except ValueError:
        regles.append("R08_lien_invalide")

    article = {
        **trace,
        "identifiant_article": construire_identifiant(item, lien),
        "titre": titre,
        "extrait": extrait,
        "lien": lien,
        "date_publication": publication,
        "date_traitement": maintenant,
    }
    return article, regles


def rechercher_doublon(article: dict, precedents: list[dict], seuil: float) -> str | None:
    titre = normaliser_titre_comparaison(article["titre"])
    candidats_proches = []
    for precedent in precedents:
        meme_source = article["source_id"] == precedent["source_id"]
        if meme_source and (
            article["identifiant_article"] == precedent["identifiant_article"]
            or article["lien"] == precedent.get("lien")
        ):
            return "R09_doublon_exact"
        # Les comparaisons entre médias portent sur la même journée de publication UTC.
        if article["date_publication"].date() != precedent["date_publication"].date():
            continue
        if titre == normaliser_titre_comparaison(precedent["titre"]):
            return "R09_doublon_exact"
        candidats_proches.append(precedent)
    if any(
        similarite_jaccard(article["titre"], precedent["titre"]) >= seuil
        for precedent in candidats_proches
    ):
        return "R10_doublon_proche"
    return None


def produire_rapport(articles, rejets, volumes, maintenant, configuration) -> dict:
    par_source = {}
    par_regle = Counter()
    for source_id, nombre in sorted(volumes.items()):
        gardes = sum(article["source_id"] == source_id for article in articles)
        ecartes = [rejet for rejet in rejets if rejet["source_id"] == source_id]
        regles_source = Counter(regle for rejet in ecartes for regle in set(rejet["regles_rejet"]))
        par_source[source_id] = {
            "entres": nombre,
            "gardes": gardes,
            "rejetes": len(ecartes),
            "taux_rejet": len(ecartes) / nombre if nombre else 0.0,
            "par_regle": dict(sorted(regles_source.items())),
        }
        par_regle.update(regles_source)
    controles = {
        "titres_non_vides": all(article["titre"].strip() for article in articles),
        "aucune_date_future": all(
            article["date_publication"] <= maintenant for article in articles
        ),
        "volumes_non_vides": bool(volumes) and all(nombre > 0 for nombre in volumes.values()),
        "taux_rejet_par_source": all(
            source["taux_rejet"] <= configuration.taux_rejet_max for source in par_source.values()
        ),
    }
    return {
        "date_execution": maintenant.isoformat(),
        "version_regles": configuration.version,
        "parametres": {
            "seuil_jaccard": configuration.seuil_jaccard,
            "taux_rejet_max": configuration.taux_rejet_max,
        },
        "entres": sum(volumes.values()),
        "gardes": len(articles),
        "rejetes": len(rejets),
        "par_source": par_source,
        "par_regle": dict(sorted(par_regle.items())),
        "cinq_rejets_frequents": [
            {"regle": regle, "nombre": nombre}
            for regle, nombre in sorted(
                par_regle.items(), key=lambda element: (-element[1], element[0])
            )[:5]
        ],
        "controles": controles,
        "qualite_validee": all(controles.values()),
    }


def produire_rapport_par_regle(rapport: dict) -> dict:
    """Présente les compteurs d'un passage par règle, y compris celles à zéro."""
    comptes = rapport["par_regle"]
    par_regle = {}
    for regle in sorted(LIBELLES_REGLES.keys() | comptes.keys()):
        nombre = comptes.get(regle, 0)
        sources = {
            source: chiffres["par_regle"][regle]
            for source, chiffres in sorted(rapport["par_source"].items())
            if chiffres["par_regle"].get(regle, 0) > 0
        }
        par_regle[regle] = {
            "libelle": LIBELLES_REGLES.get(regle, "Règle non répertoriée"),
            "rejetes": nombre,
            "taux_sur_entres": nombre / rapport["entres"] if rapport["entres"] else 0.0,
            "part_des_rejets": nombre / rapport["rejetes"] if rapport["rejetes"] else 0.0,
            "par_source": sources,
        }
    metadonnees = {
        cle: rapport[cle]
        for cle in ("execution_id", "date_execution", "version_regles", "parametres")
        if cle in rapport
    }
    return {
        **metadonnees,
        "entres": rapport["entres"],
        "gardes": rapport["gardes"],
        "rejetes": rapport["rejetes"],
        "declenchements_regles": sum(comptes.values()),
        "par_regle": par_regle,
        "cinq_rejets_frequents": rapport["cinq_rejets_frequents"],
    }


def traiter_documents(
    documents,
    configuration: ConfigurationNettoyage | None = None,
    maintenant: datetime | None = None,
    articles_existants=(),
) -> ResultatNettoyage:
    """Retourne des lignes silver sans modifier les documents ni effectuer d'I/O."""
    configuration = configuration or ConfigurationNettoyage()
    maintenant = normaliser_date(maintenant or datetime.now(UTC))
    articles, rejets = [], []
    precedents = list(articles_existants)
    volumes = Counter()
    references = set()
    for reference, document in documents:
        if not isinstance(document, dict):
            raise ValueError(f"Le document bronze doit être un objet : {reference}")
        if not reference or reference in references:
            raise ValueError(f"Référence bronze vide ou répétée : {reference}")
        references.add(reference)
        source_id = document.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"source_id absent dans {reference}")
        collecte = normaliser_date(document.get("fetched_at"))
        items = extraire_items(document)
        volumes[source_id] += len(items)
        for position, item in enumerate(items, start=1):
            trace = {
                "source_id": source_id,
                "reference_bronze": reference,
                "position_item": position,
                "date_collecte": collecte,
            }
            article, regles = normaliser_item(
                item, trace, maintenant, document.get("source_url", "")
            )
            if not regles:
                doublon = rechercher_doublon(article, precedents, configuration.seuil_jaccard)
                if doublon:
                    regles.append(doublon)
            if regles:
                rejets.append(
                    {
                        **trace,
                        "regles_rejet": list(dict.fromkeys(regles)),
                        "date_traitement": maintenant,
                    }
                )
            else:
                articles.append(article)
                precedents.append(article)
    rapport = produire_rapport(articles, rejets, volumes, maintenant, configuration)
    return ResultatNettoyage(articles, rejets, rapport)
