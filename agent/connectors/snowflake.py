"""Connecteur Snowflake — **le seul fichier de `agent/` où du SQL a le droit d'exister**.

C'est la couture du socle (phase 4.0). Au-dessus de ce fichier, l'agent ne
manipule que des dictionnaires : `profile`, `detect`, `diagnose` ignorent qu'une
base de données existe. Un test (`tests/test_socle.py::test_aucun_sql_hors_des_connecteurs`)
échoue si une requête apparaît ailleurs sous `agent/`.

## La règle qui gouverne ce fichier : constater, ne pas trébucher

Une table déclarée dans le registre mais **absente** de la base ne fait pas lever
le connecteur — il retourne `None`. Sans ça, `detect` ne pourrait jamais signaler
une table disparue : le run planterait avant, et le pire incident possible
ressemblerait à un bug d'infrastructure. L'agent doit **constater** l'absence,
pas mourir dessus.

La réciproque est vraie aussi : un registre **mal écrit** (une `batch_column` qui
n'existe pas) lève, lui, immédiatement. Ce n'est pas une anomalie de donnée, c'est
une erreur de déclaration — et la masquer reviendrait à profiler la table entière
en croyant filtrer un lot, ce qui diluerait précisément l'anomalie qu'on cherche.

## Ce que ce connecteur ne fait pas

Il ne touche **jamais** au schéma `OPS`. `OPS` n'est pas le système observé, c'est
la mémoire de l'agent (`_SCHEMA_HISTORY`, `_PROFILES`, `INCIDENTS`). Les inclure
dans `list_tables()` ferait apparaître la mémoire de l'agent comme « tables non
déclarées » à chaque run — l'agent se découvrirait lui-même, indéfiniment.
"""

import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Optional

import snowflake.connector
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent.parent

# Schémas que l'agent ne surveille pas : sa propre mémoire, et les vues système.
SCHEMAS_INTERNES = ("OPS", "INFORMATION_SCHEMA")

# Un identifiant Snowflake acceptable. Les noms de tables viennent d'un YAML
# écrit à la main : ils sont interpolés dans du SQL, donc jamais paramétrables.
# Ce filtre est la seule chose qui sépare une faute de frappe d'une injection.
IDENTIFIANT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


class TableMalNommee(Exception):
    """Le nom déclaré n'est pas un `SCHEMA.TABLE` exploitable."""


class DeclarationFausse(Exception):
    """Le registre décrit une colonne que la table ne possède pas."""


def ouvrir_connexion(base: str):
    """Ouvre une connexion Snowflake depuis le `.env` (même contrat que `ingestion/`).

    Extraite de la classe parce que **deux clients** en ont besoin, et qu'ils ne
    jouent pas le même rôle : `ConnecteurSnowflake` lit le système *observé*,
    `agent/connectors/ops.py` lit et écrit la *mémoire de l'agent* (ADR 010,
    décision 8). Ils partagent le pilote, pas la responsabilité — et le jour où
    le système observé sera ailleurs, seul le premier changera.
    """
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=base,
        login_timeout=15,
    )


def _decouper(table: str) -> tuple[str, str]:
    """`"RAW.ORDERS"` -> `("RAW", "ORDERS")`, en refusant tout le reste.

    La qualification est exigée plutôt que déduite d'un schéma par défaut : sur
    un pipeline Medallion, la couche *est* le schéma. Laisser `ORDERS` sans
    préfixe rendrait ambigu ce qu'on profile — RAW, STAGING ou MARTS.
    """
    morceaux = table.split(".")
    if len(morceaux) != 2 or not all(IDENTIFIANT.match(m) for m in morceaux):
        raise TableMalNommee(
            f"Nom de table invalide : {table!r} — attendu `SCHEMA.TABLE` "
            f"(lettres, chiffres, `_`, `$` ; pas d'espace ni de guillemet)"
        )
    return morceaux[0], morceaux[1]


def _json_sur(valeur):
    """Rend une valeur Snowflake sérialisable — les profils finiront en JSON.

    `Decimal` et les dates ne passent pas `json.dumps`. On les convertit ici
    plutôt qu'au moment de l'écriture : le profil doit être du JSON dès sa
    sortie du connecteur, sinon chaque appelant devra y penser.
    """
    if valeur is None or isinstance(valeur, (bool, int, float, str)):
        return valeur
    if isinstance(valeur, Decimal):
        return float(valeur)
    return str(valeur)


