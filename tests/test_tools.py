"""Contrôle des tools (phase 4.1), testés **isolément** — sans base, sans réseau.

Deux niveaux :
  - `MemoireOps` est éprouvée avec un curseur factice : on vérifie le SQL émis
    et la normalisation, pas Snowflake ;
  - le tool lui-même est éprouvé avec une mémoire factice : on vérifie qu'il
    délègue et qu'il referme, pas ce que la requête renvoie.

Et un garde-fou structurel : **aucun `bind_tools` dans le projet** (ADR 004).
"""

import importlib
import re
from pathlib import Path

import pytest

from agent.connectors.ops import MemoireOps, _cle_de_table
from agent.registry import Registre, TableDeclaree
from agent.tools import profile_table, read_schema_history, robust_stats, top_values
from agent.tools._connecteur import TableNonDeclaree
from agent.tools.top_values import TOP_K_DEFAUT

RACINE = Path(__file__).resolve().parent.parent

# ⚠️ Même piège que pour `agent.nodes` (cf. conftest.py) : `agent.tools`
# réexporte le tool sous le nom de son module. `agent.tools.read_schema_history`
# désigne donc le **tool**, pas le module — un `monkeypatch` dessus ne
# remplacerait rien, silencieusement. On va chercher le module explicitement.
tool_mod = importlib.import_module("agent.tools.read_schema_history")
# Le socle commun des tools qui lisent la base : c'est **lui** qui charge le
# registre, donc c'est lui qu'on remplace — pas chaque tool.
socle_mod = importlib.import_module("agent.tools._connecteur")


# Ce que l'ingestion a réellement écrit en phase 2.1 : nom de fichier CSV,
# colonnes en minuscules. C'est la forme d'origine, pas une simplification.
LIGNES_HISTORIQUE = [
    ("order_id", 1, "2018-04-29"),
    ("customer_id", 2, "2018-04-29"),
    ("payment_value", 3, "2018-04-29"),
]


class CurseurFactice:
    """Enregistre le SQL émis, rend les lignes qu'on lui a préparées.

    Volontairement redéfini ici plutôt qu'importé de `test_socle.py` : les
    fichiers de test restent autonomes, aucun ne dépend d'un autre.
    """

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []
        self._courant = []

    def execute(self, sql, parametres=None):
        self.appels.append((" ".join(sql.split()), parametres))
        self._courant = self.reponses.pop(0) if self.reponses else []

    def fetchall(self):
        return self._courant

    @property
    def sql(self):
        return self.appels[-1][0]


def brancher(monkeypatch, reponses):
    memoire = MemoireOps(base="TEST_DB")
    curseur = CurseurFactice(reponses)
    monkeypatch.setattr(memoire, "_curseur", lambda: curseur)
    return memoire, curseur


# ---------------------------------------------------------------------------
# MemoireOps : les deux pièges hérités de la phase 2.1
# ---------------------------------------------------------------------------


def test_les_colonnes_sont_rendues_en_majuscules(monkeypatch):
    """LE test qui évite un faux positif permanent en 4.3.

    L'ingestion a écrit les colonnes avec la casse du CSV (`order_id`), alors
    que `INFORMATION_SCHEMA` les rend en majuscules (`ORDER_ID`). Comparer les
    deux telles quelles ferait apparaître **toutes** les colonnes comme
    renommées, à chaque run, sur chaque table.
    """
    memoire, _ = brancher(monkeypatch, [LIGNES_HISTORIQUE])

    colonnes = memoire.lire_schema("RAW.ORDERS")
    assert [c["name"] for c in colonnes] == ["ORDER_ID", "CUSTOMER_ID", "PAYMENT_VALUE"]


def test_le_schema_du_registre_retrouve_la_table_de_l_ingestion(monkeypatch):
    """Le registre déclare `RAW.ORDERS` ; l'ingestion avait écrit `orders`."""
    memoire, curseur = brancher(monkeypatch, [LIGNES_HISTORIQUE])

    memoire.lire_schema("RAW.ORDERS")
    assert curseur.appels[-1][1] == ("orders", "orders")
    assert "LOWER(table_name)" in curseur.sql


