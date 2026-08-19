"""État partagé de l'agent (phase 3.1, §5.2 du cahier des charges).

Chaque nœud reçoit l'état complet et retourne un **dictionnaire partiel** : les
clés qu'il retourne écrasent celles de l'état, les autres sont laissées intactes.

    def detect(state: AgentState) -> dict:
        return {"anomalies": [...]}      # seul `anomalies` est modifié

La seule exception est `logs` (voir le commentaire sur le réducteur plus bas).

Révision 2026-07-28 (agent générique) : ajout de `dataset`, `contract`,
`contract_version`, et `human_decision` accepte désormais trois valeurs au lieu
de deux (`amend_contract` = « la donnée est juste, c'est le contrat qui a tort »).
"""

from datetime import datetime, timezone
from operator import add
from typing import Annotated, Optional, TypedDict

# --- Décisions humaines possibles (HITL) -----------------------------------
# Ce sont des constantes et non des chaînes libres : le test de preuve P3
# (« aucun chemin n'atteint apply sans approbation ») s'appuie dessus, et une
# faute de frappe dans un "approved" écrit à la main ouvrirait un trou.
DECISION_APPROVED = "approved"  # la donnée est fausse → apply corrige
DECISION_AMEND = "amend_contract"  # la donnée est juste → amend met à jour le contrat
DECISION_REJECTED = (
    "rejected"  # rien à faire → log seul (faux positif classé sans suite)
)

DECISIONS = frozenset({DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED})

# --- Demander avant de décider ----------------------------------------------
# `question` n'est **pas** une décision, et c'est pour ça qu'elle ne figure pas
# dans `DECISIONS` : elle ne clôt rien, elle diffère. Un humain à qui on ne laisse
# que trois boutons approuve vite et mal — c'est la faiblesse connue du HITL
# (« et si l'humain approuve sans lire ? », §5.3 de DESIGN.md). Pouvoir demander
# « pourquoi ? » avant de trancher est ce qui rend l'approbation informée.
#
# La décision finale reste malgré tout l'un des trois mots ci-dessus : c'est elle
# qui route le graphe, qui est enregistrée dans INCIDENTS, et qui sert à calculer
# la précision au benchmark. Si elle devenait du texte libre, l'aiguillage devrait
# *interpréter* ce que l'humain a voulu dire — exactement ce qu'on s'interdit.
DEMANDE_QUESTION = "question"


