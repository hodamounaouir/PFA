"""Vérifie tous les accès externes du projet en une exécution (phase 0.2).

Usage : uv run python scripts/check_access.py
Sortie : ✅/❌ par service ; code retour 0 seulement si tout est vert.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ce script est le seul du projet qu'on lance par son chemin
# (`python scripts/check_access.py`) et non en `-m scripts.…` : c'est la
# commande écrite dans le README, dans CONTRIBUTING et dans la Definition of
# Done de la phase 0 — un tiers qui clone le repo tape celle-là. Lancé ainsi,
# Python met `scripts/` sur le chemin d'import et non la racine, donc
# `import agent` échoue. On ajoute la racine plutôt que de changer une commande
# que la documentation promet.
sys.path.insert(0, str(PROJECT_ROOT))


def check_snowflake() -> str:
    import snowflake.connector

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        login_timeout=15,
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_VERSION(), CURRENT_DATABASE()")
        version, database = cur.fetchone()
        return f"Snowflake {version}, base {database}"
    finally:
        conn.close()


def check_groq() -> str:
    from groq import Groq

    # Le nom du modèle est importé, pas recopié : le 2026-08-17, Groq a
    # décommissionné `llama-3.3-70b-versatile` et ce script testait encore le
    # modèle mort après correction de `agent/llm.py`. Un contrôle d'accès qui
    # valide autre chose que ce que le code appelle ne contrôle rien.
    from agent.llm import MODELE

    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=30)
    reply = client.chat.completions.create(
        model=MODELE,
        messages=[{"role": "user", "content": "Réponds uniquement : OK"}],
        # `gpt-oss-120b` est un modèle de **raisonnement** : il dépense des
        # tokens dans un champ `reasoning` séparé avant d'écrire sa réponse.
        # Les 5 tokens qui suffisaient à Llama partaient entièrement dans la
        # réflexion, et `content` revenait **vide** (`finish_reason="length"`).
        max_tokens=100,
    )
    contenu = (reply.choices[0].message.content or "").strip()

    # On vérifie ce qui est revenu, au lieu de se contenter de « aucune
    # exception ». Sans cette ligne le contrôle affichait ✅ sur une réponse
    # vide : un contrôle qui ne peut pas échouer ne prouve rien — c'est la même
    # règle que la vérification par mutation appliquée à la suite de tests.
    if contenu != "OK":
        raise AssertionError(
            f"réponse inattendue {contenu!r} "
            f"(finish_reason={reply.choices[0].finish_reason})"
        )
    return f"LLM répond : {contenu!r} ({MODELE})"


def check_olist() -> str:
    folder = PROJECT_ROOT / "data" / "olist"
    csvs = sorted(folder.glob("*.csv"))
    if len(csvs) < 9:
        raise RuntimeError(f"{len(csvs)}/9 fichiers CSV dans {folder}")
    return f"{len(csvs)} fichiers CSV dans data/olist/"


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    checks = [
        ("Snowflake", check_snowflake),
        ("LLM Groq", check_groq),
        ("Dataset Olist", check_olist),
    ]
    failures = 0
    for name, check in checks:
        try:
            detail = check()
            print(f"✅ {name:<14} {detail}")
        except Exception as exc:  # noqa: BLE001 — on veut un bilan, pas un crash
            failures += 1
            print(f"❌ {name:<14} {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"❌ {failures} service(s) en échec")
    else:
        print("🎉 Tous les accès sont opérationnels")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
