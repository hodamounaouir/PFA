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
    """Un connecteur en mémoire — les deux familles du contrat, aucune base.

    Il prouve deux choses à la fois : que le contrat des connecteurs tient sans
    classe abstraite, et que rien au-dessus de `agent/connectors/` ne suppose
    Snowflake.

    Pas de `close()` : un connecteur en mémoire n'a rien à fermer. C'est
    exactement le cas que `connectors.fermer()` doit absorber sans broncher.
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
            {"matricule": [("A-1", 1), ("A-2", 1), ("A-3", 1)]},
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

    def top_values(self, table, column, k, batch_column=None, batch_id=None):
        entree = self.TABLES.get(table)
        comptes = entree[2].get(column) if entree else None
        if comptes is None:
            return None
        total = sum(c for _, c in comptes)
        retenues = comptes[:k]
        return {
            "table": table,
            "column": column,
            "batch_id": batch_id,
            "k": k,
            "non_null_count": total,
            "coverage": sum(c for _, c in retenues) / total,
            "top": [{"value": v, "count": c} for v, c in retenues],
        }

    def robust_stats(self, table, column, batch_column=None, batch_id=None):
        entree = self.TABLES.get(table)
        if entree is None or not any(c["name"] == column for c in entree[0]):
            return None
        return {
            "table": table,
            "column": column,
            "type": "NUMBER",
            "batch_id": batch_id,
            "non_null_count": 2,
            "numeric_count": 2,
            "numeric_rate": 1.0,
            "median": 2500.0,
            "mad": 500.0,
            "min": 2000.0,
            "max": 3000.0,
        }


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
    # les deux familles du contrat, sur un backend qui n'est pas une base
    assert connecteur.top_values(table.name, "matricule", 2)["top"]
    assert connecteur.robust_stats(table.name, "salaire_brut")["median"] == 2500.0


def test_une_table_declaree_absente_ne_fait_pas_lever(registre_jouet):
    """La clause qui rend la famille *inventaire* (4.3) possible.

    Sans elle, le connecteur lèverait, le run planterait, et l'incident le plus
    grave qui puisse arriver — une table disparue — ressemblerait à un bug.
    """
    connecteur = connectors.ouvrir(registre_jouet.connector)
    absente = registre_jouet.table("RH.DISPARUE")

    assert connecteur.get_schema(absente.name) is None
    assert connecteur.profile(absente.name, absente.batch_column, "lot-1") is None
    assert connecteur.top_values(absente.name, "matricule", 5) is None
    assert connecteur.robust_stats(absente.name, "matricule") is None
    # et elle est bien déclarée : c'est l'écart déclaré/présent qui fait l'incident
    assert absente.name not in connecteur.list_tables()


def test_fermer_un_connecteur_qui_n_a_rien_a_fermer(registre_jouet):
    """`close()` ne fait pas partie du contrat, et ne doit pas y entrer.

    L'exiger obligerait chaque connecteur en mémoire à écrire une méthode vide,
    pour un besoin qui ne concerne que ceux qui tiennent une session ouverte.
    Les tools passent donc par `fermer()`, et c'est lui qui absorbe le cas.
    """
    connecteur = connectors.ouvrir(registre_jouet.connector)
    assert not hasattr(connecteur, "close")
    connectors.fermer(connecteur)  # ne doit pas lever


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


# ---------------------------------------------------------------------------
# `top_values` — la 4ᵉ méthode, celle qui rend la détection sémantique possible
# ---------------------------------------------------------------------------

# Troisième colonne = le total des lignes renseignées, rendu par la fenêtre
# `SUM(COUNT(*)) OVER ()` : la même valeur sur chaque ligne, par construction.
VILLES = [("sao paulo", 6, 10), ("santos", 3, 10), ("são paulo", 1, 10)]


def test_top_values_rend_les_valeurs_et_leur_poids(monkeypatch):
    """LE tool sans lequel rien de sémantique n'est détectable.

    Le profil sait qu'il y a 3 villes distinctes ; seul le top-K sait que deux
    d'entre elles sont la même. C'est la matière première de la famille
    *collisions sémantiques* (4.3).
    """
    connecteur, _ = brancher(monkeypatch, [COLONNES, VILLES])

    fiche = connecteur.top_values("RH.EMPLOYES", "matricule", 20, "_batch_id", "lot-1")

    assert fiche["top"][0] == {"value": "sao paulo", "count": 6}
    assert fiche["non_null_count"] == 10
    assert fiche["coverage"] == 1.0
    assert fiche["column"] == "MATRICULE", (
        "la casse réelle est rendue, pas celle demandée"
    )


def test_top_values_dit_ce_qu_il_ne_couvre_pas(monkeypatch):
    """`coverage` est ce qui distingue une colonne catégorielle d'une longue traîne.

    Sans lui, `detect` ne pourrait pas savoir si les 20 valeurs qu'il lit
    décrivent la colonne ou en effleurent 2 %. C'est aussi le garde-fou de R2 :
    une longue traîne, c'est du texte libre, et ses valeurs n'ont rien à faire
    dans un prompt.
    """
    traine = [("a", 3, 300), ("b", 2, 300), ("c", 1, 300)]
    connecteur, _ = brancher(monkeypatch, [COLONNES, traine])

    fiche = connecteur.top_values("RH.EMPLOYES", "matricule", 3, "_batch_id", "lot-1")
    assert fiche["coverage"] == 0.02
    assert len(fiche["top"]) == fiche["k"], "top plein = on n'a vu que la tête"


def test_top_values_ne_projette_que_la_colonne_demandee(monkeypatch):
    """La nuance de R2, rendue vérifiable (ADR 010, « point de bascule »).

    `profile` ne projette aucune colonne nue — il n'y a rien à fuiter. Ici,
    projeter la colonne **est** le sujet : une valeur accompagnée de sa
    fréquence est une *distribution*, pas une ligne. La frontière tient tant
    qu'il n'y a **qu'une** colonne nue, et qu'elle est groupée : ajouter une
    seconde colonne au SELECT rendrait les lignes recomposables — ce ne serait
    plus une distribution, ce serait un extrait de table.
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES, VILLES])
    connecteur.top_values("RH.EMPLOYES", "matricule", 20, "_batch_id", "lot-1")

    projections = curseur.sql.split(" FROM ")[0].removeprefix("SELECT ").split(", ")
    nues = [p for p in projections if not re.match(r"(COUNT|SUM|MIN|MAX)\(", p)]
    assert nues == ['"MATRICULE"'], f"projection nue inattendue : {nues}"
    assert 'GROUP BY "MATRICULE"' in curseur.sql


