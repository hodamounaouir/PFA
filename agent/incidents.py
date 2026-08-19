"""La signature d'une anomalie — ce qui définit « la même anomalie » (phase 4.4).

C'est la pièce dont dépend toute la mémoire de l'agent, dans **les deux sens** :

    approuvé  →  au J85, l'agent retrouve l'incident du J60 et propose la même
                 correction (objectif O7, mesuré T1 vs T2 au benchmark) ;
    refusé    →  l'agent se tait : l'écart est journalisé, mais pas resoumis.

## La granularité est le vrai sujet

Trop **large**, l'agent devient aveugle : une signature réduite à
`(table, colonne, type)` transformerait un refus sur « 3 % de nulls, c'est
normal le lundi » en « plus jamais de nulls sur `customer_id` » — et le jour où
la colonne en porte 90 %, il se tairait.

Trop **étroite**, la mémoire ne sert jamais : une signature qui inclurait la
valeur exacte (0,301) ne se répéterait pour ainsi dire jamais, et le J85 ne
retrouverait pas le J60 alors qu'il s'agit de la *même* anomalie.

D'où le quatrième terme : un **ordre de grandeur**, et non l'ampleur exacte.

## Pourquoi l'octave plutôt que la décade

`floor(log10(x))` mettrait 30 % et 90 % de nulls dans le même seau — or
`PROGRESS` §4.4 exige explicitement qu'ils soient distingués. `floor(log2(x))`
change de seau **quand l'ampleur double**, ce qui répond à la question posée :
*l'anomalie a-t-elle franchement changé d'échelle ?*

    0,30 → -2      0,30 et 0,35 : même seau, l'agent reste silencieux
    0,35 → -2      (une variation mineure ne rouvre pas un refus)
    0,85 → -1      0,85 : nouveau seau, l'agent reparle

L'échelle est logarithmique donc **sans unité** : elle vaut pour un taux comme
pour un décompte, sur n'importe quel dataset. C'est la même exigence de
généricité que partout ailleurs dans `agent/`.
"""

import math
from typing import Optional

# Signature sans ampleur mesurable : une table absente est absente, il n'y a pas
# de « plus ou moins ». Le seau est explicite plutôt que `None` — sinon deux
# signatures sans ampleur ne se compareraient pas égales dans un ensemble.
SANS_AMPLEUR = "n/a"

# En dessous, l'ampleur est traitée comme nulle. `log2(0)` vaut -inf et
# `log2(1e-300)` un nombre qui n'a plus aucun sens métier : un taux de nulls de
# 10⁻¹² n'est pas « mille fois moins grave » qu'un taux de 10⁻⁹, c'est zéro.
AMPLEUR_NULLE = 1e-9


def octave(ampleur: Optional[float]) -> str:
    """L'ordre de grandeur d'une ampleur, en octaves signées.

    Rend une **chaîne** et non un nombre : cette valeur finit dans `INCIDENTS`,
    dans une clé de comparaison et dans les écrans de la phase 6. Un entier s'y
    lirait comme une quantité alors que c'est une étiquette — et `0` comme un
    seau se confondrait avec `0` comme absence.
    """
    if ampleur is None:
        return SANS_AMPLEUR
    valeur = abs(float(ampleur))
    if valeur < AMPLEUR_NULLE:
        return "0"
    return str(math.floor(math.log2(valeur)))


def signature(ecart: dict) -> tuple:
    """`(table, colonne, type, octave)` — l'identité d'une anomalie.

    Un tuple et non une chaîne : il se compare, se met dans un ensemble, et ses
    quatre termes restent lisibles séparément dans le journal. La chaîne, elle,
    se fabrique au moment d'écrire en base (`texte()`).
    """
    return (
        ecart.get("table"),
        ecart.get("colonne"),
        ecart.get("type"),
        octave(ecart.get("ampleur")),
    )


def texte(sig: tuple) -> str:
    """La signature sous forme stockable — `RAW.ORDERS|CUSTOMER_ID|nulls|-2`.

    Le `|` plutôt que le point ou le tiret : les deux apparaissent déjà dans les
    noms de tables (`RAW.ORDERS`) et dans les octaves négatives (`-2`), et une
    signature qu'on ne peut pas redécouper est une signature qu'on ne peut pas
    expliquer à l'humain qui la voit dans l'écran « signatures en silence ».
    """
    return "|".join("" if terme is None else str(terme) for terme in sig)


def depuis_texte(brut: str) -> tuple:
    """L'inverse de `texte()`, pour relire ce qui a été écrit en base."""
    parties = brut.split("|")
    return tuple(p if p != "" else None for p in parties)