@pytest.mark.parametrize(
    "declare,attendu",
    [
        ("RAW.ORDERS", "orders"),
        ("STAGING.STG_ORDERS", "stg_orders"),
        ("orders", "orders"),
    ],
)
def test_cle_de_table(declare, attendu):
    assert _cle_de_table(declare) == attendu


def test_table_jamais_observee_rend_une_liste_vide(monkeypatch):
    """Une table réelle a toujours au moins une colonne : la liste vide est sans ambiguïté."""
    memoire, _ = brancher(monkeypatch, [[]])
    assert memoire.lire_schema("RAW.CE_QUI_N_EXISTE_PAS") == []


def test_sans_batch_on_prend_le_dernier_observe(monkeypatch):
    """`batch_id` est un VARCHAR ISO : MAX() y vaut « le plus récent »."""
    memoire, curseur = brancher(monkeypatch, [LIGNES_HISTORIQUE])
    memoire.lire_schema("RAW.ORDERS")
    assert "MAX(batch_id)" in curseur.sql


def test_avec_un_batch_on_ne_prend_pas_le_dernier(monkeypatch):
    """Pouvoir remonter à une date donnée : c'est ce qui permettra de dire
    « la colonne existait encore au J44 »."""
    memoire, curseur = brancher(monkeypatch, [LIGNES_HISTORIQUE])
    memoire.lire_schema("RAW.ORDERS", "2018-04-14")
    assert "MAX(batch_id)" not in curseur.sql
    assert curseur.appels[-1][1] == ("orders", "2018-04-14")


# ---------------------------------------------------------------------------
# Le tool
# ---------------------------------------------------------------------------


class MemoireFactice:
    def __init__(self, resultat=None, plante=False):
        self.resultat = resultat or []
        self.plante = plante
        self.ferme = False
        self.appels = []

    def lire_schema(self, table, batch_id=None):
        self.appels.append((table, batch_id))
        if self.plante:
            raise RuntimeError("Snowflake indisponible")
        return self.resultat

    def close(self):
        self.ferme = True


def brancher_memoire(monkeypatch, memoire):
    monkeypatch.setattr(tool_mod, "MemoireOps", lambda *a, **k: memoire)
    return memoire


def test_le_tool_delegue_et_rend_le_schema(monkeypatch):
    memoire = brancher_memoire(monkeypatch, MemoireFactice([{"name": "ORDER_ID"}]))

    resultat = read_schema_history.invoke({"table": "RAW.ORDERS"})

    assert resultat == [{"name": "ORDER_ID"}]
    assert memoire.appels == [("RAW.ORDERS", None)]


def test_un_batch_vide_veut_dire_le_dernier(monkeypatch):
    """La signature d'un `@tool` n'accepte que des valeurs simples : `""` tient
    lieu de « non précisé », et ne doit pas être transmis tel quel."""
    memoire = brancher_memoire(monkeypatch, MemoireFactice())
    read_schema_history.invoke({"table": "RAW.ORDERS", "batch_id": ""})
    assert memoire.appels == [("RAW.ORDERS", None)]


def test_la_connexion_est_fermee_meme_si_la_lecture_echoue(monkeypatch):
    """Un run interrompu ne doit pas laisser une session Snowflake derrière lui."""
    memoire = brancher_memoire(monkeypatch, MemoireFactice(plante=True))

    with pytest.raises(RuntimeError):
        read_schema_history.invoke({"table": "RAW.ORDERS"})
    assert memoire.ferme


def test_le_tool_est_bien_un_tool():
    """Le §5.6 du cahier demande le format `@tool` — vérifié, pas supposé."""
    assert hasattr(read_schema_history, "invoke")
    assert read_schema_history.name == "read_schema_history"
    assert read_schema_history.args_schema is not None


# ---------------------------------------------------------------------------
# Les tools qui lisent la base résolvent leur connecteur eux-mêmes
# ---------------------------------------------------------------------------

REGISTRE_FACTICE = Registre(
    name="jouet",
    connector="jouet_top",
    tables=(
        TableDeclaree(name="RH.EMPLOYES", layer="bronze", batch_column="_lot"),
        TableDeclaree(name="MARTS.FCT_TOTAL", layer="gold"),
    ),
)


