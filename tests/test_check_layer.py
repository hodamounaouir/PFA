"""Contrôle du lanceur de couche (phase 4.5, volet B).

C'est ce qu'Airflow appelle après chaque couche. Le DAG lui-même ne contient
aucune logique — trois `BashOperator` — donc **tout ce qui peut mal tourner se
teste ici**, sans Docker et sans Airflow.

Le test qui compte est `test_une_proposition_en_attente_ne_fait_pas_rougir_le_dag` :
si une pause sortait en erreur, le pipeline serait rouge chaque fois que l'agent
fait son travail, et l'équipe apprendrait à ignorer un pipeline rouge.
"""

import importlib
import json

import pytest

from agent.dbt_results import lire_echecs
from agent.detect import dbt as famille_dbt
from agent.state import new_state
from conftest import PROFIL_FACTICE, REFERENCES

check_layer = importlib.import_module("scripts.check_layer")


class TableJouet:
    def __init__(self, name, layer):
        self.name, self.layer = name, layer
        self.batch_column = "_batch_id"


class RegistreJouet:
    connector = "factice"

    def __init__(self, tables):
        self.tables = tuple(tables)

    def tables_de(self, couche):
        return tuple(t for t in self.tables if t.layer == couche)


@pytest.fixture
def couche_bronze(monkeypatch, tmp_path):
    """Deux tables Bronze, et un graphe persistant jetable."""
    registre = RegistreJouet(
        [TableJouet("RAW.ORDERS", "bronze"), TableJouet("RAW.CUSTOMERS", "bronze")]
    )
    monkeypatch.setattr(check_layer, "charger_registre", lambda ds: registre)
    monkeypatch.setattr(check_layer, "echecs_dbt", lambda couche, reg: [])
    REFERENCES.declarees = ["RAW.ORDERS", "RAW.CUSTOMERS"]
    REFERENCES.presentes = ["RAW.ORDERS", "RAW.CUSTOMERS"]
    return tmp_path / "checkpoints.sqlite"


# ---------------------------------------------------------------------------
# La convention qui décide de tout
# ---------------------------------------------------------------------------


def test_une_proposition_en_attente_ne_fait_pas_rougir_le_dag(couche_bronze):
    """⭐ LE test du volet B.

    Le double de `profile_table` pose une collision sémantique sur la 2ᵉ colonne,
    donc l'agent trouve, donc il s'arrête sur `propose`. Si ce script sortait
    alors en erreur, le DAG serait rouge **chaque fois que l'agent fait son
    travail** — et un pipeline rouge en permanence est un pipeline qu'on cesse de
    regarder. Même convention qu'en 2.3 pour les tests dbt : détection = vert.
    """
    PROFIL_FACTICE.colonnes = ["c0", "c1", "c2", "c3"]
    rapports, ratees = check_layer.parcourir(
        "olist", "bronze", "2018-04-29", couche_bronze
    )

    assert ratees == []
    assert rapports, "aucune table examinée : le test ne prouverait rien"
    assert all(r["en_attente"] for r in rapports), "l'agent n'a rien trouvé, test creux"


def test_le_code_de_sortie_ne_dit_que_si_l_agent_a_pu_tourner(
    couche_bronze, monkeypatch
):
    """0 quoi qu'il ait trouvé ; 1 seulement s'il n'a pas pu tourner."""
    PROFIL_FACTICE.colonnes = ["c0", "c1", "c2", "c3"]
    monkeypatch.setattr(
        check_layer,
        "parcourir",
        lambda *a, **k: (
            [{"table": "T", "thread": "t", "anomalies": 3, "en_attente": True}],
            [],
        ),
    )
    assert check_layer.main(["olist", "bronze", "--day", "2018-04-29"]) == 0

    monkeypatch.setattr(check_layer, "parcourir", lambda *a, **k: ([], ["T : boom"]))
    assert check_layer.main(["olist", "bronze", "--day", "2018-04-29"]) == 1


def test_une_table_qui_echoue_n_emporte_pas_les_autres(couche_bronze, monkeypatch):
    """Examiner dix-sept tables ne doit pas mourir sur la troisième. L'échec est
    rapporté **avec sa cause**, pas avalé — même règle qu'en 4.2.5."""
    vrai = check_layer.examiner
    appels = []

    def capricieux(app, dataset, couche, table, jour, echecs):
        appels.append(table)
        if table == "RAW.ORDERS":
            raise RuntimeError("Snowflake indisponible")
        return vrai(app, dataset, couche, table, jour, echecs)

    monkeypatch.setattr(check_layer, "examiner", capricieux)
    rapports, ratees = check_layer.parcourir(
        "olist", "bronze", "2018-04-29", couche_bronze
    )

    assert appels == ["RAW.ORDERS", "RAW.CUSTOMERS"], "le balayage s'est arrêté"
    assert len(rapports) == 1 and len(ratees) == 1
    assert "RAW.ORDERS" in ratees[0] and "Snowflake indisponible" in ratees[0]


def test_une_couche_vide_echoue_bruyamment(monkeypatch, tmp_path):
    """Ce n'est pas une anomalie de donnée mais une erreur de déclaration : la
    masquer ferait croire qu'une couche a été surveillée alors qu'elle ne
    contient aucune table déclarée. Même symétrie que dans le connecteur (4.0).
    """
    monkeypatch.setattr(check_layer, "charger_registre", lambda ds: RegistreJouet([]))
    with pytest.raises(SystemExit):
        check_layer.parcourir("olist", "gold", "2018-04-29", tmp_path / "c.sqlite")


