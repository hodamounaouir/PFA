"""Tool `profile_table` — l'assembleur : une table, une fiche (phase 4.1.5).

C'est le point où 4.1 devient consommable par 4.3. Jusqu'ici l'agent disposait
de trois mesures séparées et d'aucune vue d'ensemble : les agrégats du
connecteur (`profile`), les valeurs fréquentes (`top_values`), la position et la
dispersion (`robust_stats`). `profile_table` les demande dans le bon ordre et
les range dans une seule fiche — celle que `detect` lira, et que `OPS._PROFILES`
archivera.

## Le critère provisoire, et pourquoi il vit ici

Chaque mesure de colonne coûte une requête dédiée ([ADR 010](../../docs/adr/010-agent-generique.md),
décision 10a) : les demander toutes sur toutes les colonnes multiplierait le
coût du profilage par le nombre de colonnes, pour un résultat sans intérêt (le
top-K d'un identifiant) ou impossible (la médiane d'un texte libre). Il faut
donc **choisir**, et quelqu'un doit porter ce choix.

Décision (2026-08-04) : c'est `profile_table` qui le porte, pour qu'il soit
appelable seul — `profile_table("olist", "RAW.ORDERS", "2018-04-29")` et rien
d'autre. La **caractérisation par rôle** de 4.2 remplacera `_mesure_pour()` par
un vrai classement (identifiant, clé étrangère, catégoriel, numérique, temporel,
texte libre) ; c'est cette fonction-là, et elle seule, qui changera.

## Ce que le critère regarde — et ce qu'il ne regarde pas

Il ne regarde **jamais le nom du type SQL**. Ni `VARCHAR`, ni `NUMBER`, ni
`TEXT` : ces mots sont du vocabulaire Snowflake, et un tool qui les
interpréterait ferait entrer un dialecte de base dans une couche qui doit les
ignorer (ADR 010, décision 2). Il ne lit que des **faits mesurés**, disponibles
pour n'importe quel backend :

| Ce qu'on observe | Ce qu'on en déduit | Mesure |
|---|---|---|
| aucune valeur distincte | colonne vide sur ce lot | aucune |
| min **et** max se lisent comme des nombres | la colonne porte des quantités | `robust_stats` |
| cardinalité ≤ 50 % des lignes | la colonne se répète, donc elle catégorise | `top_values` |
| le reste (identifiants, texte libre) | rien d'exploitable à ce stade | aucune |

**Le test par les bornes est ce qui sauve Bronze.** Là-bas tout est VARCHAR par
construction (phase 2.1) : un critère fondé sur le type déclaré n'y trouverait
*aucune* colonne numérique — donc aucune statistique sur la couche où les
anomalies sont précisément injectées. Les bornes, elles, disent la vérité :
`min="0.00"`, `max="99.99"` est une colonne de montants, quel que soit son type.

## Les deux imprécisions assumées

1. **Un code postal est « lisible comme un nombre ».** Il recevra donc une
   médiane, qui ne veut rien dire. Le critère confond « écrit comme un nombre »
   et « est une quantité » — c'est exactement la distinction *identifiant* vs
   *numérique* que le classement par rôle de 4.2 tranchera.
2. **Une colonne de dates peu variée peut recevoir un top-K.** Sans intérêt,
   sans danger ; 4.2 lui donnera le rôle *temporel* et la fraîcheur (4.1.4).

Le seuil de cardinalité penche volontairement **du côté généreux** : rater une
colonne catégorielle, c'est rater une détection ; en mesurer une de trop, c'est
une requête, et `coverage` le dit tout de suite.
"""

import re
from typing import Optional

from langchain_core.tools import tool

from agent.tools._connecteur import connecteur_pour
from agent.tools.top_values import TOP_K_DEFAUT

# Au-delà, la colonne ne catégorise plus : elle identifie (cardinalité ≈ lignes)
# ou elle raconte (texte libre). Réglage de détection — il rejoindra
# `agent/config.py` en 4.3, et le vrai critère viendra de 4.2.
RATIO_CARDINALITE_MAX = 0.5

# Un nombre écrit. Volontairement plus strict que `float()`, qui accepte `nan`,
# `inf` et `1_000` : une ville nommée « nan » passerait pour une quantité.
NOMBRE_ECRIT = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _lisible_comme_nombre(valeur) -> bool:
    """La valeur est-elle un nombre, ou l'écriture d'un nombre ?

    Les deux cas comptent : en Silver une borne arrive déjà typée, en Bronze
    elle arrive en texte. C'est le seul endroit où la différence est absorbée.
    """
    if valeur is None or isinstance(valeur, bool):
        return False
    if isinstance(valeur, (int, float)):
        return True
    return bool(NOMBRE_ECRIT.match(str(valeur).strip()))


