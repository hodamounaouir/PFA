"""Le filtre de silence — ne pas resoumettre ce qu'un humain a déjà refusé (4.4).

Un agent qui repose chaque jour la même question qu'on lui a déjà refusée est un
agent qu'on finit par ignorer — et un HITL dont l'humain se détourne ne protège
plus rien. Ce filtre s'applique **entre `detect` et `diagnose`** : l'écart reste
constaté et journalisé, il n'est simplement pas soumis à décision.

## Ce qui rouvre la bouche de l'agent

La signature porte un **ordre de grandeur** (`agent/incidents.py`). Un refus sur
« 3 % de nulls le lundi » ne fait donc pas taire « 90 % de nulls le mardi » :
l'ampleur a changé d'octave, la signature diffère, l'écart repart en décision.
C'est tout l'objet du 4ᵉ terme.

## Garde-fou anti-cécité

Rien n'est supprimé : les écarts tus sont **rendus séparément**, journalisés
dans `INCIDENTS`, et la liste des signatures en silence est requêtable — c'est
l'écran de la phase 6, réactivable d'un clic. Sans lui, l'agent deviendrait
progressivement muet sans que personne s'en aperçoive, et ce serait invisible
précisément parce qu'il ne dirait plus rien.

## Seules les décisions humaines comptent (R5)

Un incident sans `human_decision` n'a rien tranché : il peut s'agir d'un run
encore en pause, ou clos sans réponse au bout de dix échanges. Le lire comme un
refus ferait taire l'agent sur une question **que personne n'a jamais lue**.
"""

from agent.incidents import signature, texte
from agent.state import DECISION_REJECTED


def signatures_refusees(incidents) -> set:
    """Les signatures qu'un humain a explicitement refusées, **en texte**.

    Une seule représentation, et c'est celle qui est stockée : les signatures
    relues d'`INCIDENTS` sont des chaînes, celles calculées à la volée des
    tuples. Comparer les deux formes reviendrait à ce que la mémoire ne
    reconnaisse jamais ce qu'elle a elle-même écrit.
    """
    refusees = set()
    for incident in incidents or []:
        if incident.get("human_decision") != DECISION_REJECTED:
            continue
        for sig in incident.get("signatures") or []:
            refusees.add(sig if isinstance(sig, str) else texte(tuple(sig)))
    return refusees


def filtrer(anomalies, incidents) -> tuple[list, list]:
    """`(à soumettre, tues)` — jamais une liste amputée sans son complément.

    Rendre les deux plutôt que de filtrer en place : un appelant qui ne
    recevrait que les écarts retenus ne pourrait pas journaliser les autres, et
    le garde-fou anti-cécité deviendrait un vœu pieux.
    """
    refusees = signatures_refusees(incidents)
    if not refusees:
        return list(anomalies or []), []

    retenus, tus = [], []
    for anomalie in anomalies or []:
        cible = tus if texte(signature(anomalie)) in refusees else retenus
        cible.append(anomalie)
    return retenus, tus
