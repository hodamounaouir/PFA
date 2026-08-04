"""Les connecteurs : la seule porte entre l'agent et une base (phase 4.0).

## Le contrat

Un connecteur expose **quatre méthodes**, et l'agent ne lui demande jamais rien
d'autre :

    list_tables()                              -> list[str]        les tables réellement présentes
    get_schema(table)                          -> list[dict]|None  les colonnes, ou None si absente
    profile(table, batch_column, batch_id)     -> dict|None        des agrégats, ou None si absente
    top_values(table, column, k,               -> dict|None        les k valeurs les plus fréquentes,
               batch_column, batch_id)                             ou None si table/colonne absente

`profile` reçoit **la colonne de lot et sa valeur**, jamais un fragment de SQL.
La nuance n'est pas cosmétique : si l'appelant passait `"_batch_id = '2018-04-29'"`,
du SQL existerait au-dessus de cette couche — c'est-à-dire exactement ce que le
socle sert à empêcher. Le connecteur reçoit des données, il fabrique le SQL.

**Pourquoi `top_values` est une méthode et non un cas de `profile`** (phase 4.1.2) :
`profile` fait *un* passage sur la table et rend la même chose pour toutes les
colonnes. Un top-K coûte un `GROUP BY` **par colonne** — l'imposer à toutes
multiplierait le coût du profilage par le nombre de colonnes, pour un résultat
sans intérêt sur un identifiant ou du texte libre. Les deux ne se paient pas au
même prix, donc elles ne se demandent pas ensemble.

## Fermer, quand il y a quelque chose à fermer

`close()` ne fait **pas** partie du contrat : un connecteur en mémoire n'a rien
à fermer, et l'exiger de tous obligerait chacun à écrire une méthode vide. Les
appelants passent donc par `fermer(connecteur)`, qui ferme si le connecteur sait
le faire — la règle vit à un seul endroit plutôt que dans chaque tool.

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


def fermer(connecteur) -> None:
    """Ferme le connecteur s'il a quelque chose à fermer, sinon ne fait rien.

    Un run interrompu ne doit pas laisser une session ouverte derrière lui : le
    warehouse Snowflake se suspend au bout de 60 s, mais la session, elle,
    traîne. Un connecteur en mémoire, lui, n'a rien à libérer — d'où le `getattr`
    plutôt qu'une méthode obligatoire dans le contrat.
    """
    close = getattr(connecteur, "close", None)
    if callable(close):
        close()


def _fabrique_snowflake():
    # Import différé : `import agent.connectors` ne doit pas exiger le driver
    # Snowflake ni les variables d'environnement. Seul un appel effectif à
    # `ouvrir("snowflake")` les réclame.
    from agent.connectors.snowflake import ConnecteurSnowflake

    return ConnecteurSnowflake()


enregistrer("snowflake", _fabrique_snowflake)