class ConnecteurEspion:
    """Enregistre ce qu'on lui demande, rend une fiche fixe."""

    def __init__(self, plante=False):
        self.plante = plante
        self.ferme = False
        self.appels = []

    def top_values(self, table, column, k, batch_column=None, batch_id=None):
        self.appels.append((table, column, k, batch_column, batch_id))
        if self.plante:
            raise RuntimeError("Snowflake indisponible")
        return {"table": table, "column": column, "top": [], "coverage": 0.0}

    def robust_stats(self, table, column, batch_column=None, batch_id=None):
        self.appels.append((table, column, batch_column, batch_id))
        if self.plante:
            raise RuntimeError("Snowflake indisponible")
        return {"table": table, "column": column, "median": 42.0, "mad": 1.5}

    def close(self):
        self.ferme = True


@pytest.fixture
def espion(monkeypatch):
    """Un registre factice et un connecteur espion, sans base ni fichier YAML."""
    from agent import connectors

    connecteur = ConnecteurEspion()
    monkeypatch.setattr(socle_mod, "charger", lambda nom: REGISTRE_FACTICE)
    connectors.enregistrer("jouet_top", lambda: connecteur)
    yield connecteur
    connectors._FABRIQUES.pop("jouet_top", None)


def test_le_tool_lit_le_registre_pour_trouver_la_colonne_de_lot(espion):
    """Le cœur de l'ADR 004 : un `@tool` ne reçoit que des chaînes.

    On ne peut pas lui passer un connecteur — il va donc chercher dans le
    registre quel connecteur ouvrir *et* quelle colonne porte le lot. C'est
    aussi la forme dont Airflow aura besoin en 4.5.
    """
    top_values.invoke(
        {
            "dataset": "jouet",
            "table": "RH.EMPLOYES",
            "column": "ville",
            "batch_id": "l-1",
        }
    )
    assert espion.appels == [("RH.EMPLOYES", "ville", TOP_K_DEFAUT, "_lot", "l-1")]


def test_une_table_gold_n_a_pas_de_colonne_de_lot(espion):
    """Pas un cas dégradé : un agrégat est reconstruit en entier, on le lit en entier."""
    top_values.invoke(
        {"dataset": "jouet", "table": "MARTS.FCT_TOTAL", "column": "ville"}
    )
    assert espion.appels[-1][3] is None


def test_un_batch_vide_veut_dire_toute_la_table(espion):
    """La signature d'un `@tool` n'accepte que des valeurs simples : `""` tient
    lieu de « non précisé », et ne doit pas descendre tel quel dans un `WHERE`."""
    top_values.invoke({"dataset": "jouet", "table": "RH.EMPLOYES", "column": "ville"})
    assert espion.appels[-1][4] is None


def test_une_table_non_declaree_echoue_bruyamment(espion):
    """Erreur d'appel, pas anomalie de donnée — donc bruyante.

    Sans `batch_column`, on lirait toute la table en croyant lire un jour : les
    fréquences du lot se dilueraient dans 92 jours cumulés et la collision
    cherchée deviendrait invisible. Le message nomme les tables déclarées, pour
    que la faute de frappe saute aux yeux.
    """
    with pytest.raises(TableNonDeclaree, match="RH.EMPLOYES"):
        top_values.invoke(
            {"dataset": "jouet", "table": "RH.INCONNUE", "column": "ville"}
        )
    assert espion.appels == [], "aucune requête n'est partie"


def test_le_connecteur_est_ferme_meme_si_la_lecture_echoue(monkeypatch):
    from agent import connectors

    connecteur = ConnecteurEspion(plante=True)
    monkeypatch.setattr(socle_mod, "charger", lambda nom: REGISTRE_FACTICE)
    connectors.enregistrer("jouet_top", lambda: connecteur)
    try:
        with pytest.raises(RuntimeError):
            top_values.invoke(
                {"dataset": "jouet", "table": "RH.EMPLOYES", "column": "ville"}
            )
        assert connecteur.ferme
    finally:
        connectors._FABRIQUES.pop("jouet_top", None)


