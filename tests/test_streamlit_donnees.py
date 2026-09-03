"""Contrôle de la couche de données des écrans (phase 6.1).

Les vues Streamlit ne contiennent que de l'affichage : tout ce qui se raisonne
vit dans `streamlit/donnees.py`, et se teste donc **sans navigateur**. Même
partage qu'entre le DAG Airflow et `scripts/check_layer.py` — une logique
enfermée dans un `st.button()` n'est éprouvable qu'à la main, et un écran de
décision qu'on ne peut pas tester est un écran dont on ne sait pas s'il montre
la vérité.

Le test qui compte est `test_le_journal_montre_AUSSI_les_runs_sans_anomalie` :
un historique plus propre que la réalité est pire qu'un historique absent.
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

from agent.state import DECISION_APPROVED, DECISION_REJECTED
from conftest import MEMOIRE_FACTICE

# ⚠️ **Collision de noms assumée** : le dossier de l'application s'appelle
# `streamlit/`, comme le paquet installé. `import streamlit.donnees` résoudrait
# donc vers `site-packages` et échouerait — au chargement, pas à l'exécution, ce
# qui rend l'erreur d'autant plus déroutante. On ajoute le dossier au chemin et
# on importe le module nu : exactement ce que fait `streamlit run`, qui place le
# dossier du script en tête de `sys.path`.
#
# Le dossier garde son nom : il figure dans la structure du dépôt depuis la
# phase 0, dans le README et dans le cahier. Renommer coûterait plus que ce
# commentaire.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "streamlit"))
donnees = importlib.import_module("donnees")


def incident(**kw):
    base = {
        "incident_id": "i1",
        "run_ts": "2026-08-17T10:00:00",
        "dataset": "olist",
        "layer": "bronze",
        "table_name": "RAW.ORDERS",
        "batch_id": "2018-04-29",
        "anomalies": [],
        "signatures": [],
        "diagnosis": None,
        "human_decision": None,
        "decided_by": None,
        "decided_at": None,
        "applied_fix": None,
        "validation_status": None,
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def memoire(monkeypatch):
    """Le journal en mémoire — `lire_journal` ne filtre pas, contrairement à la
    mémoire de l'agent."""

    def lire_journal(dataset, table=None, couche=None, depuis=None, limite=500):
        return [
            i
            for i in reversed(MEMOIRE_FACTICE.incidents)
            if i.get("dataset") == dataset
            and (table is None or i.get("table_name") == table)
            and (couche is None or i.get("layer") == couche)
        ]

    MEMOIRE_FACTICE.lire_journal = lire_journal
    monkeypatch.setattr(donnees, "_memoire", lambda: MEMOIRE_FACTICE)
    return MEMOIRE_FACTICE


# ===========================================================================
# Le journal n'est pas la mémoire
# ===========================================================================


def test_le_journal_montre_AUSSI_les_runs_sans_anomalie(memoire):
    """⭐ `lire_incidents` filtre aux décisions humaines (R5) parce que c'est ce
    que l'**agent** relit — lui donner ses propres hypothèses le ferait tourner
    en rond. `lire_journal` ne filtre rien, parce que c'est ce qu'un **humain**
    relit.

    Les cacher donnerait un historique **plus propre que la réalité**, et c'est
    précisément là qu'on regarde pour savoir ce que l'agent a fait cette nuit.
    """
    memoire.incidents = [
        incident(incident_id="calme"),
        incident(incident_id="tranche", human_decision=DECISION_APPROVED),
    ]
    assert {i["incident_id"] for i in donnees.journal("olist")} == {"calme", "tranche"}


@pytest.mark.parametrize(
    "champs,attendu",
    [
        ({}, "rien d'anormal"),
        ({"anomalies": [{"x": 1}]}, "en attente"),
        ({"anomalies": [{"x": 1}], "human_decision": DECISION_REJECTED}, "rejected"),
    ],
)
def test_le_statut_est_derive_jamais_stocke(champs, attendu):
    """« En attente » n'est pas une valeur de `human_decision`, c'est son
    absence. Le calculer plutôt que l'écrire évite un champ qui pourrait mentir
    — un incident tranché dont le statut serait resté « en attente » serait
    invisible pour toujours."""
    assert donnees.statut(incident(**champs)) == attendu


