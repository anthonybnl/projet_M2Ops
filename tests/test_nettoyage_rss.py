from la_gazette_des_sorciers.nettoyage_rss import date_depuis_url, nettoyer_flux, parser_date


def flux(items, fetched_at="2026-10-21T08:00:00+00:00"):
    return {
        "source_id": "test",
        "fetched_at": fetched_at,
        "content": {"rss": {"channel": {"item": items}}},
    }


def test_parser_date_gmt_et_decalage():
    assert parser_date("Wed, 21 Oct 2026 06:59:49 GMT").isoformat() == "2026-10-21T06:59:49+00:00"
    assert parser_date("Wed, 21 Oct 2026 09:28:20 +0200").isoformat() == "2026-10-21T07:28:20+00:00"
    assert parser_date("n'importe quoi") is None


def test_un_seul_item_et_guid_dict():
    item = {
        "title": " Titre <b>gras</b> &amp; co ",
        "link": "https://exemple.fr/a",
        "guid": {"@isPermaLink": "true", "#text": "https://exemple.fr/a"},
        "pubDate": "Wed, 21 Oct 2026 09:28:20 +0200",
        "description": "<p>Texte</p>",
    }
    articles, stats = nettoyer_flux(flux(item))
    assert stats["total"] == 1
    assert articles[0]["title"] == "Titre gras & co"
    assert articles[0]["guid"] == "https://exemple.fr/a"
    assert articles[0]["description"] == "Texte"


def test_date_depuis_url_parisien():
    url = "https://www.leparisien.fr/sports/psg/titre-21-10-2026-5JRXKZY6JZHNHDAZRSKQLVZGUI.php"
    assert date_depuis_url(url).isoformat() == "2026-10-20T22:00:00+00:00"
    assert date_depuis_url("https://exemple.fr/sans-date") is None
    assert date_depuis_url("https://e.fr/t-99-99-2026-ABC.php") is None


def test_filtre_24h_invalides_et_origine_de_la_date():
    items = [
        {"title": "vieux", "link": "https://e.fr/1", "pubDate": "Mon, 05 Oct 2026 11:33:13 +0200"},
        {"title": "", "link": "https://e.fr/2"},
        {"title": "sans date", "link": "https://e.fr/3"},
        {"title": "ok", "link": "https://e.fr/4", "pubDate": "Wed, 21 Oct 2026 06:00:00 GMT"},
        {"title": "parisien", "link": "https://e.fr/t-21-10-2026-AB12.php"},
        {"title": "parisien vieux", "link": "https://e.fr/t-19-10-2026-AB12.php"},
    ]
    articles, stats = nettoyer_flux(flux(items))
    assert [(a["title"], a["date_source"]) for a in articles] == [
        ("sans date", "collecte"),
        ("ok", "pubDate"),
        ("parisien", "url"),
    ]
    assert articles[0]["published_at"] == "2026-10-21T08:00:00+00:00"
    assert stats == {
        "total": 6,
        "invalides": 1,
        "trop_vieux": 2,
        "date_url": 1,
        "date_collecte": 1,
    }
