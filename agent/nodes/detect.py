"""Nœud `detect` — constate les écarts, ne les juge pas (phase 4.3).

`detect` ne dit jamais « c'est une anomalie ». Il dit « ceci s'écarte de la
référence R, de tant ». Qualifier l'écart — vraie anomalie ou changement métier
légitime — est le travail de l'humain, et c'est pour ça que `propose` offre deux
« non » différents (`rejected` quand le cas est isolé, `amend_contract` quand
c'est la règle qui a vieilli).

**Aucun LLM ici, jamais** (R1). La détection doit être reproductible pour être
mesurable au benchmark : deux exécutions sur le même lot rendent exactement le
même verdict. Le modèle n'intervient qu'ensuite, dans `diagnose`, pour
*expliquer* ce que ces cinq familles ont constaté.

**Aucune entrée-sortie non plus.** Les cinq familles sont des fonctions pures
sur l'état ; c'est `profile` qui a rassemblé tout ce à quoi on compare. Une
famille qui interrogerait la base pendant qu'elle raisonne comparerait des
choses mesurées à des instants différents — l'écart n'aurait alors pas de sens.

## L'ordre des familles est celui de la lecture, pas de la logique

`inventaire` en premier parce qu'un écart de table éclaire tous les autres :
si la table a disparu, le profil vide qui suit n'est pas une anomalie de
complétude, c'en est la **conséquence**. Un humain qui lit la liste dans cet
ordre comprend en une ligne ; dans l'ordre inverse, il lit dix écarts avant
d'apprendre pourquoi.

## Une famille qui échoue n'emporte pas les autres

Cinq détecteurs indépendants : si l'un lève sur une forme de profil inattendue,
les quatre autres doivent quand même rendre leur verdict. Un agent qui ne
signale rien parce qu'un détecteur sur cinq a trébuché est pire qu'un agent
partiellement aveugle — il est **silencieusement** aveugle. L'échec est
journalisé, pas avalé.

Ajout prévu en 4.4 : un dernier filtre avant de sortir. Si la *signature* d'un
écart a déjà été refusée par un humain, il est journalisé mais pas soumis.
"""

from agent.detect import (
    contrat,
    dbt,
    inventaire,
    schema,
    semantique,
    silence,
    statistique,
)
from agent.incidents import signature, texte
from agent.state import AgentState, log_entry

# L'ordre compte pour la lecture (cf. l'en-tête), pas pour le calcul : les
# familles sont indépendantes et ne se transmettent rien.
FAMILLES = (
    ("inventaire", inventaire.detecter),
    ("schema", schema.detecter),
    ("contrat", contrat.detecter),
    ("statistique", statistique.detecter),
    ("semantique", semantique.detecter),
    # En dernier, et à part : `dbt` ne détecte rien, elle traduit des verdicts
    # déjà rendus. La lire après les cinq autres met le constat de l'agent avant
    # celui d'un outil tiers — c'est l'ordre dans lequel un humain veut lire.
    ("dbt", dbt.detecter),
)


def detect(state: AgentState) -> dict:
    anomalies: list[dict] = []
    echecs: list[str] = []

    for nom, detecter in FAMILLES:
        try:
            anomalies += detecter(state)
        except Exception as exc:  # noqa: BLE001 — voir l'en-tête : on isole
            echecs.append(f"{nom}: {type(exc).__name__}: {exc}")

    # Le filtre de silence (4.4) : ce qu'un humain a déjà refusé n'est pas
    # resoumis. L'écart reste **constaté et journalisé** — il n'est simplement
    # pas porté à décision. Sans les deux listes, le garde-fou anti-cécité
    # deviendrait un vœu pieux : on ne saurait plus ce qu'on ne dit plus.
    retenus, tus = silence.filtrer(anomalies, state.get("past_incidents"))

    journal = log_entry(
        "detect",
        f"{len(retenus)} écart(s) constaté(s)"
        + (f", {len(tus)} tu(s) par décision passée" if tus else ""),
        table=state["table"],
        batch_id=state["batch_id"],
        par_famille=_compter(retenus),
    )
    if tus:
        journal["signatures_tues"] = [texte(signature(a)) for a in tus]
    if echecs:
        # Un détecteur en panne est une information, pas un détail
        # d'implémentation : sans cette trace, l'agent paraîtrait avoir
        # regardé là où il n'a rien vu.
        journal["familles_en_echec"] = echecs

    return {"anomalies": retenus, "logs": [journal]}


def _compter(anomalies: list) -> dict:
    """Combien d'écarts par famille — le résumé que lira `INCIDENTS`."""
    compte: dict = {}
    for a in anomalies:
        compte[a["famille"]] = compte.get(a["famille"], 0) + 1
    return compte
