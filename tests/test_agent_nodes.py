"""Contrôle des nœuds de l'agent (phase 3.1), testés **isolément** (sans graphe).

C'est tout l'intérêt d'avoir des fonctions pures `AgentState -> dict` : on peut
vérifier chaque nœud sans compiler le graphe, sans checkpointer, sans Snowflake
et sans LLM.

⚠️ C'est **ici** que vivent les noms de colonnes, jamais dans `agent/`. Même
séparation que `ground_truth.yaml` : le dataset appartient au banc d'essai, pas
à l'agent. Un test branche un dataset de commandes, l'autre un dataset RH sans
aucun rapport — et le même nœud doit traiter les deux.

Ce fichier grandit d'un bloc à chaque nœud ajouté.
"""

import copy
import importlib
import json

import pytest
from pydantic import ValidationError

from agent.llm import CONSIGNES, Diagnostic
from agent.nodes import amend, apply, detect, diagnose, log, profile, propose, validate
from agent.nodes.amend import _version_suivante
from agent.nodes.validate import VALIDATION_OK

# Le double de `profile_table` (cf. conftest.py) : depuis 4.3 c'est lui, et non
# plus l'état, qui décide des colonnes que la mesure rendra. pytest place le
# dossier des tests sur `sys.path`, d'où l'import direct du conftest.
from conftest import MEMOIRE_FACTICE, PROFIL_FACTICE
from agent.nodes.propose import build_proposal, lire_reponse
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    log_entry,
    new_state,
)

# ⚠️ `agent.nodes.__init__` réexporte les fonctions sous le nom de leur module :
# `agent.nodes.diagnose` désigne donc la **fonction**, pas le module. Un
# `import agent.nodes.diagnose as m` récupère la fonction et les `monkeypatch`
# ne remplacent rien — silencieusement, en laissant partir de vrais appels
# réseau. On va donc chercher le module explicitement.
diagnose_mod = importlib.import_module("agent.nodes.diagnose")

# Deux datasets volontairement étrangers l'un à l'autre.
SCHEMA_COMMANDES = [
    {"name": "order_id"},
    {"name": "customer_id"},
    {"name": "order_status"},
    {"name": "order_purchase_timestamp"},
]
SCHEMA_RH = [
    {"name": "matricule"},
    {"name": "departement"},
    {"name": "salaire_brut"},
]


def base_state(schema=None, table="RAW.ORDERS"):
    state = new_state(
        dataset="olist", layer="bronze", table=table, batch_id="2018-04-29"
    )
    state["schema_history"] = schema or []
    # Depuis 4.3, `profile` mesure vraiment : ce sont les colonnes que le double
    # de `profile_table` rendra (cf. tests/conftest.py), et non plus l'état, qui
    # décident de la fiche. Le test continue de piloter la forme du lot — il le
    # fait simplement là où la mesure a lieu.
    if schema:
        PROFIL_FACTICE.colonnes = [c["name"] for c in schema]
    return state


# --- Nœud 1/8 : profile ------------------------------------------------------


def test_profile_ne_produit_que_des_agregats():
    """Le profil ne doit jamais contenir de lignes brutes : le LLM les verrait."""
    fiche = profile(base_state(SCHEMA_COMMANDES))["profile"]
    assert set(fiche) == {"table", "batch_id", "row_count", "columns"}
    assert isinstance(fiche["row_count"], int)
    # Aucune valeur de la fiche n'est une collection de lignes : les seules
    # listes admises sont les top-K, qui sont une distribution et non un extrait.
    for stats in fiche["columns"].values():
        for cle, valeur in stats.items():
            assert cle == "top" or not isinstance(valeur, (list, tuple)), cle


def test_profile_s_adapte_a_n_importe_quel_dataset():
    """LE test de portabilité : le même nœud, deux datasets sans rapport.

    Si un jour il devient rouge parce qu'un nom de colonne s'est glissé dans
    `agent/`, c'est que l'agent a cessé d'être portable.
    """
    commandes = profile(base_state(SCHEMA_COMMANDES))["profile"]
    rh = profile(base_state(SCHEMA_RH, table="HR.EMPLOYES"))["profile"]

    assert list(commandes["columns"]) == [c["name"] for c in SCHEMA_COMMANDES]
    assert list(rh["columns"]) == [c["name"] for c in SCHEMA_RH]


def test_profile_calcule_les_memes_metriques_partout():
    """Les métriques ne dépendent pas du dataset, seulement de ce qui a été mesuré.

    On compare **position par position** : la 1ʳᵉ colonne d'un dataset RH doit
    recevoir exactement le même jeu de métriques que la 1ʳᵉ colonne d'un dataset
    e-commerce. Comparer globalement serait faux — une colonne qui a reçu un
    top-K porte légitimement plus de clés qu'une colonne écartée par le critère,
    et exiger l'uniformité interdirait la mesure à la carte de 4.1.5.
    """
    commandes = profile(base_state(SCHEMA_COMMANDES))["profile"]["columns"]
    rh = profile(base_state(SCHEMA_RH))["profile"]["columns"]

    for rang, (une, autre) in enumerate(zip(commandes.values(), rh.values())):
        assert set(une) == set(autre), f"colonne de rang {rang}"


