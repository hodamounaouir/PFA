"""Tool `top_values` — quelles valeurs, et pas seulement combien (phase 4.1.2).

C'est le tool sans lequel **aucune détection sémantique n'est possible**. Le
profil du connecteur sait déjà qu'une colonne porte 8 000 villes distinctes ; il
ne sait pas *lesquelles*. Or `sao paulo` et `são paulo` sont, pour un compteur,
deux unités parfaitement indiscernables — il faut voir les valeurs pour voir
qu'elles n'en font qu'une. C'est ce que ce tool rend, et rien de plus : il ne
normalise pas, ne rapproche pas, ne juge pas. Les clusters de collision sont
l'affaire de `detect` (4.3), leur interprétation celle de `diagnose`, la décision
celle de l'humain.

## Le tool résout tout seul son connecteur

Un `@tool` dérive son schéma de ses arguments : on ne peut pas lui passer un
objet connecteur, seulement des valeurs simples ([ADR 004](../../docs/adr/004-langgraph-vs-function-calling.md)).
Il reçoit donc le **nom du dataset** et va lire lui-même `datasets/<dataset>.yaml`
pour savoir quel connecteur ouvrir et quelle colonne porte le lot. C'est aussi la
forme dont Airflow aura besoin en 4.5 : `(dataset, layer, table, batch_id)`.

## Le point de bascule de la règle R2 — à dire franchement

Jusqu'ici, tout ce qui remontait de la base était un **chiffre** : des comptes,
des cardinalités, des bornes. Rien à fuiter. Ce tool est le premier à rendre de
**vraies valeurs**, et l'[ADR 010](../../docs/adr/010-agent-generique.md) l'avait
identifié comme le moment où la question Groq/Cortex se reposerait sérieusement.

R2 (« le LLM ne reçoit jamais de lignes brutes ») n'est pas enfreinte : une
valeur de colonne catégorielle accompagnée de sa fréquence est une
**distribution**, pas une ligne — on ne peut pas recomposer un client à partir
de `{"sao paulo": 8 412}`. Mais la nuance ne tient que tant qu'on interroge des
colonnes **catégorielles**. Le top-K d'une adresse, d'un nom ou d'un e-mail,
lui, serait bel et bien une fuite.

D'où `coverage` dans la réponse : la part des lignes que le top-K couvre. Proche
de 1, quelques valeurs décrivent la colonne — elle est catégorielle. Proche de 0,
c'est une longue traîne, et ses valeurs n'ont rien à faire dans un prompt. Le
tool **constate** cette part ; c'est la caractérisation (4.2) qui s'en servira
pour choisir les colonnes à interroger. Un tool qui déciderait tout seul de se
taire cacherait un fait à `detect` — ce n'est pas son rôle.
"""

from typing import Optional

from langchain_core.tools import tool

from agent.tools._connecteur import connecteur_pour

# Combien de valeurs on regarde. C'est un réglage de **détection**, pas une
# propriété du moteur — d'où sa place ici plutôt que dans le connecteur, et son
# départ vers `agent/config.py` en 4.3 avec les autres seuils.
#
# 20 est un compromis assumé : assez large pour que deux variantes d'une même
# grande ville s'y retrouvent toutes les deux (le cas São Paulo), assez étroit
# pour qu'une colonne à longue traîne se trahisse par un `coverage` faible.
TOP_K_DEFAUT = 20


@tool
def top_values(
    dataset: str, table: str, column: str, batch_id: str = "", k: int = TOP_K_DEFAUT
) -> Optional[dict]:
    """Les `k` valeurs les plus fréquentes d'une colonne, dans un lot donné.

    `dataset` est le nom d'un registre (`datasets/<dataset>.yaml`), `table` un
    nom qui y est déclaré (ex. `RAW.GEOLOCATION`), `column` une colonne de cette
    table — la casse n'a pas d'importance, elle est résolue contre le schéma
    réel. `batch_id` vide signifie « toute la table », comme pour une table Gold
    qui n'a pas de notion de lot.

    Rend `{"table", "column", "batch_id", "k", "non_null_count", "coverage",
    "top": [{"value", "count"}, …]}`, du plus fréquent au moins fréquent, ou
    `None` si la table ou la colonne n'existe pas. Les NULL sont exclus : ils
    sont déjà comptés par le profil. Si `top` contient moins de `k` entrées,
    c'est qu'on a vu **toute** la colonne et pas seulement sa tête.
    """
    with connecteur_pour(dataset, table) as (connecteur, declaree):
        return connecteur.top_values(
            table, column, k, declaree.batch_column, batch_id or None
        )
