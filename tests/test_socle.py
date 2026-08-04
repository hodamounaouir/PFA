"""Contrôle du socle générique (phase 4.0) : registre, fabrique, connecteur.

Aucun de ces tests n'ouvre de connexion. Le connecteur Snowflake est éprouvé
avec un **curseur factice** qui enregistre le SQL émis et rend des lignes
préparées : on vérifie la requête et le calcul, pas Snowflake.

⚠️ Comme dans `test_agent_nodes.py`, les noms de tables et de colonnes vivent
**ici**, jamais dans `agent/`.
"""

import re
from pathlib import Path

import pytest

from agent import connectors
from agent.connectors.snowflake import (
    SCHEMAS_INTERNES,
    ConnecteurSnowflake,
    DeclarationFausse,
    TableMalNommee,
    _decouper,
)
from agent.registry import RegistreInvalide, charger

RACINE = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Le registre réel
# ---------------------------------------------------------------------------


def test_le_registre_olist_se_charge():
    registre = charger("olist")
    assert registre.connector == "snowflake"
    assert registre.tables, "un registre sans table ne surveille rien"


def test_les_trois_couches_sont_declarees():
    """L'agent doit tourner sur Bronze, Silver et Gold (objectif O2)."""
    registre = charger("olist")
    for couche in ("bronze", "silver", "gold"):
        assert registre.tables_de(couche), f"aucune table déclarée en {couche}"


def test_gold_n_a_pas_de_colonne_de_lot():
    """Un agrégat est reconstruit en entier : il n'a pas de notion de lot.

    Ce n'est pas un oubli de déclaration — c'est ce qui dira au connecteur de
    profiler la table complète, et c'est le comportement correct pour Gold.
    """
    registre = charger("olist")
    assert all(t.batch_column is None for t in registre.tables_de("gold"))
    assert all(t.batch_column for t in registre.tables_de("bronze"))


def test_une_table_non_surveillee_retourne_none():
    """`table()` ne lève pas : « non déclarée » est une information, pas une erreur.

    C'est cette réponse-là que la famille *inventaire* (4.3) transformera en
    incident « table nouvelle non déclarée ».
    """
    assert charger("olist").table("RAW.CE_QUI_N_EXISTE_PAS") is None


# ---------------------------------------------------------------------------
# Un registre mal écrit échoue au chargement, pas trois nœuds plus loin
# ---------------------------------------------------------------------------


def _ecrire(dossier: Path, nom: str, contenu: str) -> Path:
    (dossier / f"{nom}.yaml").write_text(contenu, encoding="utf-8")
    return dossier


VALIDE = """
name: jouet
connector: memoire
tables:
  - {name: RH.EMPLOYES, layer: bronze, batch_column: _lot}
"""


def test_registre_absent(tmp_path):
    with pytest.raises(RegistreInvalide, match="introuvable"):
        charger("inexistant", dossier=tmp_path)


def test_couche_mal_orthographiee(tmp_path):
    """`brnze` doit être refusé : propagé, il fausserait toute analyse par couche."""
    _ecrire(tmp_path, "faux", VALIDE.replace("bronze", "brnze"))
    with pytest.raises(RegistreInvalide, match="layer"):
        charger("faux", dossier=tmp_path)


def test_champ_inconnu_refuse(tmp_path):
    """`bath_column` est une faute de frappe — l'ignorer profilerait toute la table."""
    _ecrire(tmp_path, "faux", VALIDE.replace("batch_column", "bath_column"))
    with pytest.raises(RegistreInvalide, match="inconnu"):
        charger("faux", dossier=tmp_path)


def test_table_declaree_deux_fois(tmp_path):
    """Deux déclarations = deux `batch_column` possibles et aucune qui fasse foi."""
    _ecrire(tmp_path, "faux", VALIDE + "  - {name: RH.EMPLOYES, layer: gold}\n")
    with pytest.raises(RegistreInvalide, match="deux fois"):
        charger("faux", dossier=tmp_path)


def test_registre_sans_table(tmp_path):
    _ecrire(tmp_path, "vide", "name: vide\nconnector: memoire\ntables: []\n")
    with pytest.raises(RegistreInvalide, match="tables"):
        charger("vide", dossier=tmp_path)


# ---------------------------------------------------------------------------
# La fabrique de connecteurs
# ---------------------------------------------------------------------------


def test_snowflake_est_enregistre():
    assert "snowflake" in connectors.enregistres()