def test_profile_sans_schema_reste_neutre():
    """Sans introspection, le stub retombe sur des noms qui n'évoquent aucun dataset."""
    colonnes = profile(base_state())["profile"]["columns"]
    assert all(nom.startswith("col_") for nom in colonnes)


def test_profile_ne_modifie_pas_l_etat_recu():
    """Fonction pure : le nœud retourne ses changements, il ne mute rien."""
    state = base_state(SCHEMA_COMMANDES)
    avant = copy.deepcopy(state)
    profile(state)
    assert state == avant


def test_profile_ecrit_une_ligne_de_journal_au_format_commun():
    entry = profile(base_state(SCHEMA_RH))["logs"][0]
    assert entry["node"] == "profile"
    assert entry["colonnes"] == 3
    assert set(log_entry("x", "y")) <= set(entry)  # ts + node + message garantis


# --- profile : la mesure est rangée dans l'historique (phase 4.3) ------------


def test_profile_archive_la_mesure_du_jour():
    """Mesurer sans archiver ne construirait jamais de référence.

    C'est `_PROFILES` qui rend la famille statistique possible : sans écriture,
    l'agent recommencerait chaque jour à zéro et ne pourrait comparer qu'au
    contrat — soit un pilier de détection sur trois.
    """
    etat = base_state(SCHEMA_COMMANDES)
    resultat = profile(etat)

    assert ("olist", "RAW.ORDERS", "2018-04-29") in MEMOIRE_FACTICE.lots
    assert resultat["logs"][0]["mesures_archivees"] > 0


def test_profile_charge_l_historique_dans_l_etat():
    """`detect` ne fait aucune entrée-sortie : c'est `profile` qui lui apporte
    la référence. Un détecteur qui ouvre une connexion est un détecteur qu'on ne
    peut pas rejouer à l'identique au benchmark."""
    MEMOIRE_FACTICE.lots[("olist", "RAW.ORDERS", "2018-04-01")] = {
        (None, "row_count"): 300.0
    }
    resultat = profile(base_state(SCHEMA_COMMANDES))
    assert resultat["profile_history"][(None, "row_count")] == [300.0]


def test_le_lot_du_jour_n_entre_pas_dans_sa_propre_reference():
    """⭐ La garantie qui survit au rejeu.

    On archive d'abord le lot courant — comme si un run précédent l'avait déjà
    fait — puis on relance. S'il ressortait dans l'historique, sa médiane se
    rapprocherait de lui à chaque tentative, jusqu'à ce que l'anomalie devienne
    la norme. Airflow rejoue une tâche en cas d'échec : le cas n'est pas
    théorique.
    """
    MEMOIRE_FACTICE.lots[("olist", "RAW.ORDERS", "2018-04-29")] = {
        (None, "row_count"): 999.0
    }
    MEMOIRE_FACTICE.lots[("olist", "RAW.ORDERS", "2018-04-28")] = {
        (None, "row_count"): 300.0
    }
    historique = profile(base_state(SCHEMA_COMMANDES))["profile_history"]

    assert historique[(None, "row_count")] == [300.0], "le lot courant a fuité"


def test_une_table_absente_ne_fait_pas_lever():
    """La table déclarée a disparu : c'est **l'anomalie**, pas un plantage.

    Un agent qui casse quand la donnée manque disparaît au moment précis où on
    a le plus besoin de lui — c'est la famille *inventaire* de `detect` qui
    doit la constater. Même symétrie que dans le connecteur (4.0).
    """
    PROFIL_FACTICE.absente = True
    resultat = profile(base_state(SCHEMA_COMMANDES))

    assert resultat["profile"] == {}
    assert "absente" in resultat["logs"][0]["message"]
    assert MEMOIRE_FACTICE.lots == {}, "rien à archiver pour une table absente"


def test_la_connexion_est_fermee_meme_si_le_profilage_echoue(monkeypatch):
    """Un run interrompu ne doit pas laisser une session Snowflake ouverte : le
    warehouse se suspend au bout de 60 s, la session non."""

    class Explose:
        def invoke(self, arguments):
            raise RuntimeError("Snowflake indisponible")

    monkeypatch.setattr(
        importlib.import_module("agent.nodes.profile"), "profile_table", Explose()
    )

    with pytest.raises(RuntimeError):
        profile(base_state(SCHEMA_COMMANDES))
    assert MEMOIRE_FACTICE.fermee


def test_profile_journalise_la_taille_de_sa_reference():
    """« 4 lots de référence » est une explication ; « aucune anomalie » n'en est
    pas une. C'est ce chiffre qui rendra lisible, dans INCIDENTS, pourquoi un run
    n'a rien détecté statistiquement."""
    for jour in ("2018-04-26", "2018-04-27", "2018-04-28"):
        MEMOIRE_FACTICE.lots[("olist", "RAW.ORDERS", jour)] = {
            (None, "row_count"): 300.0
        }
    entree = profile(base_state(SCHEMA_COMMANDES))["logs"][0]
    assert entree["lots_de_reference"] == 3


