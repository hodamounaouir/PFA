"""La caractérisation : de « ce qu'on a mesuré » à « ce que c'est » (phase 4.2).

Le profilage (4.1) rend des faits ; la caractérisation leur donne un **rôle**, et
c'est le rôle qui dit quels contrôles ont un sens. C'est le moteur de généricité
du projet : rien ici ne connaît Olist, ni Snowflake, ni un nom de colonne.

    from agent.characterize import classer

    classer({"distinct": 8, "null_count": 0, "min": "approved", "max": "shipped"}, 1000)
    # -> "categorical"

Le classement ne lit que des agrégats déjà calculés : il ne coûte aucune requête,
ce qui est indispensable puisque c'est *lui* qui décide quelles requêtes
coûteuses valent la peine d'être posées.
"""

from agent.characterize.collisions import grouper_collisions, normaliser
from agent.characterize.roles import (
    CATEGORIEL,
    CLE_ETRANGERE,
    IDENTIFIANT,
    INDETERMINE,
    NUMERIQUE,
    RATIO_CATEGORIEL_MAX,
    RATIO_UNICITE_MIN,
    ROLES,
    TEMPOREL,
    TEXTE_LIBRE,
    classer,
    classer_fiche,
    lisible_comme_date,
    lisible_comme_nombre,
)

__all__ = [
    "CATEGORIEL",
    "CLE_ETRANGERE",
    "IDENTIFIANT",
    "INDETERMINE",
    "NUMERIQUE",
    "RATIO_CATEGORIEL_MAX",
    "RATIO_UNICITE_MIN",
    "ROLES",
    "TEMPOREL",
    "TEXTE_LIBRE",
    "classer",
    "classer_fiche",
    "grouper_collisions",
    "lisible_comme_date",
    "lisible_comme_nombre",
    "normaliser",
]