def test_le_thread_est_reconstructible_de_tete():
    """Un identifiant aléatoire obligerait l'humain à le chercher dans un journal
    avant de pouvoir reprendre un run."""
    assert (
        check_layer.identifiant("olist", "RAW.ORDERS", "2018-04-29")
        == "olist|RAW.ORDERS|2018-04-29"
    )


def test_bronze_n_a_pas_de_resultats_dbt():
    """Bronze est une *source* : rien n'y est typé, dbt ne la teste pas."""
    assert check_layer.echecs_dbt("bronze", None) == []


# ---------------------------------------------------------------------------
# Lire les verdicts de dbt
# ---------------------------------------------------------------------------


def artefacts(tmp_path, resultats, noeuds):
    (tmp_path / "run_results.json").write_text(json.dumps({"results": resultats}))
    (tmp_path / "manifest.json").write_text(json.dumps({"nodes": noeuds}))
    return tmp_path / "run_results.json", tmp_path / "manifest.json"


UID = "test.pfa_dbt.not_null_stg_customers_customer_id.abc123"
NOEUD = {
    UID: {
        "attached_node": "model.pfa_dbt.stg_customers",
        "column_name": "customer_id",
        "name": "not_null_stg_customers_customer_id",
        "test_metadata": {"name": "not_null"},
    }
}


def test_seuls_les_tests_en_echec_remontent(tmp_path):
    rr, mf = artefacts(
        tmp_path,
        [
            {"unique_id": UID, "status": "fail", "failures": 51},
            {"unique_id": "test.pfa_dbt.autre.x", "status": "pass", "failures": 0},
        ],
        NOEUD,
    )
    echecs = lire_echecs(rr, mf, None)
    assert len(echecs) == 1 and echecs[0]["failures"] == 51


def test_le_manifest_dit_de_quoi_il_s_agit(tmp_path):
    """⭐ On pourrait découper le nom du test — mais rien ne sépare le modèle de
    la colonne dans `not_null_stg_customers_customer_id`, et un modèle nommé
    `customers_customer` rendrait le découpage ambigu sans prévenir."""
    rr, mf = artefacts(
        tmp_path, [{"unique_id": UID, "status": "fail", "failures": 51}], NOEUD
    )
    echec = lire_echecs(rr, mf, None)[0]
    assert echec["colonne"] == "CUSTOMER_ID"
    assert echec["sorte"] == "not_null"
    assert echec["dama"] == "completude"


def test_le_registre_donne_le_vrai_nom_de_table(tmp_path):
    """dbt connaît `stg_customers`, le registre déclare `STAGING.STG_CUSTOMERS`.
    La correspondance passe par le registre et non par une table de schémas
    écrite en dur : un dataset qui range son Silver ailleurs ne casse rien."""
    registre = RegistreJouet([TableJouet("STAGING.STG_CUSTOMERS", "silver")])
    rr, mf = artefacts(
        tmp_path, [{"unique_id": UID, "status": "fail", "failures": 1}], NOEUD
    )
    assert lire_echecs(rr, mf, registre)[0]["table"] == "STAGING.STG_CUSTOMERS"


def test_un_artefact_absent_ne_fait_pas_lever(tmp_path):
    """Un run sans artefact dbt n'est pas un run sans échec, c'est un run dont on
    ne sait rien. Le dire par une liste vide est le moins trompeur — et l'agent
    doit pouvoir tourner même quand dbt a mal fini."""
    assert lire_echecs(tmp_path / "absent.json", tmp_path / "absent.json", None) == []


def test_un_artefact_corrompu_ne_fait_pas_lever(tmp_path):
    (tmp_path / "run_results.json").write_text("{ ceci n'est pas du JSON")
    assert lire_echecs(tmp_path / "run_results.json", tmp_path / "x.json", None) == []


# ---------------------------------------------------------------------------
# La famille `dbt` — elle traduit, elle ne détecte pas
# ---------------------------------------------------------------------------


def etat_avec_echecs(echecs, table="STAGING.STG_CUSTOMERS"):
    etat = new_state("olist", "silver", table, "2018-04-29")
    etat["dbt_failures"] = echecs
    return etat


def test_un_echec_dbt_devient_un_ecart():
    """Ce qui referme la boucle de 4.1.8 : l'agent génère des règles dbt, dbt les
    exécute, et leurs échecs **reviennent** à l'agent — donc gagnent un
    diagnostic, une signature, une place dans INCIDENTS et la mémoire."""
    ecarts = famille_dbt.detecter(
        etat_avec_echecs(
            [
                {
                    "table": "STAGING.STG_CUSTOMERS",
                    "colonne": "CUSTOMER_ID",
                    "test": "not_null_x",
                    "sorte": "not_null",
                    "dama": "completude",
                    "failures": 51,
                    "statut": "fail",
                }
            ]
        )
    )
    assert [e["type"] for e in ecarts] == ["test_dbt_echoue"]
    assert ecarts[0]["famille"] == "dbt"
    assert ecarts[0]["ampleur"] == 51
    assert ecarts[0]["dama"] == "completude"


def test_un_echec_d_une_autre_table_est_ignore():
    """L'agent est invoqué table par table : mélanger les verdicts ferait
    signaler à `STG_CUSTOMERS` une anomalie de `STG_PRODUCTS`."""
    ecarts = famille_dbt.detecter(
        etat_avec_echecs([{"table": "STAGING.STG_PRODUCTS", "failures": 3}])
    )
    assert ecarts == []


def test_sans_echec_la_famille_se_tait():
    assert famille_dbt.detecter(etat_avec_echecs([])) == []
