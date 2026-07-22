-- Silver : référentiel produits (chargé au J1 seul). Typage des mesures numériques.
with source as (
    select * from {{ source('raw', 'products') }}
)
select
    product_id,
    product_category_name,
    try_cast(product_name_lenght as integer)        as product_name_length,
    try_cast(product_description_lenght as integer) as product_description_length,
    try_cast(product_photos_qty as integer)         as product_photos_qty,
    try_cast(product_weight_g as number(12, 2))     as product_weight_g,
    try_cast(product_length_cm as number(12, 2))    as product_length_cm,
    try_cast(product_height_cm as number(12, 2))    as product_height_cm,
    try_cast(product_width_cm as number(12, 2))     as product_width_cm,
    _batch_id,
    _ingested_at
from source
