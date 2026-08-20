"""Contrôle du cycle Découverte (phase 4.2.5) — sans base, sans réseau.

`profile_table` est remplacé par une fiche préparée : on éprouve l'enchaînement
profilage → proposition → disque → validation, pas Snowflake.

Le fil conducteur de ce fichier est ce que la découverte **refuse** de faire :
mourir sur une table, valider sans signataire, valider sans avoir regardé ce
qu'elle a critiqué, et surtout **écraser ce qu'un humain a corrigé**.
"""

import importlib

import pytest

import scripts.discover as discover
from agent.contracts import ContratInvalide, charger, lister
from agent.registry import Registre, TableDeclaree

REGISTRE = Registre(
    name="jouet",
    connector="peu_importe",
    tables=(
        TableDeclaree(name="RAW.ORDERS", layer="bronze", batch_column="_lot"),
        TableDeclaree(name="RAW.CUSTOMERS", layer="bronze", batch_column="_lot"),
    ),
)


def fiche_propre(table="RAW.ORDERS"):
    return {
        "table": table,
        "batch_id": None,
        "row_count": 1000,
        "columns": {
            "ORDER_ID": {"role": "identifier", "null_count": 0, "distinct": 1000},
        },
    }


def fiche_sale(table="RAW.CUSTOMERS"):
    """Une table qui porte le fil rouge : `sao paulo` et `são paulo` côte à côte."""
    return {
        "table": table,
        "batch_id": None,
        "row_count": 1000,
        "columns": {
            "CUSTOMER_CITY": {
                "role": "categorical",
                "null_count": 0,
                "distinct": 2,
                "coverage": 1.0,
                "top": [
                    {"value": "sao paulo", "count": 600},
                    {"value": "são paulo", "count": 400},
                ],
            },
        },
    }


@pytest.fixture
def branche(monkeypatch):
    """Un registre factice et un `profile_table` qui rend des fiches préparées."""
    fiches = {}

    class ProfileFactice:
        appels = []

        @staticmethod
        def invoke(arguments):
            ProfileFactice.appels.append(arguments)
            return fiches.get(arguments["table"])

    ProfileFactice.appels = []
    monkeypatch.setattr(discover, "charger_registre", lambda nom: REGISTRE)
    monkeypatch.setattr(discover, "profile_table", ProfileFactice)
    return fiches, ProfileFactice


# ---------------------------------------------------------------------------
# La découverte
# ---------------------------------------------------------------------------


def test_la_decouverte_profile_la_table_entiere(branche, tmp_path):
    """À rebours de la surveillance, et c'est délibéré.

    La surveillance filtre par lot — sans quoi 30 % de nulls sur un jour ne
    pèsent plus que 0,3 % noyés dans 92 jours. La découverte cherche ce qui est
    *normal* : un contrat bâti sur une seule journée serait absurdement étroit,
    et les valeurs légitimes absentes ce jour-là deviendraient des violations
    dès le lendemain.
    """
    fiches, profile = branche
    fiches["RAW.ORDERS"] = fiche_propre()

    discover.decouvrir("jouet", ["RAW.ORDERS"], dossier=tmp_path)

    assert profile.appels == [{"dataset": "jouet", "table": "RAW.ORDERS"}]
    assert "batch_id" not in profile.appels[0], "aucun lot : la fenêtre entière"


def test_toutes_les_tables_declarees_par_defaut(branche, tmp_path):
    fiches, _ = branche
    fiches["RAW.ORDERS"] = fiche_propre()
    fiches["RAW.CUSTOMERS"] = fiche_sale()

    rendus = discover.decouvrir("jouet", dossier=tmp_path)
    assert [r["table"] for r in rendus] == ["RAW.ORDERS", "RAW.CUSTOMERS"]


