"""Les 8 nœuds du graphe (phase 3.1), ajoutés **un par un**.

Tous sont des **stubs** : ils retournent des valeurs en dur, sans Snowflake ni
LLM. On valide ici la tuyauterie du graphe, pas l'intelligence — les stubs
deviennent réels en phase 4.

Chaque nœud est une fonction pure `AgentState -> dict` : elle lit l'état, ne le
modifie jamais en place, et retourne les seules clés qu'elle veut changer. C'est
ce qui permet de tester un nœud isolément, sans graphe.

Règle tenue dans tout `agent/` : **aucun nom de table ou de colonne réel**, pas
même en exemple. Les noms de datasets vivent dans `datasets/*.yaml`, les noms de
colonnes dans les tests et les contrats — jamais dans le code de l'agent.

Avancement : 8/8 ✅
  [x] profile   [x] detect    [x] diagnose  [x] propose
  [x] apply     [x] amend     [x] validate  [x] log

Le câblage des huit nœuds est dans `agent/graph.py`. Reste de la phase 3 :
brancher le checkpointer et `interrupt()`, écrire `scripts/decide.py`, puis
rendre `diagnose` réel (Groq).
"""

# ⚠️ **Piège de cette réexportation, à connaître avant d'écrire un test.**
#
# Chaque nœud est réexporté sous **le nom de son propre module** : après ces
# imports, `agent.nodes.diagnose` désigne la *fonction*, plus le module. Un
# `import agent.nodes.diagnose as m` rend donc silencieusement le mauvais objet,
# et le `monkeypatch` qui suit lève un `AttributeError` qui ne ressemble pas à
# sa cause. Pour atteindre le module :
#
#     diagnose_mod = importlib.import_module("agent.nodes.diagnose")
#
# Le piège s'est manifesté **cinq fois** (conftest, test_tools, le lanceur de
# sous-processus, `nodes/log.py`, `test_preuves`). Reconsidéré à la cinquième et
# **conservé** : le supprimer demanderait de renommer les huit fonctions ou de
# casser `from agent.nodes import …` dans `graph.py` et la moitié des tests,
# pour un défaut qui coûte une minute à qui a lu ce commentaire. L'avertissement
# vit désormais **ici**, à l'endroit où on le cherche, et plus seulement dans
# les fichiers qui s'y sont fait prendre.

from agent.nodes.amend import amend
from agent.nodes.apply import apply
from agent.nodes.detect import detect
from agent.nodes.diagnose import diagnose
from agent.nodes.log import log
from agent.nodes.profile import profile
from agent.nodes.propose import propose
from agent.nodes.validate import validate

__all__ = [
    "profile",
    "detect",
    "diagnose",
    "propose",
    "apply",
    "amend",
    "validate",
    "log",
]
