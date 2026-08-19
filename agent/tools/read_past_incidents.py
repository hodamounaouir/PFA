"""Tool `read_past_incidents` — la mémoire de l'agent (phase 4.4, §5.6).

Rend les incidents de la table qui ont **reçu une décision humaine**, les plus
récents d'abord. C'est l'objectif O7 : au J85, l'agent retrouve l'incident du
J60 et cite la correction qui avait été approuvée.

## La mémoire sert dans les deux sens

    approuvé  →  `diagnose` propose la même correction, en citant le précédent
    refusé    →  le filtre de silence retire l'écart avant qu'il soit soumis

Les deux passent par la même lecture : c'est la **signature** qui distingue les
usages, pas deux requêtes différentes.

## Pourquoi seulement les décisions humaines (R5)

Un incident sans `human_decision` n'a rien tranché — run encore en pause, ou
clos sans réponse au bout de dix échanges. L'injecter dans le contexte du modèle
lui ferait citer comme précédent une question que **personne n'a jamais lue**,
et la mémoire de l'agent se remplirait de ses propres hypothèses.

Le filtre vit dans le SQL (`agent/connectors/ops.py`) et non ici : une garantie
qu'on peut oublier en appelant le tool autrement n'est pas une garantie.
"""

from typing import Optional

from langchain_core.tools import tool

from agent.connectors import ops


@tool
def read_past_incidents(dataset: str, table: str, limite: int = 50) -> list:
    """Les incidents passés de cette table, déjà tranchés par un humain.

    `dataset` est le nom d'un registre, `table` un nom qualifié
    (`RAW.ORDERS`). Rend une liste de dictionnaires portant l'anomalie
    constatée, le diagnostic rendu, la décision et son auteur.

    Liste vide si la table n'a pas d'antécédent — ce qui est le cas normal au
    premier passage, et n'est pas une erreur.
    """
    memoire = ops.MemoireOps()
    try:
        return memoire.lire_incidents(dataset, table, limite=limite)
    finally:
        # Un run interrompu ne doit pas laisser une session ouverte derrière lui.
        memoire.close()


def incidents_similaires(incidents: list, anomalies: list) -> list:
    """Ceux dont une signature coïncide avec un écart du jour.

    Fonction pure, volontairement **hors du tool** : c'est du rapprochement, pas
    de la lecture. La garder ici plutôt que dans `diagnose` évite que le nœud
    qui parle au modèle décide aussi de ce qu'il lui montre.
    """
    from agent.incidents import signature, texte

    cherchees = {texte(signature(a)) for a in anomalies or []}
    if not cherchees:
        return []

    retenus = []
    for incident in incidents or []:
        connues = {
            s if isinstance(s, str) else texte(tuple(s))
            for s in incident.get("signatures") or []
        }
        if connues & cherchees:
            retenus.append(incident)
    return retenus


def resumer(incidents: list, maximum: int = 3) -> list[dict]:
    """Ce qui part au modèle : le strict nécessaire, choisi champ par champ.

    ⚠️ **C'est une frontière R2.** Un incident porte le profil, le diagnostic et
    la correction — donc potentiellement des valeurs de données. On ne fait pas
    confiance à la forme stockée : on énumère ce qui sort, exactement comme
    `construire_contexte()` le fait pour le profil.

    Borné à trois : au-delà, le contexte grossit sans que le diagnostic
    s'améliore, et un prompt qui grossit à chaque run finit par coûter plus cher
    que l'incident qu'il explique.
    """
    resumes = []
    for incident in (incidents or [])[:maximum]:
        diagnostic = incident.get("diagnosis") or {}
        resumes.append(
            {
                "lot": incident.get("batch_id"),
                "cause_racine": _texte_court(diagnostic.get("root_cause")),
                "correction_proposee": _texte_court(diagnostic.get("proposed_fix")),
                "decision_humaine": incident.get("human_decision"),
                "decide_par": incident.get("decided_by"),
            }
        )
    return resumes


def _texte_court(valeur: Optional[str], maximum: int = 400) -> Optional[str]:
    """Tronque plutôt que d'envoyer un texte sans borne connue."""
    if not isinstance(valeur, str):
        return None
    return valeur if len(valeur) <= maximum else valeur[:maximum] + "…"