def test_connecteur_inconnu_nomme_les_disponibles():
    """Le message doit dire quoi écrire dans le YAML, pas seulement que c'est faux."""
    with pytest.raises(connectors.ConnecteurInconnu, match="snowflake"):
        connectors.ouvrir("postgres_imaginaire")


# ---------------------------------------------------------------------------
# LE test de généricité : un second dataset, zéro ligne de code modifiée
# ---------------------------------------------------------------------------


class ConnecteurJouet:
    """Un connecteur en mémoire — les trois méthodes du contrat, aucune base.

    Il prouve deux choses à la fois : que le contrat des connecteurs tient sans
    classe abstraite, et que rien au-dessus de `agent/connectors/` ne suppose
    Snowflake.
    """

    TABLES = {
        "RH.EMPLOYES": (
            [
                {"name": "matricule", "type": "TEXT", "position": 1},
                {"name": "salaire_brut", "type": "NUMBER", "position": 2},
            ],
            {
                "row_count": 3,
                "columns": {
                    "matricule": {"null_rate": 0.0, "distinct": 3},
                    "salaire_brut": {"null_rate": 0.33, "distinct": 2},
                },
            },
        )
    }

    def list_tables(self):
        return sorted(self.TABLES)

    def get_schema(self, table):
        entree = self.TABLES.get(table)
        return entree[0] if entree else None

    def profile(self, table, batch_column=None, batch_id=None):
        entree = self.TABLES.get(table)
        return {**entree[1], "table": table, "batch_id": batch_id} if entree else None


JOUET = """
name: jouet
connector: jouet_memoire
tables:
  - {name: RH.EMPLOYES, layer: bronze, batch_column: _lot}
  - {name: RH.DISPARUE, layer: bronze, batch_column: _lot}
"""


@pytest.fixture
def registre_jouet(tmp_path):
    connectors.enregistrer("jouet_memoire", ConnecteurJouet)
    _ecrire(tmp_path, "jouet", JOUET)
    yield charger("jouet", dossier=tmp_path)
    connectors._FABRIQUES.pop("jouet_memoire", None)


def test_un_dataset_etranger_tourne_sans_toucher_au_code(registre_jouet):
    """Un YAML et un connecteur enregistré : c'est tout ce qu'il faut.

    Rien sous `agent/` n'a été modifié pour faire passer ce test — c'est
    précisément ce qu'il vérifie.
    """
    connecteur = connectors.ouvrir(registre_jouet.connector)
    table = registre_jouet.tables_de("bronze")[0]

    assert connecteur.get_schema(table.name) is not None
    profil = connecteur.profile(table.name, table.batch_column, "lot-1")
    assert profil["row_count"] == 3
    assert "salaire_brut" in profil["columns"]


def test_une_table_declaree_absente_ne_fait_pas_lever(registre_jouet):
    """La clause qui rend la famille *inventaire* (4.3) possible.

    Sans elle, le connecteur lèverait, le run planterait, et l'incident le plus
    grave qui puisse arriver — une table disparue — ressemblerait à un bug.
    """
    connecteur = connectors.ouvrir(registre_jouet.connector)
    absente = registre_jouet.table("RH.DISPARUE")

    assert connecteur.get_schema(absente.name) is None
    assert connecteur.profile(absente.name, absente.batch_column, "lot-1") is None
    # et elle est bien déclarée : c'est l'écart déclaré/présent qui fait l'incident
    assert absente.name not in connecteur.list_tables()


# ---------------------------------------------------------------------------
# Le connecteur Snowflake, sans Snowflake
# ---------------------------------------------------------------------------


class CurseurFactice:
    """Enregistre le SQL émis, rend les lignes qu'on lui a préparées."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []
        self._courant = []

    def execute(self, sql, parametres=None):
        self.appels.append((" ".join(sql.split()), parametres))
        self._courant = self.reponses.pop(0) if self.reponses else []

    def fetchall(self):
        return self._courant

    def fetchone(self):
        return self._courant[0] if self._courant else None

    @property
    def sql(self):
        return self.appels[-1][0]


def brancher(monkeypatch, reponses) -> tuple[ConnecteurSnowflake, CurseurFactice]:
    connecteur = ConnecteurSnowflake(base="TEST_DB")
    curseur = CurseurFactice(reponses)
    monkeypatch.setattr(connecteur, "_curseur", lambda: curseur)
    return connecteur, curseur


COLONNES = [
    ("MATRICULE", "TEXT", 1),
    ("SALAIRE_BRUT", "NUMBER", 2),
    ("_BATCH_ID", "TEXT", 3),
]


def test_get_schema_rend_none_quand_la_table_est_absente(monkeypatch):
    """Zéro ligne dans INFORMATION_SCHEMA = la table n'existe pas. On constate."""
    connecteur, _ = brancher(monkeypatch, [[]])
    assert connecteur.get_schema("RH.EMPLOYES") is None


