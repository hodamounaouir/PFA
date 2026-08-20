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


# ---------------------------------------------------------------------------
# Lecture seule (phase 4.1.6)
# ---------------------------------------------------------------------------
#
# `controler()` ci-dessus juge une correction *proposée* : elle a le droit
# d'écrire, on vérifie seulement qu'elle n'écrit pas n'importe où. `lecture_seule()`
# répond à une autre question — cette requête peut-elle modifier quoi que ce
# soit ? — et sa réponse doit être « non » sans la moindre nuance.

# Les verbes qui ont le droit d'ouvrir une requête. **Une liste blanche, et pas
# seulement une liste noire de mots interdits.** Une liste noire ne protège que
# de ce qu'on a pensé à y mettre : un `COPY INTO`, un `PUT`, un `CALL` vers une
# procédure, une syntaxe ajoutée par une version future du moteur — tout ce qui
# n'y figure pas passe. Une liste blanche inverse la charge : ce qui n'est pas
# explicitement autorisé est refusé, y compris ce qui n'existe pas encore.
VERBES_DE_LECTURE = ("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN")

# Et la liste noire **en plus**, pour ce qui se cache après un verbe autorisé.
# `SELECT 1; DROP TABLE x` commence bien par SELECT.
MOTS_CLES_D_ECRITURE = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "CREATE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "COPY",
    "PUT",
    "REMOVE",
    "CALL",
    "EXECUTE",
    "UNDROP",
    "USE",
)


def lecture_seule(sql: Optional[str]) -> list[str]:
    """Ce qui empêche cette requête d'être en lecture seule. Vide = elle l'est.

    Trois barrières, et la troisième est celle qu'on oublie :

    1. le premier verbe doit être un verbe de lecture (liste blanche) ;
    2. aucun mot-clé d'écriture nulle part (liste noire, en plus de la blanche) ;
    3. **une seule instruction** — `SELECT 1; DROP TABLE x` franchit les deux
       premières sans peine. Un point-virgule final est toléré : c'est une
       habitude d'écriture, pas une seconde instruction.
    """
    if not sql or not isinstance(sql, str):
        return ["requête vide"]

    normalise = _normaliser(sql).rstrip(";").strip()
    if not normalise:
        return ["requête vide"]

    refus = []

    premier = normalise.split(None, 1)[0].lstrip("(")
    if premier not in VERBES_DE_LECTURE:
        refus.append(
            f"une requête de lecture commence par {' ou '.join(VERBES_DE_LECTURE)} — "
            f"reçu {premier}"
        )

    for mot in MOTS_CLES_D_ECRITURE:
        if re.search(rf"\b{re.escape(mot)}\b", normalise):
            refus.append(f"mot-clé d'écriture : {mot}")

    if ";" in normalise:
        refus.append("plusieurs instructions : une requête, une seule")

    return refus