def test_le_contrat_atterrit_sur_disque_en_attente(branche, tmp_path):
    fiches, _ = branche
    fiches["RAW.ORDERS"] = fiche_propre()

    discover.decouvrir("jouet", ["RAW.ORDERS"], dossier=tmp_path)

    (vu,) = lister("jouet", dossier=tmp_path)
    assert vu["status"] == "proposed"
    assert charger("jouet", "RAW.ORDERS", dossier=tmp_path) is None


def test_les_avertissements_remontent_dans_le_compte_rendu(branche, tmp_path):
    """C'est ce que la découverte a **refusé de graver** : ça doit se voir."""
    fiches, _ = branche
    fiches["RAW.CUSTOMERS"] = fiche_sale()

    (rendu,) = discover.decouvrir("jouet", ["RAW.CUSTOMERS"], dossier=tmp_path)

    assert rendu["warnings"][0]["kind"] == "semantic_collision"
    assert "são paulo" in rendu["warnings"][0]["detail"]


def test_une_table_absente_n_arrete_pas_les_autres(branche, tmp_path):
    """Découvrir dix-sept tables ne doit pas mourir sur la troisième."""
    fiches, _ = branche
    fiches["RAW.CUSTOMERS"] = fiche_sale()  # `RAW.ORDERS` reste absente

    rendus = discover.decouvrir("jouet", dossier=tmp_path)

    absente, presente = rendus
    assert absente["error"] == "table absente de la base"
    assert presente["path"] is not None, "la suivante a bien été traitée"


def test_une_table_qui_leve_est_rapportee_pas_avalee(branche, tmp_path):
    """L'échec figure dans le compte rendu **avec sa cause** : un run qui se tait
    sur ce qu'il n'a pas pu faire vaut moins qu'un run qui plante."""
    _, profile = branche

    def plante(arguments):
        raise RuntimeError("Snowflake indisponible")

    profile.invoke = staticmethod(plante)

    (rendu,) = discover.decouvrir("jouet", ["RAW.ORDERS"], dossier=tmp_path)
    assert "Snowflake indisponible" in rendu["error"]


# ---------------------------------------------------------------------------
# La validation humaine
# ---------------------------------------------------------------------------


def test_valider_fait_passer_le_contrat_en_vigueur(branche, tmp_path):
    fiches, _ = branche
    fiches["RAW.ORDERS"] = fiche_propre()
    discover.decouvrir("jouet", ["RAW.ORDERS"], dossier=tmp_path)

    discover.approuver("jouet", "RAW.ORDERS", par="hoda", dossier=tmp_path)

    applique = charger("jouet", "RAW.ORDERS", dossier=tmp_path)
    assert applique["status"] == "approved"
    assert applique["approved_by"] == "hoda"


def test_valider_relit_le_fichier_et_conserve_les_corrections(branche, tmp_path):
    """LE test qui justifie d'avoir écarté `interrupt()`.

    L'humain ouvre le YAML et ajuste une borne — c'est tout l'objet de l'étape :
    la machine propose du *descriptif*, lui le rend *normatif*. Si la validation
    reprenait une copie gardée en mémoire (ou dans un checkpoint), elle
    réécrirait la version d'origine et **effacerait la correction**, sans que
    rien ne le signale.
    """
    fiches, _ = branche
    fiches["RAW.ORDERS"] = fiche_propre()
    (rendu,) = discover.decouvrir("jouet", ["RAW.ORDERS"], dossier=tmp_path)

    # Ce que fait un humain : il ouvre le fichier et il corrige.
    texte = rendu["path"].read_text(encoding="utf-8")
    rendu["path"].write_text(
        texte.replace("unique: true", "unique: true\n    max_length: 32"),
        encoding="utf-8",
    )

    discover.approuver("jouet", "RAW.ORDERS", par="hoda", dossier=tmp_path)

    applique = charger("jouet", "RAW.ORDERS", dossier=tmp_path)
    assert applique["columns"]["ORDER_ID"]["max_length"] == 32, (
        "la correction a survécu"
    )


