"""Archive le résultat des tests dbt (baseline) — livrable de la phase 2.3.

Confronte les tests dbt (Silver + Gold) du jour rejoué à ground_truth.yaml et
écrit/complète benchmarks/baseline_run.json (une entrée par jour). C'est la trace
figée de ce que la baseline « dbt tests, sans agent » détecte — et de ce qu'elle
rate structurellement : le fan-out sémantique São Paulo.

Appelé par Airflow en fin de DAG :
    python -m benchmarks.archive_baseline --day 2018-04-14

Les résultats dbt sont lus dans dbt/target/silver/ et dbt/target/gold/ : le DAG
lance chaque `dbt test` avec un --target-path dédié pour ne pas les écraser
(sinon le `dbt run` gold suivant écraserait le run_results.json du test silver).
"""

import argparse
import json
from datetime import date
from pathlib import Path

import yaml

from data import config

ROOT = config.DATA_DIR.parent
BASELINE_JSON = ROOT / "benchmarks" / "baseline_run.json"
GROUND_TRUTH = config.DATA_DIR / "ground_truth.yaml"
RUN_RESULTS = {
    "silver": ROOT / "dbt" / "target" / "silver" / "run_results.json",
    "gold": ROOT / "dbt" / "target" / "gold" / "run_results.json",
}


def read_tests(path: Path) -> list[dict]:
    """Extrait les tests (nom, statut, nb d'échecs) d'un run_results.json dbt."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    tests = []
    for r in payload.get("results", []):
        uid = r.get("unique_id", "")
        if not uid.startswith("test."):
            continue
        tests.append(
            {
                "name": uid.rsplit(".", 1)[0],  # retire le hash final du unique_id
                "status": r.get("status"),      # pass | fail | error | skipped
                "failures": r.get("failures"),
            }
        )
    return tests


def expected_anomalies(day: date) -> list[str]:
    """Ids des anomalies injectées prévues ce jour (le cas réel sémantique n'a pas de date)."""
    spec = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))
    return [
        a["id"]
        for a in spec.get("anomalies", [])
        if "date" in a and date.fromisoformat(str(a["date"])) == day
    ]


def build_entry(day: date) -> dict:
    silver = read_tests(RUN_RESULTS["silver"])
    gold = read_tests(RUN_RESULTS["gold"])
    failed = [t["name"] for t in silver + gold if t["status"] in ("fail", "error")]
    return {
        "expected_anomalies": expected_anomalies(day),
        "silver_tests": silver,
        "gold_tests": gold,
        "failed_tests": failed,
        "baseline_detected": bool(failed),
        # La baseline est structurellement aveugle au fan-out sémantique São Paulo
        # (villes laissées brutes en Silver) : c'est ce que l'agent devra rattraper.
        "semantic_sao_paulo_missed": True,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Archive le résultat baseline dbt du jour")
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)

    archive = {}
    if BASELINE_JSON.exists():
        archive = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))

    archive[args.day.isoformat()] = build_entry(args.day)

    BASELINE_JSON.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_JSON.write_text(
        json.dumps(dict(sorted(archive.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    entry = archive[args.day.isoformat()]
    print(
        f"🗃️  {args.day} archivé → {BASELINE_JSON.name}  "
        f"(attendu={entry['expected_anomalies']}, "
        f"détecté={entry['baseline_detected']}, échecs={entry['failed_tests']})"
    )


if __name__ == "__main__":
    main()
