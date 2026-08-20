"""Les cinq familles de détection (phase 4.3).

`detect` **constate**, il ne juge pas. Il ne dit jamais « c'est une anomalie » :
il dit « ceci s'écarte de la référence R, de tant ». Qualifier l'écart — vraie
anomalie ou changement métier légitime — est le travail de l'humain, et c'est
pour ça que `propose` offre deux « non » différents (`rejected` quand le cas est
isolé, `amend_contract` quand c'est la règle qui a vieilli).

## Cinq familles, cinq références

| Famille        | Compare le lot à…                    | Attrape (corrigé Olist) |
|----------------|--------------------------------------|-------------------------|
| `inventaire`   | le registre `datasets/<nom>.yaml`     | table absente, renommée |
| `schema`       | `_SCHEMA_HISTORY`, sinon le contrat   | `schema_drift_j45`      |
| `contrat`      | les clauses de `contracts/*.yaml`     | `nulls_j60`, `duplicates_j75` |
| `statistique`  | les N lots précédents (`_PROFILES`)   | `truncate_j80`, `nulls_j60` |
| `semantique`   | **le lot avec lui-même**              | `semantic_drift_j50` ⭐ |

La dernière est la seule qui n'a besoin d'aucune référence extérieure : deux
écritures d'une même valeur se contredisent *dans le même lot*. C'est ce qui la
rend capable de voir ce qu'aucune baseline ne voit — et c'est le fil rouge du
projet.

## Aucune entrée-sortie, et c'est structurel

Toutes les familles sont des **fonctions pures** : elles lisent l'état, elles
rendent des écarts. Rien n'ouvre de connexion. Deux raisons, et la seconde est
la vraie :

1. le benchmark (phase 8) doit pouvoir rejouer la détection à l'identique — deux
   exécutions sur le même lot doivent rendre exactement le même verdict ;
2. une famille qui interroge la base pendant qu'elle raisonne compare des choses
   mesurées à des instants différents. L'écart qu'elle rapporterait n'aurait
   alors pas de sens : ni celui du lot, ni celui d'aujourd'hui.

C'est `profile` qui rassemble tout ce à quoi on compare — profil du jour,
historique, contrat, schéma connu, inventaire — et le dépose dans l'état.

## Aucun LLM ici, jamais

La détection doit être reproductible pour être mesurable. Le modèle n'intervient
qu'ensuite, dans `diagnose`, pour *expliquer* ce que ces cinq familles ont
constaté (règle R1).
"""

from typing import Optional

# --- Le vocabulaire des écarts ---------------------------------------------
#
# Les cinq familles produisent **le même dictionnaire**. Sans cette contrainte,
# `diagnose`, `propose`, le journal et les écrans de la phase 6 devraient
# connaître un format par famille — et chaque nouvelle famille casserait les
# quatre lecteurs. Les champs propres à une famille vivent dans `details`.

INVENTAIRE = "inventaire"
SCHEMA = "schema"
CONTRAT = "contrat"
STATISTIQUE = "statistique"
SEMANTIQUE = "semantique"

# ⚠️ `dbt` n'est pas une famille de **détection** : elle ne constate rien, elle
# traduit les verdicts d'un outil qui a déjà tranché. Elle porte quand même une
# étiquette de famille pour que ses écarts traversent la même forme commune —
# donc le même diagnostic, la même signature, la même mémoire, le même journal.
DBT = "dbt"

FAMILLES = (INVENTAIRE, SCHEMA, CONTRAT, STATISTIQUE, SEMANTIQUE, DBT)

# Les six dimensions DAMA retenues par le cahier des charges. Chaque écart en
# porte une : c'est elle qui permettra, en phase 8, de dire *quelle sorte* de
# qualité l'agent améliore, et pas seulement combien d'anomalies il trouve.
COMPLETUDE = "completude"
UNICITE = "unicite"
VALIDITE = "validite"
COHERENCE = "coherence"
EXACTITUDE = "exactitude"
FRAICHEUR = "fraicheur"


def ecart(
    famille: str,
    table: str,
    type: str,
    dama: str,
    colonne: Optional[str] = None,
    observe=None,
    reference=None,
    ampleur: Optional[float] = None,
    **details,
) -> dict:
    """Un écart constaté, dans la forme unique que toutes les familles rendent.

    `observe` et `reference` sont volontairement **non typés** : un écart de
    schéma compare des listes de colonnes, un écart statistique des nombres, un
    écart d'inventaire des noms de tables. Les contraindre obligerait à
    sérialiser, donc à perdre ce que `diagnose` a besoin de lire.

    `colonne` vaut `None` quand l'écart porte sur la table entière — une table
    absente, un volume qui s'effondre. Le champ existe quand même : un lecteur
    qui devrait deviner sa présence finirait par écrire un `.get()` de trop.

    `ampleur` est **un champ de premier rang et non un détail** (phase 4.4) :
    c'est le 4ᵉ terme de la signature d'anomalie, celui qui décide si un écart
    déjà refusé doit rester silencieux ou reparler. Chaque famille nomme sa
    propre ampleur — un taux, un décompte, un score — parce qu'elle seule sait
    ce qui, chez elle, veut dire « plus grave ». L'aller chercher après coup
    dans `details` demanderait au lecteur de connaître un format par famille,
    exactement ce que la forme commune existe pour éviter.

    `None` est un cas légitime : une table est absente ou elle ne l'est pas, il
    n'y a pas de « plus ou moins ». La signature porte alors `n/a`.
    """
    assert famille in FAMILLES, f"famille inconnue : {famille!r}"
    return {
        "famille": famille,
        "table": table,
        "colonne": colonne,
        "type": type,
        "observe": observe,
        "reference": reference,
        "ampleur": ampleur,
        "dama": dama,
        "details": details,
    }
