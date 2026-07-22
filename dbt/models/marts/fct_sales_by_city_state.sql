-- Gold : ventes agrégées par ville / état du client.
-- NB : customer_city est déjà normalisée en ASCII par Olist (une seule variante
-- 'sao paulo') → le fan-out sémantique NE se voit PAS ici. Le cas São Paulo vit
-- dans la table de référence geolocation (voir fct_geolocation_by_city).
with payments as (
    select order_id, sum(payment_amount) as order_amount
    from {{ ref('stg_order_payments') }}
    group by order_id
),
orders as (
    select order_id, customer_id
    from {{ ref('stg_orders') }}
),
customers as (
    select customer_id, customer_city, customer_state
    from {{ ref('stg_customers') }}
)
select
    c.customer_state,
    c.customer_city,
    count(distinct o.order_id) as n_orders,
    sum(p.order_amount)        as revenue
from orders o
join customers c on o.customer_id = c.customer_id
left join payments p on o.order_id = p.order_id
group by c.customer_state, c.customer_city
order by revenue desc nulls last
