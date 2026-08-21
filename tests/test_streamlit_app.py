"""Les six écrans, exécutés pour de vrai (phase 6.2).

`streamlit.testing.v1.AppTest` exécute l'application **sans navigateur** : on
clique, on lit ce qui s'affiche, on vérifie ce qui a été appelé. C'est ce qui
permet de tenir la promesse de 6.2 — *« le clic passe par le même mécanisme que
`scripts/decide.py` (une seule voie de reprise, **testée**) »* — au lieu de la
supposer.

Sans ce fichier, la garantie reposerait sur la lecture du code : un bouton qui
appellerait un raccourci maison passerait inaperçu jusqu'à la démo.

## Ce qu'on vérifie ici, et pas ailleurs

`test_streamlit_donnees.py` éprouve la logique ; ce fichier éprouve le
**câblage** : les écrans se rendent, les boutons appellent la bonne fonction
avec les bons arguments, et les garde-fous d'interface (nom obligatoire, bouton
désactivé) sont réellement posés.

Un nœud parfait relié au mauvais endroit ne protège de rien — la même raison qui
avait fait écrire `test_agent_graph.py` à côté de `test_agent_nodes.py`.
"""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import agent.hitl as hitl
from agent.state import DECISION_APPROVED, DECISION_REJECTED

APP = str(Path(__file__).resolve().parent.parent / "streamlit" / "app.py")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "streamlit"))

ATTENTE = [
    {
        "thread_id": "olist|RAW.ORDERS|2018-04-29",
        "table": "RAW.ORDERS",
        "batch_id": "2018-04-29",
        "anomalies": 1,
        "resume": "51 ligne(s) sur 351 (14.5%) · CUSTOMER_ID — completude",
    }
]

PROPOSITION = {
    "dataset": "olist",
    "layer": "bronze",
    "table": "RAW.ORDERS",
    "batch_id": "2018-04-29",
    "anomalies": [{"type": "nulls_interdits", "colonne": "CUSTOMER_ID"}],
    "root_cause": "ingestion partielle",
    "proposed_fix": "UPDATE RAW.ORDERS SET CUSTOMER_ID = NULL WHERE CUSTOMER_ID = ''",
    "explanation": "…",
    "impact": {
        "resume": "51 ligne(s) sur 351 (14.5%)",
        "aval": "non calculé — phase 7.1",
    },
    "past_incidents": [],
    "choix": [DECISION_APPROVED, "amend_contract", DECISION_REJECTED],
    "gestes_autorises": {"isoler": "marquer les lignes en quarantaine"},
    "alertes_p6": None,
    "correction_par_defaut": None,
    "conversation": [],
    "questions_restantes": 10,
}


@pytest.fixture
def app(monkeypatch):
    """L'application, avec une proposition en attente et la reprise espionnée."""
    import donnees

    monkeypatch.setattr(donnees, "file_attente", lambda db=None: list(ATTENTE))
    monkeypatch.setattr(donnees, "journal", lambda dataset, **k: [])
    monkeypatch.setattr(donnees, "silences", lambda dataset, table=None: [])
    monkeypatch.setattr(donnees, "contrats", lambda dataset: [])
    monkeypatch.setattr(
        donnees, "tables_gold", lambda dataset: ["MARTS.FCT_DAILY_SALES"]
    )
    monkeypatch.setattr(
        donnees, "agregat", lambda ds, t, limite=200: {"rows": [], "truncated": False}
    )
    # L'accueil (6.2) agrège les quatre sources : on le double d'un bloc plutôt
    # que de le laisser interroger Snowflake.
    monkeypatch.setattr(
        donnees,
        "vue_ensemble",
        lambda dataset: {
            "tables": 17,
            "contrats": [],
            "attente": list(ATTENTE),
            "incidents": [],
            "contrats_en_vigueur": 0,
            "contrats_a_signer": 2,
            "decisions_en_attente": 1,
            "runs": 0,
            "runs_avec_ecart": 0,
            "a_faire": 3,
            "erreurs": [],
        },
    )

    # ⚠️ On patche `agent.hitl`, pas l'application : `app.py` fait
    # `from agent.hitl import trancher` **au moment où AppTest l'exécute**, donc
    # il récupère la version espionnée. Patcher l'inverse ne remplacerait rien.
    appels = []
    monkeypatch.setattr(hitl, "proposition", lambda fil, db=None: dict(PROPOSITION))
    monkeypatch.setattr(
        hitl,
        "trancher",
        lambda fil, decision, par=None, fix_override=None, db=None: (
            appels.append(
                {"fil": fil, "decision": decision, "par": par, "fix": fix_override}
            )
            or {
                "ok": True,
                "decision": decision,
                "parcours": ["profile", "detect", "log"],
                "applied_fix": None,
                "contract_version": None,
                "en_attente": False,
            }
        ),
    )
    at = AppTest.from_file(APP, default_timeout=30)
    at.appels = appels
    return at


