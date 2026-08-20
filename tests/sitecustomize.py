"""Installe les doubles dans les **sous-processus** lancés par les tests.

Python importe `sitecustomize` au démarrage de l'interpréteur, avant toute autre
chose. Il suffit donc que ce dossier soit sur le `PYTHONPATH` d'un sous-processus
pour que ses doubles y soient posés — ce que les fixtures `autouse` de
`conftest.py` ne peuvent pas faire, puisqu'elles ne franchissent pas la frontière
d'un `subprocess`.

## Pourquoi ce fichier existe

Les tests de reprise après mort du process lancent de vrais interpréteurs
(`python -c …`, `python -m scripts.decide …`). Jusqu'ici ils installaient leurs
doubles à la main, et **seulement ceux qu'on avait remarqués** : `profile_table`
et la mémoire. `diagnose` n'en avait pas — ces sous-processus appelaient donc le
**vrai Groq**, en silence, à chaque exécution de la suite.

C'est exactement l'incident de la phase 3.3 (« trois helpers appelaient la vraie
API »), reproduit un an plus tard par un chemin que les fixtures ne couvraient
pas. Et c'est la même leçon, une troisième fois : *une règle qu'on peut oublier
n'est pas une règle.* Elle vit maintenant à un seul endroit, et tout
sous-processus qui reçoit ce dossier sur son `PYTHONPATH` l'hérite.

⚠️ Sans effet sur le process pytest lui-même : `sitecustomize` est importé avant
que pytest n'ajoute `tests/` au `sys.path`, donc seuls les sous-processus lancés
explicitement avec ce dossier au `PYTHONPATH` sont concernés.
"""

import importlib
from contextlib import contextmanager


def _installer() -> None:
    conftest = importlib.import_module("conftest")

    profile_mod = importlib.import_module("agent.nodes.profile")
    profile_mod.profile_table = conftest.PROFIL_FACTICE
    profile_mod.ops.MemoireOps = lambda *a, **k: conftest.MEMOIRE_FACTICE
    profile_mod.charger_registre = lambda dataset: conftest.REFERENCES
    profile_mod.ouvrir = lambda nom: conftest.REFERENCES
    profile_mod.fermer = lambda connecteur: None
    profile_mod.loader.charger = lambda ds, t: conftest.REFERENCES.contrat

    # La couture LLM — celle qui manquait, et qui partait sur le réseau.
    diagnose_mod = importlib.import_module("agent.nodes.diagnose")
    diagnose_mod.diagnostiquer = lambda contexte: conftest.DIAGNOSTIC_FACTICE
    diagnose_mod.repondre = lambda contexte, conversation, question: (
        f"(réponse factice à : {question})"
    )

    # L'écriture réelle d'`apply` (5.3) : aucun test ne touche une base, et
    # surtout pas en écriture.
    apply_mod = importlib.import_module("agent.nodes.apply")

    @contextmanager
    def _connecteur(dataset, table):
        yield conftest.REFERENCES, conftest.REFERENCES

    apply_mod.connecteur_pour = _connecteur

    # `validate` re-profile (5.3) et importe sa propre référence au tool.
    validate_mod = importlib.import_module("agent.nodes.validate")
    validate_mod.profile_table = conftest.PROFIL_FACTICE


try:
    _installer()
except Exception:  # noqa: BLE001
    # Un interpréteur qui reçoit ce dossier sans le projet sur son chemin ne
    # doit pas refuser de démarrer : on ne casse jamais un process qu'on ne
    # cherchait pas à instrumenter.
    pass
