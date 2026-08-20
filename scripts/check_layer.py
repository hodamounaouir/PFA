"""Lance l'agent sur toutes les tables d'une couche (phase 4.5).

Usage :
    uv run python -m scripts.check_layer olist bronze --day 2018-04-29

C'est ce qu'Airflow appelle après chaque couche du DAG (`check_bronze`,
`check_silver`, `check_gold`). Le DAG ne contient donc aucune logique : trois
`BashOperator` de trois lignes, comme les huit tâches qui existaient déjà. Tout
ce qui se raisonne vit ici, et se teste sans Docker ni Airflow.

## ⭐ Une pause n'est pas un échec

C'est le point qui décide si ce script est utilisable. `propose` appelle
`interrupt()` : dès que l'agent trouve quelque chose, le run **s'arrête** en
attendant une décision humaine. Si ce script sortait alors en erreur, le DAG
passerait au rouge **chaque fois que l'agent fait son travail** — et l'équipe
apprendrait en une semaine à ignorer un pipeline rouge, ce qui coûterait bien
plus cher que l'anomalie signalée.

Le code de sortie ne dit donc qu'une chose : *l'agent a-t-il pu tourner ?* Ce
qu'il a trouvé se lit dans `INCIDENTS`, pas dans un code de retour. C'est la même
convention qu'en 2.3 pour les tests dbt (`rc=1` = détection = vert), et pour la
même raison.

    0  toutes les tables ont été examinées (avec ou sans proposition en attente)
    1  au moins une table n'a pas pu l'être — là, il y a vraiment un problème

## Une table qui échoue n'emporte pas les autres

Examiner dix-sept tables ne doit pas mourir sur la troisième. L'échec est
**rapporté avec sa cause** et le balayage continue — même règle qu'en 4.2.5 pour
la découverte, et que dans `detect` pour les familles.

## Le `thread_id` est ce qui rend la pause reprenable

`<dataset>|<table>|<jour>` : stable, lisible, et reconstructible de tête par
l'humain qui veut reprendre un run depuis `scripts/decide.py`. Un identifiant
aléatoire obligerait à le retrouver dans un journal avant de pouvoir décider.
"""

import argparse
import sys
from pathlib import Path

from agent.dbt_results import lire_echecs
from agent.graph import agent_persistant, proposition_en_attente, thread
from agent.registry import charger as charger_registre
from agent.state import new_state

RACINE = Path(__file__).resolve().parent.parent

# Le DAG écrit les résultats de chaque `dbt test` dans un dossier dédié, pour que
# le `dbt run` suivant n'écrase pas le `run_results.json` du précédent (cf.
# `benchmarks/archive_baseline.py`). Bronze n'est pas testé par dbt : c'est une
# source, et rien n'y est encore typé.
RESULTATS_DBT = {
    "silver": RACINE / "dbt" / "target" / "silver",
    "gold": RACINE / "dbt" / "target" / "gold",
}


def identifiant(dataset: str, table: str, jour: str) -> str:
    """Le `thread_id` d'un run — reconstructible de tête."""
    return f"{dataset}|{table}|{jour}"


def echecs_dbt(couche: str, registre) -> list:
    """Les tests dbt en échec pour cette couche, ou une liste vide.

    Vide n'est pas « tout va bien » : c'est « on n'a rien à dire ». Bronze n'a
    pas de tests dbt, et un run où dbt n'a pas produit d'artefact n'apprend rien
    non plus. Les deux cas se ressemblent ici, et c'est sans conséquence — la
    famille `dbt` ne fait que traduire ce qu'on lui donne.
    """
    dossier = RESULTATS_DBT.get(couche)
    if dossier is None:
        return []
    return lire_echecs(
        dossier / "run_results.json", dossier / "manifest.json", registre
    )


def examiner(app, dataset: str, couche: str, table: str, jour: str, echecs) -> dict:
    """Un run d'agent sur une table. Rend ce qu'il faut pour le rapport."""
    etat = new_state(dataset, couche, table, jour)
    # Les échecs qui concernent cette table ; la famille `dbt` refiltrera, mais
    # ne pas charger le reste garde l'état d'un run lisible dans `INCIDENTS`.
    etat["dbt_failures"] = [e for e in echecs if e.get("table") in (None, table)]

    fil = identifiant(dataset, table, jour)
    resultat = app.invoke(etat, thread(fil))
    proposition = proposition_en_attente(resultat)

    return {
        "table": table,
        "thread": fil,
        "anomalies": len(resultat.get("anomalies") or []),
        "en_attente": proposition is not None,
    }


def parcourir(dataset: str, couche: str, jour: str, db) -> tuple[list, list]:
    """`(rapports, echecs)` — le balayage complet d'une couche."""
    registre = charger_registre(dataset)
    tables = registre.tables_de(couche)
    if not tables:
        raise SystemExit(
            f"Aucune table déclarée en couche {couche!r} pour {dataset!r} — "
            f"vérifiez datasets/{dataset}.yaml"
        )

    echecs_du_run = echecs_dbt(couche, registre)
    rapports, ratees = [], []

    # Une seule ouverture du graphe persistant pour toute la couche : c'est la
    # même base de checkpoints pour les dix-sept tables, et l'ouvrir par table
    # multiplierait les connexions SQLite sans rien apporter.
    with agent_persistant(db) as app:
        for declaree in tables:
            try:
                rapports.append(
                    examiner(app, dataset, couche, declaree.name, jour, echecs_du_run)
                )
            except Exception as exc:  # noqa: BLE001 — voir l'en-tête : on continue
                ratees.append(f"{declaree.name} : {type(exc).__name__}: {exc}")
    return rapports, ratees


def rapporter(couche: str, jour: str, rapports: list, ratees: list) -> None:
    for r in rapports:
        marque = "⏸" if r["en_attente"] else "✓"
        detail = f"{r['anomalies']} écart(s)" if r["anomalies"] else "rien à signaler"
        print(f"  {marque} {r['table']:<32} {detail}")
        if r["en_attente"]:
            # L'humain doit pouvoir reprendre sans chercher : on lui donne la
            # commande, pas seulement l'identifiant.
            print(f"      → uv run python -m scripts.decide {r['thread']}")

    for echec in ratees:
        print(f"  ❌ {echec}")

    en_attente = sum(1 for r in rapports if r["en_attente"])
    print(
        f"\n{len(rapports)} table(s) examinée(s) en couche {couche} au {jour} · "
        f"{en_attente} en attente de décision · {len(ratees)} échec(s)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lance l'agent sur toutes les tables d'une couche"
    )
    parser.add_argument("dataset", help="nom d'un registre datasets/<nom>.yaml")
    parser.add_argument("layer", choices=("bronze", "silver", "gold"))
    parser.add_argument(
        "--day", required=True, help="le lot à examiner, ex. 2018-04-29"
    )
    parser.add_argument(
        "--db",
        default=None,
        help="base de checkpoints (défaut : celle d'agent/graph.py). "
        "Doit être la MÊME que celle de scripts/decide.py, sinon la pause "
        "est introuvable depuis l'extérieur.",
    )
    args = parser.parse_args(argv)

    from agent.graph import CHECKPOINT_DB

    rapports, ratees = parcourir(
        args.dataset, args.layer, args.day, args.db or CHECKPOINT_DB
    )
    rapporter(args.layer, args.day, rapports, ratees)

    # ⭐ Seul un échec **d'exécution** fait rougir le DAG. Une proposition en
    # attente est le fonctionnement normal de l'agent, pas une panne.
    return 1 if ratees else 0


if __name__ == "__main__":
    sys.exit(main())
