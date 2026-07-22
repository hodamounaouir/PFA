-- Gold : panier moyen par jour (montant moyen d'une commande).
with per_order as (
    select order_id, sum(payment_amount) as order_amount
    from {{ ref('stg_order_payments') }}
    group by order_id
),
orders as (
    select order_id, order_purchase_date
    from {{ ref('stg_orders') }}
)
select
    o.order_purchase_date       as sales_date,
    count(*)                    as n_orders,
    avg(po.order_amount)        as avg_order_value
from orders o
join per_order po on o.order_id = po.order_id
where o.order_purchase_date is not null
group by o.order_purchase_date
order by o.order_purchase_date
