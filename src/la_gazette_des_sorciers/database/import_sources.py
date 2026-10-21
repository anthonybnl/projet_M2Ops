import argparse
import csv
from pathlib import Path

from la_gazette_des_sorciers.database.crud_sources import upsert_sources
from la_gazette_des_sorciers.database.db import SessionLocal

PROJECT_PATH = Path(__file__).resolve().parents[3]
CSV_PATH = PROJECT_PATH / "sources.csv"

# Colonnes mises à jour au conflit; actif et l'état de collecte sont préservés.
UPDATE_COLUMNS = ["name", "type", "region", "url_flux", "conditions", "notes"]


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            {
                "id": row["id"].strip(),
                "name": row["nom"].strip(),
                "type": row["type"].strip(),
                "region": row["region"].strip(),
                "url_flux": row["acces"].strip(),
                "conditions": (row["conditions"] or "").strip(),
                "notes": (row["notes"] or "").strip(),
                "actif": True,
            }
            for row in csv.DictReader(f)
            if row["id"].strip()
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert de sources.csv dans la table sources")
    parser.add_argument("csv_path", nargs="?", type=Path, default=CSV_PATH)
    args = parser.parse_args()

    rows = read_csv(args.csv_path)
    with SessionLocal() as session:
        count = upsert_sources(session, rows, UPDATE_COLUMNS)
    print(f"{count} sources importées depuis {args.csv_path}")


if __name__ == "__main__":
    main()
