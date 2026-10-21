import os
import subprocess
import sys
from pathlib import Path


def test_chemins_env_resolus_depuis_la_racine_du_projet(tmp_path):
    (tmp_path / ".env").write_text(
        "SOURCES_FILE=./sources.csv\nDATA_DIR=./data\n", encoding="utf-8"
    )
    sous_dossier = tmp_path / "src" / "la_gazette_des_sorciers"
    sous_dossier.mkdir(parents=True)

    dossier_scripts = Path(__file__).resolve().parents[1] / "src" / "la_gazette_des_sorciers"
    environnement = os.environ.copy()
    environnement.pop("SOURCES_FILE", None)
    environnement.pop("DATA_DIR", None)
    environnement.update(
        {
            "PROJET_TEST": str(tmp_path),
            "COLLECTE_XML_TEST": str(dossier_scripts / "collecte_xml.py"),
            "COLLECTE_JSON_TEST": str(dossier_scripts / "collecte_json.py"),
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(dossier_scripts), environnement.get("PYTHONPATH")))
            ),
        }
    )
    code = """
import os
import runpy
from pathlib import Path

projet = Path(os.environ["PROJET_TEST"])
xml = runpy.run_path(os.environ["COLLECTE_XML_TEST"], run_name="configuration_test")
json = runpy.run_path(os.environ["COLLECTE_JSON_TEST"], run_name="configuration_test")
assert xml["SOURCES_FILE"] == projet / "sources.csv"
assert xml["DATA_DIR"] == projet / "data"
assert json["DATA_DIR"] == projet / "data"
"""
    resultat = subprocess.run(
        [sys.executable, "-c", code],
        cwd=sous_dossier,
        env=environnement,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
