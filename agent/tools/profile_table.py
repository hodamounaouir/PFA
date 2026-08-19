"""Tool `profile_table` — l'assembleur : une table, une fiche (phase 4.1.5).

C'est le point où 4.1 devient consommable par 4.3. Jusqu'ici l'agent disposait
de trois mesures séparées et d'aucune vue d'ensemble : les agrégats du
connecteur (`profile`), les valeurs fréquentes (`top_values`), la position et la
dispersion (`robust_stats`). `profile_table` les demande dans le bon ordre et
les range dans une seule fiche — celle que `detect` lira, et que `OPS._PROFILES`
archivera.

## Qui décide ce qu'on mesure

Chaque mesure de colonne coûte une requête dédiée ([ADR 010](../../docs/adr/010-agent-generique.md),
décision 10a) : les demander toutes sur toutes les colonnes multiplierait le
coût du profilage par le nombre de colonnes, pour un résultat sans intérêt (le
top-K d'un identifiant) ou impossible (la médiane d'un texte libre). Il faut
donc **choisir**.

Depuis la phase 4.2, ce n'est plus un critère bricolé ici : c'est le **rôle**
rendu par `agent/characterize/`. L'assembleur ne fait plus que traduire un rôle
en mesure, et cette traduction tient en un dictionnaire :

| Rôle | Mesure | Pourquoi |
|---|---|---|
| `categorical` | `top_values` | ses valeurs font sens — collisions sémantiques |
| `numeric` | `robust_stats` | position et dispersion, bornes numériques |
| `identifier` | aucune | un top-K de clés primaires n'apprend rien |
| `temporal` | aucune | `min`/`max` du profil **sont** déjà la fraîcheur |
| `free_text` | aucune | nulls et longueurs seulement — jamais de valeurs (R2) |
| `unknown` | aucune | la colonne n'a rien montré sur ce lot |

Le classement se fait sur les agrégats que `profile` vient de rendre : décider
ne coûte **aucune requête**, ce qui est indispensable puisque c'est la décision
qui engage les requêtes coûteuses.

## Ce que 4.2 a corrigé, et ce qui reste

Le critère provisoire de 4.1.5 lisait les bornes et la cardinalité, sans rôles.
Il se trompait sur deux cas, tous deux consignés à l'époque :

- **une colonne de dates peu variée recevait un top-K** — corrigé : elle est
  désormais `temporal` et ne reçoit plus rien ;
- **un code non unique lisible comme un nombre recevait une médiane** — *pas*
  corrigé, et ce n'est pas un oubli : rien dans les faits mesurés ne distingue
  un préfixe de code postal d'un montant. C'est une question de sens, et c'est
  la validation humaine du contrat (4.2.5) qui la tranchera.
"""

from typing import Optional

from langchain_core.tools import tool

from agent.characterize import CATEGORIEL, NUMERIQUE, classer
from agent.tools._connecteur import connecteur_pour
from agent.tools.top_values import CARDINALITE_ENUMERABLE_MAX, TOP_K_DEFAUT

# Rôle -> mesure de colonne. Les rôles absents n'en reçoivent aucune, et c'est
# une décision : voir le tableau du docstring.
MESURE_PAR_ROLE = {
    CATEGORIEL: "top_values",
    NUMERIQUE: "robust_stats",
}


# Deux étapes séparées volontairement : `classer()` dit **ce que la colonne
# est** — une propriété de la donnée, que le contrat (4.2) et `detect` (4.3)
# reliront — et `MESURE_PAR_ROLE` dit **ce qu'on lui demande**, une décision de
# profilage. Les confondre ferait qu'ajouter une mesure obligerait à toucher au
# classement.


def _k_pour(stats: dict) -> int:
    """Combien de valeurs demander à une colonne catégorielle.

    Deux régimes, et ce qui les sépare est la **preuve** :

    - cardinalité modeste → on demande tout (`k = distinct`) : la couverture
      atteint 1, et `accepted_values` devient démontrable ;
    - longue traîne → `TOP_K_DEFAUT`, et le `coverage` faible qui en résulte
      **est** l'information — il dit que la colonne ne s'énumère pas.

    `distinct` est déjà dans le profil : choisir ne coûte **aucune requête**, et
    demander 27 valeurs au lieu de 20 n'élargit qu'un `LIMIT` sur un `GROUP BY`
    déjà payé. C'est la même économie qu'en 4.2.1 — décider avec ce qu'on a
    mesuré, pas en mesurant à nouveau.

    R2 n'y perd rien, et y gagne plutôt : une colonne de moins de cent modalités
    est catégorielle par n'importe quelle mesure, c'est-à-dire exactement le
    régime où « une distribution, pas une ligne » est le plus solide. Le tool
    continue par ailleurs de **constater** sa couverture au lieu de se censurer.
    """
    distinct = stats.get("distinct") or 0
    if 0 < distinct <= CARDINALITE_ENUMERABLE_MAX:
        return distinct
    return TOP_K_DEFAUT


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

        # Le rôle est **rangé dans la fiche**, pas seulement consommé : c'est
        # lui que la proposition de contrat (4.2) et `detect` (4.3) reliront
        # pour savoir quels contrôles ont un sens sur cette colonne. Le
        # recalculer ailleurs, c'est risquer de le recalculer autrement.
        role = classer(stats, lignes)
        stats["role"] = role

        voulue = MESURE_PAR_ROLE.get(role)
        obtenue = None

        if voulue == "top_values":
            mesure = connecteur.top_values(
                table, nom, _k_pour(stats), batch_column, batch_id
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