# --- Nœud 2/8 : detect -------------------------------------------------------


def etat_avec_profil(colonnes: dict, table="RAW.ORDERS"):
    """Un état porteur d'un profil donné — ce que `profile` aurait produit."""
    state = base_state(table=table)
    state["profile"] = {"row_count": 351, "columns": colonnes}
    return state


def test_detect_ne_signale_rien_quand_tout_est_propre():
    """Le chemin « rien d'anormal » doit exister : c'est un des 4 du graphe.

    Aucune référence extérieure, aucune collision : les cinq familles se taisent.
    Un profil « sale » ne suffit plus à produire un écart — depuis 4.3, il faut
    qu'une **référence** dise en quoi il l'est.
    """
    state = etat_avec_profil(
        {
            "a": {"role": "categorical", "null_rate": 0.0, "distinct": 351},
            "b": {"role": "categorical", "null_rate": 0.02, "distinct": 12},
        }
    )
    assert detect(state)["anomalies"] == []


def test_detect_agrege_toutes_les_familles():
    """Le nœud n'est qu'un chef d'orchestre : la logique vit dans les familles.

    On vérifie ici qu'il les appelle **toutes** et concatène — le détail de
    chacune est éprouvé dans `tests/test_detect.py`.

    `dbt` vient en dernier, et à part : elle ne détecte rien, elle traduit des
    verdicts déjà rendus par un outil tiers. La lire après les cinq autres met
    le constat de l'agent avant celui d'un outil tiers, ce qui est l'ordre dans
    lequel un humain veut lire.
    """
    from agent.nodes.detect import FAMILLES

    assert [nom for nom, _ in FAMILLES] == [
        "inventaire",
        "schema",
        "contrat",
        "statistique",
        "semantique",
        "dbt",
    ]


def test_detect_produit_un_fait_chiffre_pas_un_jugement():
    """La forme de sortie est commune aux cinq familles.

    Aucun champ ne porte de verdict (« grave », « à corriger ») — seulement des
    mesures et leur référence. Le jugement appartient à l'humain.
    """
    state = etat_avec_profil(
        {
            "ville": {
                "role": "categorical",
                "coverage": 1.0,
                "top": [
                    {"value": "sao paulo", "count": 200},
                    {"value": "são paulo", "count": 151},
                ],
            }
        }
    )
    ecart = detect(state)["anomalies"][0]

    assert set(ecart) == {
        "famille",
        "table",
        "colonne",
        "type",
        "observe",
        "reference",
        # 4ᵉ terme de la signature d'anomalie (4.4) : champ de premier rang et
        # non détail, parce que c'est lui qui décide si un écart déjà refusé
        # doit rester silencieux ou reparler.
        "ampleur",
        "dama",
        "details",
    }
    assert ecart["table"] == "RAW.ORDERS"
    assert ecart["colonne"] == "ville"
    assert not {"grave", "severite", "a_corriger"} & set(ecart)


def test_detect_marche_sur_n_importe_quel_dataset():
    """Aucun nom de colonne n'est connu d'avance : l'écart est trouvé, pas su."""

    def collision(colonne, table):
        return etat_avec_profil(
            {
                colonne: {
                    "role": "categorical",
                    "coverage": 1.0,
                    "top": [
                        {"value": "CDI", "count": 10},
                        {"value": "cdi", "count": 3},
                    ],
                }
            },
            table,
        )

    rh = detect(collision("contrat", "HR.EMPLOYES"))
    capteurs = detect(collision("statut", "IOT.MESURES"))

    assert rh["anomalies"][0]["colonne"] == "contrat"
    assert capteurs["anomalies"][0]["colonne"] == "statut"


def test_detect_supporte_un_profil_vide():
    """Robustesse : un lot vide ne doit pas faire exploser le graphe."""
    assert detect(base_state())["anomalies"] == []


def test_une_famille_qui_leve_n_emporte_pas_les_autres(monkeypatch):
    """⭐ Un agent silencieusement aveugle est pire qu'un agent partiel.

    Si un détecteur trébuche sur une forme de profil inattendue, les quatre
    autres doivent rendre leur verdict — et la panne doit **se voir** dans le
    journal, sans quoi l'agent paraîtrait avoir regardé là où il n'a rien vu.
    """
    detect_mod = importlib.import_module("agent.nodes.detect")

    def explose(state):
        raise ValueError("profil inattendu")

    monkeypatch.setattr(
        detect_mod, "FAMILLES", (("qui_explose", explose),) + detect_mod.FAMILLES[1:]
    )
    resultat = detect(
        etat_avec_profil(
            {
                "ville": {
                    "role": "categorical",
                    "coverage": 1.0,
                    "top": [
                        {"value": "sao paulo", "count": 200},
                        {"value": "são paulo", "count": 151},
                    ],
                }
            }
        )
    )

    assert len(resultat["anomalies"]) == 1, "les autres familles ont été emportées"
    assert "qui_explose" in resultat["logs"][0]["familles_en_echec"][0]