def test_top_values_est_bien_un_tool():
    assert top_values.name == "top_values"
    champs = set(top_values.args_schema.model_fields)
    assert {"dataset", "table", "column", "batch_id", "k"} == champs


# ---------------------------------------------------------------------------
# `robust_stats` (4.1.3)
# ---------------------------------------------------------------------------


def test_robust_stats_passe_par_le_meme_socle(espion):
    """Écrit à la deuxième occurrence : les deux tools font les mêmes gestes.

    Ce qui compte n'est pas d'économiser douze lignes, c'est que le message
    d'erreur d'une table non déclarée et la garantie de fermeture existent à un
    seul endroit — donc qu'un troisième tool (4.1.4) ne puisse pas les oublier
    à moitié.
    """
    robust_stats.invoke(
        {
            "dataset": "jouet",
            "table": "RH.EMPLOYES",
            "column": "salaire",
            "batch_id": "l-1",
        }
    )
    assert espion.appels == [("RH.EMPLOYES", "salaire", "_lot", "l-1")]


def test_robust_stats_sur_une_table_non_declaree(espion):
    with pytest.raises(TableNonDeclaree, match="RH.EMPLOYES"):
        robust_stats.invoke(
            {"dataset": "jouet", "table": "RH.INCONNUE", "column": "salaire"}
        )
    assert espion.appels == []


def test_robust_stats_un_batch_vide_veut_dire_toute_la_table(espion):
    robust_stats.invoke(
        {"dataset": "jouet", "table": "MARTS.FCT_TOTAL", "column": "salaire"}
    )
    assert espion.appels[-1][2:] == (None, None), "ni colonne de lot, ni lot"


def test_robust_stats_est_bien_un_tool():
    assert robust_stats.name == "robust_stats"
    champs = set(robust_stats.args_schema.model_fields)
    assert {"dataset", "table", "column", "batch_id"} == champs


# ---------------------------------------------------------------------------
# `profile_table` (4.1.5) : le critère provisoire, puis l'assemblage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cas,stats,attendu",
    [
        # Bronze : tout est VARCHAR, et c'est LE cas qui condamne un critère
        # fondé sur le type déclaré — il n'y trouverait aucune colonne numérique.
        (
            "montant écrit en texte",
            {"min": "0.00", "max": "99.99", "distinct": 800},
            "robust_stats",
        ),
        ("nombre déjà typé", {"min": 1, "max": 8000, "distinct": 800}, "robust_stats"),
        ("ville", {"min": "arcoverde", "max": "santos", "distinct": 300}, "top_values"),
        ("statut", {"min": "approved", "max": "shipped", "distinct": 8}, "top_values"),
        ("identifiant", {"min": "a1", "max": "zz", "distinct": 1000}, None),
        ("texte libre", {"min": "ah", "max": "zut", "distinct": 950}, None),
        ("colonne vide sur ce lot", {"min": None, "max": None, "distinct": 0}, None),
        # ⚠️ Les deux bornes doivent être numériques, pas seulement une. Une
        # seule suffirait sur une colonne Bronze salie par un `N/A` ou un
        # `inconnu` : elle serait déclarée quantitative, et sa médiane porterait
        # sur les 3 % de valeurs castables. Ces deux cas ont été ajoutés après
        # qu'un sabotage (« oublier le `max` ») soit passé inaperçu.
        (
            "montant sali par un marqueur texte en fin d'ordre",
            {"min": "0.00", "max": "N/A", "distinct": 60},
            "top_values",
        ),
        (
            "code sali par un marqueur texte en début d'ordre",
            {"min": "inconnu", "max": "99.99", "distinct": 60},
            "top_values",
        ),
    ],
)
def test_le_critere_provisoire(cas, stats, attendu):
    """Le critère ne lit que des **faits mesurés**, jamais un nom de type SQL.

    `VARCHAR`, `NUMBER`, `TEXT` sont du vocabulaire Snowflake : les interpréter
    ferait entrer un dialecte de base dans une couche qui doit l'ignorer
    (ADR 010, décision 2). Bornes et cardinalité, elles, existent partout.
    """
    from agent.tools.profile_table import _mesure_pour

    assert _mesure_pour(stats, 1000) == attendu, cas


