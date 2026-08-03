"""Injecte une décision humaine dans un run en pause (phase 3.2).

Usage (depuis la racine du dépôt, comme `data.replay` et `benchmarks.archive_baseline`) :
    uv run python -m scripts.decide <thread_id>                  # voir la proposition
    uv run python -m scripts.decide <thread_id> ask "pourquoi … ?"   # demander avant
    uv run python -m scripts.decide <thread_id> approve [--by NOM] [--fix SQL]
    uv run python -m scripts.decide <thread_id> amend   [--by NOM]
    uv run python -m scripts.decide <thread_id> reject  [--by NOM]

`ask` ne tranche rien : il diffère. La question part à `diagnose`, la réponse
revient, et la proposition attend de nouveau — autant de fois qu'il le faut. Un
humain à qui on ne laisse que trois boutons approuve vite et mal ; celui qui peut
demander « pourquoi ? » décide en connaissance de cause. Chaque échange est
conservé dans l'état, donc dans le journal, donc dans `INCIDENTS`.

C'est la **seule voie de reprise** du graphe, et elle le restera : les boutons
Streamlit de la phase 6 appelleront exactement le même mécanisme (`Command(resume=…)`
sur le même `thread_id`). Un seul chemin testé plutôt que deux chemins parallèles
dont un seul est vérifié.

Le script tourne dans un **process séparé** de celui qui a lancé le run — c'est
tout l'intérêt : la proposition attend sur disque, on peut répondre le lendemain,
depuis un autre terminal, après un redémarrage de la machine.

Les trois verbes de la ligne de commande (`approve`/`amend`/`reject`) sont plus
courts que les valeurs stockées (`approved`/`amend_contract`/`rejected`) : on tape
au clavier ce qui est commode, on écrit en base ce qui est explicite.
"""

import argparse
import sys

from langgraph.types import Command

from agent.graph import CHECKPOINT_DB, agent_persistant, proposition_en_attente, thread
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DEMANDE_QUESTION,
)

# Les trois verbes qui **tranchent** — ils terminent le run.
VERBES = {
    "approve": DECISION_APPROVED,
    "amend": DECISION_AMEND,
    "reject": DECISION_REJECTED,
}

# `ask` est à part : il ne décide rien, il diffère. Le graphe repart vers
# `diagnose`, revient ici, et attend de nouveau.
VERBE_QUESTION = "ask"