def test_top_values_exclut_les_nulls(monkeypatch):
    """Les NULL sont déjà comptés par `profile` : les garder mangerait un rang."""
    connecteur, curseur = brancher(monkeypatch, [COLONNES, VILLES])
    connecteur.top_values("RH.EMPLOYES", "matricule", 20, "_batch_id", "lot-1")

    assert '"MATRICULE" IS NOT NULL' in curseur.sql
    assert '"_BATCH_ID" = %s' in curseur.sql, "le filtre de lot tient toujours"
    assert curseur.appels[-1][1] == ("lot-1",)


def test_top_values_departage_les_ex_aequo(monkeypatch):
    """Sans départage, le k-ième rang basculerait d'un run à l'autre.

    Deux valeurs de même fréquence sortiraient dans un ordre arbitraire, et une
    détection qui dépend du top-K deviendrait intermittente — l'un des pires
    défauts possibles pour un projet dont la reproductibilité est le socle
    (même leçon qu'au repli des variantes en phase 1.5).
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES, VILLES])
    connecteur.top_values("RH.EMPLOYES", "matricule", 20, "_batch_id", "lot-1")

    assert 'ORDER BY COUNT(*) DESC, "MATRICULE" ASC' in curseur.sql


def test_top_values_sur_une_colonne_absente_rend_none(monkeypatch):
    """Une colonne disparue est **l'anomalie cherchée**, pas un plantage.

    C'est le renommage `payment_value` → `amount` du J45. Si la demander faisait
    lever, le run mourrait sur l'incident qu'il est censé constater.
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES])

    assert connecteur.top_values("RH.EMPLOYES", "colonne_envolee", 20) is None
    # une seule requête : on n'a pas tenté d'agréger une colonne inexistante
    assert len(curseur.appels) == 1


def test_top_values_sur_une_table_absente_rend_none(monkeypatch):
    connecteur, _ = brancher(monkeypatch, [[]])
    assert connecteur.top_values("RH.DISPARUE", "matricule", 20) is None


def test_une_colonne_de_lot_fausse_leve_meme_en_top_values(monkeypatch):
    """La symétrie du fichier : ce qui est *déclaré* échoue fort, ce qui est
    *observé* rend None. `batch_column` vient du registre, donc elle lève."""
    connecteur, _ = brancher(monkeypatch, [COLONNES])
    with pytest.raises(DeclarationFausse, match="_lot_inexistant"):
        connecteur.top_values("RH.EMPLOYES", "matricule", 20, "_lot_inexistant", "l-1")


