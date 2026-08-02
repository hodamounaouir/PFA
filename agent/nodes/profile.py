"""Nœud `profile` — résume un batch en agrégats (stub, phase 3.1).

**Aucun nom de table ni de colonne n'apparaît dans ce fichier** : l'agent doit
fonctionner sur n'importe quel dataset (décision du 2026-07-28). Les colonnes
viennent toujours de l'extérieur — de l'introspection en phase 4.3, de l'état ici.

Ce qui est profilé : **le batch qui arrive**, pas la table entière. Profiler la
table entière diluerait l'anomalie : 30 % de nulls sur un batch ne pèsent plus
que 0,3 % noyés dans 92 jours cumulés.

Réel en phase 4.3 : appelle `profile_table` via le connecteur, puis persiste le
profil du jour dans `OPS._PROFILES` — **après** avoir lu l'historique, jamais
avant, sinon le jour courant entre dans sa propre référence.

Règle intangible : le profil ne contient **que des agrégats**, jamais de lignes
brutes. C'est ce qui garantit que le LLM (`diagnose`) ne verra jamais une donnée
réelle — il raisonne sur des chiffres, pas sur des clients.
"""

from agent.state import AgentState, log_entry

# Colonnes utilisées quand l'appelant n'en fournit aucune. Les noms sont
# volontairement neutres : ils ne doivent évoquer aucun dataset particulier.
STUB_COLUMNS = ("col_1", "col_2", "col_3", "col_4")

STUB_ROW_COUNT = 351


def _colonnes(state: AgentState) -> list[str]:
    """D'où viennent les colonnes à profiler.

    Phase 4.3 : de l'introspection (`INFORMATION_SCHEMA`) via le connecteur.
    Ici : de `schema_history`, que l'appelant remplit. Dans les deux cas la
    liste vient de l'extérieur, jamais d'un littéral écrit dans ce fichier.
    """
    colonnes = [c["name"] for c in state["schema_history"] if "name" in c]
    return colonnes or list(STUB_COLUMNS)


def _stats(position: int, row_count: int) -> dict:
    """Statistiques bidon, calculées sur la *position* et non sur le nom.

    Sur la position : c'est ce qui garantit que le stub se comporte pareil quel
    que soit le dataset branché.
    """
    return {
        # une colonne sur quatre porte des nulls, pour que `detect` ait quelque
        # chose à constater quel que soit le dataset
        "null_rate": 0.301 if position % 4 == 1 else 0.0,
        "distinct": max(1, row_count - position * 10),
    }



def profile(state: AgentState) -> dict:
    colonnes = _colonnes(state)
    fiche = {
        "row_count": STUB_ROW_COUNT,
        "columns": {
            nom: _stats(position, STUB_ROW_COUNT) for position, nom in enumerate(colonnes)
        },
    }
    return {
        "profile": fiche,
        "logs": [
            log_entry(
                "profile",
                "profil calculé (stub)",
                table=state["table"],
                lignes=STUB_ROW_COUNT,
                colonnes=len(colonnes),
            )
        ],
    }