def afficher_proposition(proposal: dict) -> None:
    """Ce que l'humain doit avoir sous les yeux pour décider en connaissance de cause."""
    print(f"\n  Table    : {proposal['table']}  (couche {proposal['layer']})")
    print(f"  Batch    : {proposal['batch_id']}")
    print(f"\n  Constaté : {len(proposal['anomalies'])} écart(s)")
    for anomalie in proposal["anomalies"]:
        print(
            f"    - {anomalie.get('colonne')} : {anomalie.get('type')} "
            f"= {anomalie.get('observe')} (référence {anomalie.get('reference')})"
        )
    print(f"\n  Cause    : {proposal['root_cause']}")
    print(f"  Correction proposée : {proposal['proposed_fix']}")
    # L'impact est la ligne qui permet de juger : « 1 ligne sur 351 » paraît
    # négligeable jusqu'à voir qu'elle déplace un indicateur métier de 54 %.
    print(f"  Impact   : {proposal['impact']}")
    if proposal["past_incidents"]:
        print(
            f"  Antécédents : {len(proposal['past_incidents'])} incident(s) similaire(s)"
        )

    # Le dialogue déjà tenu — c'est ce qui permet de reprendre le fil le
    # lendemain, depuis un autre poste, sans avoir rien à se rappeler.
    if proposal.get("conversation"):
        print("\n  ── Échanges ──")
        for e in proposal["conversation"]:
            qui = "Vous " if e["role"] == "humain" else "Agent"
            print(f"  {qui} │ {e['message']}")

    restantes = proposal.get("questions_restantes")
    print(f"\n  Réponses possibles : {', '.join(VERBES)}")
    if restantes:
        print(
            f"  Ou poser une question : {VERBE_QUESTION} « … »  ({restantes} restantes)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("thread_id", help="identifiant du run en pause")
    parser.add_argument(
        "decision",
        nargs="?",
        choices=sorted([*VERBES, VERBE_QUESTION]),
        help="sans valeur : affiche la proposition",
    )
    parser.add_argument(
        "question",
        nargs="?",
        help=f"la question à poser (avec '{VERBE_QUESTION}')",
    )
    parser.add_argument(
        "--by", dest="decided_by", help="qui décide (tracé dans INCIDENTS)"
    )
    parser.add_argument(
        "--fix",
        dest="fix_override",
        help="ta propre correction, si tu ne veux pas celle proposée",
    )
    parser.add_argument("--db", default=CHECKPOINT_DB, help="base de checkpoints")
    args = parser.parse_args()

    with agent_persistant(args.db) as app:
        config = thread(args.thread_id)

        etat = app.get_state(config)
        if not etat.next:
            print(f"❌ Aucun run en attente pour le thread {args.thread_id!r}")
            return 1

        proposal = (etat.tasks[0].interrupts[0].value) if etat.tasks else None
        if proposal is None:
            print(
                f"❌ Le run {args.thread_id!r} est arrêté, mais pas sur une proposition"
            )
            return 1

        if args.decision is None:
            afficher_proposition(proposal)
            print(f"\n  → uv run python -m scripts.decide {args.thread_id} approve\n")
            return 0

        # --- Poser une question plutôt que trancher -------------------------
        if args.decision == VERBE_QUESTION:
            if not args.question:
                print(
                    f"❌ Il manque la question : "
                    f'... {args.thread_id} {VERBE_QUESTION} "pourquoi … ?"'
                )
                return 1

            resultat = app.invoke(
                Command(
                    resume={
                        "decision": DEMANDE_QUESTION,
                        "question": args.question,
                        "decided_by": args.decided_by,
                    }
                ),
                config,
            )

            suite = proposition_en_attente(resultat)
            if suite is None:
                # Le run s'est terminé au lieu de revenir : plafond d'échanges.
                print(
                    "⚠️  Plafond d'échanges atteint — le run s'est clos sans décision."
                )
                print("   Rien n'a été écrit. Relance un run pour reprendre.")
                return 1

            print(f"\n  Agent │ {suite['conversation'][-1]['message']}\n")
            print(f"  ({suite['questions_restantes']} question(s) restante(s))")
            print(f"  → uv run python -m scripts.decide {args.thread_id} approve\n")
            return 0

        # `fix_override` n'a de sens que sur une approbation : amender un contrat
        # ou refuser n'écrit rien dans les données, donc il n'y a pas de SQL à
        # réécrire. L'accepter silencieusement laisserait croire le contraire.
        if args.fix_override and VERBES[args.decision] != DECISION_APPROVED:
            print("❌ --fix n'a de sens qu'avec 'approve' (les autres n'écrivent rien)")
            return 1

        resultat = app.invoke(
            Command(
                resume={
                    "decision": VERBES[args.decision],
                    "decided_by": args.decided_by,
                    "fix_override": args.fix_override,
                }
            ),
            config,
        )

        if proposition_en_attente(resultat) is not None:
            print(
                "⏸  Le run s'est de nouveau interrompu (autre proposition en attente)"
            )
            return 0

        parcours = " → ".join(entree["node"] for entree in resultat["logs"])
        print(f"✅ Décision {VERBES[args.decision]!r} enregistrée")
        print(f"   Parcours : {parcours}")
        if resultat["applied_fix"]:
            print(f"   Appliqué : {resultat['applied_fix']}")
        if resultat["contract_version"]:
            print(f"   Contrat  : version {resultat['contract_version']}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
