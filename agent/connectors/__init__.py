"""Les connecteurs : la seule porte entre l'agent et une base (phase 4.0).

## Le contrat

Un connecteur expose **trois méthodes**, et l'agent ne lui demande jamais rien
d'autre :

    list_tables()                          -> list[str]        les tables réellement présentes
    get_schema(table)                      -> list[dict]|None  les colonnes, ou None si absente
    profile(table, batch_column, batch_id) -> dict|None        des agrégats, ou None si absente

`profile` reçoit **la colonne de lot et sa valeur**, jamais un fragment de SQL.
La nuance n'est pas cosmétique : si l'appelant passait `"_batch_id = '2018-04-29'"`,
du SQL existerait au-dessus de cette couche — c'est-à-dire exactement ce que le
socle sert à empêcher. Le connecteur reçoit des données, il fabrique le SQL.

## Aucune classe abstraite — et pourquoi (ADR 010, décision 7)

Le projet n'a **qu'un seul backend réel** : Snowflake. Écrire une classe abstraite
pour une implémentation unique, c'est de la généralisation spéculative : on paie
aujourd'hui une souplesse dont on ne connaît pas encore la forme.

Ce qu'on garde à la place, c'est la **couture** : tout le SQL du projet vit sous
`agent/connectors/`, et un test (`tests/test_socle.py`) échoue si une requête
apparaît ailleurs dans `agent/`. La discipline qu'aurait imposée l'héritage est
donc imposée par un test — qui, lui, ne peut pas être contourné par distraction.

Le jour où un second backend arrive, extraire l'interface est un refactor
mécanique d'un seul fichier, parce que la couture est déjà là.

## Ajouter un connecteur

    from agent import connectors
    connectors.enregistrer("csv", lambda: MonConnecteurCSV(...))

Le nom enregistré est celui qu'un registre écrira dans son champ `connector`.
"""

from typing import Callable

# nom déclaré dans `datasets/*.yaml`  ->  fabrique sans argument
_FABRIQUES: dict[str, Callable[[], object]] = {}


class ConnecteurInconnu(Exception):
    """Le registre demande un connecteur qui n'est pas enregistré."""


def enregistrer(nom: str, fabrique: Callable[[], object]) -> None:
    """Associe un nom de connecteur à sa fabrique.

    Une *fabrique* et non une instance : ouvrir une connexion coûte cher et
    demande des secrets. On ne la crée qu'au moment où quelqu'un la réclame —
    ce qui permet à la suite de tests d'importer `agent/` sans Snowflake, sans
    `.env` et sans réseau.
    """
    _FABRIQUES[nom] = fabrique


def enregistres() -> tuple[str, ...]:
    """Les noms de connecteurs disponibles (pour les messages d'erreur, et les tests)."""
    return tuple(sorted(_FABRIQUES))


def ouvrir(nom: str):
    """Instancie le connecteur nommé. Lève `ConnecteurInconnu` si le nom est faux."""
    fabrique = _FABRIQUES.get(nom)
    if fabrique is None:
        raise ConnecteurInconnu(
            f"Connecteur {nom!r} inconnu — enregistrés : {', '.join(enregistres()) or '(aucun)'}"
        )
    return fabrique()


def _fabrique_snowflake():
    # Import différé : `import agent.connectors` ne doit pas exiger le driver
    # Snowflake ni les variables d'environnement. Seul un appel effectif à
    # `ouvrir("snowflake")` les réclame.
    from agent.connectors.snowflake import ConnecteurSnowflake

    return ConnecteurSnowflake()


enregistrer("snowflake", _fabrique_snowflake)
