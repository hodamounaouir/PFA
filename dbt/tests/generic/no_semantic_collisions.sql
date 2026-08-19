{#
  Test générique `no_semantic_collisions` — deux écritures d'une même valeur.

  C'est la règle que la baseline ne savait pas exprimer : `not_null`, `unique` et
  `accepted_values` passent tous sur une colonne où `sao paulo` et `são paulo`
  coexistent, et pourtant le total par ville est faux.

  Le test rend les formes portées par **au moins deux écritures distinctes** ;
  dbt échoue dès qu'il en trouve une.

  ⚠️ **Cette règle existe à deux endroits, et c'est un coût assumé.**
  `agent/characterize/collisions.py::normaliser()` fait le même repli en Python,
  parce que l'agent doit pouvoir constater une collision *sans* passer par dbt —
  y compris sur Bronze, que dbt ne teste pas. Les deux implémentations doivent
  rester alignées ; la référence est la section `preparation` de
  `data/ground_truth.yaml`, qui décrit ce qui a été fait au dataset.

  Le repli couvre **casse, accents et espaces multiples** — et rien d'autre. Il
  ne supprime pas les espaces (décision 13c de l'ADR 010) : `sãopaulo` lui
  échappe, mais les supprimer fusionnerait `arco verde` et `arcoverde`, deux
  communes distinctes du Pernambouc. Perdre une variante rare coûte moins cher
  que déclarer identiques deux villes qui ne le sont pas.

  `COLLATE(…, 'en-ci-ai')` porte la casse et les accents en une fois : c'est du
  Snowflake, assumé — ce test vit dans le projet dbt, qui n'a qu'une cible.
#}

{% test no_semantic_collisions(model, column_name) %}

with prepare as (

    select
        {{ column_name }} as valeur,
        regexp_replace(trim({{ column_name }}), '\\s+', ' ') as espaces_replies
    from {{ model }}
    where {{ column_name }} is not null
      and trim({{ column_name }}) <> ''

)

select
    collate(espaces_replies, 'en-ci-ai') as forme_normalisee,
    count(distinct valeur) as ecritures_distinctes,
    min(valeur) as exemple_1,
    max(valeur) as exemple_2
from prepare
group by 1
having count(distinct valeur) > 1

{% endtest %}
