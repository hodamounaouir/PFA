"""Quand deux valeurs sont la même chose écrite deux fois (phase 4.2).

C'est le cœur du fil rouge du projet. Dans `customer_city`, `sao paulo` et
`são paulo` désignent la même métropole ; pour un compteur, ce sont deux unités
sans rapport. Aucun test de complétude, d'unicité ou de format ne bronche — et
l'agrégat des ventes par ville coupe la plus grande ville du Brésil en deux.

## Ce module constate, il ne corrige pas

Il rend des **grappes de collision** : des valeurs distinctes qui se replient sur
la même forme. Il ne choisit pas de forme canonique, ne remplace rien, ne touche
à aucune donnée. La correction, si elle a lieu, passe par une décision humaine
(règle R7 et le cycle `Propose`).

La nuance est ce qui sépare ce module de `data/prepare.py`, qui lui *nettoie* la
fenêtre de référence. Les deux replient de la même façon, mais l'un agit sur les
données du benchmark et l'autre observe celles du client. Ils ne partagent
volontairement aucun code : `agent/` ne doit rien importer de `data/`, qui est
l'outillage du benchmark et non l'agent.

## Ce que le repli fait, et ce qu'il se refuse à faire

Casse, accents, espaces multiples. **Pas la suppression des espaces.**

`sãopaulo` échappe donc au repli — c'est une limite connue et assumée. Supprimer
les espaces attraperait cette forme, mais fusionnerait aussi `arco verde` et
`arcoverde`, qui sont deux communes brésiliennes distinctes. Un détecteur qui
invente des égalités est pire que le désordre qu'il signale : il ferait retirer
du contrat des valeurs parfaitement légitimes.

Ce choix est sans coût sur le corrigé du projet : les 18 variantes injectées au
J50 sont **toutes accentuelles**, et les variantes d'espace réelles du dataset
ont été repliées dans la fenêtre de référence par la phase 1.5.
"""

import re
import unicodedata

_ESPACES = re.compile(r"\s+")


def normaliser(valeur) -> str:
    """`"  São   PAULO "` -> `"sao paulo"`. Casse, accents, espaces. Rien d'autre.

    Une valeur qui n'est pas du texte est rendue telle quelle, en chaîne : deux
    nombres ne se replient pas l'un sur l'autre, et une colonne numérique n'a
    de toute façon pas à passer par ici.
    """
    if not isinstance(valeur, str):
        return str(valeur)
    decompose = unicodedata.normalize("NFD", valeur)
    sans_accent = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return _ESPACES.sub(" ", sans_accent).strip().lower()


def grouper_collisions(valeurs) -> list[dict]:
    """Les grappes de valeurs distinctes qui se replient sur la même forme.

    Rend `[{"normalized": "sao paulo", "values": ["sao paulo", "são paulo"]}]`,
    trié par forme repliée puis par valeur — deux exécutions doivent produire le
    même rapport, sans quoi une détection qui en dépend deviendrait
    intermittente.

    Une valeur seule ne fait pas une grappe : seules les formes portées par
    **au moins deux** écritures différentes sont rendues.
    """
    par_forme: dict[str, set] = {}
    for valeur in valeurs:
        par_forme.setdefault(normaliser(valeur), set()).add(valeur)

    return [
        {"normalized": forme, "values": sorted(ecritures)}
        for forme, ecritures in sorted(par_forme.items())
        if len(ecritures) > 1
    ]
