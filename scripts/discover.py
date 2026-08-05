"""Cycle Découverte : profiler une base, en proposer les contrats (phase 4.2.5).

Usage (depuis la racine du dépôt, comme `scripts.decide`) :

    uv run python -m scripts.discover olist                    # toutes les tables déclarées
    uv run python -m scripts.discover olist --table RAW.ORDERS # une seule
    uv run python -m scripts.discover olist --list             # où en est chaque contrat
    uv run python -m scripts.discover olist --approve RAW.ORDERS --by hoda

C'est le **cycle A** du projet, celui qui tourne hors du DAG : une fois par
table, puis à la demande. Le cycle B — la surveillance quotidienne, le graphe à
8 nœuds — s'appuiera ensuite sur ce qu'un humain a signé ici.

    introspection ──► profilage ──► caractérisation ──► proposition ⏸ ──► contrat validé
                                                             │                    │
                                                    décision humaine    contracts/<dataset>/…

## La pause est un fichier, pas un `interrupt()`

**Écart au plan assumé.** La roadmap prévoyait le mécanisme d'`interrupt()` de la
phase 3.2. Il a été écarté ici, pour une raison qui n'est pas de commodité.

Un `interrupt()` garde l'état du run dans un checkpoint SQLite. Or ce que
l'humain valide, c'est un **fichier YAML qu'il ouvre et qu'il modifie** — il
ajuste une borne, retire une valeur, ajoute un commentaire. Il y aurait donc
deux copies du contrat : celle du checkpoint et celle du disque. À la reprise,
le graphe écrirait la sienne — et **effacerait les corrections**. C'est le pire
bug possible pour cette étape : silencieux, et il détruit exactement ce que la
validation humaine sert à produire.

Le fichier est donc la seule source de vérité, et la pause est sa présence sur
disque avec `status: proposed`. Elle survit à un redémarrage mieux qu'un
checkpoint, elle se relit dans une pull request, et elle se compare d'une
version à l'autre.

La propriété qui comptait est conservée : **rien n'est appliqué sans décision
humaine**, et c'est `agent/contracts/loader.py` qui l'impose — `charger()` ne
rend jamais un contrat `proposed`.

## Pourquoi la découverte profile la table ENTIÈRE

À rebours de la surveillance, et c'est délibéré.

La surveillance filtre par lot, sans quoi 30 % de nulls sur un jour ne pèsent
plus que 0,3 % noyés dans 92 jours : **la dilution y est l'ennemi**. La
découverte, elle, cherche à savoir ce qui est *normal* — et un contrat bâti sur
une seule journée serait absurdement étroit : les valeurs légitimes absentes ce
jour-là deviendraient des violations dès le lendemain.

Elle a donc besoin de la **fenêtre de référence complète**, et c'est pour ça
qu'elle passe `batch_id` vide. Chez Olist, Bronze porte aujourd'hui les jours 1
à 43, nettoyés par la phase 1.5 : la fenêtre est propre par construction, et le
contrat n'apprendra pas d'anomalie comme normale.
"""

import argparse
import sys

from agent.contracts import (
    APPROUVE,
    PROPOSE,
    ContratInvalide,
    ecrire,
    lister,
    proposer,
)
from agent.contracts.loader import CONTRACTS_DIR, _lire
from agent.registry import charger as charger_registre
from agent.tools import profile_table


def decouvrir(dataset: str, tables=None, dossier=CONTRACTS_DIR) -> list[dict]:
    """Profile, propose, écrit. Rend un compte rendu par table.

    Une table qui échoue n'arrête pas les autres : découvrir dix-sept tables ne
    doit pas mourir sur la troisième. L'échec est **rapporté**, pas avalé — il
    figure dans le compte rendu avec sa cause.
    """
    registre = charger_registre(dataset)
    voulues = tables or [t.name for t in registre.tables]

    comptes_rendus = []
    for table in voulues:
        rendu = {"table": table, "path": None, "warnings": [], "error": None}
        try:
            # `batch_id` vide = toute la table : c'est la fenêtre de référence.
            fiche = profile_table.invoke({"dataset": dataset, "table": table})
            if fiche is None:
                rendu["error"] = "table absente de la base"
            else:
                contrat = proposer(fiche)
                rendu["path"] = ecrire(contrat, dataset, dossier)
                rendu["warnings"] = contrat["warnings"]
                rendu["row_count"] = contrat["source"]["row_count"]
        except Exception as erreur:  # noqa: BLE001 — on rapporte, on ne meurt pas
            rendu["error"] = f"{type(erreur).__name__}: {erreur}"
        comptes_rendus.append(rendu)

    return comptes_rendus


