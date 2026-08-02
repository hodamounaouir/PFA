"""Assemblage du graphe LangGraph (phase 3.1).

Les huit nœuds existent déjà et sont testés isolément. Ce fichier n'ajoute
aucune logique métier : il **câble**, et le câblage est lui-même une garantie.

    START ─► profile ─► detect ──(rien d'anormal)──────────────► log ─► END
                          │ (des écarts)
                          ▼
                      diagnose
                          │
                          ▼
                      propose  ⏸ décision humaine (interrupt, étape 3.2)
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

Deux propriétés se lisent directement sur ce dessin, et c'est tout l'intérêt de
les avoir mises dans la **topologie** plutôt que dans du code défensif :

  - `apply` n'a qu'une seule arête entrante, et elle vient de `propose` par la
    branche `approved` (test de preuve P3, étape 3.4) ;
  - `log` est le seul nœud relié à END : aucun run ne peut se terminer sans
    laisser de trace (test « sortie unique », étape 3.4).

Les nœuds restent des stubs jusqu'à la phase 4 — ce qu'on valide ici, c'est la
tuyauterie, pas l'intelligence.
"""

from langgraph.graph import END, START, StateGraph

from agent.nodes import amend, apply, detect, diagnose, log, profile, propose, validate
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
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

    # Aiguillage 2 — les trois issues de la décision humaine, plus le cas « pas
    # de décision ». Les deux dernières aboutissent au même nœud sans se
    # confondre dans le code : `route_after_propose` distingue « l'humain a dit
    # non » de « personne n'a répondu », et chacune est testable par son nom.
    # (Le diagramme exporté, lui, n'en montre qu'une : LangGraph fusionne les
    # arêtes de même origine et même destination, et ne garde que le premier
    # libellé. Perte acceptable — c'est le graphe exécuté qui fait foi.)
    builder.add_conditional_edges(
        "propose",
        route_after_propose,
        {
            DECISION_APPROVED: "apply",
            DECISION_AMEND: "amend",
            DECISION_REJECTED: "log",
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

    `checkpointer` reste à None en phase 3.1 : le graphe traverse alors ses
    quatre chemins d'une traite, ce qui suffit à les tester. À l'étape 3.2 on
    passera un `SqliteSaver` — c'est lui qui rend `interrupt()` possible, en
    persistant l'état pendant que le graphe attend une décision humaine qui peut
    arriver des jours plus tard, depuis un autre process.
    """
    return build_graph().compile(checkpointer=checkpointer)