def test_profile_rend_none_quand_la_table_est_absente(monkeypatch):
    connecteur, curseur = brancher(monkeypatch, [[]])
    assert connecteur.profile("RH.EMPLOYES", "_batch_id", "lot-1") is None
    # une seule requête : on n'a même pas tenté d'agréger une table inexistante
    assert len(curseur.appels) == 1


def test_profile_calcule_nulls_et_cardinalites(monkeypatch):
    # 10 lignes ; matricule : 10 renseignés / 10 distincts ; salaire : 7 renseignés
    agregats = [(10, 10, 10, "a", "z", 7, 4, 1000, 9000, 10, 1, "lot-1", "lot-1")]
    connecteur, _ = brancher(monkeypatch, [COLONNES, agregats])

    profil = connecteur.profile("RH.EMPLOYES", "_batch_id", "lot-1")

    assert profil["row_count"] == 10
    assert profil["columns"]["SALAIRE_BRUT"]["null_count"] == 3
    assert profil["columns"]["SALAIRE_BRUT"]["null_rate"] == 0.3
    assert profil["columns"]["SALAIRE_BRUT"]["distinct"] == 4
    assert profil["columns"]["SALAIRE_BRUT"]["max"] == 9000
    assert profil["columns"]["MATRICULE"]["null_rate"] == 0.0


def test_profile_ne_contient_aucune_ligne_brute(monkeypatch):
    """Règle R2, rendue structurelle : il n'y a rien à fuiter dans un profil.

    Le SQL émis ne contient que des fonctions d'agrégation — pas de projection
    de colonne nue, donc aucune valeur individuelle ne peut remonter.
    """
    agregats = [(10, 10, 10, "a", "z", 7, 4, 1000, 9000, 10, 1, "lot-1", "lot-1")]
    connecteur, curseur = brancher(monkeypatch, [COLONNES, agregats])
    connecteur.profile("RH.EMPLOYES", "_batch_id", "lot-1")

    projections = curseur.sql.split(" FROM ")[0].removeprefix("SELECT ").split(", ")
    nues = [p for p in projections if not re.match(r"(COUNT|MIN|MAX)\(", p)]
    assert not nues, f"projection non agrégée dans le profil : {nues}"


def test_table_vide_ne_divise_pas_par_zero(monkeypatch):
    """0 ligne : le taux de nulls vaut 0 %, pas une exception.

    Une table vide est un problème de **volume** — c'est la dérive statistique
    qui doit le crier, pas une division par zéro qui tue le run.
    """
    agregats = [(0, 0, 0, None, None, 0, 0, None, None, 0, 0, None, None)]
    connecteur, _ = brancher(monkeypatch, [COLONNES, agregats])

    profil = connecteur.profile("RH.EMPLOYES", "_batch_id", "lot-1")
    assert profil["row_count"] == 0
    assert profil["columns"]["SALAIRE_BRUT"]["null_rate"] == 0.0


def test_sans_colonne_de_lot_toute_la_table_est_profilee(monkeypatch):
    """Le cas Gold : pas de `WHERE`, et c'est voulu."""
    agregats = [(10, 10, 10, "a", "z", 7, 4, 1000, 9000, 10, 1, "x", "x")]
    connecteur, curseur = brancher(monkeypatch, [COLONNES, agregats])

    connecteur.profile("MARTS.FCT_TOTAL")
    assert "WHERE" not in curseur.sql


def test_la_casse_de_la_colonne_de_lot_est_resolue(monkeypatch):
    """Snowflake replie les identifiants non quotés : `_batch_id` est stocké `_BATCH_ID`.

    Exiger la casse exacte ferait échouer un registre pourtant juste.
    """
    agregats = [(10, 10, 10, "a", "z", 7, 4, 1000, 9000, 10, 1, "lot-1", "lot-1")]
    connecteur, curseur = brancher(monkeypatch, [COLONNES, agregats])

    connecteur.profile("RH.EMPLOYES", "_batch_id", "lot-1")
    assert '"_BATCH_ID" = %s' in curseur.sql
    assert curseur.appels[-1][1] == ("lot-1",)