def test_detect_s_enchaine_avec_profile():
    """Les deux nœuds bout à bout, comme dans le graphe."""
    state = base_state(SCHEMA_COMMANDES)
    state.update(profile(state))
    anomalies = detect(state)["anomalies"]

    # le double de `profile_table` pose une collision sur la 2e colonne
    assert [a["colonne"] for a in anomalies] == [SCHEMA_COMMANDES[1]["name"]]


def test_detect_ne_modifie_pas_l_etat_recu():
    state = etat_avec_profil({"trouee": {"role": "categorical", "null_rate": 0.301}})
    avant = copy.deepcopy(state)
    detect(state)
    assert state == avant


def test_detect_ecrit_une_ligne_de_journal_au_format_commun():
    state = etat_avec_profil(
        {
            "ville": {
                "role": "categorical",
                "coverage": 1.0,
                "top": [
                    {"value": "sao paulo", "count": 200},
                    {"value": "são paulo", "count": 151},
                ],
            }
        }
    )
    entry = detect(state)["logs"][0]
    assert entry["node"] == "detect"
    assert entry["par_famille"] == {"semantique": 1}
    assert set(log_entry("x", "y")) <= set(entry)


def test_un_ecart_deja_refuse_n_est_pas_resoumis():
    """Le filtre de silence, vu depuis le nœud : l'écart est **constaté et
    journalisé**, mais retiré de ce qui part en décision."""
    from agent.incidents import signature, texte

    state = etat_avec_profil(
        {
            "ville": {
                "role": "categorical",
                "coverage": 1.0,
                "top": [
                    {"value": "sao paulo", "count": 200},
                    {"value": "são paulo", "count": 151},
                ],
            }
        }
    )
    vu = detect(state)["anomalies"][0]
    state["past_incidents"] = [
        {"human_decision": "rejected", "signatures": [texte(signature(vu))]}
    ]

    resultat = detect(state)
    assert resultat["anomalies"] == []
    assert resultat["logs"][0]["signatures_tues"] == [texte(signature(vu))]


# --- Nœud 3/8 : diagnose -----------------------------------------------------


def etat_avec_ecart(colonne="col_trouee", table="RAW.ORDERS"):
    """Un état porteur d'un écart — ce que `detect` aurait produit."""
    state = base_state(table=table)
    state["anomalies"] = [
        {
            "famille": "statistique",
            "table": table,
            "colonne": colonne,
            "type": "nulls",
            "observe": 0.301,
            "reference": 0.0,
            "dama": "completude",
        }
    ]
    return state


# Depuis l'étape 3.3, `diagnose` appelle vraiment Groq. **Aucun test n'appelle un
# LLM** (`CONTRIBUTING` : la CI doit être déterministe, gratuite, et tourner sans
# clé API). On remplace donc `diagnostiquer`, la seule couture réseau du projet.


@pytest.fixture
def llm_qui_repond(monkeypatch):
    """Un modèle qui répond correctement — et qui enregistre ce qu'il a reçu."""
    recu = {}

    def faux(contexte):
        recu.update(contexte)
        return Diagnostic(
            root_cause="Cause plausible",
            proposed_fix="Isoler les lignes concernées en quarantaine",
            explanation="Parce que.",
        )

    monkeypatch.setattr(diagnose_mod, "diagnostiquer", faux)
    return recu


@pytest.fixture
def llm_en_panne(monkeypatch):
    def faux(contexte):
        raise ConnectionError("Groq injoignable")

    monkeypatch.setattr(diagnose_mod, "diagnostiquer", faux)


def test_diagnose_produit_les_trois_champs_attendus(llm_qui_repond):
    """Le contrat de sortie, désormais **imposé** par Pydantic côté `agent/llm.py`."""
    diagnosis = diagnose(etat_avec_ecart())["diagnosis"]
    assert set(diagnosis) == {"root_cause", "proposed_fix", "explanation"}
    assert all(isinstance(v, str) and v for v in diagnosis.values())


def test_diagnose_transmet_l_ecart_recu_au_modele(llm_qui_repond):
    """Générique : il transmet la colonne trouvée par `detect`, il ne la connaît pas."""
    diagnose(etat_avec_ecart("salaire_brut", "HR.EMPLOYES"))

    assert llm_qui_repond["table"] == "HR.EMPLOYES"
    assert llm_qui_repond["ecarts_constates"][0]["colonne"] == "salaire_brut"


