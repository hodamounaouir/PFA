"""Nœud `detect` — constate les écarts (stub, phase 3.1).

`detect` ne dit jamais « c'est une anomalie ». Il dit « ceci s'écarte de la
référence R, de tant ». Qualifier l'écart — vraie anomalie ou changement métier
légitime — c'est le travail de l'humain, et c'est pour ça que `propose` aura
deux « non » différents (`rejected` et `amend_contract`).

**Aucun LLM ici, jamais.** La détection doit être reproductible pour être
mesurable au benchmark (phase 8) : deux exécutions sur le même lot doivent
rendre exactement le même verdict.

Réel en phase 4.3 — quatre familles, toutes déterministes :

  | Famille      | Lit                  | Seuil ?        |
  |--------------|----------------------|----------------|
  | schéma       | `_SCHEMA_HISTORY`    | non, binaire   |
  | contrat      | `contracts/*.yaml`   | la clause      |
  | statistique  | `_PROFILES`          | oui, ~3,5 MAD  |
  | sémantique   | le lot lui-même      | non            |

Le stub n'implémente que la famille statistique, dans sa forme la plus pauvre :
un seuil fixe sur le taux de nulls, sans historique. Ce qui compte à ce stade,
c'est la **forme de la sortie** — elle ne changera plus.

Ajout prévu en phase 4.4 : un dernier filtre avant de sortir. Si la *signature*
d'un écart a déjà été refusée par un humain, il est journalisé mais pas soumis.
"""

from agent.state import AgentState, log_entry

# Seuil bidon. En phase 4.3 les vrais seuils vivront dans `agent/config.py` :
# ce sont des réglages de *détection*, pas des règles de *décision*.
STUB_NULL_THRESHOLD = 0.10


def _ecart_nulls(table: str, colonne: str, stats: dict) -> dict | None:
    """Un écart de complétude, ou None si la colonne est dans les clous.

    Forme de sortie volontairement figée dès maintenant : les quatre familles
    devront toutes produire ce même dictionnaire, sinon `diagnose` et le journal
    auraient à connaître un format par famille.
    """
    observe = stats.get("null_rate", 0.0)
    if observe <= STUB_NULL_THRESHOLD:
        return None
    return {
        "famille": "statistique",
        "table": table,
        "colonne": colonne,
        "type": "nulls",
        "observe": observe,
        # En 4.3 : la médiane des N derniers jours lue dans `_PROFILES`,
        # accompagnée d'un score en MAD. Ici, faute d'historique, le seuil.
        "reference": STUB_NULL_THRESHOLD,
        "dama": "completude",
    }


def detect(state: AgentState) -> dict:
    colonnes = state["profile"].get("columns", {})
    anomalies = [
        ecart
        for nom, stats in colonnes.items()
        if (ecart := _ecart_nulls(state["table"], nom, stats)) is not None
    ]
    return {
        "anomalies": anomalies,
        "logs": [
            log_entry(
                "detect",
                f"{len(anomalies)} écart(s) constaté(s) (stub)",
                batch_id=state["batch_id"],
                colonnes_examinees=len(colonnes),
            )
        ],
    }