def ouvrir(at, ecran: str):
    at.run()
    at.sidebar.radio[0].set_value(ecran).run()
    return at


# ===========================================================================
# Les six écrans se rendent
# ===========================================================================


@pytest.mark.parametrize(
    "ecran",
    [
        "📊 Vos données",
        "✅ Décisions",
        "📚 Historique",
        "🏠 Accueil",
        "🔕 Alertes désactivées",
        "📜 Règles",
    ],
)
def test_chaque_ecran_se_rend_sans_exception(app, ecran):
    """Un écran qui plante emporte l'application entière — et l'humain qui
    devait décider perd aussi les écrans qui, eux, fonctionnaient."""
    at = ouvrir(app, ecran)
    assert not at.exception, f"{ecran} : {at.exception}"


def test_une_panne_de_donnees_n_efface_pas_l_application(app, monkeypatch):
    """⭐ Le garde-fou qui n'était pas testé — donc du poids mort.

    Une table absente, un trial expiré, un JSON corrompu : si l'exception
    remontait, **l'application entière** disparaîtrait derrière une trace, et
    l'humain qui devait décider perdrait aussi les écrans qui, eux,
    fonctionnaient.

    Écrit après un sabotage passé inaperçu : retirer le `try/except` de chaque
    écran laissait la suite verte, faute d'un test qui fasse réellement échouer
    une source.
    """
    import donnees

    def indisponible(*args, **kwargs):
        raise RuntimeError("Snowflake indisponible")

    monkeypatch.setattr(donnees, "journal", indisponible)

    at = ouvrir(app, "📚 Historique")
    assert not at.exception, "la panne a emporté l'application"
    assert any("Snowflake indisponible" in e.value for e in at.error)
    assert any("restent utilisables" in c.value for c in at.caption)


def test_un_ecran_vide_le_dit_au_lieu_de_rester_blanc(app):
    """« Aucune signature en silence » et un écran vide ne veulent pas dire la
    même chose : le second laisse croire à une panne."""
    at = ouvrir(app, "🔕 Alertes désactivées")
    assert any("signale tout" in s.value for s in at.success)


# ===========================================================================
# ⭐ Le clic passe par la voie unique
# ===========================================================================


def test_la_file_montre_l_impact_pour_choisir(app):
    """C'est l'impact qui permet de décider **laquelle** traiter en premier
    quand il y en a dix."""
    at = ouvrir(app, "✅ Décisions")
    assert "51 ligne" in at.selectbox[0].options[0]


def test_le_clic_approuver_appelle_hitl_et_rien_d_autre(app):
    """⭐ LA promesse de 6.2, vérifiée plutôt que supposée.

    Un bouton qui appellerait un raccourci maison serait une **seconde voie de
    reprise**, donc une seconde façon de contourner P3 — et personne ne le
    verrait avant la démo.
    """
    at = ouvrir(app, "✅ Décisions")
    at.text_input(key="decideur").set_value("hoda").run()
    at.button[0].click().run()

    assert not at.exception
    assert app.appels == [
        {
            "fil": "olist|RAW.ORDERS|2018-04-29",
            "decision": DECISION_APPROVED,
            "par": "hoda",
            "fix": None,
        }
    ]


def test_les_trois_reponses_sont_offertes(app):
    at = ouvrir(app, "✅ Décisions")
    libelles = [b.label for b in at.button]
    # ⭐ Le vocabulaire s'adresse au métier : « Corriger » et non « Approuver »,
    # « Ajuster la règle » et non « Amender le contrat ».
    for reponse in ("Corriger", "Ajuster la règle", "Écarter"):
        assert any(reponse in libelle for libelle in libelles), reponse


# ===========================================================================
# L'identité du validateur — `decided_by`
# ===========================================================================


def test_sans_nom_aucune_decision_n_est_possible(app):
    """⭐ `decided_by` n'est pas un ornement : une décision sans auteur ne se
    conteste pas six mois plus tard, et le taux d'approbation de la phase 8
    n'aurait personne à qui l'attribuer.

    Le bouton est **désactivé**, pas refusé après coup : apprendre un refus
    après avoir cliqué n'apprend rien.
    """
    at = ouvrir(app, "✅ Décisions")
    assert all(b.disabled for b in at.button[:3])

    at.text_input(key="decideur").set_value("hoda").run()
    assert not any(b.disabled for b in at.button[:3])


