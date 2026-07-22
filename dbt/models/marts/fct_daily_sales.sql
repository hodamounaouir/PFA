-- Gold : chiffre d'affaires et nombre de commandes par jour d'achat.
-- Au J45, payment_amount est NULL (renommage) → le CA du jour chute : anomalie visible.
with payments as (
    select order_id, sum(payment_amount) as order_amount
    from {{ ref('stg_order_payments') }}
    group by order_id
),
orders as (
    select order_id, order_purchase_date
    from {{ ref('stg_orders') }}
)
select
    o.order_purchase_date          as sales_date,
    count(distinct o.order_id)     as n_orders,
    sum(p.order_amount)            as revenue
from orders o
left join payments p on o.order_id = p.order_id
where o.order_purchase_date is not null
group by o.order_purchase_date
order by o.order_purchase_date
