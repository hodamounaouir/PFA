"""Assemblage du graphe LangGraph (phase 3.1).

Les huit nœuds existent déjà et sont testés isolément. Ce fichier n'ajoute
aucune logique métier : il **câble**, et le câblage est lui-même une garantie.

    START ─► profile ─► detect ──(rien d'anormal)──────────────► log ─► END
                          │ (des écarts)
                          ▼
                   ┌─► diagnose
                   │      │
        (question) │      ▼
                   └── propose  ⏸ décision humaine (interrupt, étape 3.2)
                          │
                 ┌────────┼──────────────────┐
            (approved) (amend_contract)  (rejected / rien)
                 │        │                  │
                 ▼        ▼                  │
               apply    amend                │
                 │        │                  │
                 ▼        │                  │
             validate     │                  │
                 │        │                  │
                 └────────┴──────────────────┴─► log ─► END

La branche `question` est la seule qui **remonte** : l'humain demande à
comprendre, `diagnose` lui répond, et on revient à la proposition — autant de fois
qu'il le faut, dans la limite d'un plafond. Elle ne rapproche en rien de
l'écriture.

Deux propriétés se lisent directement sur ce dessin, et c'est tout l'intérêt de
les avoir mises dans la **topologie** plutôt que dans du code défensif :

  - `apply` n'a qu'une seule arête entrante, et elle vient de `propose` par la
    branche `approved` (test de preuve P3, étape 3.4) — dix questions ne
    l'ouvrent pas davantage qu'une ;
  - `log` est le seul nœud relié à END : aucun run ne peut se terminer sans
    laisser de trace (test « sortie unique », étape 3.4).

Les nœuds restent des stubs jusqu'à la phase 4 — ce qu'on valide ici, c'est la
tuyauterie, pas l'intelligence.
"""

from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent.nodes import amend, apply, detect, diagnose, log, profile, propose, validate
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DEMANDE_QUESTION,
    AgentState,
)

# --- Les deux aiguillages ---------------------------------------------------
# Ce sont les seules décisions de parcours du graphe. Elles sont volontairement
# écrites comme des fonctions pures `AgentState -> str` : testables sans graphe,
# et lisibles d'un coup d'œil — un aiguillage qu'on ne peut pas lire est un
# aiguillage qu'on ne peut pas auditer.
#
# Une fonction d'aiguillage retourne un **nom de branche**, pas un nom de nœud ;
# c'est le `path_map` passé à `add_conditional_edges` qui traduit branche → nœud.
# Les deux pourraient être confondus (« retourner "log" pour aller à `log` »),
# mais les dissocier a deux effets concrets : le nom de branche décrit *pourquoi*
# on prend ce chemin plutôt que *où* il mène, et c'est lui qui étiquette les
# flèches du diagramme exporté (étape 3.1). Deux branches peuvent alors aboutir
# au même nœud pour des raisons différentes — et le dire.

BRANCHE_ANOMALIES = "anomalies"
BRANCHE_RAS = "rien d'anormal"

# Les trois décisions humaines servent telles quelles de noms de branche : le
# diagramme affiche donc le vocabulaire exact qu'emploient `INCIDENTS` et
# `scripts/decide.py`. Une quatrième branche couvre l'absence de décision — la
# confondre avec `rejected` ferait mentir le diagramme, alors que ce sont deux
# situations distinctes (« l'humain a dit non » ≠ « personne n'a répondu »).
BRANCHE_SANS_DECISION = "sans décision"


def route_after_detect(state: AgentState) -> str:
    """Y a-t-il quelque chose à expliquer ?

    Sans écart, on ne dérange ni le LLM ni l'humain — mais on journalise quand
    même. Un run « rien d'anormal » est une information : c'est lui qui prouve,
    en phase 8, que l'agent regardait bien ce jour-là.
    """
    return BRANCHE_ANOMALIES if state["anomalies"] else BRANCHE_RAS


def route_after_propose(state: AgentState) -> str:
    """Qu'a répondu l'humain ?

    Un seul chemin mène à l'écriture des données, et il exige une valeur exacte.
    Tout le reste retombe sur `log` :

      - `rejected` — l'humain a dit non, c'est un cas prévu ;
      - `None` — personne n'a encore répondu. En phase 3.1 c'est le cas normal
        (`propose` n'interrompt pas encore) ; à partir de 3.2 `interrupt()`
        garantit qu'une valeur est présente, et un `None` signalerait alors une
        reprise mal formée ;
      - toute autre valeur — faute de frappe, décision venue d'un client mal
        écrit, valeur inventée par une future UI. Elle est traitée comme une
        absence de décision, ce qu'elle est : on ne devine pas ce que l'humain
        a voulu dire.

    Le défaut est `log`, jamais `apply` : en cas de doute sur la décision, on ne
    touche pas aux données. Un run qui finit à tort en « rien fait » se rattrape ;
    une écriture faite à tort, non.
    """
    decision = state["human_decision"]
    if decision == DECISION_APPROVED:
        return DECISION_APPROVED
    if decision == DECISION_AMEND:
        return DECISION_AMEND
    if decision == DECISION_REJECTED:
        return DECISION_REJECTED
    # `question` n'est pas une décision : elle renvoie à `diagnose` et le cycle
    # recommence. C'est la seule branche du graphe qui **revient en arrière**.
    if decision == DEMANDE_QUESTION:
        return DEMANDE_QUESTION
    return BRANCHE_SANS_DECISION


