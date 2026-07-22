-- Silver : référentiel géo (chargé au J1 seul). Coordonnées typées en flottants.
-- geolocation_city est laissée brute (même trou de casse que les clients).
with source as (
    select * from {{ source('raw', 'geolocation') }}
)
select
    geolocation_zip_code_prefix,
    try_cast(geolocation_lat as float) as geolocation_lat,
    try_cast(geolocation_lng as float) as geolocation_lng,
    geolocation_city,                  -- brute, non normalisée
    upper(geolocation_state) as geolocation_state,
    _batch_id,
    _ingested_at
from source