class AgentState(TypedDict):
    """L'état qui circule de START à END, une instance par batch analysé."""

    # --- Entrée : fourni par l'appelant (Airflow en phase 4.5) --------------
    dataset: str  # nom du registre datasets/<dataset>.yaml
    layer: str  # bronze | silver | gold
    table: str
    batch_id: str  # le jour rejoué, ex. "2018-04-29"

    # --- Références : ce à quoi on compare (chargé au début du run) ---------
    contract: dict  # contracts/<table>.yaml — « ce qui devrait être vrai »
    contract_version: Optional[
        str
    ]  # ex. "v1" ; None si la table n'a pas encore de contrat
    schema_history: list  # OPS._SCHEMA_HISTORY — le dernier schéma connu

    # --- Profile : le batch résumé en agrégats ------------------------------
    profile: dict  # volumes, nulls, cardinalités, min/max… jamais de lignes brutes

    # OPS._PROFILES — les mêmes mesures, sur les lots **précédents** (phase 4.3).
    # Forme : {(colonne, métrique): [valeurs, du plus ancien au plus récent]},
    # `colonne` valant None pour une métrique de table.
    #
    # Chargé par `profile` plutôt que lu par `detect`, pour que **`detect` ne
    # fasse aucune entrée-sortie** : ses cinq familles doivent être déterministes
    # et reproductibles au benchmark (phase 8), donc éprouvables sur de simples
    # dictionnaires, sans base ni réseau. Un détecteur qui ouvre une connexion
    # est un détecteur qu'on ne peut pas rejouer à l'identique.
    profile_history: dict

    # --- Detect : les écarts constatés (fait mesurable, pas jugement) -------
    anomalies: list

    # --- Mémoire : incidents passés déjà tranchés par un humain (O7) --------
    past_incidents: list

    # --- Diagnose : le seul nœud qui appelle le LLM -------------------------
    diagnosis: Optional[
        dict
    ]  # {root_cause, proposed_fix, explanation} ou None si parsing KO

    # --- Propose : la pause HITL --------------------------------------------
    human_decision: Optional[str]  # une valeur de DECISIONS, ou None tant qu'on attend
    decided_by: Optional[str]  # qui a tranché (rempli en phase 5, tracé dans INCIDENTS)
    decided_at: Optional[str]  # quand (ISO 8601)

    # --- Le dialogue avant la décision --------------------------------------
    # Même réducteur que `logs` : les échanges s'accumulent au lieu de s'écraser.
    # C'est ce qui permet de montrer, dans INCIDENTS puis dans Streamlit, non pas
    # « l'humain a approuvé » mais « l'humain a posé deux questions, obtenu ces
    # réponses, **puis** approuvé ». Bien meilleure réponse à « et s'il approuve
    # sans lire ? » qu'un simple taux d'approbation.
    # Forme d'une entrée : {"role": "humain" | "agent", "message": str, "ts": str}
    conversation: Annotated[list, add]

    # --- Apply : quelle correction a réellement été exécutée ? ---------------
    # L'humain peut approuver *sa propre* correction plutôt que celle proposée.
    # Sans cette possibilité, il irait corriger à la main dans la base : la
    # donnée serait juste, mais INCIDENTS ne le saurait pas — et le journal
    # deviendrait faux.
    fix_override: Optional[str]  # la correction écrite par l'humain, si différente
    applied_fix: Optional[str]  # celle qui a réellement tourné (proposée OU réécrite)

    # --- Validate : la correction a-t-elle eu l'effet attendu ? -------------
    validation: Optional[dict]

    # --- Journal : le seul champ qui s'accumule au lieu d'être écrasé -------
    # `Annotated[list, add]` installe un *réducteur* : quand un nœud retourne
    # {"logs": [x]}, LangGraph fait `ancien + [x]` au lieu de remplacer. C'est ce
    # qui fait du journal un historique append-only — chaque nœud ajoute sa
    # ligne sans effacer celles des autres.
    logs: Annotated[list, add]


def new_state(dataset: str, layer: str, table: str, batch_id: str) -> AgentState:
    """Construit un état initial complet (toutes les clés présentes, vides).

    Passer par cette fabrique plutôt que d'écrire le dict à la main : ça évite
    les `KeyError` dans les nœuds et garantit que l'état de test ressemble à
    l'état de production.
    """
    return AgentState(
        dataset=dataset,
        layer=layer,
        table=table,
        batch_id=batch_id,
        contract={},
        contract_version=None,
        schema_history=[],
        profile={},
        profile_history={},
        anomalies=[],
        past_incidents=[],
        diagnosis=None,
        human_decision=None,
        decided_by=None,
        decided_at=None,
        fix_override=None,
        applied_fix=None,
        validation=None,
        conversation=[],
        logs=[],
    )


def echange(role: str, message: str) -> dict:
    """Une réplique du dialogue, à retourner dans `{"conversation": [ ... ]}`.

    `role` vaut `"humain"` ou `"agent"`. Même principe que `log_entry` : le nœud
    retourne une liste d'une seule entrée, le réducteur concatène.
    """
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "role": role,
        "message": message,
    }


def log_entry(node: str, message: str, **extra) -> dict:
    """Une ligne de journal horodatée, à retourner dans `{"logs": [ ... ]}`.

    Les nœuds n'écrivent jamais dans `logs` directement : ils retournent une
    liste d'une seule entrée, et le réducteur `add` s'occupe de la concaténer.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "node": node,
        "message": message,
    }
    entry.update(extra)
    return entry