# --- Le câblage -------------------------------------------------------------


def build_graph() -> StateGraph:
    """Le graphe non compilé — utile pour l'inspecter ou le dessiner."""
    builder = StateGraph(AgentState)

    # Les noms sont donnés explicitement plutôt que déduits de `__name__` : ce
    # sont eux qui apparaîtront dans les checkpoints (3.2), dans le PNG et dans
    # `INCIDENTS` (4.4). Ils ne doivent pas bouger si une fonction est renommée.
    builder.add_node("profile", profile)
    builder.add_node("detect", detect)
    builder.add_node("diagnose", diagnose)
    builder.add_node("propose", propose)
    builder.add_node("apply", apply)
    builder.add_node("amend", amend)
    builder.add_node("validate", validate)
    builder.add_node("log", log)

    # Le tronc commun : tout run mesure avant de juger.
    builder.add_edge(START, "profile")
    builder.add_edge("profile", "detect")

    # Aiguillage 1 — le troisième argument (`path_map`) est la liste **exhaustive**
    # des destinations autorisées. Il ne sert pas qu'à documenter : une fonction
    # d'aiguillage qui retournerait un nom absent de cette liste fait échouer le
    # run au lieu de router n'importe où. C'est aussi ce que lit le générateur de
    # diagramme pour étiqueter les branches.
    builder.add_conditional_edges(
        "detect",
        route_after_detect,
        {BRANCHE_ANOMALIES: "diagnose", BRANCHE_RAS: "log"},
    )

    # `diagnose` n'a qu'une seule sortie : `propose`. C'est structurel — le LLM
    # ne peut rien déclencher directement, il ne peut que soumettre.
    builder.add_edge("diagnose", "propose")

    # Aiguillage 2 — les trois issues de la décision humaine, la demande
    # d'explication, et le cas « pas de décision ».
    #
    # `question` est la seule branche qui **remonte** dans le graphe : l'humain
    # demande à comprendre, `diagnose` lui répond, et on revient ici. Elle ne
    # rapproche en rien de l'écriture — discuter n'est pas approuver, et `apply`
    # garde son unique arête entrante.
    #
    # Renvoyer vers `diagnose` plutôt que répondre sur place n'est pas un détour :
    # c'est ce qui préserve la règle R1 (« le LLM n'est appelé que dans
    # Diagnose »). Si `propose` répondait lui-même, deux nœuds parleraient au
    # modèle, et il y aurait deux endroits à auditer, à simuler et à surveiller.
    #
    # Les deux dernières branches aboutissent au même nœud sans se confondre dans
    # le code : `route_after_propose` distingue « l'humain a dit non » de
    # « personne n'a répondu ». (Le diagramme exporté, lui, n'en montre qu'une :
    # LangGraph fusionne les arêtes de même origine et même destination et ne
    # garde que le premier libellé. Perte acceptable — c'est le graphe exécuté
    # qui fait foi.)
    builder.add_conditional_edges(
        "propose",
        route_after_propose,
        {
            DECISION_APPROVED: "apply",
            DECISION_AMEND: "amend",
            DECISION_REJECTED: "log",
            DEMANDE_QUESTION: "diagnose",
            BRANCHE_SANS_DECISION: "log",
        },
    )

    # Après une écriture, on re-mesure : jamais de correction crue sur parole.
    builder.add_edge("apply", "validate")
    builder.add_edge("validate", "log")

    # `amend` ne touche pas aux données, donc rien à re-mesurer : il n'y a aucune
    # métrique qui aurait changé. Il file droit au journal.
    builder.add_edge("amend", "log")

    # La sortie unique.
    builder.add_edge("log", END)

    return builder


def build_agent(checkpointer=None):
    """Le graphe compilé, prêt à `invoke()`.

    Sans `checkpointer`, le graphe est compilable et inspectable — c'est ce dont
    se servent les tests de topologie — mais il ne peut pas aller **au bout** :
    il s'arrête sur `propose` et n'a nulle part où sauvegarder son état, donc
    aucune décision ne peut le relancer. Pour un run réel, `agent_persistant()`.
    """
    return build_graph().compile(checkpointer=checkpointer)


