"""Famille *sémantique* — le lot se contredit lui-même (phase 4.3).

⭐ **La famille qui justifie le projet.** Les quatre autres comparent le lot à
quelque chose d'extérieur : un registre, un schéma connu, un contrat, un
historique. Celle-ci ne compare le lot **qu'à lui-même**, et c'est ce qui la
rend capable de voir ce qu'aucune baseline ne voit.

    sao paulo   135 800
    são paulo    24 918

Pour un compteur, ce sont deux villes. `not_null` passe, `unique` passe, le
typage passe, le pipeline est vert — et le total de São Paulo est faux. Aucun
test dbt ne peut le dire, parce qu'aucun ne sait que ces deux chaînes désignent
la même chose. Le repli le sait : elles ont la même forme normalisée.

## Toute colonne catégorielle, aucune colonne nommée

La détection s'applique à **toute colonne classée `categorical`** — jamais à une
liste de colonnes connues. C'est ce qui fait que São Paulo est attrapé *par
généricité* et non par cas particulier : brancher un dataset RH et la même
famille trouvera `CDI` / `cdi` sans qu'une ligne change.

## Ce qu'elle ne fait pas, et pourquoi

Elle ne **corrige** pas, ne choisit pas la bonne écriture, ne fusionne rien.
Elle constate une grappe. Choisir entre `sao paulo` et `são paulo` est une
décision métier — celle de l'humain, en phase 5.

Elle ne supprime pas non plus les espaces au repli (décision 13c) : `sãopaulo`
lui échappe, et c'est assumé — les supprimer fusionnerait `arco verde` et
`arcoverde`, **deux communes distinctes du Pernambouc**. Perdre une variante
rare coûte moins cher que déclarer identiques deux villes qui ne le sont pas.

## Une limite à dire franchement

Le repli travaille sur le **top-K**, pas sur toutes les valeurs. Une collision
entre deux formes rares, hors du top-K, passe inaperçue. C'est le prix du coût :
comparer toutes les valeurs deux à deux demanderait de les faire toutes sortir
de la base, ce que R2 interdit autant que le portefeuille. `coverage` accompagne
donc chaque écart : il dit sur quelle part du lot le constat porte.
"""

from agent.characterize import CATEGORIEL, grouper_collisions
from agent.detect import COHERENCE, SEMANTIQUE, ecart


def detecter(state: dict) -> list[dict]:
    """Les grappes de valeurs qui se replient sur la même forme normalisée."""
    table = state["table"]
    ecarts = []

    for colonne, stats in state.get("profile", {}).get("columns", {}).items():
        if stats.get("role") != CATEGORIEL:
            continue

        # `top` absent = la colonne n'a pas reçu de top-K (cardinalité trop
        # élevée, ou mesure qui n'a pas abouti). On ne signale rien : ne pas
        # avoir regardé n'est pas avoir constaté que tout va bien.
        valeurs = [entree["value"] for entree in stats.get("top") or []]
        if not valeurs:
            continue

        for grappe in grouper_collisions(valeurs):
            ecarts.append(
                ecart(
                    SEMANTIQUE,
                    table,
                    type="collision_semantique",
                    dama=COHERENCE,
                    colonne=colonne,
                    observe=grappe["values"],
                    reference=grappe["normalized"],
                    # Le nombre de lignes touchées : une collision sur 3 lignes
                    # et une sur 160 000 ne sont pas le même incident.
                    ampleur=_lignes(stats, grappe["values"]),
                    # La part du lot sur laquelle le constat porte : sans elle,
                    # « 2 écritures » ne dit pas si l'on parle de 3 lignes ou de
                    # 160 000.
                    coverage=stats.get("coverage"),
                    lignes_concernees=_lignes(stats, grappe["values"]),
                )
            )
    return ecarts


def _lignes(stats: dict, valeurs: list) -> int:
    """Combien de lignes portent les écritures de la grappe.

    C'est **l'ampleur**, et c'est elle qui décidera de l'ordre de grandeur dans
    la signature d'anomalie (4.4) : une collision sur 3 lignes et une collision
    sur 160 000 ne sont pas le même incident, et confondre les deux ferait taire
    l'agent sur la seconde après un refus sur la première.
    """
    cherchees = set(valeurs)
    return sum(
        entree.get("count", 0)
        for entree in stats.get("top") or []
        if entree.get("value") in cherchees
    )