def test_le_modele_ne_voit_que_des_agregats(llm_qui_repond):
    """**Règle R2.** `construire_contexte` choisit champ par champ ce qui part.

    On glisse ici un profil qui transporte un échantillon de lignes — la
    tentation exacte de la phase 4 — et on vérifie qu'il ne franchit pas la
    barrière. Sans ce test, un ajout innocent dans `profile` enverrait des
    données clients à un service tiers sans que personne ne s'en aperçoive.
    """
    state = etat_avec_ecart()
    state["profile"] = {
        "row_count": 351,
        "columns": {"nom_client": {"null_rate": 0.3}},
        "echantillon": [{"nom_client": "Maria Silva"}],  # ne doit PAS sortir
    }
    diagnose(state)

    envoye = json.dumps(llm_qui_repond, ensure_ascii=False)
    assert "Maria Silva" not in envoye
    assert "echantillon" not in envoye
    # les agrégats, eux, sont bien transmis
    assert llm_qui_repond["lignes_dans_le_lot"] == 351
    assert llm_qui_repond["colonnes_profilees"] == ["nom_client"]


def test_les_consignes_interdisent_de_deviner_une_valeur():
    """Règle « ne jamais inventer une valeur » (P6). La barrière dure sera dans
    `apply` (phase 5.2) ; ici c'est la ligne éditoriale envoyée au modèle.

    Ce test protège une **consigne**, pas un comportement : il devient rouge si
    quelqu'un allège le prompt, ce qui est exactement le genre de modification
    qui passerait inaperçue autrement.
    """
    consignes = CONSIGNES.lower()
    assert "jamais" in consignes and "remplacer" in consignes
    for autorise in ("isoler", "quarantaine", "null", "exclure"):
        assert autorise in consignes


def test_diagnose_sans_ecart_ne_fabrique_pas_de_diagnostic(llm_qui_repond):
    """Le graphe ne route pas ici sans écart, mais un nœud ne suppose rien."""
    result = diagnose(base_state())
    assert result["diagnosis"] is None
    assert result["logs"][0]["node"] == "diagnose"
    assert llm_qui_repond == {}, "le LLM n'aurait pas dû être appelé"


def test_un_llm_en_panne_ne_tue_pas_le_run(llm_en_panne):
    """**Mode dégradé, pas panne.** Réseau coupé, quota dépassé, JSON illisible :
    le run continue et l'humain voit les faits que `detect` a établis sans LLM.
    Un projet dont le graphe s'effondre quand une API tierce tousse ne tient pas
    en production."""
    result = diagnose(etat_avec_ecart())

    assert result["diagnosis"] is None
    assert "manuellement" in result["logs"][0]["message"]
    assert "ConnectionError" in result["logs"][0]["erreur"]


@pytest.mark.parametrize(
    "panne",
    [
        ConnectionError("réseau coupé"),
        KeyError("GROQ_API_KEY"),
        ValueError("JSON illisible"),
        RuntimeError("quota dépassé"),
    ],
)
def test_toutes_les_pannes_menent_au_meme_mode_degrade(monkeypatch, panne):
    """On ne distingue pas les causes : elles ont toutes la même conséquence."""

    def faux(contexte):
        raise panne

    monkeypatch.setattr(diagnose_mod, "diagnostiquer", faux)
    assert diagnose(etat_avec_ecart())["diagnosis"] is None


def test_un_diagnostic_incomplet_est_refuse():
    """Le JSON peut être syntaxiquement valide et pourtant faux : un modèle peut
    renvoyer deux champs sur trois. C'est Pydantic qui l'attrape, et l'échec
    retombe dans le mode dégradé."""
    with pytest.raises(ValidationError):
        Diagnostic.model_validate({"root_cause": "x", "proposed_fix": "y"})


def test_diagnose_ne_modifie_pas_l_etat_recu(llm_qui_repond):
    state = etat_avec_ecart()
    avant = copy.deepcopy(state)
    diagnose(state)
    assert state == avant


def test_diagnose_ecrit_une_ligne_de_journal_au_format_commun(llm_qui_repond):
    entry = diagnose(etat_avec_ecart())["logs"][0]
    assert entry["node"] == "diagnose"
    assert entry["anomalies"] == 1
    assert set(log_entry("x", "y")) <= set(entry)


def test_les_trois_noeuds_s_enchainent(llm_qui_repond):
    """profile → detect → diagnose, comme dans le graphe.

    On vérifie que l'écart trouvé par `detect` arrive bien jusqu'au modèle —
    pas ce que le modèle en dit, qui ne nous appartient pas.
    """
    state = base_state(SCHEMA_COMMANDES)
    state["profile"] = profile(state)["profile"]
    state["anomalies"] = detect(state)["anomalies"]
    assert diagnose(state)["diagnosis"] is not None

    ecart = llm_qui_repond["ecarts_constates"][0]
    assert ecart["colonne"] == SCHEMA_COMMANDES[1]["name"]


# --- Nœud 4/8 : propose ------------------------------------------------------


def etat_diagnostique(colonne="col_trouee", table="RAW.ORDERS"):
    """Un état prêt à être soumis — ce que `diagnose` aurait laissé.

    Le diagnostic est écrit en dur plutôt qu'obtenu en appelant `diagnose` :
    depuis l'étape 3.3 cet appel partirait chez Groq, ce qui rendrait toute la
    suite lente, payante et non déterministe. **Un helper de test ne doit
    dépendre d'aucune API tierce.**
    """
    state = etat_avec_ecart(colonne, table)
    state["diagnosis"] = {
        "root_cause": f"Écart de complétude sur « {colonne} » dans {table}.",
        "proposed_fix": f"Isoler en quarantaine les lignes de {table} concernées.",
        "explanation": "Un écart net et partiel évoque un incident technique amont.",
    }
    return state