def test_une_correction_reecrite_desactive_les_deux_autres_reponses(app):
    """Amender un contrat ou refuser n'écrit rien dans les données : il n'y a
    donc pas de SQL à réécrire. `agent/hitl.py` le refuserait — l'interface,
    elle, l'empêche **avant** le clic."""
    at = ouvrir(app, "✅ Décisions")
    at.text_input(key="decideur").set_value("hoda").run()
    at.text_area(key="fix").set_value("UPDATE t SET a = NULL WHERE b").run()

    boutons = {b.label: b.disabled for b in at.button[:3]}
    # « Corriger » reste ouvert : réécrire la correction n'a de sens que là.
    assert not [d for lib, d in boutons.items() if "Corriger" in lib and d]
    # Les deux autres n'écrivent rien dans les données — donc rien à réécrire.
    assert all(d for lib, d in boutons.items() if "Corriger" not in lib), boutons


# ===========================================================================
# Ce que l'écran de décision montre — et n'invente pas
# ===========================================================================


def test_l_impact_est_en_tete(app):
    """Sans lui, l'humain n'approuve pas : il signe."""
    at = ouvrir(app, "✅ Décisions")
    assert "concernées" in at.metric[0].label, "l'impact doit être en tête, en clair"
    assert "51 ligne" in at.metric[0].value


def test_l_effet_aval_non_calcule_est_dit(app):
    """Un impact qui omettrait l'aval en silence laisserait approuver une
    correction qui déplace un indicateur de moitié."""
    at = ouvrir(app, "✅ Décisions")
    assert any("7.1" in c.value for c in at.caption)


def test_une_alerte_P6_est_montree_AVANT_la_decision(app, monkeypatch):
    """`apply` refuserait de toute façon — mais découvrir le refus après avoir
    approuvé est inutile : l'humain doit pouvoir réécrire tout de suite, son
    autorité n'étant pas soumise à P6."""
    proposition = dict(PROPOSITION, alertes_p6=["PRIX = 80 : valeur jamais observée"])
    monkeypatch.setattr(hitl, "proposition", lambda fil, db=None: dict(proposition))

    at = ouvrir(app, "✅ Décisions")
    assert any("inventer une valeur" in e.value for e in at.error), (
        "le refus se dit en français, pas par le nom d'un invariant"
    )


# ===========================================================================
# 📜 Valider une règle depuis l'écran (phase 6.2)
# ===========================================================================


CONTRAT_PROPOSE = {
    "table": "RAW.CUSTOMERS",
    "version": 1,
    "status": "proposed",
    "columns": {
        "CUSTOMER_ID": {"role": "identifier", "unique": True, "not_null": True},
        "CUSTOMER_CITY": {"role": "categorical", "no_semantic_collisions": True},
    },
    "warnings": [
        {
            "column": "CUSTOMER_CITY",
            "kind": "partial_evidence",
            "detail": "les valeurs relevées ne couvrent que 43% des lignes",
        }
    ],
}


@pytest.fixture
def avec_contrat(app, monkeypatch):
    """Une règle proposée, et la signature espionnée."""
    import donnees

    signatures = []
    monkeypatch.setattr(
        donnees,
        "contrats",
        lambda dataset: [
            {"table": "RAW.CUSTOMERS", "version": 1, "status": "proposed", "path": "x"}
        ],
    )
    monkeypatch.setattr(donnees, "contrat", lambda chemin: dict(CONTRAT_PROPOSE))
    monkeypatch.setattr(
        donnees,
        "valider_contrat",
        lambda ds, table, par, accepter=False: signatures.append(
            {"table": table, "par": par, "accepter": accepter}
        ),
    )
    app.signatures = signatures
    return app


def test_les_clauses_sont_dites_en_francais(avec_contrat):
    """⭐ `{"between": [1, 100]}` ne se relit pas ; « doit rester entre 1 et
    100 » se relit. Le contrat est **la** chose qu'un métier doit pouvoir lire
    avant de la signer."""
    at = ouvrir(avec_contrat, "📜 Règles")
    tableau = at.dataframe[0].value
    colonnes = list(tableau["Ce qui est exigé"])
    assert any("ne doit jamais être vide" in c for c in colonnes)
    assert any("São Paulo" in c for c in colonnes)


def test_les_reserves_de_l_agent_sont_montrees(avec_contrat):
    """La découverte critique ses propres propositions. Cacher ces réserves
    rendrait la critique décorative."""
    at = ouvrir(avec_contrat, "📜 Règles")
    assert any("réserve" in w.value for w in at.warning), (
        "la réserve doit sauter aux yeux"
    )
    # …et son **détail** doit être lisible, pas seulement son décompte : « 1
    # réserve » sans « 43 % de couverture » ne permet pas de décider.
    assert any("43%" in m.value for m in at.markdown)


def test_signer_exige_un_nom(avec_contrat):
    """Un contrat sans signataire ne prouve rien six mois plus tard."""
    at = ouvrir(avec_contrat, "📜 Règles")
    assert at.button[0].disabled