def test_top_values_sur_un_lot_vide(monkeypatch):
    """Zéro groupe : la colonne ne porte rien. C'est une réponse, pas une absence."""
    connecteur, _ = brancher(monkeypatch, [COLONNES, []])

    fiche = connecteur.top_values("RH.EMPLOYES", "matricule", 20, "_batch_id", "lot-1")
    assert fiche["top"] == []
    assert fiche["non_null_count"] == 0
    assert fiche["coverage"] == 0.0, "0/0 vaut 0, pas une division par zéro"


def test_un_k_absurde_est_refuse(monkeypatch):
    """`k` finit interpolé dans un `LIMIT` : il est converti en entier, mais un
    zéro ou un négatif est une erreur d'appel qui doit se voir tout de suite."""
    connecteur, _ = brancher(monkeypatch, [COLONNES, VILLES])
    with pytest.raises(ValueError, match="k"):
        connecteur.top_values("RH.EMPLOYES", "matricule", 0, "_batch_id", "lot-1")


# ---------------------------------------------------------------------------
# `robust_stats` — médiane + MAD, et le VARCHAR de Bronze devenu signal
# ---------------------------------------------------------------------------

# (renseignés, numériques, médiane, MAD, min, max)
SALAIRES = [(10, 10, 2000.0, 150.0, 1000.0, 9000.0)]


def test_les_stats_sont_robustes_et_pas_moyennes(monkeypatch):
    """Médiane + MAD, jamais AVG + STDDEV.

    Ce n'est pas une préférence de statisticien : avec moyenne + σ, l'anomalie
    du J60 entre dans l'historique, gonfle σ, et la récidive du J85 tombe *dans*
    la nouvelle normale. La référence se contaminerait elle-même.
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES, SALAIRES])

    fiche = connecteur.robust_stats("RH.EMPLOYES", "salaire_brut", "_batch_id", "lot-1")

    assert fiche["median"] == 2000.0
    assert fiche["mad"] == 150.0
    assert "MEDIAN(" in curseur.sql
    assert "AVG(" not in curseur.sql and "STDDEV" not in curseur.sql


def test_le_mad_se_calcule_contre_la_mediane_du_lot(monkeypatch):
    """MAD = médiane(|x − médiane(x)|) : il faut la médiane **avant** de la soustraire.

    D'où la fenêtre `MEDIAN(...) OVER ()`, qui la répète sur chaque ligne en un
    seul balayage — au lieu d'une seconde requête pour aller la chercher.
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES, SALAIRES])
    connecteur.robust_stats("RH.EMPLOYES", "salaire_brut", "_batch_id", "lot-1")

    assert "MEDIAN(ABS(v - m))" in curseur.sql
    assert "OVER ()" in curseur.sql


def test_bronze_est_relu_en_nombre_sans_faire_echouer_la_requete(monkeypatch):
    """Tout Bronze est VARCHAR (phase 2.1) : `AVG` y échouerait franchement.

    `TRY_CAST` rend NULL sur ce qui n'est pas lisible au lieu de lever — une
    valeur illisible est **comptée**, pas fatale.
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES, SALAIRES])
    connecteur.robust_stats("RH.EMPLOYES", "matricule", "_batch_id", "lot-1")

    assert 'TRY_CAST("MATRICULE" AS DOUBLE)' in curseur.sql


def test_une_colonne_deja_numerique_n_est_pas_castee(monkeypatch):
    """Piège Snowflake : `TRY_CAST` **n'accepte qu'une source texte**.

    L'appliquer à une colonne déjà `NUMBER` lève. Le type vient de
    `INFORMATION_SCHEMA`, qu'on interroge de toute façon pour résoudre la casse.
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES, SALAIRES])
    connecteur.robust_stats("RH.EMPLOYES", "salaire_brut", "_batch_id", "lot-1")

    assert "TRY_CAST" not in curseur.sql
    assert 'MEDIAN("SALAIRE_BRUT") OVER ()' in curseur.sql


def test_le_taux_numerique_est_une_mesure_de_derive_de_format(monkeypatch):
    """Sur Bronze, « combien de valeurs se laissent lire comme un nombre » est
    une information : 10 renseignées dont 7 numériques = 30 % de format cassé."""
    connecteur, _ = brancher(monkeypatch, [COLONNES, [(10, 7, 50.0, 5.0, 1.0, 99.0)]])

    fiche = connecteur.robust_stats("RH.EMPLOYES", "matricule", "_batch_id", "lot-1")
    assert fiche["non_null_count"] == 10
    assert fiche["numeric_count"] == 7
    assert fiche["numeric_rate"] == 0.7


