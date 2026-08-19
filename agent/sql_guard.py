"""Garde-fou sur le SQL proposé par le modèle (phase 4.4).

**Première ligne de défense, pas la dernière.** `apply` re-vérifiera en phase 5,
et c'est lui qui refusera d'exécuter. Ici on se contente de *constater* ce qui
cloche et de l'attacher au diagnostic, pour que l'humain le voie **avant** de
décider — pas après.

Pourquoi deux contrôles au lieu d'un : celui-ci s'exerce sur une proposition que
personne n'a encore approuvée, celui d'`apply` sur une décision déjà prise. Le
premier informe, le second protège. Confondre les deux reviendrait soit à
laisser passer une proposition dangereuse jusqu'à l'écriture, soit à cacher à
l'humain la raison pour laquelle on la lui refusera ensuite.

## Ce qui est refusé

    mot-clé destructeur   DROP, TRUNCATE, ALTER, GRANT, DELETE sans WHERE…
    table étrangère       une table que le diagnostic ne concerne pas

Le second est le moins évident et le plus utile : un modèle qui diagnostique
`RAW.ORDERS` n'a aucune raison d'écrire dans `MARTS.FCT_DAILY_SALES`, et une
correction qui déborde de sa table est soit une hallucination, soit bien pire.

## Ce que ce module ne fait **pas**

Il ne parse pas le SQL. Une analyse syntaxique complète donnerait une fausse
impression d'exhaustivité — un moteur accepte des formes qu'aucun parseur maison
ne couvre. On cherche des **motifs**, on le dit, et la vraie garantie reste
structurelle : `apply` est inatteignable sans approbation humaine (P3), et la
règle « ne jamais inventer une valeur » (P6) est vérifiée séparément.
"""

import re
from typing import Optional

# Les mots-clés qui n'ont rien à faire dans une correction de qualité de
# données. `DELETE` n'y est pas seul : c'est `DELETE` **sans `WHERE`** qui vide
# une table, et le distinguer évite de refuser la correction la plus naturelle
# qui soit (« supprimer les lignes dupliquées de ce lot »).
MOTS_CLES_DESTRUCTEURS = (
    "DROP",
    "TRUNCATE",
    "ALTER",
    "GRANT",
    "REVOKE",
    "CREATE OR REPLACE",
    "MERGE",
)

# `RAW.ORDERS`, `MARTS.FCT_DAILY_SALES` — un nom qualifié, la forme que le
# registre déclare et la seule que l'agent manipule.
TABLE_QUALIFIEE = re.compile(r"\b([A-Za-z_][\w$]*\.[A-Za-z_][\w$]*)\b")


def _normaliser(sql: str) -> str:
    return " ".join(sql.upper().split())


def controler(sql: Optional[str], table: str) -> list[str]:
    """Ce qui cloche dans ce SQL, en clair. Liste vide = rien à signaler.

    Des phrases et non des codes : elles finissent sous les yeux de l'humain qui
    décide, dans la proposition puis dans `INCIDENTS`. « mot-clé destructeur
    DROP » se comprend sans documentation ; `E_DESTRUCTIVE_KW` non.
    """
    if not sql or not isinstance(sql, str):
        return []

    normalise = _normaliser(sql)
    alertes = []

    for mot in MOTS_CLES_DESTRUCTEURS:
        if re.search(rf"\b{re.escape(mot)}\b", normalise):
            alertes.append(f"mot-clé destructeur : {mot}")

    if re.search(r"\bDELETE\b", normalise) and not re.search(r"\bWHERE\b", normalise):
        alertes.append("DELETE sans WHERE : la table entière serait vidée")

    etrangeres = sorted(
        nom for nom in set(TABLE_QUALIFIEE.findall(normalise)) if nom != table.upper()
    )
    for nom in etrangeres:
        alertes.append(f"table étrangère au diagnostic : {nom} (attendu {table})")

    return alertes
