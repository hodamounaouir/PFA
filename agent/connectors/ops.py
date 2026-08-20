"""La mémoire de l'agent — `OPS` (phase 4.1).

Second fichier de `agent/` où du SQL a le droit d'exister, et il est ici **par
distinction, pas par commodité** : `OPS` n'est pas le système observé, c'est ce
que l'agent se souvient (`_SCHEMA_HISTORY`, `_PROFILES`, `INCIDENTS`).

La différence est structurelle (ADR 010, décision 8) : si la mémoire suivait le
connecteur, surveiller une base Postgres voudrait dire y écrire ses incidents —
la mémoire se fragmenterait en autant de bases que de datasets, et l'objectif O7
(« l'agent se souvient ») n'aurait plus de lieu où s'exercer. Le connecteur lit
ce qu'on surveille ; la mémoire reste là où l'agent vit.

## Deux pièges de la table `_SCHEMA_HISTORY`, hérités de la phase 2.1

`ingestion/load.py` la remplit à partir des CSV, ce qui a deux conséquences que
ce module absorbe une fois pour toutes :

1. **le nom de table y est le nom du fichier** — `orders`, pas `RAW.ORDERS` ;
2. **les colonnes y gardent la casse du CSV** — `order_id` — alors que Snowflake
   les stocke en majuscules (`ORDER_ID`), et que `INFORMATION_SCHEMA` les rend
   donc en majuscules.

Comparer naïvement les deux ferait apparaître **toutes** les colonnes comme
renommées, à chaque run. On normalise donc en majuscules avant de rendre : dans
Snowflake un identifiant non quoté est insensible à la casse, la casse ne fait
pas partie de l'identité d'une colonne.

## Portée, à dire honnêtement

`_SCHEMA_HISTORY` n'est écrite que par l'ingestion, donc elle ne couvre que
**Bronze**. Silver et Gold n'y figurent pas : leur dérive de schéma devra être
détectée contre le contrat (4.2), pas contre cet historique.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from agent.connectors.snowflake import ouvrir_connexion

RACINE = Path(__file__).resolve().parent.parent.parent

OPS_SCHEMA = "OPS"
SCHEMA_HISTORY = "_SCHEMA_HISTORY"
PROFILES = "_PROFILES"
INCIDENTS = "INCIDENTS"

# Ce qui est conservé d'un profil, et ce qui ne l'est pas (phase 4.3).
#
# `_PROFILES` sert **une seule chose** : comparer une mesure du jour aux mêmes
# mesures des jours précédents. Elle ne stocke donc que du **numérique**, en
# format long — une ligne par (table, lot, colonne, métrique). Trois raisons :
#
# 1. la requête de comparaison devient un `GROUP BY` avec `MEDIAN()`, donc elle
#    reste dans le connecteur au lieu de remonter en Python ;
# 2. ajouter une métrique ne demande aucun DDL — ce qui compte, puisque 4.1.3 en
#    a déjà produit une non prévue au plan (`numeric_rate`) ;
# 3. le format ne connaît aucun nom de colonne ni de métrique : il vaut pour
#    n'importe quel dataset, comme le reste du socle.
#
# Ce qui est **délibérément absent** : `top` (une liste, pas une mesure), `role`,
# `type`, et `min`/`max` **lexicographiques** — ces derniers parce qu'ils ne
# répondent pas à la même question que `numeric_min`/`numeric_max` (piège de
# 4.1.5), et les comparer d'un jour à l'autre sur Bronze n'aurait pas de sens.
# La dérive de schéma se lit dans `_SCHEMA_HISTORY`, les valeurs du jour dans le
# profil du jour : chaque question a déjà son lieu, on n'en duplique aucune ici.
METRIQUES_TABLE = ("row_count",)
METRIQUES_COLONNE = (
    "null_count",
    "null_rate",
    "distinct",
    "coverage",
    "median",
    "mad",
    "numeric_rate",
    "numeric_min",
    "numeric_max",
    # Fraîcheur (4.1.4). Les ranger ici suffit à les rendre **détectables** :
    # la famille statistique compare toute métrique numérique à son historique,
    # donc un `dates_futures` constant à 0 qui passe à 1 déclenche une
    # `rupture_de_constante` sans qu'aucun détecteur ait été écrit pour lui.
    "retard_jours",
    "amplitude_jours",
    "dates_futures",
)


class MemoireOps:
    """Accès au schéma `OPS`. Une instance par run suffit."""

    def __init__(self, base: Optional[str] = None):
        load_dotenv(RACINE / ".env")
        self.base = base or os.environ.get("SNOWFLAKE_DATABASE", "")
        self._conn = None

    def _curseur(self):
        # Même paresse que le connecteur : construire l'objet ne doit rien
        # coûter, pour que les tests l'importent sans `.env` ni réseau.
        if self._conn is None:
            self._conn = ouvrir_connexion(self.base)
        return self._conn.cursor()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def lire_schema(
        self,
        table: str,
        batch_id: Optional[str] = None,
        avant: Optional[str] = None,
    ) -> list[dict]:
        """Le schéma connu d'une table : au batch demandé, ou au dernier observé.

        Rend une liste vide si la table n'a jamais été observée — une table
        réelle a toujours au moins une colonne, la liste vide est donc sans
        ambiguïté.

        Forme d'une entrée : `{"name", "position", "batch_id"}` — `name` en
        majuscules, directement comparable à ce que rend `get_schema()` du
        connecteur.
        """
        cle = _cle_de_table(table)
        curseur = self._curseur()

        if avant is not None:
            # ⭐ Le dernier schéma connu **strictement avant** ce lot. Sans ce
            # mode, la dérive de schéma serait indétectable : l'ingestion écrit
            # `_SCHEMA_HISTORY` avant que l'agent tourne, donc « le dernier
            # schéma observé » inclurait déjà celui d'aujourd'hui — on
            # comparerait le lot à lui-même et le renommage du J45 passerait
            # inaperçu. Même raisonnement que l'exclusion du lot courant dans
            # `lire_historique` : la garantie vit dans la requête.
            curseur.execute(
                f"SELECT column_name, ordinal_position, batch_id "
                f"FROM {self.base}.{OPS_SCHEMA}.{SCHEMA_HISTORY} "
                f"WHERE LOWER(table_name) = %s AND batch_id = ("
                f"  SELECT MAX(batch_id) FROM {self.base}.{OPS_SCHEMA}.{SCHEMA_HISTORY} "
                f"  WHERE LOWER(table_name) = %s AND batch_id < %s) "
                f"ORDER BY ordinal_position",
                (cle, cle, avant),
            )
        elif batch_id is None:
            # `batch_id` est un VARCHAR au format ISO (`2018-04-29`) : l'ordre
            # lexicographique y coïncide avec l'ordre chronologique, donc MAX()
            # désigne bien le dernier batch observé.
            curseur.execute(
                f"SELECT column_name, ordinal_position, batch_id "
                f"FROM {self.base}.{OPS_SCHEMA}.{SCHEMA_HISTORY} "
                f"WHERE LOWER(table_name) = %s AND batch_id = ("
                f"  SELECT MAX(batch_id) FROM {self.base}.{OPS_SCHEMA}.{SCHEMA_HISTORY} "
                f"  WHERE LOWER(table_name) = %s) "
                f"ORDER BY ordinal_position",
                (cle, cle),
            )
        else:
            curseur.execute(
                f"SELECT column_name, ordinal_position, batch_id "
                f"FROM {self.base}.{OPS_SCHEMA}.{SCHEMA_HISTORY} "
                f"WHERE LOWER(table_name) = %s AND batch_id = %s "
                f"ORDER BY ordinal_position",
                (cle, batch_id),
            )

        return [
            {"name": nom.upper(), "position": int(position), "batch_id": lot}
            for nom, position, lot in curseur.fetchall()
        ]

    # -- Les profils : la série temporelle des mesures ----------------------

    def _creer_profiles(self, curseur) -> None:
        """Crée `OPS._PROFILES` si besoin. Même convention qu'`ingestion/load.py`
        pour `_SCHEMA_HISTORY` : c'est l'écrivain qui la pose, paresseusement.

        Conséquence voulue : rejouer l'infrastructure sur un second trial ne
        demande **aucune** étape de plus — la table réapparaît au premier profil
        écrit. C'est le plan B de l'ADR 001 appliqué à la mémoire de l'agent.
        """
        curseur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.base}.{OPS_SCHEMA}.{PROFILES} (
                dataset      VARCHAR,
                table_name   VARCHAR,
                batch_id     VARCHAR,
                column_name  VARCHAR,
                metric       VARCHAR,
                value        FLOAT,
                captured_at  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
            """
        )

    def ecrire_profil(
        self, dataset: str, table: str, batch_id: str, profil: dict
    ) -> int:
        """Range un profil dans l'historique. Rend le nombre de mesures écrites.

        ⚠️ `batch_id` est **le lot du run**, pas celui qui a servi à filtrer le
        profilage — et la nuance décide si l'historique existe. Un mart Gold n'a
        pas de colonne de lot : `profil["batch_id"]` y vaut toujours `None`, si
        bien qu'en prenant cette valeur pour clé, chaque run écraserait le
        précédent et **Gold n'accumulerait jamais d'historique**. La couche où
        les chiffres faux se voient serait la seule sans dérive statistique.

        Ce que la clé désigne, c'est *quand la mesure a été prise* — et c'est
        bien ce qui fait une série temporelle. Que le profil couvre un jour
        (Bronze) ou toute la table (Gold) est une propriété de la mesure, pas de
        sa date.

        **Idempotent** : réécrire le même lot remplace ses mesures au lieu de les
        empiler (`DELETE` puis `INSERT`, comme l'ingestion en 2.1). Airflow
        rejoue une tâche en cas d'échec ; sans ça, un lot rejoué compterait deux
        fois dans sa propre médiane et l'attirerait vers sa propre valeur.

        `column_name` vaut `NULL` pour une métrique **de table** (`row_count`) :
        c'est ce qui garde une table unique sans inventer un nom de colonne
        fictif, qui entrerait en collision le jour où une vraie colonne le
        porterait.
        """
        mesures = [
            (dataset, table, batch_id, None, nom, float(profil[nom]))
            for nom in METRIQUES_TABLE
            if _est_un_nombre(profil.get(nom))
        ]
        for colonne, stats in profil.get("columns", {}).items():
            mesures += [
                (dataset, table, batch_id, colonne, nom, float(stats[nom]))
                for nom in METRIQUES_COLONNE
                if _est_un_nombre(stats.get(nom))
            ]

        curseur = self._curseur()
        self._creer_profiles(curseur)
        curseur.execute(
            f"DELETE FROM {self.base}.{OPS_SCHEMA}.{PROFILES} "
            f"WHERE dataset = %s AND table_name = %s AND batch_id = %s",
            (dataset, table, batch_id),
        )
        if mesures:
            curseur.executemany(
                f"INSERT INTO {self.base}.{OPS_SCHEMA}.{PROFILES} "
                f"(dataset, table_name, batch_id, column_name, metric, value) "
                f"VALUES (%s, %s, %s, %s, %s, %s)",
                mesures,
            )
        return len(mesures)

    def lire_historique(
        self,
        dataset: str,
        table: str,
        avant: Optional[str] = None,
        jours: Optional[int] = None,
    ) -> dict:
        """Les mesures des lots **précédents**, prêtes à servir de référence.

        Rend `{(colonne, métrique): [valeurs, du plus ancien au plus récent]}`,
        où `colonne` vaut `None` pour une métrique de table.

        ⭐ **Le lot `avant` est exclu par le SQL, pas par l'ordre des appels.**
        Le plan disait « lire l'historique avant d'y écrire le profil du jour » ;
        l'ordre suffit au premier passage et **casse au rejeu** — si le lot a
        déjà été profilé hier, le relire aujourd'hui le ferait entrer dans sa
        propre référence et sa médiane se rapprocherait de lui, jusqu'à ce que
        l'anomalie devienne la norme. Une garantie portée par la requête tient
        quel que soit l'appelant, y compris celui auquel on n'a pas pensé.

        `jours` borne la fenêtre aux N lots les plus récents — des **lots**, pas
        des jours calendaires : un jour sans livraison ne doit pas consommer une
        place dans la référence, sinon une interruption du pipeline raccourcirait
        l'historique en silence.

        `batch_id` est un VARCHAR ISO, donc son ordre lexicographique **est**
        l'ordre chronologique : la même propriété que `lire_schema()` exploite.
        """
        curseur = self._curseur()
        self._creer_profiles(curseur)

        table_sql = f"{self.base}.{OPS_SCHEMA}.{PROFILES}"
        filtre, parametres = "", [dataset, table]
        if avant is not None:
            filtre = " AND batch_id < %s"
            parametres.append(avant)

        limite = ""
        if jours:
            limite = (
                f" AND batch_id IN (SELECT batch_id FROM ("
                f"SELECT DISTINCT batch_id FROM {table_sql} "
                f"WHERE dataset = %s AND table_name = %s{filtre} "
                f"ORDER BY batch_id DESC LIMIT {int(jours)}))"
            )
            parametres += [dataset, table] + ([avant] if avant is not None else [])

        curseur.execute(
            f"SELECT column_name, metric, value FROM {table_sql} "
            f"WHERE dataset = %s AND table_name = %s{filtre}{limite} "
            f"ORDER BY batch_id",
            tuple(parametres),
        )

        series: dict = {}
        for colonne, metrique, valeur in curseur.fetchall():
            series.setdefault((colonne, metrique), []).append(float(valeur))
        return series

    # -- Les incidents : le journal métier, la mémoire, la source du benchmark -

    def _creer_incidents(self, curseur) -> None:
        """Crée `OPS.INCIDENTS` si besoin. Schéma du §5.5 du cahier, **plus**
        une colonne `signatures`.

        ⚠️ **Ajout au cahier, assumé.** Les signatures des anomalies du run sont
        dérivables du JSON `anomalies` — mais seulement en Python, après lecture.
        Les stocker à part rend deux choses possibles qui ne l'étaient pas :
        retrouver un incident **par signature** en SQL (la mémoire de `diagnose`,
        objectif O7), et lister les signatures qu'un humain a fait taire — c'est
        l'écran anti-cécité de la phase 6, sans lequel l'agent devient
        progressivement muet sans que personne s'en aperçoive.

        Append-only : aucune méthode de ce module ne met à jour ni ne supprime
        une ligne. Un journal qu'on peut réécrire n'est pas un journal.
        """
        curseur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.base}.{OPS_SCHEMA}.{INCIDENTS} (
                incident_id        VARCHAR,
                run_ts             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                dataset            VARCHAR,
                layer              VARCHAR,
                table_name         VARCHAR,
                batch_id           VARCHAR,
                anomalies          VARCHAR,
                signatures         VARCHAR,
                diagnosis          VARCHAR,
                proposed_fix       VARCHAR,
                human_decision     VARCHAR,
                decided_by         VARCHAR,
                decided_at         VARCHAR,
                applied_fix        VARCHAR,
                validation_status  VARCHAR,
                duration_s         FLOAT
            )
            """
        )

    def ecrire_incident(self, incident: dict) -> str:
        """Ajoute une ligne au journal. Rend l'`incident_id`.

        Les champs structurés (`anomalies`, `signatures`, `diagnosis`) partent en
        **JSON dans du VARCHAR** plutôt qu'en `VARIANT` : c'est ce qui garde le
        module lisible par un connecteur qui ne serait pas Snowflake le jour où
        la mémoire changera de moteur. Le coût est nul à ce volume — une ligne
        par run et par table.
        """
        curseur = self._curseur()
        self._creer_incidents(curseur)

        colonnes = [
            "incident_id",
            "dataset",
            "layer",
            "table_name",
            "batch_id",
            "anomalies",
            "signatures",
            "diagnosis",
            "proposed_fix",
            "human_decision",
            "decided_by",
            "decided_at",
            "applied_fix",
            "validation_status",
            "duration_s",
        ]
        valeurs = [incident.get(c) for c in colonnes]
        curseur.execute(
            f"INSERT INTO {self.base}.{OPS_SCHEMA}.{INCIDENTS} "
            f"({', '.join(colonnes)}) VALUES ({', '.join(['%s'] * len(colonnes))})",
            tuple(valeurs),
        )
        return incident.get("incident_id")

    def lire_incidents(self, dataset: str, table: str, limite: int = 200) -> list[dict]:
        """Les incidents **tranchés par un humain** sur cette table (R5).

        `human_decision IS NOT NULL` n'est pas un filtre de confort : un
        incident sans décision n'a rien tranché — run encore en pause, ou clos
        sans réponse au bout de dix échanges. Le lire comme un refus ferait
        taire l'agent sur une question que **personne n'a jamais lue**.

        Les plus récents d'abord, bornés : la mémoire doit servir, pas grossir
        indéfiniment jusqu'à ne plus tenir dans un prompt.
        """
        curseur = self._curseur()
        self._creer_incidents(curseur)
        curseur.execute(
            f"SELECT incident_id, batch_id, anomalies, signatures, diagnosis, "
            f"proposed_fix, human_decision, decided_by, decided_at, applied_fix "
            f"FROM {self.base}.{OPS_SCHEMA}.{INCIDENTS} "
            f"WHERE dataset = %s AND table_name = %s AND human_decision IS NOT NULL "
            f"ORDER BY run_ts DESC LIMIT {int(limite)}",
            (dataset, table),
        )
        champs = (
            "incident_id",
            "batch_id",
            "anomalies",
            "signatures",
            "diagnosis",
            "proposed_fix",
            "human_decision",
            "decided_by",
            "decided_at",
            "applied_fix",
        )
        return [_decoder(dict(zip(champs, ligne))) for ligne in curseur.fetchall()]


def _decoder(ligne: dict) -> dict:
    """Rend les champs JSON sous forme d'objets Python.

    Un JSON illisible ne fait **pas** lever : la mémoire est un confort, pas une
    condition d'exécution. Un agent qui refuserait de tourner parce qu'une ligne
    d'historique est corrompue serait plus fragile que s'il n'avait pas de
    mémoire du tout.
    """
    import json

    for champ in ("anomalies", "signatures", "diagnosis", "proposed_fix"):
        brut = ligne.get(champ)
        if isinstance(brut, str):
            try:
                ligne[champ] = json.loads(brut)
            except (ValueError, TypeError):
                ligne[champ] = None
    return ligne


def _est_un_nombre(valeur) -> bool:
    """Une mesure numérique exploitable — `bool` exclu explicitement.

    En Python `True` est un `int` : sans ce filtre, un futur champ booléen du
    profil entrerait dans l'historique en valant 1,0 et se retrouverait comparé
    par médiane comme une quantité.
    """
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def _cle_de_table(table: str) -> str:
    """`"RAW.ORDERS"` -> `"orders"` — la forme sous laquelle l'ingestion l'a écrite.

    On ne garde que le dernier segment : l'ingestion a enregistré le nom du
    fichier CSV, sans schéma. Le rapprochement se fait donc sur ce segment, en
    minuscules, et le SQL applique `LOWER()` de son côté pour que la comparaison
    tienne quelle que soit la casse réellement stockée.
    """
    return table.split(".")[-1].lower()
