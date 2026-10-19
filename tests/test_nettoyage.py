from datetime import timedelta

from la_gazette_des_sorciers.nettoyage import clean_document, strip_html

SOURCE = {"nom": "Test", "type": "PQN", "region": "France", "url": "http://x"}


def rss(*items):
    return {
        "source": SOURCE,
        "fetched_at": "2026-10-19T05:00:00+00:00",
        "feed": {"rss": {"channel": {"item": list(items)}}},
    }


def item(title, pub, link="http://x/1"):
    return {
        "title": title,
        "link": link,
        "description": "<p>Un &amp; deux</p>",
        "pubDate": pub,
        "author": "ignoré",
    }


def test_strip_html():
    assert strip_html("<p>Un &amp;\n  deux</p>") == "Un & deux"


def test_garde_les_articles_recents_et_les_champs_autorises():
    doc = rss(
        item("Récent", "Mon, 19 Oct 2026 04:00:00 +0000"),
        item("Ancien", "Fri, 16 Oct 2026 04:00:00 +0000", link="http://x/2"),
    )
    articles = clean_document(doc, timedelta(hours=24))
    assert [a["title"] for a in articles] == ["Récent"]
    assert articles[0]["summary"] == "Un & deux"
    assert "author" not in articles[0]


def test_flux_atom():
    doc = {
        "source": SOURCE,
        "fetched_at": "2026-10-19T05:00:00+00:00",
        "feed": {
            "feed": {
                "entry": {
                    "title": "Atom",
                    "link": {"@href": "http://x/a", "@rel": "alternate"},
                    "summary": "S",
                    "updated": "2026-10-19T03:00:00Z",
                }
            }
        },
    }
    assert clean_document(doc, timedelta(hours=24))[0]["link"] == "http://x/a"