def test_colonne_de_lot_declaree_mais_absente_leve(monkeypatch):
    """Erreur de **déclaration**, pas anomalie de donnée : elle doit être bruyante.

    Profiler toute la table en croyant filtrer un lot diluerait l'anomalie
    cherchée — 30 % de nulls sur un jour ne pèsent plus rien sur 92 jours.
    """
    connecteur, _ = brancher(monkeypatch, [COLONNES])
    with pytest.raises(DeclarationFausse, match="_lot_inexistant"):
        connecteur.profile("RH.EMPLOYES", "_lot_inexistant", "lot-1")


@pytest.mark.parametrize(
    "nom",
    [
        "ORDERS",
        "RAW.ORDERS.TROP",
        "RAW.ORDERS; DROP TABLE X",
        "RAW.MES ORDRES",
        'RAW."x"',
    ],
)
def test_les_noms_de_tables_douteux_sont_refuses(nom):
    """Les noms viennent d'un YAML écrit à la main et finissent dans du SQL.

    Ils ne sont pas paramétrables (aucun moteur n'accepte un identifiant en
    `%s`) : ce filtre est donc la seule chose entre une faute de frappe et une
    injection.
    """
    with pytest.raises(TableMalNommee):
        _decouper(nom)


def test_list_tables_ignore_la_memoire_de_l_agent(monkeypatch):
    """`OPS` n'est pas le système observé, c'est la mémoire de l'agent.

    L'inclure ferait apparaître `INCIDENTS` et `_PROFILES` comme « tables non
    déclarées » à chaque run : l'agent se découvrirait lui-même, indéfiniment.
    """
    connecteur, curseur = brancher(monkeypatch, [[("RAW", "ORDERS")]])
    assert connecteur.list_tables() == ["RAW.ORDERS"]
    assert curseur.appels[-1][1] == SCHEMAS_INTERNES
    assert "OPS" in SCHEMAS_INTERNES


# ---------------------------------------------------------------------------
# Le garde-fou qui remplace la classe abstraite
# ---------------------------------------------------------------------------

# On cherche des **requêtes**, pas des mots isolés : `apply.py` cite `DROP` et
# `DELETE` en prose (la liste des mots interdits), et `profile.py` mentionne
# `INFORMATION_SCHEMA` dans sa docstring. Aucun des deux ne construit de SQL.
# Majuscules exigées : le SQL du projet s'écrit en majuscules, le Python en
# minuscules — ce qui évite d'attraper `select` ou `from` dans du code.
MOTIFS_SQL = (
    re.compile(r"\bSELECT\b[\s\S]{0,400}?\bFROM\b"),
    re.compile(r"\bINSERT\s+INTO\b"),
    re.compile(r"\bDELETE\s+FROM\b"),
    re.compile(r"\bUPDATE\s+\w+\s+SET\b"),
    re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?(TABLE|VIEW)\b"),
    re.compile(r"\bALTER\s+TABLE\b"),
)


def test_aucun_sql_hors_des_connecteurs():
    """La règle du socle, rendue structurelle.

    C'est ce test qui remplace la classe abstraite qu'on n'a pas écrite (ADR 010,
    décision 7). Une interface abstraite se contourne par distraction — on peut
    toujours ouvrir une connexion à côté. Ce test, non : il relit tout `agent/`.

    S'il devient rouge, ce n'est pas lui qu'il faut assouplir — c'est la requête
    qu'il faut déplacer dans `agent/connectors/`.
    """
    fautifs = []
    for fichier in sorted((RACINE / "agent").rglob("*.py")):
        if "connectors" in fichier.parts:
            continue
        texte = fichier.read_text(encoding="utf-8")
        for motif in MOTIFS_SQL:
            trouve = motif.search(texte)
            if trouve:
                relatif = fichier.relative_to(RACINE)
                fautifs.append(f"{relatif} : {trouve.group(0)[:60]!r}")

    assert not fautifs, (
        "Du SQL est apparu au-dessus de la couche connecteur :\n  "
        + "\n  ".join(fautifs)
        + "\n→ déplacez la requête dans agent/connectors/."
    )
