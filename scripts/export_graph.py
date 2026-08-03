"""Exporte le diagramme du graphe (phase 3.1).

Usage :
    uv run python -m scripts.export_graph

Produit deux fichiers dans `docs/img/` :

  - `agent_graph.mmd` — la source Mermaid, **hors ligne**. C'est la version de
    référence : GitHub la rend nativement dans un README, elle se lit dans un
    éditeur, et un `git diff` montre exactement ce qui a changé dans le câblage.
  - `agent_graph.png` — l'image, pour le rapport et les diapos de soutenance.
    Son rendu passe par le service **mermaid.ink**, donc par le réseau : si
    l'accès est coupé, le `.mmd` est quand même écrit et le script le dit.

**Pourquoi un script plutôt qu'une génération faite une fois à la main.** Le
diagramme est extrait du graphe compilé : il ne peut pas mentir *au moment où on
le génère*. Mais il vieillit dès que le câblage change. Un fichier régénérable
d'une commande se remet à jour ; une image produite une fois et oubliée devient
exactement ce qu'on a passé une séance à corriger dans `README.md` et
`CAHIER_DES_CHARGES.md` — une documentation qui décrit un agent qui n'existe plus.

À relancer donc après toute modification de `agent/graph.py`.
"""

import sys
from pathlib import Path

from agent.graph import build_agent

DESTINATION = Path(__file__).resolve().parent.parent / "docs" / "img"


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    graphe = build_agent().get_graph()

    mmd = DESTINATION / "agent_graph.mmd"
    mmd.write_text(graphe.draw_mermaid(), encoding="utf-8")
    print(f"✅ {mmd.relative_to(DESTINATION.parent.parent)}")

    png = DESTINATION / "agent_graph.png"
    try:
        png.write_bytes(graphe.draw_mermaid_png())
    except Exception as exc:  # noqa: BLE001 — le rendu distant peut échouer
        # Pas un échec du script : le `.mmd` est écrit, et c'est lui la référence.
        print(
            f"⚠️  {png.name} non généré ({type(exc).__name__}) — rendu distant indisponible"
        )
        print("   Le .mmd suffit : GitHub le rend nativement dans un README.")
        return 0

    print(
        f"✅ {png.relative_to(DESTINATION.parent.parent)} ({png.stat().st_size // 1024} Ko)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
