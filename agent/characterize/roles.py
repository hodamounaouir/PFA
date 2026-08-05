"""Classer une colonne par **rôle inféré** — le moteur de généricité (phase 4.2).

C'est ici que l'agent cesse d'être un profileur pour devenir un agent qualité :
savoir qu'une colonne porte 8 000 valeurs distinctes ne dit pas quoi lui
demander. Savoir qu'elle est *catégorielle* le dit — on y cherche des valeurs
nouvelles, disparues, et des collisions sémantiques. Savoir qu'elle est
*identifiant* le dit aussi, et ce n'est pas la même liste.

    | Rôle          | Ce qu'on en attend (4.3)                                     |
    |---------------|--------------------------------------------------------------|
    | identifier    | unicité, nulls, format                                       |
    | foreign_key   | intégrité référentielle, orphelins                           |
    | categorical   | valeurs nouvelles/disparues, **collisions sémantiques**      |
    | numeric       | bornes, outliers, négatifs/zéros                             |
    | temporal      | fraîcheur, dates futures, trous, monotonie                   |
    | free_text     | nulls et longueurs **seulement** — surtout pas de valeurs    |
    | unknown       | rien : la colonne n'a rien montré sur ce lot                 |

## Le rôle se déduit des faits, jamais du type déclaré

Même raison qu'en 4.1.5 ([ADR 010](../../docs/adr/010-agent-generique.md),
décision 11), et elle est encore plus tranchante ici : **en Bronze tout est
VARCHAR** par construction (phase 2.1). Un classement fondé sur `DATA_TYPE` y
verrait six colonnes de texte libre et rien d'autre — donc aucun contrôle, sur
la couche où les anomalies sont injectées.

On ne lit donc que ce qui a été **mesuré** : le nombre de lignes, la cardinalité,
les nulls, et les deux bornes. Ces cinq faits existent sur n'importe quel
backend, et ils survivent au typage : `min="2018-04-29"` désigne une date qu'elle
soit stockée en `DATE` ou en `VARCHAR`.

Conséquence heureuse : le classement travaille sur ce que `profile` rend déjà.
Aucune requête supplémentaire n'est nécessaire pour classer — ce qui est vital,
puisque c'est le classement qui décide *quelles* requêtes coûteuses valent
la peine d'être posées.

## Ce que le classement ne peut pas faire, et pourquoi c'est écrit ici

**La clé étrangère n'est pas un fait de colonne.** « Valeurs ⊂ identifiants
d'une autre table » exige de regarder *deux* tables : aucune statistique de la
colonne seule ne peut la révéler. Elle est donc absente de ce module et traitée
à part (4.2.2), avec la comparaison croisée qu'elle réclame.

**Un code non unique reste indiscernable d'une quantité.** Un préfixe de code
postal (`01001`) se lit comme un nombre, se répète, et n'est unique nulle part :
il sera classé `numeric` et recevra une médiane qui ne veut rien dire. Aucun fait
mesuré ne l'en distingue — c'est une question de **sens**, pas de forme.

C'est précisément ce que la validation humaine du contrat (4.2.5) existe pour
corriger : la machine propose du *descriptif*, l'humain rend *normatif*. Le
signaler ici plutôt que de bricoler une heuristique de plus, c'est reconnaître
où passe la frontière entre ce qu'on mesure et ce qu'on sait.
"""

import datetime
import re
from typing import Optional

# Les rôles, en anglais comme toutes les clés de données du projet : ils
# finiront dans `contracts/*.yaml` et dans `OPS.INCIDENTS`.
IDENTIFIANT = "identifier"
CLE_ETRANGERE = "foreign_key"
CATEGORIEL = "categorical"
NUMERIQUE = "numeric"
TEMPOREL = "temporal"
TEXTE_LIBRE = "free_text"
INDETERMINE = "unknown"

ROLES = (
    IDENTIFIANT,
    CLE_ETRANGERE,
    CATEGORIEL,
    NUMERIQUE,
    TEMPOREL,
    TEXTE_LIBRE,
    INDETERMINE,
)

# Au-dessus, la colonne identifie. Pas 1.0 exactement : sur un lot réel, une
# poignée de doublons ne fait pas d'une clé primaire une catégorie — et c'est
# justement l'écart que le contrat (4.2) fera constater comme une violation
# d'unicité, au lieu de reclasser la colonne et de se taire.
RATIO_UNICITE_MIN = 0.99

