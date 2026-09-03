"""Contrôle de l'ingestion Bronze (phase 2.1) — ce que le registre journalise.

Aucun de ces tests ne touche à Snowflake : `ensure_bronze_table` et
`record_schema` ne font qu'émettre du SQL, on leur donne donc un curseur qui
l'enregistre. C'est suffisant pour verrouiller la seule chose qui compte ici —
que `OPS._SCHEMA_HISTORY` décrive **la table qui existe**, et non le CSV qui
l'a alimentée.

L'écart entre les deux a produit un faux positif permanent en phase 4.3 : trois
colonnes « nouvelles » à chaque run et sur chaque table Bronze, parce que le
registre ignorait des colonnes que `INFORMATION_SCHEMA` — donc le profil de
l'agent — rendait toujours.
"""

import re

from ingestion.load import (
    META_BATCH,
    META_INGESTED,
    META_SOURCE,
    ensure_bronze_table,
    record_schema,
)

COLONNES_CSV = ["geolocation_zip_code_prefix", "geolocation_city", "geolocation_state"]


class CurseurFactice:
    """Enregistre le SQL émis. Rien d'autre n'est nécessaire ici.

    Redéfini dans ce fichier plutôt qu'importé de `test_tools.py` : les fichiers
    de test restent autonomes, aucun ne dépend d'un autre.
    """

    def __init__(self):
        self.appels = []

    def execute(self, sql, parametres=None):
        self.appels.append((" ".join(sql.split()), parametres))

    def executemany(self, sql, sequence):
        self.appels.append((" ".join(sql.split()), list(sequence)))


def colonnes_creees(curseur) -> set:
    """Les colonnes que le SQL émis crée réellement — le `CREATE` et les `ALTER`."""
    creees = set()
    for sql, _ in curseur.appels:
        if sql.startswith("CREATE TABLE"):
            corps = sql[sql.index("(") + 1 : sql.rindex(")")]
            creees |= {clause.split()[0] for clause in corps.split(",")}
        elif ajout := re.search(r"ADD COLUMN IF NOT EXISTS (\S+)", sql):
            creees.add(ajout.group(1))
    return creees


def colonnes_journalisees(curseur) -> list:
    """Les colonnes écrites dans `_SCHEMA_HISTORY`, dans l'ordre des positions."""
    lignes = [appel for appel in curseur.appels if appel[0].startswith("INSERT")]
    return [colonne for _, _, colonne, _ in sorted(lignes[-1][1], key=lambda r: r[3])]


def test_le_registre_journalise_les_colonnes_techniques():
    """⭐ Le faux positif que ce test existe pour empêcher.

    `_ingested_at` n'est dans aucun CSV — c'est un `DEFAULT` posé par Snowflake —
    et `_batch_id`/`_source` sont ajoutés au DataFrame **après** l'appel. Les
    journaliser depuis les seules colonnes du CSV laissait donc le registre
    décrire une table qui n'existe pas.
    """
    curseur = CurseurFactice()

    record_schema(curseur, "2018-05-14", "geolocation", COLONNES_CSV)

    journalisees = colonnes_journalisees(curseur)
    assert journalisees[:3] == [META_BATCH, META_SOURCE, META_INGESTED]
    assert journalisees[3:] == COLONNES_CSV


def test_le_registre_decrit_exactement_la_table_creee():
    """La garantie, et pas seulement ses trois symptômes connus.

    Toute colonne créée par l'ingestion sans être journalisée reviendrait comme
    « nouvelle » à chaque run ; toute colonne journalisée sans être créée
    reviendrait comme « disparue ». Les deux inventaires doivent coïncider.
    """
    curseur = CurseurFactice()

    ensure_bronze_table(curseur, "geolocation", COLONNES_CSV)
    record_schema(curseur, "2018-05-14", "geolocation", COLONNES_CSV)

    assert colonnes_creees(curseur) == set(colonnes_journalisees(curseur))
