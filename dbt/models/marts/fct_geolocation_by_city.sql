-- Gold : agrégat de la table de référence géo par (état, ville).
-- ⭐ C'EST LE DÉMONSTRATEUR DU TROU SÉMANTIQUE (ground_truth : semantic_sao_paulo).
-- Comme Silver n'a pas normalisé la casse/les accents, une même métropole éclate en
-- plusieurs lignes : 'são paulo', 'sao paulo', 'sãopaulo' apparaissent séparément,
-- chacune avec sa part de points géo (~85/15). Aucun test baseline ne couvre ce cas
-- (impossible à écrire sans connaître les fautes à l'avance) → réservé à l'agent.
select
    geolocation_state,
    geolocation_city,
    count(*)                                   as n_points,
    count(distinct geolocation_zip_code_prefix) as n_zip_prefixes
from {{ ref('stg_geolocation') }}
group by geolocation_state, geolocation_city
order by n_points desc