def test_une_colonne_qui_ne_peut_pas_porter_de_nombre_n_est_pas_lue(monkeypatch):
    """Le schéma suffit à répondre : scanner la table pour l'apprendre serait
    payer un balayage pour rien."""
    dates = [("EMBAUCHE", "DATE", 1)]
    connecteur, curseur = brancher(monkeypatch, [dates])

    fiche = connecteur.robust_stats("RH.EMPLOYES", "embauche")
    assert fiche["type"] == "DATE"
    assert fiche["median"] is None and fiche["non_null_count"] is None
    assert len(curseur.appels) == 1, "aucune requête d'agrégation n'est partie"


def test_un_mad_nul_est_rendu_tel_quel(monkeypatch):
    """Une colonne constante a un MAD de 0. C'est un **fait**, pas une valeur à
    corriger : le plancher qui évitera la division par zéro est un réglage de
    détection, il appartient à `detect` (4.3). Une mesure qui se corrige
    elle-même ment sur ce qu'elle a vu."""
    connecteur, _ = brancher(monkeypatch, [COLONNES, [(10, 10, 42.0, 0.0, 42.0, 42.0)]])

    fiche = connecteur.robust_stats("RH.EMPLOYES", "salaire_brut", "_batch_id", "l-1")
    assert fiche["mad"] == 0.0


def test_les_bornes_sont_numeriques_et_non_lexicographiques(monkeypatch):
    """Ce que `profile` ne peut pas donner sur Bronze : là-bas `"8000" < "90"`.

    C'est ce qui rend enfin exploitable le cas « une seule ligne à 8000 dans une
    colonne à [1–100] » — elle ne déplace presque pas la médiane, mais elle fait
    exploser le max.
    """
    connecteur, curseur = brancher(
        monkeypatch, [COLONNES, [(10, 10, 50.0, 5.0, 1.0, 8000.0)]]
    )

    fiche = connecteur.robust_stats("RH.EMPLOYES", "matricule", "_batch_id", "lot-1")
    assert fiche["max"] == 8000.0
    assert "MAX(v)" in curseur.sql, (
        "le max porte sur la lecture numérique, pas sur le texte"
    )


def test_les_stats_ne_rendent_aucune_valeur_individuelle(monkeypatch):
    """Règle R2, et la frontière est **la projection externe**, pas la sous-requête.

    Première version de ce test : « la sous-requête ne projette pas la colonne
    nue ». Faux — sur une colonne déjà numérique elle la projette forcément (il
    faut bien lire les valeurs pour les trier), et le test est devenu rouge sur
    du code juste. La sous-requête ne **quitte jamais la base** : ce qui traverse
    le réseau, c'est le SELECT du dessus.

    L'invariant correct est donc celui de `profile` : toute projection rendue au
    client est une agrégation. Six scalaires sortent, jamais une ligne.
    """
    connecteur, curseur = brancher(monkeypatch, [COLONNES, SALAIRES])
    connecteur.robust_stats("RH.EMPLOYES", "salaire_brut", "_batch_id", "lot-1")

    exterieur = curseur.sql.split(" FROM (")[0].removeprefix("SELECT ")
    nues = [
        p
        for p in exterieur.split(", ")
        if not re.match(r"(SUM|COUNT|MEDIAN|MIN|MAX)\(", p)
    ]
    assert not nues, f"projection non agrégée dans les stats : {nues}"
    assert 'IFF("SALAIRE_BRUT" IS NULL, 0, 1)' in curseur.sql, (
        "les renseignés se comptent sur un drapeau"
    )


def test_stats_sur_un_lot_vide(monkeypatch):
    """`SUM` sur zéro ligne rend NULL, pas 0 — sans quoi `int(None)` tue le run."""
    connecteur, _ = brancher(
        monkeypatch, [COLONNES, [(None, 0, None, None, None, None)]]
    )

    fiche = connecteur.robust_stats("RH.EMPLOYES", "salaire_brut", "_batch_id", "l-1")
    assert fiche["non_null_count"] == 0
    assert fiche["numeric_rate"] == 0.0
    assert fiche["median"] is None


def test_stats_sur_une_colonne_ou_une_table_absente(monkeypatch):
    """Même règle que `top_values` : constater, ne pas trébucher."""
    connecteur, _ = brancher(monkeypatch, [COLONNES])
    assert connecteur.robust_stats("RH.EMPLOYES", "colonne_envolee") is None

    connecteur, _ = brancher(monkeypatch, [[]])
    assert connecteur.robust_stats("RH.DISPARUE", "salaire_brut") is None


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