class ConnecteurSnowflake:
    """Accès en lecture à la base surveillée. Quatre méthodes, pas une de plus."""

    def __init__(self, base: Optional[str] = None):
        load_dotenv(RACINE / ".env")
        self.base = base or os.environ.get("SNOWFLAKE_DATABASE", "")
        self._conn = None

    # --- connexion ---------------------------------------------------------

    def _curseur(self):
        """Ouvre la connexion au premier besoin, la réutilise ensuite.

        Paresseux volontairement : construire un `ConnecteurSnowflake` ne doit
        rien coûter et ne rien exiger. C'est ce qui permet aux tests d'importer
        le module sans `.env` et sans réseau.
        """
        if self._conn is None:
            self._conn = ouvrir_connexion(self.base)
        return self._conn.cursor()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- les quatre méthodes du contrat ------------------------------------

    def list_tables(self) -> list[str]:
        """Les tables et vues réellement présentes, en `SCHEMA.TABLE`.

        C'est la source de vérité de la famille *inventaire* (4.3) : ce que la
        base contient vraiment, à confronter à ce que le registre déclare.
        """
        exclus = ", ".join("%s" for _ in SCHEMAS_INTERNES)
        curseur = self._curseur()
        curseur.execute(
            f"SELECT TABLE_SCHEMA, TABLE_NAME "
            f"FROM {self.base}.INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA NOT IN ({exclus}) "
            f"ORDER BY TABLE_SCHEMA, TABLE_NAME",
            SCHEMAS_INTERNES,
        )
        return [f"{schema}.{nom}" for schema, nom in curseur.fetchall()]

    def get_schema(self, table: str) -> Optional[list[dict]]:
        """Les colonnes de la table, ou **None si elle n'existe pas**.

        Forme d'une colonne : `{"name": str, "type": str, "position": int}` —
        la même que `schema_history` dans l'état, pour que `detect` compare des
        objets de même forme sans traduction intermédiaire.
        """
        schema, nom = _decouper(table)
        curseur = self._curseur()
        curseur.execute(
            f"SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION "
            f"FROM {self.base}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            f"ORDER BY ORDINAL_POSITION",
            (schema, nom),
        )
        lignes = curseur.fetchall()
        # Zéro colonne = zéro ligne dans INFORMATION_SCHEMA = la table n'existe
        # pas. On ne lève pas : c'est un constat, et `detect` en fera un incident.
        if not lignes:
            return None
        return [{"name": c, "type": t, "position": p} for c, t, p in lignes]

    def profile(
        self,
        table: str,
        batch_column: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Résume un lot en agrégats. **None si la table n'existe pas.**

        Jamais une ligne brute : uniquement des compteurs, des cardinalités et
        des bornes. C'est ce qui garantit structurellement que le LLM ne verra
        jamais une donnée réelle (règle R2) — il n'y a rien à fuiter ici.

        `batch_column` absent (ou `batch_id` absent) → toute la table est
        profilée. C'est le cas normal des agrégats Gold, reconstruits en entier.

        ⚠️ `min`/`max` suivent le type **de la colonne en base**. En Bronze tout
        est VARCHAR (choix de la phase 2.1) : la comparaison y est donc
        lexicographique, et `"8000" < "90"`. Les bornes numériques ne prennent
        leur sens qu'à partir de Silver, où dbt a typé.
        """
        colonnes = self.get_schema(table)
        if colonnes is None:
            return None

        noms = [c["name"] for c in colonnes]
        schema, nom = _decouper(table)

        where, parametres = self._filtre_de_lot(table, noms, batch_column, batch_id)

        # Un seul passage sur la table : 4 agrégats par colonne, lus par
        # position plutôt que par alias (les alias devraient être échappés, et
        # certains noms de colonnes dépasseraient la longueur maximale).
        agregats = ", ".join(
            f'COUNT("{c}"), COUNT(DISTINCT "{c}"), MIN("{c}"), MAX("{c}")' for c in noms
        )
        curseur = self._curseur()
        curseur.execute(
            f"SELECT COUNT(*), {agregats} FROM {schema}.{nom}{where}", parametres
        )
        ligne = curseur.fetchone()

        total = int(ligne[0])
        fiche = {}
        for index, colonne in enumerate(noms):
            renseignes, distincts, mini, maxi = ligne[1 + index * 4 : 5 + index * 4]
            manquants = total - int(renseignes)
            fiche[colonne] = {
                "null_count": manquants,
                # Sur une table vide, 0/0 vaut 0 % et non « indéfini » : une table
                # vide est un problème de volume, pas un problème de nullité.
                "null_rate": round(manquants / total, 6) if total else 0.0,
                "distinct": int(distincts),
                "min": _json_sur(mini),
                "max": _json_sur(maxi),
            }

        return {
            "table": table,
            "batch_id": batch_id,
            "row_count": total,
            "columns": fiche,
        }

    def top_values(
        self,
        table: str,
        column: str,
        k: int,
        batch_column: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Les `k` valeurs les plus fréquentes d'une colonne, et leur poids.

        C'est **la** méthode qui rend la détection sémantique possible : le
        profil sait qu'il y a 8 000 villes distinctes, il ne sait pas
        *lesquelles*. Sans les valeurs, `sao paulo` et `são paulo` restent deux
        unités indiscernables dans un compteur.

        Rend `None` quand la question n'a pas d'objet — table absente **ou**
        colonne absente. La règle du fichier vaut ici aussi : constater, ne pas
        trébucher. Une colonne disparue est précisément l'anomalie que la phase
        4.3 doit attraper (le renommage `payment_value` → `amount` du J45) ; si
        la demander faisait lever, le run mourrait sur l'incident qu'il cherche.

        C'est la **symétrique** de `batch_column`, qui lève : celle-là est
        *déclarée* par un humain dans le registre, donc son absence est une
        erreur de déclaration. La colonne profilée, elle, vient de
        l'introspection : son absence est un fait observé.

        Forme rendue :

            {"table", "column", "batch_id", "k",
             "non_null_count": int,          lignes renseignées du lot
             "coverage": float,              part de ces lignes couverte par le top-K
             "top": [{"value", "count"}, …]} du plus fréquent au moins fréquent

        `coverage` est ce qui dit si la colonne mérite qu'on la lise : proche de
        1, quelques valeurs suffisent à décrire la colonne (elle est
        catégorielle) ; proche de 0, c'est une longue traîne — du texte libre ou
        un identifiant, dont le top-K n'apprend rien et ne doit pas partir vers
        le modèle. Et `len(top) < k` signifie qu'on a vu **toute** la colonne, pas
        seulement sa tête.

        Les NULL sont exclus du décompte : ils sont déjà mesurés par `profile`,
        et les garder mangerait un rang du top-K sans rien apprendre.

        `k` n'a volontairement **pas** de valeur par défaut ici : combien de
        valeurs on regarde est un réglage de *détection*, pas une propriété du
        moteur. Il appartient à l'appelant (`agent/tools/top_values.py`), et
        rejoindra `agent/config.py` avec les autres seuils en 4.3.
        """
        if k < 1:
            raise ValueError(f"`k` doit valoir au moins 1 — reçu {k!r}")

        colonnes = self.get_schema(table)
        if colonnes is None:
            return None

        noms = [c["name"] for c in colonnes]
        reelle = next((c for c in noms if c.upper() == column.upper()), None)
        if reelle is None:
            return None

        schema, nom = _decouper(table)
        where, parametres = self._filtre_de_lot(table, noms, batch_column, batch_id)
        renseignee = f'"{reelle}" IS NOT NULL'
        where = f"{where} AND {renseignee}" if where else f" WHERE {renseignee}"

        # `SUM(COUNT(*)) OVER ()` rend le total des lignes renseignées du lot :
        # la fenêtre s'applique après le GROUP BY et **avant** le LIMIT, donc
        # elle compte tous les groupes, pas seulement les k retenus. C'est ce
        # qui permet de calculer `coverage` sans une seconde requête.
        #
        # Le départage à égalité (`, "col" ASC`) n'est pas cosmétique : sans lui
        # le k-ième rang basculerait d'un run à l'autre entre deux valeurs de
        # même fréquence, et une détection qui dépend du top-K deviendrait
        # intermittente. Même raison qu'au repli des variantes en phase 1.5.
        curseur = self._curseur()
        curseur.execute(
            f'SELECT "{reelle}", COUNT(*), SUM(COUNT(*)) OVER () '
            f"FROM {schema}.{nom}{where} "
            f'GROUP BY "{reelle}" '
            f'ORDER BY COUNT(*) DESC, "{reelle}" ASC '
            f"LIMIT {int(k)}",
            parametres,
        )
        lignes = curseur.fetchall()

        # Zéro groupe = lot vide ou colonne entièrement nulle. Ce n'est pas une
        # absence de réponse, c'est une réponse : la colonne ne porte rien.
        total = int(lignes[0][2]) if lignes else 0
        top = [
            {"value": _json_sur(valeur), "count": int(compte)}
            for valeur, compte, _ in lignes
        ]

        return {
            "table": table,
            "column": reelle,
            "batch_id": batch_id,
            "k": k,
            "non_null_count": total,
            "coverage": (
                round(sum(v["count"] for v in top) / total, 6) if total else 0.0
            ),
            "top": top,
        }

    # --- interne -----------------------------------------------------------

    def _filtre_de_lot(
        self,
        table: str,
        colonnes: list[str],
        batch_column: Optional[str],
        batch_id: Optional[str],
    ) -> tuple[str, tuple]:
        """Construit le `WHERE` du lot — ou rien du tout.

        La colonne déclarée est résolue **sans tenir compte de la casse** :
        Snowflake replie les identifiants non quotés en majuscules, si bien que
        le `_batch_id` écrit dans le registre est stocké `_BATCH_ID`. Exiger la
        casse exacte ferait échouer un registre pourtant juste.
        """
        if not batch_column or batch_id is None:
            return "", ()

        reelle = next((c for c in colonnes if c.upper() == batch_column.upper()), None)
        if reelle is None:
            # Erreur de déclaration, pas anomalie de donnée : on lève. Profiler
            # la table entière en croyant filtrer un lot diluerait l'anomalie
            # cherchée — 30 % de nulls sur un jour ne pèsent plus rien sur 92.
            raise DeclarationFausse(
                f"`batch_column: {batch_column}` déclarée pour {table}, "
                f"mais la table ne possède pas cette colonne — présentes : {colonnes}"
            )
        return f' WHERE "{reelle}" = %s', (batch_id,)
