-- Silver : commandes typées. On caste les VARCHAR de Bronze en dates réelles.
-- Les nulls injectés sur customer_id (J60/J85) sont conservés → le test not_null
-- du baseline les attrapera. On dérive la date d'achat pour les agrégats Gold.
with source as (
    select * from {{ source('raw', 'orders') }}
)
select
    order_id,
    customer_id,
    order_status,
    try_to_timestamp(order_purchase_timestamp)        as order_purchase_ts,
    to_date(try_to_timestamp(order_purchase_timestamp)) as order_purchase_date,
    try_to_timestamp(order_approved_at)               as order_approved_ts,
    try_to_timestamp(order_delivered_carrier_date)    as order_delivered_carrier_ts,
    try_to_timestamp(order_delivered_customer_date)   as order_delivered_customer_ts,
    try_to_timestamp(order_estimated_delivery_date)   as order_estimated_delivery_ts,
    _batch_id,
    _ingested_at
from source