def _mesure_pour(stats: dict, row_count: int) -> Optional[str]:
    """`"robust_stats"`, `"top_values"`, ou rien — le critère provisoire de 4.1.

    **C'est cette fonction que la phase 4.2 remplace**, et elle seule : tout le
    reste de l'assembleur est indifférent à la façon dont le choix est fait.
    """
    if not row_count or not stats.get("distinct"):
        # Table vide, ou colonne entièrement nulle sur ce lot : il n'y a rien à
        # regarder, et `profile` a déjà dit qu'il n'y avait rien.
        return None

    if _lisible_comme_nombre(stats.get("min")) and _lisible_comme_nombre(
        stats.get("max")
    ):
        return "robust_stats"

    if stats["distinct"] / row_count <= RATIO_CARDINALITE_MAX:
        return "top_values"

    return None


def _assembler(connecteur, table: str, batch_column, batch_id) -> Optional[dict]:
    """Le corps du tool, séparé pour être éprouvé sans passer par LangChain."""
    profil = connecteur.profile(table, batch_column, batch_id)
    if profil is None:
        return None

    # Le schéma pour le type et la position : ils ne servent pas au critère
    # (qui ignore les noms de types), mais `detect` compare des schémas et
    # l'ordre des colonnes fait partie de ce qu'il regarde.
    colonnes = connecteur.get_schema(table) or []
    lignes = profil["row_count"]
    fiche = {}

    for colonne in colonnes:
        nom = colonne["name"]
        stats = dict(profil["columns"].get(nom, {}))
        stats["type"] = colonne.get("type")
        stats["position"] = colonne.get("position")

        voulue = _mesure_pour(stats, lignes)
        obtenue = None

        if voulue == "top_values":
            mesure = connecteur.top_values(
                table, nom, TOP_K_DEFAUT, batch_column, batch_id
            )
            if mesure is not None:
                stats["top"] = mesure["top"]
                stats["coverage"] = mesure["coverage"]
                obtenue = voulue
        elif voulue == "robust_stats":
            mesure = connecteur.robust_stats(table, nom, batch_column, batch_id)
            if mesure is not None:
                stats["median"] = mesure["median"]
                stats["mad"] = mesure["mad"]
                stats["numeric_rate"] = mesure["numeric_rate"]
                # ⚠️ **Surtout pas `min`/`max`** : ceux du profil sont
                # lexicographiques sur Bronze (`"8000" < "90"`), ceux-ci sont
                # numériques. Les écraser ferait croire à une borne qui n'a pas
                # été mesurée de cette façon — et la comparaison de bornes en
                # 4.3 porterait sur deux grandeurs différentes selon la couche.
                stats["numeric_min"] = mesure["min"]
                stats["numeric_max"] = mesure["max"]
                obtenue = voulue

        # `measure` n'est posé qu'après une mesure réussie : une fiche qui
        # annonce un top-K sans le porter ferait planter son lecteur.
        stats["measure"] = obtenue
        fiche[nom] = stats

    return {
        "table": table,
        "batch_id": batch_id,
        "row_count": lignes,
        "columns": fiche,
    }


@tool
def profile_table(dataset: str, table: str, batch_id: str = "") -> Optional[dict]:
    """La fiche complète d'une table sur un lot : agrégats, top-K et stats.

    `dataset` est le nom d'un registre (`datasets/<dataset>.yaml`), `table` un
    nom qui y est déclaré. `batch_id` vide signifie « toute la table », comme
    pour un agrégat Gold qui n'a pas de notion de lot.

    Rend `{"table", "batch_id", "row_count", "columns"}`, ou `None` si la table
    n'existe pas. Chaque colonne porte ses agrégats (`null_count`, `null_rate`,
    `distinct`, `min`, `max`, `type`, `position`) et, selon ce que le critère a
    décidé, `measure` valant :

    - `"top_values"` → `top` et `coverage` en plus ;
    - `"robust_stats"` → `median`, `mad`, `numeric_rate`, `numeric_min`,
      `numeric_max` en plus ;
    - `None` → rien de plus, la colonne n'a reçu aucune mesure dédiée.

    `numeric_min`/`numeric_max` ne remplacent pas `min`/`max` : sur Bronze les
    premiers sont numériques et les seconds lexicographiques (`"8000" < "90"`),
    et ils ne répondent pas à la même question.

    ⚠️ Coût : une requête d'agrégats pour la table, plus **une requête par
    colonne mesurée**. Tout passe par une seule connexion.
    """
    with connecteur_pour(dataset, table) as (connecteur, declaree):
        return _assembler(connecteur, table, declaree.batch_column, batch_id or None)
