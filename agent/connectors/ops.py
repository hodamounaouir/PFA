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

    def lire_schema(self, table: str, batch_id: Optional[str] = None) -> list[dict]:
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

        if batch_id is None:
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


def _cle_de_table(table: str) -> str:
    """`"RAW.ORDERS"` -> `"orders"` — la forme sous laquelle l'ingestion l'a écrite.

    On ne garde que le dernier segment : l'ingestion a enregistré le nom du
    fichier CSV, sans schéma. Le rapprochement se fait donc sur ce segment, en
    minuscules, et le SQL applique `LOWER()` de son côté pour que la comparaison
    tienne quelle que soit la casse réellement stockée.
    """
    return table.split(".")[-1].lower()
