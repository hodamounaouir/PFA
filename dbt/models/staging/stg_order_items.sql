-- Silver : lignes de commande typées. PAS de dédoublonnage ici, volontairement :
-- les doublons injectés au J75 doivent survivre pour que le test `unique` du
-- baseline (sur la clé order_item_sk) les détecte. L'idempotence de l'ingestion
-- empêche déjà tout doublon technique.
with source as (
    select * from {{ source('raw', 'order_items') }}
)
select
    order_id || '-' || order_item_id  as order_item_sk,   -- clé de ligne (order_id, order_item_id)
    order_id,
    try_cast(order_item_id as integer) as order_item_id,
    product_id,
    seller_id,
    try_to_timestamp(shipping_limit_date) as shipping_limit_ts,
    try_cast(price as number(12, 2))       as price,
    try_cast(freight_value as number(12, 2)) as freight_value,
    _batch_id,
    _ingested_at
from source
