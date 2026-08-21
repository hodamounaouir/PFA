"""Ce que les écrans lisent (phase 6.1) — **toute la logique, aucune interface**.

Même partage que pour Airflow en 4.5 : le DAG ne contient que des
`BashOperator`, toute la logique vit dans `scripts/check_layer.py`. Ici, les
vues Streamlit ne contiennent que de l'affichage, tout ce qui se raisonne vit
dans ce module — et se teste donc sans navigateur.

Ce n'est pas une préférence de style. Une logique enfermée dans un `st.button()`
n'est éprouvable qu'à la main, et un écran de décision qu'on ne peut pas tester
est un écran dont on ne sait pas s'il montre la vérité.

## Les six écrans et leur source

    Dashboard BI          les agrégats Gold, via le connecteur
    Incidents             `OPS.INCIDENTS` — le journal COMPLET, sans filtre R5
    Décision              un incident, déplié
    Validation HITL       le checkpointer, et `agent/hitl.py` pour trancher
    Signatures en silence `INCIDENTS` filtré aux refus — le garde-fou anti-cécité
    Contrats              `contracts/*.yaml` et leur historique de versions

## ⭐ Le journal n'est pas la mémoire

`lire_incidents` filtre aux décisions humaines (R5) parce que c'est ce que
l'agent relit : lui donner ses propres hypothèses le ferait tourner en rond.
`lire_journal` ne filtre rien, parce que c'est ce qu'un humain relit — un run
sans anomalie, un run sans décision, un run refusé y figurent tous.

Les cacher donnerait un historique **plus propre que la réalité**, et c'est
précisément là qu'on regarde pour savoir ce que l'agent a fait cette nuit.
"""

from typing import Optional

from agent.connectors import fermer, ouvrir, ops
from agent.contracts import loader
from agent.graph import propositions_en_attente
from agent.incidents import depuis_texte
from agent.registry import charger as charger_registre
from agent.state import DECISION_REJECTED


def _memoire():
    return ops.MemoireOps()


# ---------------------------------------------------------------------------
# Écran « Incidents » — le journal complet
# ---------------------------------------------------------------------------


def journal(dataset: str, **filtres) -> list[dict]:
    """L'historique des runs, du plus récent au plus ancien."""
    memoire = _memoire()
    try:
        return memoire.lire_journal(dataset, **filtres)
    finally:
        memoire.close()


def resumer_incident(incident: dict) -> dict:
    """Une ligne de tableau : ce qu'on lit d'un coup d'œil.

    `statut` est **dérivé** et non stocké : « en attente » n'est pas une valeur
    de `human_decision`, c'est son absence. Le calculer ici plutôt que de
    l'écrire en base évite un champ qui pourrait mentir — un incident tranché
    dont le statut serait resté « en attente » serait invisible pour toujours.
    """
    anomalies = incident.get("anomalies") or []
    return {
        "incident": incident.get("incident_id"),
        "lot": incident.get("batch_id"),
        "couche": incident.get("layer"),
        "table": incident.get("table_name"),
        "ecarts": len(anomalies),
        "statut": statut(incident),
        "decideur": incident.get("decided_by"),
        "applique": bool(incident.get("applied_fix")),
    }


def statut(incident: dict) -> str:
    decision = incident.get("human_decision")
    if decision:
        return decision
    return "rien d'anormal" if not (incident.get("anomalies") or []) else "en attente"


# ---------------------------------------------------------------------------
# ⭐ Écran « Signatures en silence » — le garde-fou anti-cécité
# ---------------------------------------------------------------------------


def silences(dataset: str, table: Optional[str] = None) -> list[dict]:
    """Tout ce que l'agent ne signale plus, et sur décision de qui.

    ⭐ **L'écran le plus important de la phase 6, et le moins spectaculaire.**
    Sans lui, l'agent devient progressivement muet sans que personne s'en
    aperçoive — et c'est invisible **parce qu'**il ne dit plus rien. Un système
    de surveillance qui se tait par accumulation de refus ressemble en tout
    point à un système qui n'a rien à signaler.

    Chaque ligne porte qui a refusé et quand : une décision sans auteur ne se
    conteste pas six mois plus tard.
    """
    lignes = []
    for incident in journal(dataset, table=table):
        if incident.get("human_decision") != DECISION_REJECTED:
            continue
        for brut in incident.get("signatures") or []:
            table_sig, colonne, type_, octave = _quatre(brut)
            lignes.append(
                {
                    "signature": brut,
                    "table": table_sig,
                    "colonne": colonne,
                    "type": type_,
                    "ordre_de_grandeur": octave,
                    "refuse_par": incident.get("decided_by"),
                    "refuse_le": incident.get("decided_at") or incident.get("run_ts"),
                    "lot": incident.get("batch_id"),
                    "incident": incident.get("incident_id"),
                }
            )
    return lignes


