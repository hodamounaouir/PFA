"""Tool `robust_stats` — médiane et MAD, jamais moyenne et écart-type (4.1.3).

## Pourquoi la médiane, et pas la moyenne

Parce que la moyenne se laisse déplacer par ce qu'on cherche à détecter. Le
scénario est écrit dans le corrigé du projet : une anomalie au J60, la même qui
récidive au J85. Avec moyenne + σ, l'anomalie du J60 entre dans l'historique,
gonfle l'écart-type, et la récidive du J85 tombe *dans* la nouvelle normale —
elle paraît moins grave qu'elle ne l'est. **La référence se contamine
elle-même**, et l'agent devient d'autant plus aveugle qu'on lui a montré
d'anomalies.

La médiane et le MAD (`médiane(|x − médiane(x)|)`) ne bougent pas pour une
poignée de valeurs aberrantes. C'est le point de bascule entre une détection qui
s'émousse et une détection qui tient dans la durée.

## Ce que ce tool mesure, et ce qu'il ne mesure pas

Il résume **une colonne dans un lot** : la position (médiane) et la dispersion
(MAD) des valeurs du jour. Il ne compare rien à rien — comparer le jour à
l'historique demande `OPS._PROFILES`, qui n'existe qu'en 4.3, et cette
comparaison est le travail de `detect`, pas d'une mesure.

La distinction compte : ici la médiane porte sur les *valeurs d'une colonne* ;
en 4.3 elle portera sur une *métrique à travers les jours* (le taux de nulls sur
30 jours). Même outil statistique, deux séries différentes, et c'est le même
argument anti-contamination qui les justifie toutes les deux.

## Bronze est en VARCHAR, et c'est un signal

Tout Bronze est en texte par construction (phase 2.1) : une colonne de montants
y contient des nombres *écrits*. Le connecteur les relit avec `TRY_CAST`, qui
rend `NULL` sur ce qui n'est pas lisible plutôt que de faire échouer la requête.

Ce qui aurait pu n'être qu'une précaution devient une mesure : `numeric_rate`
dit quelle part des valeurs renseignées se laisse lire comme un nombre. Il vaut
1,0 sur une colonne saine ; s'il tombe à 0,7, un tiers des valeurs a cessé
d'être numérique — c'est une dérive de format, et elle ne coûte rien puisqu'il
fallait compter de toute façon.
"""

from typing import Optional

from langchain_core.tools import tool

from agent.tools._connecteur import connecteur_pour


@tool
def robust_stats(
    dataset: str, table: str, column: str, batch_id: str = ""
) -> Optional[dict]:
    """Médiane, MAD et bornes numériques d'une colonne, dans un lot donné.

    `dataset` est le nom d'un registre (`datasets/<dataset>.yaml`), `table` un
    nom qui y est déclaré, `column` une colonne de cette table — la casse est
    résolue contre le schéma réel. `batch_id` vide signifie « toute la table »,
    comme pour un agrégat Gold qui n'a pas de notion de lot.

    Rend `{"table", "column", "type", "batch_id", "non_null_count",
    "numeric_count", "numeric_rate", "median", "mad", "min", "max"}`, ou `None`
    si la table ou la colonne n'existe pas.

    Sur une colonne dont le type ne peut pas porter de nombre (DATE, BOOLEAN…),
    toutes les mesures valent `None` : le schéma a suffi à répondre, la table
    n'a pas été lue. Un `mad` nul, lui, est un **fait** — la colonne est
    constante sur ce lot — et non une valeur à corriger ; le plancher qui évitera
    la division par zéro appartient à `detect`.
    """
    with connecteur_pour(dataset, table) as (connecteur, declaree):
        return connecteur.robust_stats(
            table, column, declaree.batch_column, batch_id or None
        )
