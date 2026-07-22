-- Silver : paiements typés.
-- CHOIX NAÏF ASSUMÉ (baseline) : on référence `payment_value`, le nom connu de la
-- colonne. Au J45, le "fournisseur" l'a renommée en `amount` sans prévenir → dans
-- Bronze, payment_value est NULL ce jour-là. On ne va PAS récupérer `amount` :
-- le montant devient donc NULL au J45, et le test not_null du baseline casse.
-- C'est exactement ce qu'on veut démontrer (cf. ground_truth.yaml schema_drift_j45).
-- L'agent (phase 4) fera mieux en lisant _SCHEMA_HISTORY.
with source as (
    select * from {{ source('raw', 'order_payments') }}
)
select
    order_id,
    try_cast(payment_sequential as integer)   as payment_sequential,
    payment_type,
    try_cast(payment_installments as integer) as payment_installments,
    try_cast(payment_value as number(12, 2))  as payment_amount,
    _batch_id,
    _ingested_at
from source