def test_une_ville_nommee_nan_n_est_pas_une_quantite():
    """`float("nan")` et `float("inf")` réussissent — d'où une regex, pas un cast."""
    from agent.tools.profile_table import _lisible_comme_nombre

    assert not _lisible_comme_nombre("nan")
    assert not _lisible_comme_nombre("inf")
    assert not _lisible_comme_nombre("1_000")
    assert _lisible_comme_nombre("-12.5e3")


def test_une_table_vide_ne_declenche_aucune_mesure():
    """0 ligne : la division par le nombre de lignes n'a pas lieu d'être posée."""
    from agent.tools.profile_table import _mesure_pour

    assert _mesure_pour({"min": "1", "max": "9", "distinct": 0}, 0) is None


class ConnecteurComplet:
    """Un connecteur en mémoire qui porte les deux familles du contrat.

    Il compte ses appels : c'est ce qui permet de vérifier qu'aucune mesure
    n'est demandée sur une colonne que le critère a écartée.
    """

    COLONNES = [
        {"name": "ORDER_ID", "type": "TEXT", "position": 1},
        {"name": "CUSTOMER_CITY", "type": "TEXT", "position": 2},
        {"name": "PAYMENT_VALUE", "type": "TEXT", "position": 3},
        {"name": "VIDE", "type": "TEXT", "position": 4},
    ]
    AGREGATS = {
        "ORDER_ID": {
            "null_count": 0,
            "null_rate": 0.0,
            "distinct": 100,
            "min": "a",
            "max": "z",
        },
        "CUSTOMER_CITY": {
            "null_count": 0,
            "null_rate": 0.0,
            "distinct": 12,
            "min": "belem",
            "max": "santos",
        },
        # Bornes lexicographiques : sur Bronze, "8000" < "90". C'est le piège
        # que `numeric_min`/`numeric_max` existent pour ne pas propager.
        "PAYMENT_VALUE": {
            "null_count": 2,
            "null_rate": 0.02,
            "distinct": 60,
            "min": "0.00",
            "max": "90",
        },
        "VIDE": {
            "null_count": 100,
            "null_rate": 1.0,
            "distinct": 0,
            "min": None,
            "max": None,
        },
    }

    def __init__(self):
        self.mesures = []
        self.ferme = False

    def get_schema(self, table):
        return list(self.COLONNES)

    def profile(self, table, batch_column=None, batch_id=None):
        return {
            "table": table,
            "batch_id": batch_id,
            "row_count": 100,
            "columns": {n: dict(s) for n, s in self.AGREGATS.items()},
        }

    # Rend `None` au lieu d'une mesure : sert au cas « la mesure n'a rien
    # donné », qu'aucun test ne couvrait avant qu'un sabotage passe inaperçu.
    MUETTE = ()

    def top_values(self, table, column, k, batch_column=None, batch_id=None):
        # ⚠️ On enregistre **tous** les arguments, pas seulement la colonne :
        # un assembleur qui oublierait de transmettre le lot profilerait la
        # table entière en croyant filtrer un jour, et l'anomalie cherchée se
        # diluerait dans 92 jours cumulés. C'est le bug le plus silencieux du
        # projet, et il est passé sous un sabotage avant que ce test existe.
        self.mesures.append(("top_values", column, batch_column, batch_id))
        if column in self.MUETTE:
            return None
        return {"top": [{"value": "sao paulo", "count": 40}], "coverage": 0.4}

    def robust_stats(self, table, column, batch_column=None, batch_id=None):
        self.mesures.append(("robust_stats", column, batch_column, batch_id))
        if column in self.MUETTE:
            return None
        return {
            "median": 50.0,
            "mad": 12.0,
            "numeric_rate": 0.98,
            "min": 0.0,
            "max": 8000.0,
        }

    def close(self):
        self.ferme = True