def test_le_resume_tient_sur_une_ligne(memoire):
    ligne = donnees.resumer_incident(
        incident(
            anomalies=[{"a": 1}, {"b": 2}],
            human_decision=DECISION_APPROVED,
            applied_fix="UPDATE …",
            decided_by="hoda",
        )
    )
    assert ligne["ecarts"] == 2 and ligne["statut"] == DECISION_APPROVED
    assert ligne["applique"] is True and ligne["decideur"] == "hoda"


def test_le_filtre_par_couche_fonctionne(memoire):
    memoire.incidents = [
        incident(incident_id="b", layer="bronze"),
        incident(incident_id="g", layer="gold"),
    ]
    assert [i["incident_id"] for i in donnees.journal("olist", couche="gold")] == ["g"]


# ===========================================================================
# ⭐ Signatures en silence — le garde-fou anti-cécité
# ===========================================================================


def test_seuls_les_refus_font_taire(memoire):
    """Approuver, c'est corriger — pas décréter que l'anomalie est normale."""
    memoire.incidents = [
        incident(human_decision=DECISION_APPROVED, signatures=["T|C|nulls|-2"]),
        incident(human_decision=None, signatures=["T|C|autre|-2"]),
        incident(human_decision=DECISION_REJECTED, signatures=["T|C|tu|-1"]),
    ]
    assert [s["signature"] for s in donnees.silences("olist")] == ["T|C|tu|-1"]


def test_chaque_silence_dit_qui_et_quand(memoire):
    """Une décision sans auteur ne se conteste pas six mois plus tard."""
    memoire.incidents = [
        incident(
            human_decision=DECISION_REJECTED,
            signatures=["RAW.ORDERS|CUSTOMER_ID|nulls_interdits|-2"],
            decided_by="hoda",
            decided_at="2026-08-17T11:00:00",
        )
    ]
    ligne = donnees.silences("olist")[0]
    assert ligne["refuse_par"] == "hoda"
    assert ligne["refuse_le"] == "2026-08-17T11:00:00"


def test_la_signature_est_decoupee_pour_etre_lisible(memoire):
    """⭐ L'ordre de grandeur doit **se voir** : c'est lui qui explique pourquoi
    l'agent reparlera si l'ampleur change d'échelle. Une chaîne opaque
    n'apprendrait rien à qui décide de réactiver."""
    memoire.incidents = [
        incident(
            human_decision=DECISION_REJECTED,
            signatures=["RAW.ORDERS|CUSTOMER_ID|nulls_interdits|-2"],
        )
    ]
    ligne = donnees.silences("olist")[0]
    assert ligne["table"] == "RAW.ORDERS"
    assert ligne["colonne"] == "CUSTOMER_ID"
    assert ligne["type"] == "nulls_interdits"
    assert ligne["ordre_de_grandeur"] == "-2"


def test_une_signature_malformee_n_efface_pas_l_ecran(memoire):
    """⭐ Un garde-fou anti-cécité qui plante sur une ligne malformée n'affiche
    plus rien du tout — ce qui est exactement la cécité qu'il combat."""
    # ⚠️ `"cassée"` **ne lève pas** : `split("|")` en fait un tuple d'un terme.
    # Une première version de ce test l'utilisait, et le sabotage « la signature
    # malformée fait tomber l'écran » passait inaperçu — le test ne pouvait pas
    # échouer. Il faut une valeur qui casse vraiment `depuis_texte`, c'est-à-dire
    # qui n'est pas une chaîne : la base peut en rendre si le JSON a mal tourné.
    memoire.incidents = [
        incident(
            human_decision=DECISION_REJECTED,
            signatures=[{"pas": "une chaîne"}, "cassée", "A|B|c|0"],
        )
    ]
    lignes = donnees.silences("olist")
    assert len(lignes) == 3, "une ligne malformée a fait disparaître les autres"
    assert lignes[2]["table"] == "A", "les lignes saines restent lisibles"


def test_sans_refus_l_ecran_est_vide(memoire):
    memoire.incidents = [incident(human_decision=DECISION_APPROVED, signatures=["x"])]
    assert donnees.silences("olist") == []


