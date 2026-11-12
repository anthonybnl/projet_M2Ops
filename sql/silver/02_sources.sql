\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE sources_import (
    id TEXT,
    nom TEXT,
    type TEXT,
    region TEXT,
    acces TEXT,
    conditions TEXT,
    notes TEXT
) ON COMMIT DROP;

\copy sources_import FROM '/seed/sources.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

INSERT INTO silver.sources (source_id, nom, url_flux, type, region)
SELECT
    btrim(id),
    btrim(nom),
    btrim(split_part(acces, '|', 1)),
    btrim(type),
    btrim(region)
FROM sources_import
WHERE btrim(split_part(acces, '|', 1)) ~ '^https?://'
ON CONFLICT (source_id) DO UPDATE SET
    nom = EXCLUDED.nom,
    url_flux = EXCLUDED.url_flux,
    type = EXCLUDED.type,
    region = EXCLUDED.region;

COMMIT;
