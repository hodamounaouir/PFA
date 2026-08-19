"""Tool `write_log` — la seule écriture du journal métier (phase 4.4, §5.6).

Ajoute **une ligne par run** dans `OPS.INCIDENTS`, quel que soit le chemin
emprunté par le graphe — y compris « rien d'anormal » et « refusé ».

## Pourquoi journaliser un run qui n'a rien trouvé

Ce n'est pas de la comptabilité. Sans ces lignes :

  - la **précision** de la phase 8 est incalculable — elle se mesure sur les
    incidents `rejected`, c'est-à-dire sur les faux positifs assumés ;
  - le filtre de silence n'a rien à relire, donc l'agent reposerait chaque jour
    une question déjà refusée ;
  - et « l'agent n'a rien signalé » deviendrait indistinguable de « l'agent n'a
    pas tourné », ce qui est le pire état d'un système de surveillance.

## Append-only

Aucune mise à jour, aucune suppression. Un journal qu'on peut réécrire ne prouve
rien — et c'est lui qui sert de preuve en soutenance comme au benchmark.
"""

import json
import uuid
from typing import Optional

from langchain_core.tools import tool

from agent.connectors import ops


@tool
def write_log(
    dataset: str,
    layer: str,
    table: str,
    batch_id: str,
    anomalies_json: str = "[]",
    signatures_json: str = "[]",
    diagnosis_json: str = "",
    human_decision: str = "",
    decided_by: str = "",
    decided_at: str = "",
    applied_fix: str = "",
    validation_status: str = "",
    duration_s: float = 0.0,
) -> str:
    """Écrit la ligne d'incident du run et rend son identifiant.

    Les champs structurés arrivent **déjà sérialisés** : un `@tool` ne prend que
    des valeurs simples (ADR 004), et laisser passer des dictionnaires ferait
    dépendre la signature du tool d'un schéma qui bouge à chaque phase.

    Les chaînes vides valent `None` en base : `""` et « pas de décision » sont
    deux choses différentes, et c'est exactement la distinction sur laquelle
    repose le filtre R5 de `lire_incidents`.
    """
    return ecrire(
        {
            "incident_id": str(uuid.uuid4()),
            "dataset": dataset,
            "layer": layer,
            "table_name": table,
            "batch_id": batch_id,
            "anomalies": anomalies_json,
            "signatures": signatures_json,
            "diagnosis": diagnosis_json or None,
            "human_decision": human_decision or None,
            "decided_by": decided_by or None,
            "decided_at": decided_at or None,
            "applied_fix": applied_fix or None,
            "validation_status": validation_status or None,
            "duration_s": duration_s,
        }
    )


def ecrire(incident: dict) -> Optional[str]:
    """Le corps du tool, appelable avec des objets Python.

    C'est par ici que passe le nœud `log` : lui a déjà les structures en mémoire,
    et les sérialiser pour les faire re-désérialiser aussitôt n'apporterait
    qu'une occasion de se tromper de format.
    """
    memoire = ops.MemoireOps()
    try:
        return memoire.ecrire_incident(incident)
    finally:
        memoire.close()


def serialiser(valeur) -> Optional[str]:
    """JSON compact, ou `None`. `ensure_ascii=False` pour que `são paulo` reste
    lisible dans la base — on ne relit pas ce qu'on ne peut pas lire."""
    if valeur is None:
        return None
    return json.dumps(valeur, ensure_ascii=False, default=str)
