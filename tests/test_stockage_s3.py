import json
from datetime import UTC, date, datetime
from importlib import import_module
from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from la_gazette_des_sorciers.stockage_s3 import connecter_bronze, deposer_bronze, fichiers_bronze


class FauxS3:
    def __init__(self, bucket_existe=False, erreur=None):
        self.bucket_existe = bucket_existe
        self.erreur = erreur
        self.buckets_crees = []
        self.objets = {}
        self.nb_upload_file = 0

    def head_bucket(self, Bucket):
        if self.erreur:
            raise ClientError({"Error": {"Code": self.erreur}}, "HeadBucket")
        if not self.bucket_existe:
            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def create_bucket(self, **kwargs):
        self.buckets_crees.append(kwargs)
        self.bucket_existe = True

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objets[(Bucket, Key)] = (Body, ContentType)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        cles = sorted(
            cle for bucket, cle in self.objets if bucket == Bucket and cle.startswith(Prefix)
        )
        return {"Contents": [{"Key": cle} for cle in cles], "IsTruncated": False}

    def get_object(self, Bucket, Key):
        return {"Body": BytesIO(self.objets[(Bucket, Key)][0])}

    def upload_file(self, filename, bucket, key, ExtraArgs):
        self.nb_upload_file += 1
        with open(filename, "rb") as fichier:
            self.objets[(bucket, key)] = (fichier.read(), ExtraArgs["ContentType"])


def test_depot_des_trois_fichiers_bronze(tmp_path):
    xml_dir = tmp_path / "xml" / "2026-10-21"
    json_dir = tmp_path / "json" / "2026-10-21"
    xml_dir.mkdir(parents=True)
    json_dir.mkdir(parents=True)
    (xml_dir / "flux.xml").write_bytes(b"<rss>brut</rss>")
    (xml_dir / "flux.json").write_bytes(b'{"filepath":"C:/local/flux.xml"}')
    (json_dir / "flux.json").write_bytes(b'{"content":{"rss":"brut"}}')
    (json_dir / "notes.txt").write_text("hors collecte")

    client = FauxS3()
    nombre = deposer_bronze(tmp_path, client, "gazette-bronze")

    assert nombre == 3
    assert client.buckets_crees == [{"Bucket": "gazette-bronze"}]
    assert client.objets == {
        ("gazette-bronze", "xml/2026-10-21/flux.xml"): (
            b"<rss>brut</rss>",
            "application/xml",
        ),
        ("gazette-bronze", "xml/2026-10-21/flux.json"): (
            b'{"filepath":"C:/local/flux.xml"}',
            "application/json",
        ),
        ("gazette-bronze", "json/2026-10-21/flux.json"): (
            b'{"content":{"rss":"brut"}}',
            "application/json",
        ),
    }


def test_filtre_par_jour_et_bucket_existant(tmp_path):
    for jour in ("2026-10-20", "2026-10-21"):
        dossier = tmp_path / "xml" / jour
        dossier.mkdir(parents=True)
        (dossier / "flux.xml").write_bytes(jour.encode())

    assert [cle for _, cle in fichiers_bronze(tmp_path, date(2026, 10, 21))] == [
        "xml/2026-10-21/flux.xml"
    ]
    client = FauxS3(bucket_existe=True)
    assert deposer_bronze(tmp_path, client, "gazette-bronze", jour=date(2026, 10, 21)) == 1
    assert client.buckets_crees == []


def test_erreur_acces_bucket_remontee(tmp_path):
    dossier = tmp_path / "xml" / "2026-10-21"
    dossier.mkdir(parents=True)
    (dossier / "flux.xml").write_bytes(b"<rss/>")

    with pytest.raises(ClientError):
        deposer_bronze(tmp_path, FauxS3(erreur="403"), "gazette-bronze")


def test_aucun_fichier_ne_cree_pas_de_bucket(tmp_path):
    client = FauxS3()
    with pytest.raises(FileNotFoundError):
        deposer_bronze(tmp_path, client, "gazette-bronze")
    assert client.buckets_crees == []