@pytest.fixture
def complet(monkeypatch):
    from agent import connectors

    connecteur = ConnecteurComplet()
    monkeypatch.setattr(socle_mod, "charger", lambda nom: REGISTRE_FACTICE)
    connectors.enregistrer("jouet_top", lambda: connecteur)
    yield connecteur
    connectors._FABRIQUES.pop("jouet_top", None)


def test_la_fiche_rassemble_les_trois_mesures(complet):
    """Le point où 4.1 devient consommable par 4.3 : une table, une fiche."""
    fiche = profile_table.invoke(
        {"dataset": "jouet", "table": "RH.EMPLOYES", "batch_id": "l-1"}
    )

    assert fiche["row_count"] == 100
    colonnes = fiche["columns"]
    assert colonnes["CUSTOMER_CITY"]["measure"] == "top_values"
    assert colonnes["CUSTOMER_CITY"]["coverage"] == 0.4
    assert colonnes["PAYMENT_VALUE"]["measure"] == "robust_stats"
    assert colonnes["PAYMENT_VALUE"]["median"] == 50.0
    # les agrégats du connecteur sont toujours là, sous chaque colonne
    assert colonnes["ORDER_ID"]["distinct"] == 100
    # …et le schéma aussi : `detect` compare des schémas, et l'ordre des
    # colonnes fait partie de ce qu'il regarde.
    assert colonnes["ORDER_ID"]["type"] == "TEXT"
    assert colonnes["ORDER_ID"]["position"] == 1
    assert list(colonnes) == [c["name"] for c in ConnecteurComplet.COLONNES]


def test_aucune_mesure_sur_une_colonne_ecartee(complet):
    """Une requête par colonne mesurée : celles que le critère écarte n'en coûtent aucune."""
    profile_table.invoke(
        {"dataset": "jouet", "table": "RH.EMPLOYES", "batch_id": "l-1"}
    )

    mesurees = {appel[1] for appel in complet.mesures}
    assert mesurees == {"CUSTOMER_CITY", "PAYMENT_VALUE"}
    assert {c["name"] for c in complet.COLONNES} - mesurees == {"ORDER_ID", "VIDE"}


def test_le_lot_est_transmis_a_chaque_mesure_de_colonne(complet):
    """Le bug le plus silencieux du projet, et il est passé sous un sabotage.

    Une mesure de colonne à qui on ne transmet pas le lot profile la table
    **entière** en croyant filtrer un jour. Rien ne plante, rien ne se voit :
    30 % de nulls sur un batch ne pèsent plus que 0,3 % noyés dans 92 jours, et
    l'anomalie cherchée disparaît dans sa propre référence.

    Le test précédent n'enregistrait que le nom de la colonne — il ne pouvait
    donc pas le voir. Écrit après coup, comme il se doit.
    """
    profile_table.invoke(
        {"dataset": "jouet", "table": "RH.EMPLOYES", "batch_id": "l-1"}
    )

    assert complet.mesures, "aucune mesure : le test ne prouverait rien"
    for _, colonne, batch_column, batch_id in complet.mesures:
        assert batch_column == "_lot", f"colonne de lot perdue pour {colonne}"
        assert batch_id == "l-1", f"lot perdu pour {colonne}"


def test_une_mesure_qui_revient_vide_n_est_pas_annoncee(monkeypatch):
    """`measure` n'est posée qu'après une mesure **réussie**.

    Une colonne peut disparaître entre le profil et la mesure (DDL concurrent),
    et le contrat autorise un connecteur à rendre `None` sur ce qu'il ne sait
    pas mesurer. Annoncer `measure: "top_values"` sans porter de `top` ferait
    planter le lecteur de la fiche — `detect`, en pleine détection.

    Ce garde-fou existait dans le code mais n'était couvert par aucun test :
    le sabotage qui l'a supprimé est passé inaperçu.
    """
    from agent import connectors

    class Muette(ConnecteurComplet):
        MUETTE = ("CUSTOMER_CITY", "PAYMENT_VALUE")

    monkeypatch.setattr(socle_mod, "charger", lambda nom: REGISTRE_FACTICE)
    connectors.enregistrer("jouet_top", Muette)
    try:
        fiche = profile_table.invoke({"dataset": "jouet", "table": "RH.EMPLOYES"})
    finally:
        connectors._FABRIQUES.pop("jouet_top", None)

    ville = fiche["columns"]["CUSTOMER_CITY"]
    assert ville["measure"] is None, "on n'annonce pas ce qu'on n'a pas"
    assert "top" not in ville and "coverage" not in ville
    # …et les agrégats du profil, eux, sont toujours là
    assert ville["distinct"] == 12


