"""Collecte des flux RSS/Atom : sauvegarde du XML brut puis de sa conversion en JSON."""

import csv
import json
import logging
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import xmltodict

from la_gazette_des_sorciers.storage import LocalStorage

log = logging.getLogger("collecte")

USER_AGENT = "Mozilla/5.0 (compatible; la-gazette-des-sorciers/0.1; projet etudiant M2Ops)"
TIMEOUT_S = 30


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def read_sources(path: str | Path) -> list[dict]:
    """Lit sources.csv. L'URL est le premier mot de la colonne `acces` ("url | RSS/XML")."""
    sources, seen = [], set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("acces") or "").split("|")[0].strip()
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "nom": row["nom"].strip(),
                    "type": (row.get("type") or "").strip(),
                    "region": (row.get("region") or "").strip(),
                    "url": url,
                }
            )
    return sources


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def collect_source(source: dict, storage: LocalStorage, day: str) -> None:
    slug = slugify(source["nom"])
    fetched_at = datetime.now(timezone.utc)
    xml = fetch(source["url"])
    storage.put(f"raw/xml/{day}/{slug}.xml", xml)

    document = {
        "source": source,
        "fetched_at": fetched_at.isoformat(),
        "feed": xmltodict.parse(xml),
    }
    payload = json.dumps(document, ensure_ascii=False, indent=2).encode()
    storage.put(f"raw/json/{day}/{slug}.json", payload)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,  # sur stderr, Kestra afficherait tous les logs en ERROR
    )
    sources_file = os.environ.get("SOURCES_FILE", "sources.csv")
    storage = LocalStorage()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sources = read_sources(sources_file)
    log.info("%d sources à collecter (%s)", len(sources), sources_file)

    ok = 0
    for source in sources:
        try:
            collect_source(source, storage, day)
            ok += 1
            log.info("OK    %s", source["nom"])
        except Exception as exc:
            log.error("ECHEC %s (%s) : %s", source["nom"], source["url"], exc)

    log.info("%d/%d sources collectées", ok, len(sources))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
