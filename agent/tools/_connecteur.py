"""Ce que tout tool qui lit la base doit faire avant de lire (phase 4.1.3).

Un `@tool` ne reçoit que des chaînes ([ADR 004](../../docs/adr/004-langgraph-vs-function-calling.md)) :
on ne peut pas lui passer un connecteur, il doit le résoudre lui-même. La suite
est toujours la même — charger le registre, y retrouver la table et sa colonne
de lot, ouvrir le connecteur déclaré, et le refermer quoi qu'il arrive.

Écrit à la deuxième occurrence, pas à la première : `top_values` (4.1.2) puis
`robust_stats` (4.1.3) faisaient les quatre gestes à l'identique, et `freshness`
(4.1.4) les refera. Ce qui compte n'est pas d'économiser douze lignes, c'est que
le message d'erreur d'une table non déclarée et la garantie de fermeture
existent **à un seul endroit** — donc qu'un troisième tool ne puisse pas les
oublier à moitié.

Le préfixe `_` le dit : ce n'est pas un tool, c'est ce sur quoi ils s'appuient.
La règle du `CONTRIBUTING` (« un fichier par tool, testé isolément ») reste tenue.
"""

from contextlib import contextmanager

from agent import connectors
from agent.registry import charger


class TableNonDeclaree(Exception):
    """On interroge une table que le registre ne surveille pas."""


@contextmanager
def connecteur_pour(dataset: str, table: str):
    """Rend `(connecteur, table_declaree)` et referme à la sortie.

    Lève `TableNonDeclaree` si la table n'est pas dans `datasets/<dataset>.yaml`.
    C'est volontairement bruyant : sans la déclaration on ignore quelle colonne
    porte le lot, donc on lirait la table **entière** en croyant lire un jour.
    Les mesures du lot se dilueraient dans 92 jours cumulés et l'anomalie
    cherchée deviendrait invisible — exactement le raisonnement qui fait lever
    une `batch_column` fausse dans le connecteur.

    Que « cette table n'est pas déclarée » soit ailleurs une *information* (la
    famille *inventaire* de 4.3 en fait un incident) ne change rien ici : c'est
    `detect` qui compare le registre au réel, pas un tool de mesure à qui on
    demande de mesurer quelque chose qui n'est pas à son programme.
    """
    registre = charger(dataset)
    declaree = registre.table(table)
    if declaree is None:
        raise TableNonDeclaree(
            f"{table!r} n'est pas déclarée dans le registre {dataset!r} — "
            f"déclarées : {', '.join(registre.noms)}"
        )

    connecteur = connectors.ouvrir(registre.connector)
    try:
        yield connecteur, declaree
    finally:
        # Fermer même si la lecture échoue : un run interrompu ne doit pas
        # laisser une session ouverte derrière lui.
        connectors.fermer(connecteur)