# En dessous, la colonne se répète assez pour catégoriser. Repris de 4.1.5, où
# il penchait déjà volontairement du côté généreux : rater une colonne
# catégorielle, c'est rater une détection (dont le cas São Paulo) ; en garder
# une de trop coûte une requête, et `coverage` le dit aussitôt.
RATIO_CATEGORIEL_MAX = 0.5

# Un nombre écrit. Volontairement plus strict que `float()`, qui accepte `nan`,
# `inf` et `1_000` : une ville nommée « nan » passerait pour une quantité.
NOMBRE_ECRIT = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

# Une date ou un horodatage ISO. C'est la forme que rend Snowflake — et celle
# que l'ingestion a écrite en Bronze, où ces colonnes sont du texte.
DATE_ECRITE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"  # 2018-04-29
    r"(?:[ T]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"  # 10:56:33.000
    r"(?:Z|[+-]\d{2}:?\d{2})?)?$"  # fuseau éventuel
)


def lisible_comme_nombre(valeur) -> bool:
    """La valeur est-elle un nombre, ou l'écriture d'un nombre ?

    Les deux cas comptent : en Silver une borne arrive déjà typée, en Bronze
    elle arrive en texte. C'est le seul endroit où la différence est absorbée.
    """
    if valeur is None or isinstance(valeur, bool):
        return False
    if isinstance(valeur, (int, float)):
        return True
    return bool(NOMBRE_ECRIT.match(str(valeur).strip()))


def lisible_comme_date(valeur) -> bool:
    """La valeur est-elle une date, ou l'écriture d'une date ?

    Éprouvé **avant** le test numérique : une date compacte (`20180429`) se lit
    aussi comme un nombre, et lui donner une médiane n'aurait aucun sens.
    """
    if valeur is None or isinstance(valeur, bool):
        return False
    if isinstance(valeur, (datetime.date, datetime.datetime)):
        return True
    if isinstance(valeur, (int, float)):
        return False
    return bool(DATE_ECRITE.match(str(valeur).strip()))


def classer(stats: dict, row_count: int) -> str:
    """Le rôle d'une colonne, déduit de ses seuls agrégats.

    `stats` est une entrée de `profile()["columns"]` : `distinct`, `null_count`,
    `min`, `max`. `row_count` est le nombre de lignes du lot.

    **L'ordre des tests est la décision**, pas un détail d'implémentation : une
    colonne peut satisfaire plusieurs signatures, et c'est le rôle le plus
    exigeant qui doit gagner — celui qui déclenche les contrôles les plus
    précis. Un horodatage de commande est presque unique : le classer
    *identifier* ferait perdre la fraîcheur, les dates futures et les trous, pour
    ne gagner qu'un contrôle d'unicité sur une colonne qui n'identifie rien.
    """
    distinct = stats.get("distinct") or 0
    if not row_count or not distinct:
        # Lot vide, ou colonne entièrement nulle : elle n'a rien montré. Dire
        # `unknown` est un constat ; lui inventer un rôle serait une supposition
        # que le contrat graverait ensuite comme une vérité.
        return INDETERMINE

    mini, maxi = stats.get("min"), stats.get("max")

    # 1. Temporel d'abord — voir `lisible_comme_date`.
    if lisible_comme_date(mini) and lisible_comme_date(maxi):
        return TEMPOREL

    unicite = distinct / row_count
    sans_trou = not stats.get("null_count")

    # 2. Identifiant : unique **et** jamais nul. Les deux, sinon une colonne de
    #    montants d'un petit lot passerait pour une clé primaire.
    if unicite >= RATIO_UNICITE_MIN and sans_trou:
        return IDENTIFIANT

    # 3. Numérique : les deux bornes se lisent comme des nombres.
    if lisible_comme_nombre(mini) and lisible_comme_nombre(maxi):
        return NUMERIQUE

    # 4. Catégoriel : elle se répète assez pour que ses valeurs fassent sens.
    if unicite <= RATIO_CATEGORIEL_MAX:
        return CATEGORIEL

    # 5. Le reste : beaucoup de valeurs différentes, pas assez pour identifier.
    #    On n'en tirera que des nulls et des longueurs — jamais des valeurs.
    return TEXTE_LIBRE


def classer_fiche(colonnes: dict, row_count: int) -> dict:
    """Le rôle de chaque colonne d'un profil : `{nom: rôle}`."""
    return {nom: classer(stats, row_count) for nom, stats in colonnes.items()}


def role_ou_none(role: Optional[str]) -> Optional[str]:
    """Un rôle connu, ou `None` — pour ne pas propager une valeur inventée."""
    return role if role in ROLES else None