def _quatre(brut: str) -> tuple:
    """Les quatre termes d'une signature, quoi qu'on ait relu.

    Une signature illisible ne fait pas tomber l'écran : elle s'affiche telle
    quelle. Un garde-fou anti-cécité qui plante sur une ligne malformée
    n'affiche plus rien du tout — ce qui est exactement la cécité qu'il combat.
    """
    try:
        termes = depuis_texte(brut)
    except Exception:  # noqa: BLE001 — voir le docstring
        termes = ()
    return (
        tuple(termes) + (None,) * (4 - len(termes)) if len(termes) < 4 else termes[:4]
    )


# ---------------------------------------------------------------------------
# Écran « Validation HITL » — la file, et la reprise
# ---------------------------------------------------------------------------


def file_attente(db=None) -> list[dict]:
    """Les propositions qui attendent une décision, la plus ancienne d'abord."""
    return propositions_en_attente(db) if db else propositions_en_attente()


# La reprise elle-même n'est **pas** ici : elle vit dans `agent/hitl.py`, la voie
# unique que `scripts/decide.py` emprunte aussi. Une seconde voie serait une
# seconde façon de contourner P3 — la garantie « aucun chemin n'atteint `apply`
# sans approbation » ne vaudrait plus que pour les chemins qu'on a testés.


# ---------------------------------------------------------------------------
# Écran « Contrats »
# ---------------------------------------------------------------------------


def contrats(dataset: str) -> list[dict]:
    """Les contrats sur disque, avec leur statut et leur version.

    On passe par `lister()` et non `charger()` : ce dernier ne rend que du
    **validé** (garantie de 4.2.4), or l'écran doit précisément montrer ce qui
    attend une signature. « Aucun contrat » et « un contrat qui attend » sont
    deux situations différentes, et les confondre serait un état silencieux.
    """
    return loader.lister(dataset)


def contrat(chemin) -> dict:
    """Le contenu d'un contrat, tel qu'il est sur le disque."""
    return loader._lire(chemin)


# ---------------------------------------------------------------------------
# Écran « Dashboard BI » — les agrégats Gold
# ---------------------------------------------------------------------------


def tables_gold(dataset: str) -> list[str]:
    return [t.name for t in charger_registre(dataset).tables_de("gold")]


def agregat(dataset: str, table: str, limite: int = 200) -> dict:
    """Le contenu d'un mart, tel qu'un dashboard le montrerait.

    ⚠️ **Le seul écran qui affiche des lignes brutes**, et c'est sa raison
    d'être : c'est là qu'on *voit* les chiffres faux — `sao paulo` et
    `são paulo` sur deux lignes — puis corrigés après décision. Un agrégat est
    déjà une agrégation ; la règle R2 protège le **modèle**, pas l'écran de
    l'humain qui décide.
    """
    registre = charger_registre(dataset)
    declaree = registre.table(table)
    if declaree is None or declaree.layer != "gold":
        raise ValueError(f"{table!r} n'est pas un mart déclaré de {dataset!r}")

    connecteur = ouvrir(registre.connector)
    try:
        return connecteur.executer(f"SELECT * FROM {table}", limite)
    finally:
        fermer(connecteur)


# ---------------------------------------------------------------------------
# Traduire pour des yeux non techniques (phase 6.2)
# ---------------------------------------------------------------------------
#
# ⭐ Les écrans s'adressent à quelqu'un qui connaît **le métier**, pas le
# vocabulaire du projet. « écart de famille sémantique, octave -2 » ne dit rien
# à la personne qui décide si les ventes par ville sont justes.
#
# La traduction vit ici et non dans les vues : c'est une règle, donc ça se teste.
# Et un mot mal traduit se corrige à un seul endroit.

ROLES_LISIBLES = {
    "identifier": "identifiant",
    "foreign_key": "référence vers une autre table",
    "categorical": "catégorie",
    "numeric": "nombre",
    "temporal": "date",
    "free_text": "texte libre",
    "unknown": "indéterminé",
}

DAMA_LISIBLES = {
    "completude": "des valeurs manquent",
    "unicite": "des doublons",
    "validite": "des valeurs inattendues",
    "coherence": "des écritures qui se contredisent",
    "exactitude": "des valeurs hors normes",
    "fraicheur": "des données en retard",
}

DECISIONS_LISIBLES = {
    "approved": "✅ corrigé",
    "amend_contract": "📝 règle ajustée",
    "rejected": "❌ écarté",
    "en attente": "⏳ à décider",
    "rien d'anormal": "✅ rien à signaler",
}


