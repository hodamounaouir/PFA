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

from agent.graph import CHECKPOINT_DB, propositions_en_attente
from agent.hitl import (
    CORRECTION_SANS_APPROBATION,
    proposition,
    questionner,
    trancher,
)
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
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
    parser.add_argument(
        "thread_id",
        nargs="?",
        help="identifiant du run en pause (omis avec --list)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="lister",
        help="la file des propositions en attente, tous runs confondus",
    )
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

    # ⭐ La file d'attente (5.1). Sans elle, un run mis en pause par Airflow à
    # 3 h du matin n'existe pour personne : il faut déjà connaître son
    # `thread_id` pour le retrouver, donc savoir qu'il existe.
    if args.lister:
        return _lister(args.db)

    if not args.thread_id:
        parser.error("thread_id est requis (ou utilisez --list)")

    # ⭐ Toute la reprise passe par `agent/hitl.py` — la **voie unique**, celle
    # que les boutons Streamlit emprunteront aussi (phase 6). Une seconde voie
    # serait une seconde façon de contourner P3 : la garantie « aucun chemin
    # n'atteint `apply` sans approbation » ne vaudrait plus que pour les chemins
    # qu'on a testés.
    proposal = proposition(args.thread_id, args.db)
    if proposal is None:
        print(f"❌ Aucune proposition en attente pour le thread {args.thread_id!r}")
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

        reponse = questionner(args.thread_id, args.question, args.decided_by, args.db)
        if not reponse["ok"]:
            print(f"⚠️  {reponse['erreur']}")
            return 1

        print(f"\n  Agent │ {reponse['reponse']}\n")
        print(f"  ({reponse['questions_restantes']} question(s) restante(s))")
        print(f"  → uv run python -m scripts.decide {args.thread_id} approve\n")
        return 0

    resultat = trancher(
        args.thread_id,
        VERBES[args.decision],
        par=args.decided_by,
        fix_override=args.fix_override,
        db=args.db,
    )
    if not resultat["ok"]:
        print(f"❌ {resultat['erreur']}")
        # Le module partagé **nomme** la situation ; c'est à l'interface de la
        # traduire dans son vocabulaire. `--fix` n'existe qu'ici — Streamlit,
        # lui, désactivera un bouton.
        if resultat.get("code") == CORRECTION_SANS_APPROBATION:
            print("   (--fix ne s'utilise qu'avec 'approve')")
        return 1

    if resultat["en_attente"]:
        print("⏸  Le run s'est de nouveau interrompu (autre proposition en attente)")
        return 0

    print(f"✅ Décision {resultat['decision']!r} enregistrée")
    print(f"   Parcours : {' → '.join(resultat['parcours'])}")
    if resultat["applied_fix"]:
        print(f"   Appliqué : {resultat['applied_fix']}")
    if resultat["contract_version"]:
        print(f"   Contrat  : version {resultat['contract_version']}")
    return 0


def _lister(db) -> int:
    """La file des propositions en attente — ce que Streamlit montrera en 6."""
    attente = propositions_en_attente(db)
    if not attente:
        print("Aucune proposition en attente.")
        return 0

    for p in attente:
        print(f"⏸  {p['thread_id']}")
        print(f"     {p['table']} · lot {p['batch_id']} · {p['anomalies']} écart(s)")
        if p["resume"]:
            # L'impact d'abord : c'est ce qui permet de choisir **laquelle**
            # traiter en premier quand il y en a dix.
            print(f"     impact : {p['resume']}")
    print(f"\n{len(attente)} proposition(s) en attente de décision.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