def test_signer_une_reserve_exige_de_la_lire(avec_contrat):
    """⭐ Le garde-fou `--accept-warnings` du CLI, **tel quel** dans l'interface.

    Signer une réserve est une décision, pas une formalité : sans cette case,
    un clic distrait validerait une collision sémantique et toute la critique de
    la découverte n'aurait servi à rien.
    """
    at = ouvrir(avec_contrat, "📜 Règles")
    at.text_input(key="signataire").set_value("hoda").run()
    assert at.button[0].disabled, "le nom seul ne doit pas suffire"

    at.checkbox(key="accepte").set_value(True).run()
    assert not at.button[0].disabled


def test_le_clic_signe_par_la_voie_partagee(avec_contrat):
    """La même fonction que `scripts/discover.py --approve` — une seconde voie
    serait une seconde façon de contourner le garde-fou."""
    at = ouvrir(avec_contrat, "📜 Règles")
    at.text_input(key="signataire").set_value("hoda").run()
    at.checkbox(key="accepte").set_value(True).run()
    at.button[0].click().run()

    assert not at.exception
    assert avec_contrat.signatures == [
        {"table": "RAW.CUSTOMERS", "par": "hoda", "accepter": True}
    ]


def test_une_regle_en_vigueur_ne_se_resigne_pas(app, monkeypatch):
    """Re-signer ce qui est déjà en vigueur n'a pas de sens — et `ecrire()` le
    refuserait de toute façon, pour protéger le travail d'un humain."""
    import donnees

    monkeypatch.setattr(
        donnees,
        "contrats",
        lambda dataset: [
            {"table": "RAW.ORDERS", "version": 1, "status": "approved", "path": "x"}
        ],
    )
    monkeypatch.setattr(
        donnees,
        "contrat",
        lambda chemin: dict(
            CONTRAT_PROPOSE, status="approved", approved_by="hoda", warnings=[]
        ),
    )
    at = ouvrir(app, "📜 Règles")
    assert any("en vigueur" in s.value for s in at.success)
    assert not at.button, "aucun bouton de signature sur une règle déjà en vigueur"


# ===========================================================================
# 🏠 L'accueil répond à « que dois-je faire ? »
# ===========================================================================


def test_l_accueil_dit_ce_qui_attend(app):
    """⭐ Un écran d'accueil contemplatif ne sert à rien : il doit répondre à
    *que dois-je faire ?*, pas seulement à *comment ça va ?*."""
    at = ouvrir(app, "🏠 Accueil")
    assert any("attendent votre décision" in w.value for w in at.warning)
    assert any("attendent votre relecture" in i.value for i in at.info)


def test_l_accueil_chiffre_l_essentiel(app):
    at = ouvrir(app, "🏠 Accueil")
    libelles = [m.label for m in at.metric]
    assert "Tables surveillées" in libelles
    assert "Décisions en attente" in libelles


def test_quand_il_n_y_a_rien_a_faire_l_accueil_le_dit(app, monkeypatch):
    """« Rien à décider » et un écran vide ne veulent pas dire la même chose :
    le second laisse croire à une panne."""
    import donnees

    monkeypatch.setattr(
        donnees,
        "vue_ensemble",
        lambda dataset: {
            "tables": 17,
            "contrats": [],
            "attente": [],
            "incidents": [],
            "contrats_en_vigueur": 17,
            "contrats_a_signer": 0,
            "decisions_en_attente": 0,
            "runs": 92,
            "runs_avec_ecart": 0,
            "a_faire": 0,
            "erreurs": [],
        },
    )
    at = ouvrir(app, "🏠 Accueil")
    assert any("Rien à décider" in s.value for s in at.success)


def test_tout_ecran_cite_dans_un_message_existe(app):
    """⭐ Le garde-fou contre une orientation qui ment.

    L'accueil renvoie vers d'autres onglets (« → onglet **Règles** »). Si un
    écran est renommé sans que le message suive, le lecteur cherche un onglet
    **qui n'existe pas** — et rien ne le signale, puisque les deux chaînes
    vivraient à deux endroits.

    C'est arrivé : après la refonte, l'accueil pointait encore vers « Contrats »
    alors que l'écran s'appelait « Règles ». Les noms sont désormais des
    constantes, et ce test vérifie que tout onglet cité est atteignable.
    """
    import re

    app_mod = __import__("app")
    at = ouvrir(app, "🏠 Accueil")

    textes = [w.value for w in at.warning] + [i.value for i in at.info]
    cites = set()
    for texte in textes:
        cites.update(re.findall(r"onglet \*\*(.+?)\*\*", texte))

    assert cites, "l'accueil doit orienter vers les écrans d'action"
    for onglet in cites:
        assert onglet in app_mod.ECRANS, f"onglet cité mais introuvable : {onglet!r}"
