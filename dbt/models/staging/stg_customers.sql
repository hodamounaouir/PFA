-- Silver : clients.
-- LE TROU VOLONTAIRE DU PROJET : customer_city est copiée TELLE QUELLE, sans
-- normaliser la casse ni les accents. 'são paulo', 'sao paulo', 'SÃO PAULO' restent
-- donc des valeurs distinctes. Un data engineer normal n'a aucune raison de deviner
-- que ce sont la même ville — c'est justement ce que l'agent doit trouver (⭐ phase 4).
-- On se contente d'harmoniser l'état en majuscules (usage standard, non piégeux).
with source as (
    select * from {{ source('raw', 'customers') }}
)
select
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix,
    customer_city,                     -- brute, non normalisée (trou sémantique)
    upper(customer_state) as customer_state,
    _batch_id,
    _ingested_at
from source