def test_la_proposition_offre_les_trois_choix_dans_l_ordre():
    """Les deux « non » sont distincts : c'est ce qui empêche le contrat de vieillir."""
    proposal = build_proposal(etat_diagnostique())
    assert proposal["choix"] == [DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED]


def test_la_proposition_porte_de_quoi_decider():
    """Tout ce dont l'humain a besoin, en un seul objet — rien à aller chercher ailleurs."""
    proposal = build_proposal(etat_diagnostique())
    assert set(proposal) == {
        "dataset",
        "layer",
        "table",
        "batch_id",
        "anomalies",
        "root_cause",
        "proposed_fix",
        "explanation",
        "impact",
        "past_incidents",
        "choix",
        # ajoutés en 5.2 : l'humain doit savoir ce que l'agent a le DROIT de
        # faire, sinon il ne comprend pas pourquoi la correction proposée
        # n'est jamais « remplacer par la bonne valeur ».
        "gestes_autorises",
        "alertes_p6",
        "correction_par_defaut",
        # ajoutés avec le dialogue : l'humain doit retrouver le fil même s'il
        # revient le lendemain, depuis un autre poste
        "conversation",
        "questions_restantes",
    }


def test_la_proposition_affiche_toujours_un_impact():
    """Sans impact chiffré, « 1 ligne sur 351 » paraît négligeable — et ne l'est pas."""
    proposal = build_proposal(etat_diagnostique())
    assert proposal["impact"]  # non vide (réel en phase 5.1)


def test_propose_ne_sappelle_pas_hors_du_graphe():
    """Depuis l'étape 3.2, `propose` appelle `interrupt()` : il ne peut plus
    s'exécuter sans checkpointer, et c'est **voulu**. Un nœud dont la raison
    d'être est de suspendre n'a pas de sens isolé, et aucun contournement n'est
    prévu — pas même pour les tests (règle R3). S'il existait un chemin où
    `propose` ne s'arrête pas, la garantie du projet ne serait plus vérifiable.

    Ce qui se testait ici se teste désormais au niveau du graphe
    (`test_agent_graph.py`), c'est-à-dire là où la pause existe vraiment.
    """
    with pytest.raises(Exception):
        propose(etat_diagnostique())


# `lire_reponse` est la partie pure de `propose` : traduire ce qu'a répondu
# l'humain en champs d'état. Testable seule, elle, et c'est elle qui décide de ce
# qui est une décision recevable.


def test_lire_reponse_accepte_une_simple_chaine():
    """Le cas courant en ligne de commande."""
    assert lire_reponse(DECISION_APPROVED)["human_decision"] == DECISION_APPROVED


def test_lire_reponse_accepte_un_dictionnaire_complet():
    lu = lire_reponse(
        {
            "decision": DECISION_APPROVED,
            "decided_by": "hoda",
            "fix_override": "UPDATE …",
        }
    )
    assert lu == {
        "human_decision": DECISION_APPROVED,
        "decided_by": "hoda",
        "fix_override": "UPDATE …",
        "question": None,
    }


@pytest.mark.parametrize("reponse", [None, 42, [], object(), {"decision": 1}])
def test_lire_reponse_traite_l_inattendu_comme_une_absence_de_decision(reponse):
    """On ne devine pas ce que l'humain a voulu dire. Sans décision lisible, le
    run repartira vers `log` sans rien écrire."""
    assert lire_reponse(reponse)["human_decision"] is None


@pytest.mark.parametrize(
    "approximation", ["Approved", "APPROVED", " approved", "approuvé"]
)
def test_lire_reponse_ne_rattrape_pas_une_decision_approximative(approximation):
    """Ni casse ni espaces normalisés : `route_after_propose` refusera ces
    valeurs, et c'est le comportement voulu. Rattraper « Approved » serait
    commode aujourd'hui et dangereux le jour où une UI enverra autre chose."""
    assert lire_reponse(approximation)["human_decision"] != DECISION_APPROVED


def test_propose_marche_sur_n_importe_quel_dataset():
    rh = build_proposal(etat_diagnostique("salaire_brut", "HR.EMPLOYES"))
    assert rh["table"] == "HR.EMPLOYES"
    assert "salaire_brut" in rh["root_cause"]


def test_propose_supporte_un_diagnostic_absent():
    """Si le parsing LLM a échoué (étape 7), la proposition reste construite."""
    state = etat_avec_ecart()  # diagnosis reste None
    proposal = build_proposal(state)
    assert proposal["root_cause"] is None
    assert proposal["anomalies"]  # les faits, eux, sont toujours là


def test_build_proposal_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    avant = copy.deepcopy(state)
    build_proposal(state)
    assert state == avant


# --- Nœud 5/8 : apply — le seul qui écrit dans les données -------------------