# --- Persistance : ce qui rend la pause réelle ------------------------------
# Sans elle, `interrupt()` ne serait qu'un `return` déguisé. C'est le
# checkpointer qui transforme « le graphe s'arrête » en « le graphe attend » :
# l'état est écrit sur disque, le process peut mourir, la machine redémarrer.

CHECKPOINT_DB = Path(__file__).resolve().parent.parent / "agent_checkpoints.sqlite"


@contextmanager
def agent_persistant(db=CHECKPOINT_DB):
    """Le graphe avec sa mémoire sur disque — la forme utilisable en vrai.

    Utilisé par `scripts/decide.py`, par les tests de reprise, et plus tard par
    Airflow (4.5) et Streamlit (6). Une seule façon d'ouvrir le graphe persistant,
    donc une seule façon de se tromper de base de checkpoints.

    `db` accepte `":memory:"` pour un run jetable — mais une base en mémoire meurt
    avec le process, ce qui fait perdre l'intérêt de la pause : à n'utiliser que
    pour tester un aller-retour dans un même process.
    """
    with SqliteSaver.from_conn_string(str(db)) as saver:
        yield build_graph().compile(checkpointer=saver)


def thread(thread_id: str) -> dict:
    """La config qui identifie un run.

    Le `thread_id` est ce qui permet de retrouver une proposition en attente
    depuis un autre process — c'est l'identifiant que `scripts/decide.py` reçoit
    en argument, et que Streamlit affichera en phase 6.
    """
    return {"configurable": {"thread_id": thread_id}}


def propositions_en_attente(db=CHECKPOINT_DB) -> list[dict]:
    """Toutes les propositions qui attendent une décision, **hors process** (5.1).

    C'est la file que Streamlit affichera en phase 6, et que `scripts/decide.py
    --list` montre aujourd'hui. Sans elle, un run mis en pause par Airflow à
    3 h du matin n'existe pour personne : il faut déjà connaître son `thread_id`
    pour le retrouver, donc savoir qu'il existe.

    Rend `[{thread_id, table, batch_id, anomalies, resume}]`, du plus ancien au
    plus récent — l'ordre dans lequel on veut traiter une file d'attente.

    ⚠️ **Ces propositions n'ont pas encore de ligne dans `INCIDENTS`** : un run
    en pause n'a pas atteint `log`, qui est sa sortie. La file se lit donc dans
    le **checkpointer seul**, et c'est normal — la jointure avec `INCIDENTS` que
    le plan évoquait vaut pour les runs *terminés*, pas pour ceux qui attendent.

    On passe par l'API du checkpointer (`saver.list`) plutôt que par une requête
    sur sa base : le schéma interne de LangGraph n'est pas un contrat, et du SQL
    ici serait du SQL hors des connecteurs.
    """
    attente = []
    with SqliteSaver.from_conn_string(str(db)) as saver:
        app = build_graph().compile(checkpointer=saver)
        # ⚠️ On **matérialise** la liste avant de la parcourir. `saver.list()`
        # rend un générateur adossé à un curseur SQLite ; interroger la même
        # connexion pendant qu'on le consomme (ce que fait `get_state`) bloque.
        # Le symptôme est une suite de tests qui ne finit jamais, et il ne
        # ressemble pas à sa cause.
        fils = []
        vus = set()
        for enregistrement in list(saver.list(None)):
            fil = enregistrement.config["configurable"]["thread_id"]
            if fil not in vus:
                vus.add(fil)
                fils.append(fil)

        for fil in fils:
            etat = app.get_state(thread(fil))
            propositions = [
                interruption.value
                for tache in etat.tasks
                for interruption in (tache.interrupts or ())
            ]
            if not propositions:
                continue

            proposition = propositions[0]
            attente.append(
                {
                    "thread_id": fil,
                    "table": proposition.get("table"),
                    "batch_id": proposition.get("batch_id"),
                    "anomalies": len(proposition.get("anomalies") or []),
                    "resume": (proposition.get("impact") or {}).get("resume"),
                }
            )
    # Du plus ancien au plus récent : `saver.list` rend l'inverse, et une file
    # d'attente se traite dans l'ordre d'arrivée.
    return sorted(attente, key=lambda p: (p["batch_id"] or "", p["thread_id"]))


def proposition_en_attente(resultat) -> dict | None:
    """La proposition soumise à l'humain, ou None si le run est allé au bout.

    LangGraph signale une interruption par une clé `__interrupt__` dans le
    résultat. On isole cette convention ici plutôt que de la disséminer : le jour
    où elle change, un seul endroit à corriger.
    """
    interruptions = (
        resultat.get("__interrupt__") if isinstance(resultat, dict) else None
    )
    return interruptions[0].value if interruptions else None
