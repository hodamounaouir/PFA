"""Tool `read_schema_history` — à quoi ressemblait cette table (phase 4.1).

C'est la **référence** de la première famille de détection (4.3) : le schéma du
jour, confronté au dernier schéma connu, fait apparaître une colonne ajoutée,
disparue ou renommée. Chez Olist, c'est ce qui doit attraper le renommage
`payment_value` → `amount` du J45.

Le tool ne compare rien et ne juge rien : il rend un fait daté. La comparaison
appartient à `detect`, l'interprétation à `diagnose`, la décision à l'humain.
"""

from langchain_core.tools import tool

from agent.connectors.ops import MemoireOps


@tool
def read_schema_history(table: str, batch_id: str = "") -> list[dict]:
    """Le schéma connu d'une table, tel qu'observé à l'ingestion.

    `table` est le nom déclaré dans le registre (ex. `RAW.ORDERS`). `batch_id`
    vide signifie « le dernier batch observé ».

    Rend une liste de `{"name", "position", "batch_id"}`, les noms en majuscules
    pour être directement comparables au schéma du jour. Liste vide = table
    jamais observée : soit elle est nouvelle, soit elle vit hors de Bronze (seule
    l'ingestion alimente cet historique).
    """
    memoire = MemoireOps()
    try:
        return memoire.lire_schema(table, batch_id or None)
    finally:
        # Toujours fermer, y compris si la lecture échoue : un run interrompu ne
        # doit pas laisser une session Snowflake ouverte derrière lui — le
        # warehouse se suspend au bout de 60 s, mais la session, elle, traîne.
        memoire.close()