@pytest.mark.parametrize("decision", [None, DECISION_REJECTED, DECISION_AMEND])
def test_apply_refuse_toute_execution_sans_approbation(decision):
    """P3, première preuve — au niveau du nœud.

    Trois cas dangereux : personne n'a répondu, l'humain a refusé, l'humain a
    demandé un amendement du contrat. Dans aucun des trois `apply` ne doit
    s'exécuter. La preuve exhaustive sur les *chemins du graphe* arrive à
    l'étape 8 ; celle-ci couvre le nœud lui-même.
    """
    state = etat_diagnostique()
    state["human_decision"] = decision
    with pytest.raises(RuntimeError, match="P3"):
        apply(state)


def test_apply_s_execute_avec_approbation():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["decided_by"] = "hoda"

    entry = apply(state)["logs"][0]
    assert entry["node"] == "apply"
    assert entry["decideur"] == "hoda"
    assert entry["fix"]  # la correction appliquée est tracée


def test_apply_ne_retourne_aucune_donnee_metier():
    """Il agit sur la base, pas sur l'état : seuls la correction et le journal remontent."""
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    assert set(apply(state)) == {"applied_fix", "logs"}


def test_apply_execute_la_correction_de_l_agent_par_defaut():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    result = apply(state)

    assert result["applied_fix"] == state["diagnosis"]["proposed_fix"]
    assert result["logs"][0]["reecrite_par_humain"] is False


def test_apply_execute_la_correction_de_l_humain_si_elle_existe():
    """L'humain peut réécrire la correction — sinon il irait corriger hors de
    l'agent, et le journal deviendrait faux."""
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["fix_override"] = "UPDATE ... SET x = y / 100 WHERE ..."

    result = apply(state)
    assert result["applied_fix"] == state["fix_override"]
    assert result["logs"][0]["reecrite_par_humain"] is True


def test_on_sait_toujours_distinguer_proposee_de_reecrite():
    """Base de la métrique de qualité en phase 8 : proposée / réécrite / refusée."""
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["fix_override"] = "ma propre correction"

    # la proposition de l'agent reste intacte dans l'état, à côté de l'appliquée
    assert apply(state)["applied_fix"] != state["diagnosis"]["proposed_fix"]


def test_apply_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    avant = copy.deepcopy(state)
    apply(state)
    assert state == avant


# --- Nœud 6/8 : amend — le miroir d'apply ------------------------------------


@pytest.mark.parametrize("decision", [None, DECISION_APPROVED, DECISION_REJECTED])
def test_amend_refuse_toute_execution_sans_decision_d_amendement(decision):
    """Un contrat amendé par erreur rendrait l'agent aveugle — silencieusement."""
    state = etat_diagnostique()
    state["human_decision"] = decision
    with pytest.raises(RuntimeError):
        amend(state)


def test_amend_ne_touche_jamais_aux_donnees():
    """LA différence avec apply : il ne retourne aucune clé de données.

    Ni profile, ni anomalies, ni validation — seulement la version du contrat
    et le journal. En phase 5.3 un test comptera les lignes avant/après.
    """
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    assert set(amend(state)) == {"contract_version", "logs"}


def test_amend_incremente_la_version_du_contrat():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    state["contract_version"] = "v1"
    assert amend(state)["contract_version"] == "v2"


@pytest.mark.parametrize(
    ("actuelle", "attendue"),
    [(None, "v1"), ("v1", "v2"), ("v9", "v10"), ("brouillon", "v1")],
)
def test_la_numerotation_des_contrats_est_previsible(actuelle, attendue):
    """Une table sans contrat démarre en v1 ; une version illisible ne plante pas."""
    assert _version_suivante(actuelle) == attendue


def test_amend_trace_le_passage_d_une_version_a_l_autre():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    state["contract_version"] = "v1"
    state["decided_by"] = "hoda"

    entry = amend(state)["logs"][0]
    assert entry["node"] == "amend"
    assert (entry["depuis"], entry["vers"]) == ("v1", "v2")
    assert entry["decideur"] == "hoda"


def test_amend_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    avant = copy.deepcopy(state)
    amend(state)
    assert state == avant


# --- Nœud 7/8 : validate -----------------------------------------------------


def test_validate_remesure_la_metrique_fautive():
    """On ne croit jamais une correction sur parole : on la re-mesure."""
    state = etat_diagnostique()
    validation = validate(state)["validation"]

    assert set(validation) == {"status", "metric", "before", "after"}
    assert validation["metric"] == "nulls(col_trouee)"
    assert validation["before"] == 0.301  # la valeur qui avait déclenché l'alerte


def test_validate_marche_sur_n_importe_quel_dataset():
    rh = validate(etat_diagnostique("salaire_brut", "HR.EMPLOYES"))["validation"]
    assert rh["metric"] == "nulls(salaire_brut)"


def test_validate_sans_ecart_ne_pretend_rien_avoir_verifie():
    validation = validate(base_state())["validation"]
    assert validation["metric"] is None
    assert validation["status"] == VALIDATION_OK