# ===========================================================================
# Dire ce qui s'est passé, et non de quelle dimension il relève
# ===========================================================================


def ecart(**kw):
    base = {"table": "RAW.GEOLOCATION", "colonne": None, "observe": None, "details": {}}
    return base | kw


def test_une_colonne_apparue_ne_se_dit_pas_une_contradiction():
    """⭐ La phrase était fausse sur l'écran même où l'on décide.

    L'écart est de dimension DAMA « cohérence », mais afficher la dimension
    donnait « des écritures qui se contredisent sur « _BATCH_ID » » — un
    diagnostic de contenu là où le constat porte sur la **structure**. Personne
    ne peut trancher sur une phrase qui décrit autre chose que ce qui s'est
    passé.
    """
    phrase = donnees.anomalie_lisible(
        ecart(type="colonne_nouvelle", dama="coherence", colonne="_BATCH_ID",
              observe="_BATCH_ID")
    )
    assert phrase == "une colonne est apparue : « _BATCH_ID »"


def test_le_chiffre_des_doublons_n_est_pas_celui_des_valeurs_saines():
    """`observe` porte le nombre de valeurs **distinctes** : « des doublons —
    3891 » faisait lire l'inverse du constat. Le décompte est dans les détails."""
    phrase = donnees.anomalie_lisible(
        ecart(type="doublons", dama="unicite", colonne="ORDER_ID",
              observe=3891, details={"doublons": 109})
    )
    assert phrase == "des doublons sur « ORDER_ID » — 109"


def test_le_chiffre_reste_affiche_quand_il_veut_dire_quelque_chose():
    """« des valeurs manquent » sans « 51 » ne sert à personne pour décider."""
    assert donnees.anomalie_lisible(
        ecart(type="nulls_interdits", dama="completude", colonne="CUSTOMER_ID",
              observe=51)
    ) == "des valeurs manquent sur « CUSTOMER_ID » — 51"


def test_un_type_inconnu_retombe_sur_la_dimension():
    """Une sixième famille ajoutée sans passer ici : l'écran montre encore
    quelque chose de vrai, au lieu de tomber sur un `KeyError`."""
    phrase = donnees.anomalie_lisible(
        ecart(type="ce_qui_n_existe_pas_encore", dama="fraicheur", colonne="X")
    )
    assert phrase == "des données en retard sur « X »"


def test_chaque_type_d_ecart_produit_par_l_agent_a_sa_phrase():
    """⭐ Le test qui empêche le retour du problème.

    Une famille de détection peut naître sans que personne pense à l'écran :
    l'écart s'afficherait alors sous la dimension DAMA du voisin, c'est-à-dire
    en disant autre chose que ce qui s'est passé. On lit donc les `type=` que
    les familles produisent réellement, plutôt que d'en tenir une liste à jour
    à la main — une liste recopiée ne prouve que sa propre recopie.
    """
    dossier = Path(donnees.__file__).resolve().parent.parent / "agent" / "detect"
    produits = {
        mot.value
        for source in dossier.glob("*.py")
        for noeud in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(noeud, ast.Call) and getattr(noeud.func, "id", "") == "ecart"
        for mot in [
            kw.value for kw in noeud.keywords
            if kw.arg == "type" and isinstance(kw.value, ast.Constant)
        ]
    }
    assert produits, "aucun type lu : le test ne prouverait plus rien"
    assert produits <= set(donnees.TYPES_LISIBLES), (
        f"sans phrase : {sorted(produits - set(donnees.TYPES_LISIBLES))}"
    )


# ===========================================================================
# La reprise n'est pas ici
# ===========================================================================


def test_la_couche_de_donnees_ne_reprend_aucun_run():
    """⭐ La reprise vit dans `agent/hitl.py`, la voie unique que
    `scripts/decide.py` emprunte aussi.

    Une seconde voie serait une seconde façon de contourner P3 : la garantie
    « aucun chemin n'atteint `apply` sans approbation » ne vaudrait plus que
    pour les chemins qu'on a testés. Ce test échouera si quelqu'un ajoute ici
    un raccourci « pratique ».
    """
    source = Path(donnees.__file__).read_text(encoding="utf-8")
    assert "Command(" not in source
    assert "resume=" not in source
