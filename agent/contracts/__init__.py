"""Les contrats : ce qui *devrait* être vrai d'une table (phase 4.2).

Troisième pilier de la détection, après l'historique du schéma et la dérive
statistique. Il attrape ce que les deux autres ratent — une colonne à 30 % de
nulls depuis toujours ne fait dériver aucune statistique, mais elle viole un
contrat qui dit « jamais nulle ».

    from agent.contracts import proposer

    contrat = proposer(fiche_de_profile_table)
    contrat["status"]    # "proposed" — rien n'est normatif sans décision humaine
    contrat["warnings"]  # ce que la découverte a critiqué : à lire en premier

Le chargement des contrats validés (`contracts/<table>.v1.yaml`) arrive en 4.2.4.
"""

from agent.contracts.proposer import (
    AUCUNE_DONNEE,
    COLLISION,
    DOUBLONS,
    NOMBRES_ILLISIBLES,
    PREUVE_PARTIELLE,
    PROPOSE,
    VERSION_INITIALE,
    proposer,
)

__all__ = [
    "AUCUNE_DONNEE",
    "COLLISION",
    "DOUBLONS",
    "NOMBRES_ILLISIBLES",
    "PREUVE_PARTIELLE",
    "PROPOSE",
    "VERSION_INITIALE",
    "proposer",
]
