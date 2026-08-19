"""Les tools de l'agent (phase 4.1) — un fichier par tool, testé isolément.

Ils sont décorés `@tool` (LangChain), comme le demande le §5.6 du cahier des
charges. Mais **aucun n'est jamais lié à un modèle** : `bind_tools` n'apparaît
nulle part dans le projet, et `tests/test_tools.py` le vérifie.

La nuance est tout l'objet de l'[ADR 004](../../docs/adr/004-langgraph-vs-function-calling.md) :
le décorateur est un *format*, le tool-calling est une *délégation de flux*. Le
cahier demande le premier, `DESIGN.md` §2 rejette la seconde. Ici, ce sont les
nœuds qui appellent les tools, dans l'ordre écrit dans `agent/graph.py`.

Conséquence sur les signatures : un `@tool` dérive son schéma de ses arguments,
qui doivent donc être des valeurs simples. On ne lui passe pas un objet
connecteur — il le résout lui-même depuis le registre. C'est aussi la forme dont
Airflow aura besoin en 4.5 : `(dataset, layer, table, batch_id)`, quatre chaînes.
"""

from agent.tools.profile_table import profile_table
from agent.tools.read_past_incidents import read_past_incidents
from agent.tools.read_schema_history import read_schema_history
from agent.tools.robust_stats import robust_stats
from agent.tools.top_values import top_values
from agent.tools.write_log import write_log

__all__ = [
    "profile_table",
    "read_past_incidents",
    "read_schema_history",
    "robust_stats",
    "top_values",
    "write_log",
]