def approuver(
    dataset: str,
    table: str,
    par: str,
    accepter_avertissements: bool = False,
    dossier=CONTRACTS_DIR,
) -> dict:
    """Fait passer un contrat de `proposed` à `approved`. **Relu depuis le disque.**

    Relu, et non repris d'une mémoire quelconque : c'est le fichier que l'humain
    a sous les yeux et qu'il a peut-être modifié qui fait foi. Prendre une autre
    copie effacerait ses corrections.

    Un contrat que la découverte a **critiqué** exige `accepter_avertissements` :
    signer une collision sémantique ou une preuve partielle est une décision, pas
    une formalité, et elle doit être posée les yeux ouverts.

    Re-signer un contrat déjà en vigueur est refusé — mais **pas ici** : c'est
    `ecrire()` qui l'interdit, parce que c'est lui qui touche au disque. Une
    première version de cette fonction refaisait le contrôle en tête ; un
    sabotage l'a retiré sans qu'aucun test ne rougisse, ce qui était le bon
    diagnostic : le contrôle en double ne portait rien, et il donnait l'illusion
    d'une garantie qui vit ailleurs.
    """
    en_attente = [c for c in lister(dataset, dossier) if c["table"] == table]
    if not en_attente:
        raise ContratInvalide(f"Aucun contrat sur disque pour {table!r} ({dataset})")

    # La **dernière** version : une v2 en discussion se signe, pendant que la v1
    # validée continue de gouverner la surveillance jusqu'à ce qu'elle le soit.
    dernier = max(en_attente, key=lambda c: c["version"])
    contrat = _lire(dernier["path"])
    if contrat["warnings"] and not accepter_avertissements:
        raise ContratInvalide(
            f"{dernier['path']} : {len(contrat['warnings'])} avertissement(s) — "
            f"relisez-les puis confirmez avec --accept-warnings"
        )

    # Qui a signé : la même traçabilité que `decided_by` dans le cycle de
    # surveillance. Un contrat sans signataire ne prouve rien six mois plus tard.
    contrat["status"] = APPROUVE
    contrat["approved_by"] = par
    ecrire(contrat, dataset, dossier)
    return contrat


# ---------------------------------------------------------------------------
# Affichage — ce que l'humain doit avoir sous les yeux
# ---------------------------------------------------------------------------


def afficher_decouverte(comptes_rendus: list[dict]) -> None:
    for rendu in comptes_rendus:
        if rendu["error"]:
            print(f"\n  ✗ {rendu['table']} — {rendu['error']}")
            continue

        print(f"\n  ✓ {rendu['table']}  ({rendu.get('row_count', 0)} lignes observées)")
        print(f"    → {rendu['path']}")
        # Les avertissements passent en premier et en toutes lettres : c'est ce
        # que la découverte a **refusé de graver**, donc ce qui demande une
        # décision. Les enfouir sous le reste reviendrait à les cacher.
        for alerte in rendu["warnings"]:
            print(f"    ⚠  {alerte['column']} [{alerte['kind']}] {alerte['detail']}")


def afficher_etat(dataset: str, dossier=CONTRACTS_DIR) -> None:
    contrats = lister(dataset, dossier)
    if not contrats:
        print(f"Aucun contrat sur disque pour {dataset!r}.")
        return

    for contrat in contrats:
        marque = "✅" if contrat["status"] == APPROUVE else "⏸ "
        print(f"  {marque} {contrat['table']}  v{contrat['version']}  {contrat['status']}")

    attente = [c for c in contrats if c["status"] == PROPOSE]
    if attente:
        print(f"\n{len(attente)} contrat(s) en attente de validation.")
        print("Relisez le fichier, ajustez les bornes, puis :")
        print(f"  uv run python -m scripts.discover {dataset} --approve <TABLE> --by <nom>")


def main() -> int:
    parseur = argparse.ArgumentParser(
        description="Cycle Découverte : profiler une base et en proposer les contrats"
    )
    parseur.add_argument("dataset", help="nom d'un registre `datasets/<nom>.yaml`")
    parseur.add_argument("--table", help="ne découvrir que cette table")
    parseur.add_argument("--list", action="store_true", help="où en est chaque contrat")
    parseur.add_argument("--approve", metavar="TABLE", help="valider le contrat d'une table")
    parseur.add_argument("--by", default="", help="qui signe (obligatoire pour --approve)")
    parseur.add_argument(
        "--accept-warnings",
        action="store_true",
        help="signer un contrat que la découverte a critiqué",
    )
    args = parseur.parse_args()

    if args.list:
        afficher_etat(args.dataset)
        return 0

    if args.approve:
        if not args.by:
            print("✗ --approve exige --by : un contrat sans signataire ne prouve rien.")
            return 1
        try:
            contrat = approuver(
                args.dataset, args.approve, args.by, args.accept_warnings
            )
        except ContratInvalide as erreur:
            print(f"✗ {erreur}")
            return 1
        print(f"✅ {contrat['table']} v{contrat['version']} validé par {args.by}")
        return 0

    tables = [args.table] if args.table else None
    comptes_rendus = decouvrir(args.dataset, tables)
    afficher_decouverte(comptes_rendus)

    echecs = [r for r in comptes_rendus if r["error"]]
    alertes = sum(len(r["warnings"]) for r in comptes_rendus)
    print(
        f"\n{len(comptes_rendus) - len(echecs)} contrat(s) proposé(s), "
        f"{alertes} avertissement(s), {len(echecs)} échec(s)."
    )
    print("Rien n'est appliqué tant qu'un humain n'a pas signé :")
    print(f"  uv run python -m scripts.discover {args.dataset} --list")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
