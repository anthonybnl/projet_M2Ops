from datetime import UTC, datetime

import pytest

from la_gazette_des_sorciers.normalisation import (
    extraire_texte,
    normaliser_date,
    normaliser_espaces,
    normaliser_texte,
    normaliser_titre_comparaison,
    normaliser_url,
    reparer_encodage,
    supprimer_html,
)


@pytest.mark.parametrize(
    "valeur,attendu",
    [
        (None, ""),
        ({"@isPermaLink": "false", "#text": "article-123"}, "article-123"),
        (["Actualité", {"#text": "France"}], "Actualité France"),
        ({"@attribut": "sans texte"}, ""),
    ],
)
def test_extraire_texte(valeur, attendu):
    assert extraire_texte(valeur) == attendu


@pytest.mark.parametrize(
    "texte,attendu",
    [
        ("Un cafÃ© à Paris", "Un café à Paris"),
        ("François et cafÃ©", "François et café"),
        ("Lâ€™actualité", "L’actualité"),
        ("Âge et santé", "Âge et santé"),
    ],
)
def test_reparer_encodage(texte, attendu):
    assert reparer_encodage(texte) == attendu


def test_supprimer_html_ignore_scripts_et_preserve_separation():
    texte = supprimer_html("<p>Bonjour</p><p>Monde</p><script>secret()</script>")
    assert normaliser_espaces(texte) == "Bonjour Monde"


def test_normaliser_espaces():
    assert normaliser_espaces(" \tUn\u00a0titre\navec\u200b espaces ") == "Un titre avec espaces"


def test_normaliser_texte_entites_et_encodage():
    assert normaliser_texte("&lt;b&gt;Un cafÃ©&lt;/b&gt; &amp; du thé") == "Un café & du thé"


@pytest.mark.parametrize(
    "valeur",
    [
        "Thu, 12 Nov 2026 08:00:00 +0200",
        "2026-11-12T07:00:00+01:00",
        datetime(2026, 11, 12, 6, tzinfo=UTC),
    ],
)
def test_normaliser_date_utc(valeur):
    assert normaliser_date(valeur) == datetime(2026, 11, 12, 6, tzinfo=UTC)


@pytest.mark.parametrize("valeur", [None, "", "date inconnue", "2026-11-12T06:00:00"])
def test_date_absente_invalide_ou_sans_fuseau(valeur):
    with pytest.raises(ValueError):
        normaliser_date(valeur)


def test_normaliser_url_conserve_parametres_metier():
    assert normaliser_url("HTTPS://EXEMPLE.TEST:443/article?utm_source=rss&id=12#suivi") == (
        "https://exemple.test/article?id=12"
    )
    assert normaliser_url("/article", "https://exemple.test/rss") == "https://exemple.test/article"


@pytest.mark.parametrize(
    "url", ["", "javascript:alert(1)", "ftp://exemple.test/a", "https://a:b@site.test"]
)
def test_refuser_liens_invalides(url):
    with pytest.raises(ValueError):
        normaliser_url(url)


def test_comparaison_titres_ignore_casse_accents_ponctuation():
    assert normaliser_titre_comparaison("ÉCOLES : une réouverture !") == "ecoles une reouverture"