def test_pipeline_s3_sans_dossier_local(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCES_FILE", str(tmp_path / "sources.csv"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    collecte_xml = import_module("la_gazette_des_sorciers.collecte_xml")
    collecte_json = import_module("la_gazette_des_sorciers.collecte_json")
    monkeypatch.setattr(collecte_xml, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collecte_json, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collecte_xml, "XML_DATA_DIR", tmp_path / "xml")
    monkeypatch.setattr(collecte_json, "JSON_DATA_DIR", tmp_path / "json")

    client = FauxS3()
    instant = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
    collecte_xml.stocker(
        b"<rss><channel><title>demo</title></channel></rss>",
        "demo",
        "url",
        instant,
        200,
        client,
        "gazette-bronze",
        "us-east-1",
    )
    cles = collecte_json.recuperer_fichiers_metadonnees(client, "gazette-bronze")
    assert cles == ["xml/2026-10-21/2026-10-21T08-00-00+00-00_demo.json"]
    collecte_json.traiter_fichier(cles[0], client, "gazette-bronze", "us-east-1")
    assert set(client.objets) == {
        ("gazette-bronze", f"{dossier}/2026-10-21/2026-10-21T08-00-00+00-00_demo.{extension}")
        for dossier, extension in (("xml", "xml"), ("xml", "json"), ("json", "json"))
    }
    assert not (tmp_path / "xml").exists()
    assert not (tmp_path / "json").exists()
    resultat = json.loads(
        client.objets[("gazette-bronze", "json/2026-10-21/2026-10-21T08-00-00+00-00_demo.json")][0]
    )
    assert resultat["content"]["rss"]["channel"]["title"] == "demo"
    assert resultat["s3_key"] == "xml/2026-10-21/2026-10-21T08-00-00+00-00_demo.xml"
    assert "filepath" not in resultat
    assert client.nb_upload_file == 0


def test_json_s3_convertit_anciens_fichiers_transferes_depuis_data(tmp_path):
    dossier = tmp_path / "xml" / "2026-10-21"
    dossier.mkdir(parents=True)
    (dossier / "flux.xml").write_bytes(b"<rss>ancien</rss>")
    (dossier / "flux.json").write_text(
        json.dumps(
            {
                "source_id": "demo",
                "fetched_at": "2026-10-21T08:00:00+00:00",
                "filepath": str(dossier / "flux.xml"),
            }
        ),
        encoding="utf-8",
    )
    client = FauxS3()
    assert deposer_bronze(tmp_path, client, "gazette-bronze") == 2

    collecte_json = import_module("la_gazette_des_sorciers.collecte_json")
    collecte_json.traiter_fichier("xml/2026-10-21/flux.json", client, "gazette-bronze", "us-east-1")

    cle_json = ("gazette-bronze", "json/2026-10-21/2026-10-21T08-00-00+00-00_demo.json")
    resultat = json.loads(client.objets[cle_json][0])
    assert resultat["content"]["rss"] == "ancien"
    assert resultat["s3_key"] == "xml/2026-10-21/flux.xml"
    assert "filepath" not in resultat


def test_mode_s3_ne_cree_pas_de_fichier_si_bucket_indisponible(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCES_FILE", str(tmp_path / "sources.csv"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    collecte_xml = import_module("la_gazette_des_sorciers.collecte_xml")
    monkeypatch.setattr(collecte_xml, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collecte_xml, "XML_DATA_DIR", tmp_path / "xml")

    with pytest.raises(ClientError):
        collecte_xml.stocker(
            b"<rss/>",
            "demo",
            "url",
            datetime(2026, 10, 21, 8, 0, tzinfo=UTC),
            200,
            FauxS3(erreur="403"),
            "gazette-bronze",
            "us-east-1",
        )

    assert not (tmp_path / "xml").exists()


def test_collecte_locale_sans_bucket(tmp_path, monkeypatch):
    monkeypatch.setenv("S3_ENABLED", "false")
    assert connecter_bronze() == (None, None, None)

    collecte_xml = import_module("la_gazette_des_sorciers.collecte_xml")
    collecte_json = import_module("la_gazette_des_sorciers.collecte_json")
    monkeypatch.setattr(collecte_xml, "XML_DATA_DIR", tmp_path / "xml")
    monkeypatch.setattr(collecte_json, "JSON_DATA_DIR", tmp_path / "json")

    collecte_xml.stocker(
        b"<rss/>",
        "demo",
        "url",
        datetime(2026, 10, 21, 8, 0, tzinfo=UTC),
        200,
        None,
        None,
        None,
    )
    metadata_path = next((tmp_path / "xml").rglob("*.json"))
    collecte_json.traiter_fichier(metadata_path, None, None, None)

    assert len(list((tmp_path / "xml").rglob("*.xml"))) == 1
    assert len(list((tmp_path / "json").rglob("*.json"))) == 1