def test_les_bornes_numeriques_n_ecrasent_pas_les_lexicographiques(complet):
    """LE piège de l'assemblage, et il est silencieux.

    Sur Bronze, `profile` rend `max="90"` (lexicographique : `"8000" < "90"`) et
    `robust_stats` rend `max=8000.0` (numérique). Fusionner les deux sous la
    même clé ferait croire à une borne qui n'a pas été mesurée de cette façon —
    et la comparaison de bornes en 4.3 porterait sur deux grandeurs différentes
    selon la couche, sans que rien ne le signale.
    """
    fiche = profile_table.invoke({"dataset": "jouet", "table": "RH.EMPLOYES"})
    montant = fiche["columns"]["PAYMENT_VALUE"]

    assert montant["max"] == "90", "la borne lexicographique du profil est intacte"
    assert montant["numeric_max"] == 8000.0, (
        "la borne numérique vit à côté, pas à la place"
    )


def test_une_seule_connexion_pour_toute_la_table(complet):
    """L'assembleur appelle le **connecteur**, pas les autres tools.

    Passer par `top_values.invoke()` rouvrirait une connexion par colonne — sur
    Snowflake, une à deux secondes chacune. Ici tout tient dans le `with` du
    socle, donc dans une seule session.
    """
    profile_table.invoke({"dataset": "jouet", "table": "RH.EMPLOYES"})
    assert complet.ferme, "et elle est refermée à la sortie"


def test_profile_table_sur_une_table_absente(monkeypatch):
    from agent import connectors

    class Absente(ConnecteurComplet):
        def profile(self, table, batch_column=None, batch_id=None):
            return None

    monkeypatch.setattr(socle_mod, "charger", lambda nom: REGISTRE_FACTICE)
    connectors.enregistrer("jouet_top", Absente)
    try:
        assert (
            profile_table.invoke({"dataset": "jouet", "table": "RH.EMPLOYES"}) is None
        )
    finally:
        connectors._FABRIQUES.pop("jouet_top", None)


def test_profile_table_est_bien_un_tool():
    assert profile_table.name == "profile_table"
    champs = set(profile_table.args_schema.model_fields)
    assert {"dataset", "table", "batch_id"} == champs


# ---------------------------------------------------------------------------
# Le garde-fou de l'ADR 004
# ---------------------------------------------------------------------------


def test_aucun_bind_tools():
    """Le format `@tool` sans la délégation de flux (ADR 004).

    `bind_tools` est ce qui donnerait les tools au modèle pour qu'il choisisse
    quoi appeler — soit exactement l'agent ReAct que `DESIGN.md` §2 rejette, et
    la fin de P1 (« le graphe contrôle le flux »).

    Ce test n'interdit pas ce choix pour toujours : il le rend **visible**. S'il
    devient rouge un jour, c'est qu'une décision d'architecture a été prise, et
    elle doit passer par un ADR — pas par un import.

    On cherche un **appel** (`.bind_tools` ou `bind_tools(`) et non le mot seul :
    sinon le test attrape la documentation qui explique pourquoi on ne l'utilise
    pas. Même leçon que le test anti-fuite SQL de la phase 4.0.
    """
    appel = re.compile(r"\.bind_tools\b|\bbind_tools\s*\(")
    fautifs = [
        str(f.relative_to(RACINE))
        for dossier in ("agent", "scripts")
        for f in sorted((RACINE / dossier).rglob("*.py"))
        if appel.search(f.read_text(encoding="utf-8"))
    ]
    assert not fautifs, (
        "`bind_tools` est apparu : le modèle pourrait désormais choisir le flux "
        f"(ADR 004, DESIGN §2) — {fautifs}"
    )