def clause_lisible(nom: str, valeur) -> str:
    """Une clause de contrat, dite en français.

    Le contrat est ce que l'agent tient pour vrai : c'est **la** chose qu'un
    métier doit pouvoir relire avant de la signer. `{"between": [1, 100]}` ne se
    relit pas ; « doit rester entre 1 et 100 » se relit.
    """
    if nom == "not_null":
        return "ne doit jamais être vide"
    if nom == "unique":
        return "chaque valeur doit être unique"
    if nom == "between":
        bas, haut = valeur
        return f"doit rester entre {bas} et {haut}"
    if nom == "accepted_values":
        apercu = ", ".join(str(v) for v in list(valeur)[:5])
        reste = f" (+{len(valeur) - 5})" if len(valeur) > 5 else ""
        return f"doit valoir l'une de {len(valeur)} valeurs : {apercu}{reste}"
    if nom == "no_semantic_collisions":
        return "deux façons d'écrire la même valeur sont interdites (São Paulo / Sao Paulo)"
    return f"{nom} : {valeur}"


def colonnes_lisibles(contrat: dict) -> list[dict]:
    """Le contrat en tableau, une ligne par colonne."""
    lignes = []
    for colonne, clauses in (contrat.get("columns") or {}).items():
        regles = [
            clause_lisible(nom, valeur)
            for nom, valeur in clauses.items()
            if nom != "role" and valeur is not None
        ]
        lignes.append(
            {
                "Colonne": colonne,
                "Nature": ROLES_LISIBLES.get(clauses.get("role"), clauses.get("role")),
                "Ce qui est exigé": " · ".join(regles) if regles else "—",
            }
        )
    return lignes


def anomalie_lisible(anomalie: dict) -> str:
    """Un écart, dit en une phrase.

    On garde le **chiffre** et on traduit le reste : « des valeurs manquent »
    sans « 51 lignes » ne servirait à personne pour décider.
    """
    quoi = DAMA_LISIBLES.get(anomalie.get("dama"), anomalie.get("type"))
    ou = anomalie.get("colonne") or anomalie.get("table") or ""
    observe = anomalie.get("observe")
    combien = ""
    if isinstance(observe, (int, float)) and not isinstance(observe, bool):
        combien = f" — {observe}"
    elif isinstance(observe, (list, tuple)) and observe:
        combien = f" — {', '.join(str(v) for v in observe[:3])}"
    return f"{quoi} sur « {ou} »{combien}"


# ---------------------------------------------------------------------------
# Écran d'accueil — l'état du système en quatre chiffres
# ---------------------------------------------------------------------------


def vue_ensemble(dataset: str) -> dict:
    """Ce qu'on veut savoir en arrivant : tout va-t-il bien, et que dois-je faire ?

    Chaque source est interrogée **séparément** et son échec est isolé : un
    accès expiré ne doit pas vider l'écran d'accueil des informations qui, elles,
    sont lisibles depuis le disque (les contrats, par exemple).
    """
    etat = {"erreurs": []}

    def _essayer(cle, appel, defaut):
        try:
            etat[cle] = appel()
        except Exception as exc:  # noqa: BLE001 — voir le docstring
            etat[cle] = defaut
            etat["erreurs"].append(f"{cle} : {type(exc).__name__}")

    _essayer("tables", lambda: len(charger_registre(dataset).tables), 0)
    _essayer("contrats", lambda: contrats(dataset), [])
    _essayer("attente", lambda: file_attente(), [])
    _essayer("incidents", lambda: journal(dataset, limite=200), [])

    signes = [c for c in etat["contrats"] if c["status"] == "approved"]
    a_signer = [c for c in etat["contrats"] if c["status"] != "approved"]
    avec_ecart = [i for i in etat["incidents"] if i.get("anomalies")]

    etat.update(
        {
            "contrats_en_vigueur": len(signes),
            "contrats_a_signer": len(a_signer),
            "decisions_en_attente": len(etat["attente"]),
            "runs": len(etat["incidents"]),
            "runs_avec_ecart": len(avec_ecart),
        }
    )
    etat["a_faire"] = etat["decisions_en_attente"] + etat["contrats_a_signer"]
    return etat


def valider_contrat(dataset: str, table: str, par: str, accepter: bool = False) -> dict:
    """Signe un contrat — **la même fonction** que `scripts/discover.py --approve`.

    Une seconde voie de validation serait une seconde façon de contourner le
    garde-fou des avertissements, et la critique de la découverte deviendrait
    décorative.
    """
    from agent.contracts.validation import approuver

    return approuver(dataset, table, par, accepter)
