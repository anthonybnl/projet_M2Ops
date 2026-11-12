"""Paramètres et règles lisibles du premier traitement bronze vers silver."""

import re
from dataclasses import dataclass

from la_gazette_des_sorciers.normalisation import normaliser_titre_comparaison


@dataclass(frozen=True)
class ConfigurationNettoyage:
    version: str = "v2"
    seuil_jaccard: float = 0.85
    taux_rejet_max: float = 0.80

    def __post_init__(self):
        if not self.version.strip():
            raise ValueError("La version des règles doit être renseignée")
        if not 0 < self.seuil_jaccard <= 1 or not 0 <= self.taux_rejet_max <= 1:
            raise ValueError("Les seuils doivent être compris entre 0 et 1")


LIBELLES_REGLES = {
    "R01_publi": "Contenu partenaire ou promotionnel",
    "R02_horoscope": "Horoscope ou astrologie",
    "R03_programme_tv": "Programme TV",
    "R04_jeux_concours": "Jeu ou concours",
    "R05_titre_vide": "Titre vide après normalisation",
    "R06_date_invalide": "Date absente, invalide ou sans fuseau",
    "R07_date_future": "Date de publication future",
    "R08_lien_invalide": "Lien absent ou invalide",
    "R09_doublon_exact": "Doublon exact",
    "R10_doublon_proche": "Titre proche d'un article déjà retenu",
    "R11_encodage": "Caractère de remplacement restant après normalisation",
}


REGLES_CONTENU = (
    (
        "R01_publi",
        r"\b(publi reportage|publireportage|contenu partenaire|contenus partenaires|"
        r"article sponsorise|en partenariat avec)\b",
        True,
    ),
    ("R02_horoscope", r"\b(horoscope|horoscopes|astrologie)\b", False),
    ("R03_programme_tv", r"\b(programme tv|programmes tv|programme tele|programmes tele)\b", False),
    (
        "R04_jeux_concours",
        r"\b(jeu concours|jeux concours|mots fleches|mots croises|sudoku)\b",
        False,
    ),
)


def regles_exclusion(titre: str, extrait: str, categories: str = "") -> list[str]:
    rubrique = normaliser_titre_comparaison(f"{titre} {categories}")
    texte_complet = f"{rubrique} {normaliser_titre_comparaison(extrait)}"
    return [
        identifiant
        for identifiant, motif, inclure_extrait in REGLES_CONTENU
        if re.search(motif, texte_complet if inclure_extrait else rubrique)
    ]


def similarite_jaccard(titre_a: str, titre_b: str) -> float:
    mots_a = set(normaliser_titre_comparaison(titre_a).split())
    mots_b = set(normaliser_titre_comparaison(titre_b).split())
    union = mots_a | mots_b
    return len(mots_a & mots_b) / len(union) if union else 0.0