def test_validate_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    avant = copy.deepcopy(state)
    validate(state)
    assert state == avant


def test_validate_ecrit_une_ligne_de_journal_au_format_commun():
    entry = validate(etat_diagnostique())["logs"][0]
    assert entry["node"] == "validate"
    assert entry["status"] == VALIDATION_OK
    assert set(log_entry("x", "y")) <= set(entry)


# --- Nœud 8/8 : log — la sortie unique ---------------------------------------


def fusionner(state: dict, result: dict) -> dict:
    """Applique le résultat d'un nœud **comme le ferait LangGraph**.

    Piège : le réducteur `Annotated[list, add]` est une mécanique *LangGraph*,
    pas *Python*. Hors du graphe, `state.update(result)` écrase `logs` au lieu
    de le concaténer — d'où cet émulateur, qui rend la règle explicite :
    `logs` s'accumule, tout le reste s'écrase.
    """
    logs = state["logs"] + result.get("logs", [])
    state.update(result)
    state["logs"] = logs
    return state


def test_log_resume_le_chemin_rien_d_anormal():
    entry = log(base_state())["logs"][0]
    assert entry["anomalies"] == 0
    assert entry["decision"] is None
    assert entry["applied_fix"] is None
    assert entry["validation"] is None


def test_log_resume_le_chemin_refuse():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_REJECTED
    entry = log(state)["logs"][0]

    assert entry["anomalies"] == 1
    assert entry["decision"] == DECISION_REJECTED
    assert entry["applied_fix"] is None  # rien n'a été écrit
    assert entry["validation"] is None  # on n'est pas passé par validate


def test_log_resume_le_chemin_amende():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    state = fusionner(state, amend(state))
    entry = log(state)["logs"][-1]

    assert entry["contract_version"] == "v1"
    assert entry["applied_fix"] is None  # amend n'écrit jamais dans les données


def test_log_resume_le_chemin_approuve():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["decided_by"] = "hoda"
    state = fusionner(state, apply(state))
    state = fusionner(state, validate(state))
    entry = log(state)["logs"][-1]

    assert entry["decision"] == DECISION_APPROVED
    assert entry["decideur"] == "hoda"
    assert entry["applied_fix"]
    assert entry["validation"] == VALIDATION_OK


def test_log_compte_les_etapes_traversees():
    """Un journal disant « 0 écart » est ambigu : rien vu, ou rien regardé ?"""
    state = base_state(SCHEMA_COMMANDES)
    state = fusionner(state, profile(state))
    state = fusionner(state, detect(state))
    entry = log(state)["logs"][-1]

    assert entry["etapes"] == 3  # profile + detect + log


def test_log_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    avant = copy.deepcopy(state)
    log(state)
    assert state == avant


def test_log_ecrit_une_ligne_dans_incidents():
    """Une ligne par run, **quel que soit le chemin** — c'est la source du
    benchmark, la matière du filtre de silence, et la preuve que l'agent a
    tourné."""
    state = base_state()
    log(state)
    assert len(MEMOIRE_FACTICE.incidents) == 1
    ligne = MEMOIRE_FACTICE.incidents[0]
    assert ligne["table_name"] == "RAW.ORDERS"
    assert ligne["batch_id"] == "2018-04-29"


def test_un_run_sans_anomalie_est_journalise_aussi():
    """⭐ « L'agent n'a rien signalé » et « l'agent n'a pas tourné » sont deux
    choses différentes — les confondre est le pire état d'un système de
    surveillance. Et sans les faux positifs journalisés, la précision de la
    phase 8 est incalculable."""
    log(base_state())
    assert MEMOIRE_FACTICE.incidents[0]["anomalies"] == "[]"


def test_les_signatures_sont_stockees_a_part():
    """Dérivables du JSON des anomalies, mais seulement en Python. Les stocker
    rend possibles la mémoire par signature (O7) et l'écran anti-cécité."""
    from agent.detect import ecart

    state = base_state()
    state["anomalies"] = [
        ecart(
            "contrat",
            "RAW.ORDERS",
            type="nulls_interdits",
            dama="completude",
            colonne="C",
            ampleur=0.3,
        )
    ]
    log(state)
    assert (
        "RAW.ORDERS|C|nulls_interdits|-2" in MEMOIRE_FACTICE.incidents[0]["signatures"]
    )


def test_un_journal_indisponible_n_emporte_pas_le_run():
    """⭐ La trace est précieuse, mais la perdre ne doit pas emporter le travail
    déjà fait ni empêcher l'humain de voir ce qui a été constaté. Conséquence
    assumée et **dite** : ce run-là ne comptera pas au benchmark."""
    MEMOIRE_FACTICE.ecriture_leve = True
    entree = log(base_state())["logs"][0]
    assert entree["incident_id"] is None
    assert "echec_ecriture" in entree
    assert "indisponible" in entree["message"]


def test_log_ne_retourne_que_du_journal():
    """Sortie unique : il conclut le run, il ne change plus rien."""
    assert set(log(etat_diagnostique())) == {"logs"}