def test_valider_un_contrat_critique_exige_de_le_dire(branche, tmp_path):
    """Signer une collision sémantique est une décision, pas une formalité.

    Sans ce garde-fou, le cas d'école du projet se validerait d'un `--approve`
    distrait — et la découverte aurait critiqué pour rien.
    """
    fiches, _ = branche
    fiches["RAW.CUSTOMERS"] = fiche_sale()
    discover.decouvrir("jouet", ["RAW.CUSTOMERS"], dossier=tmp_path)

    with pytest.raises(ContratInvalide, match="avertissement"):
        discover.approuver("jouet", "RAW.CUSTOMERS", par="hoda", dossier=tmp_path)

    discover.approuver(
        "jouet",
        "RAW.CUSTOMERS",
        par="hoda",
        accepter_avertissements=True,
        dossier=tmp_path,
    )
    assert charger("jouet", "RAW.CUSTOMERS", dossier=tmp_path) is not None


def test_valider_deux_fois_est_refuse(branche, tmp_path):
    """Un contrat en vigueur s'amende en version suivante, il ne se re-signe pas.

    Le refus vient d'`ecrire()`, pas d'`approuver()` : c'est lui qui touche au
    disque, donc c'est là que la garantie doit vivre. Un contrôle en double dans
    `approuver()` a été retiré après qu'un sabotage l'ait supprimé sans faire
    rougir un seul test — la preuve qu'il ne portait rien.
    """
    fiches, _ = branche
    fiches["RAW.ORDERS"] = fiche_propre()
    discover.decouvrir("jouet", ["RAW.ORDERS"], dossier=tmp_path)
    discover.approuver("jouet", "RAW.ORDERS", par="hoda", dossier=tmp_path)

    with pytest.raises(ContratInvalide, match="déjà validé"):
        discover.approuver("jouet", "RAW.ORDERS", par="hoda", dossier=tmp_path)


def test_c_est_la_derniere_version_qui_se_signe(branche, tmp_path):
    """Une v2 en discussion se signe ; la v1 validée gouverne jusque-là.

    C'est le chemin que l'amendement empruntera en phase 5. Il n'est pas encore
    atteignable par la découverte (qui n'écrit que des v1), mais le code le
    traite — et du code que personne n'éprouve finit par être faux le jour où
    quelqu'un s'y fie.
    """
    from agent.contracts import ecrire

    v1 = {
        "table": "RAW.ORDERS",
        "version": 1,
        "status": "approved",
        "columns": {"ORDER_ID": {"role": "identifier"}},
        "warnings": [],
    }
    ecrire(v1, "jouet", dossier=tmp_path)
    ecrire({**v1, "version": 2, "status": "proposed"}, "jouet", dossier=tmp_path)

    signe = discover.approuver("jouet", "RAW.ORDERS", par="hoda", dossier=tmp_path)

    assert signe["version"] == 2
    assert charger("jouet", "RAW.ORDERS", dossier=tmp_path)["version"] == 2


def test_valider_une_table_sans_contrat_est_refuse(tmp_path):
    with pytest.raises(ContratInvalide, match="Aucun contrat"):
        discover.approuver("jouet", "RAW.INCONNUE", par="hoda", dossier=tmp_path)


# ---------------------------------------------------------------------------
# La ligne de commande
# ---------------------------------------------------------------------------


def test_approuver_sans_signataire_est_refuse(monkeypatch, capsys):
    """Un contrat sans signataire ne prouve rien six mois plus tard — c'est la
    même traçabilité que `decided_by` dans le cycle de surveillance."""
    monkeypatch.setattr("sys.argv", ["discover", "jouet", "--approve", "RAW.ORDERS"])
    assert discover.main() == 1
    assert "--by" in capsys.readouterr().out


def test_le_script_ne_lie_aucun_tool_au_modele():
    """Le garde-fou de l'ADR 004 vaut aussi ici : la découverte enchaîne des
    appels **écrits dans le code**, elle ne délègue pas le flux à un modèle."""
    source = importlib.import_module("scripts.discover").__file__
    with open(source, encoding="utf-8") as fichier:
        assert "bind_tools" not in fichier.read()
