-- Gold : délais de livraison par commande (uniquement les commandes livrées).
-- delivery_days = achat → livraison réelle ; delay_vs_estimate = livraison réelle
-- vs date estimée (positif = en retard).
select
    order_id,
    order_purchase_date,
    datediff('day', order_purchase_ts, order_delivered_customer_ts)      as delivery_days,
    datediff('day', order_estimated_delivery_ts, order_delivered_customer_ts) as delay_vs_estimate
from {{ ref('stg_orders') }}
where order_delivered_customer_ts is not null
  and order_purchase_ts is not null
