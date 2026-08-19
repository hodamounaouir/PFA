"""Exporte la documentation lisible des contrats de données (phase 4.2).

Usage :
    uv run python -m scripts.export_contracts_doc [dataset]

Produit `docs/CONTRATS.md` : une fiche par table déclarée dans le registre,
décrivant ce que le contrat exige et ce que la découverte a refusé d'exiger.

**Pourquoi un script plutôt qu'un fichier écrit à la main.** Même raison qu'en
3.1 pour le diagramme du graphe, et elle est ici plus forte encore : un contrat
n'est pas un objet stable. Les 17 fichiers sont aujourd'hui en `proposed` ; ils
passeront en `approved` à la signature, puis en `v2` au premier amendement
(phase 5). Une fiche recopiée à la main serait fausse **dès la première
signature** — et une documentation fausse sur le statut d'un contrat est pire
que pas de documentation, puisqu'elle dit qu'une règle s'applique alors qu'elle
attend encore une décision humaine.

**Rien ici ne connaît Olist.** Le script lit le registre et les contrats ; les
phrases de rôle se déduisent de la couche déclarée et des rôles de colonnes.
Brancher un second dataset et régénérer sa documentation ne demande donc aucune
ligne de code — c'est la même promesse que celle de `agent/`, appliquée à
l'outillage.

À relancer après toute découverte, signature ou amendement.
"""

import sys
from pathlib import Path

from agent.contracts import loader
from agent.registry import charger as charger_registre

RACINE = Path(__file__).resolve().parent.parent
DESTINATION = RACINE / "docs" / "CONTRATS.md"

# Au-delà, l'énumération part dans un bloc repliable : une fiche doit rester
# lisible, et 73 catégories produit noieraient les quatre autres clauses.
VALEURS_INLINE_MAX = 12

COUCHES = {
    "bronze": "**Bronze** — données brutes ingérées telles quelles. Tout y est "
    "`VARCHAR` par construction : les bornes `min`/`max` du profil y sont "
    "lexicographiques, pas numériques.",
    "silver": "**Silver** — typé et nettoyé par dbt. Les doublons y survivent "
    "volontairement, pour que les tests baseline puissent les constater.",
    "gold": "**Gold** — agrégat métier, reconstruit en entier à chaque run. "
    "Pas de notion de lot : le profilage porte sur toute la table.",
}

# Le rôle qualifie toujours *une colonne* : accord au féminin, et pluriel pour
# la ligne de composition. Un tableau qui affiche « 3 catégoriel » se lit comme
# une sortie de machine, pas comme une fiche qu'on relit avant de signer.
ROLES_FR = {
    "identifier": ("identifiant", "identifiants"),
    "foreign_key": ("clé étrangère", "clés étrangères"),
    "categorical": ("catégorielle", "catégorielles"),
    "numeric": ("numérique", "numériques"),
    "temporal": ("temporelle", "temporelles"),
    "free_text": ("texte libre", "textes libres"),
    "unknown": ("indéterminée", "indéterminées"),
}


def _role_fr(role: str, nombre: int = 1) -> str:
    singulier, pluriel = ROLES_FR.get(role, (role, role))
    return pluriel if nombre > 1 else singulier


CLAUSES_FR = {
    "unique": "unicité",
    "not_null": "non nul",
    "between": "bornes",
    "accepted_values": "valeurs admises",
    "no_semantic_collisions": "pas de collision sémantique",
}

STATUTS = {"proposed": "⏸ en attente de signature", "approved": "✅ validé"}


def _nombre(valeur) -> str:
    """Un nombre lisible : `1 000 163` plutôt que `1000163`."""
    if isinstance(valeur, float) and valeur == int(valeur):
        valeur = int(valeur)
    if isinstance(valeur, int):
        return f"{valeur:,}".replace(",", " ")
    return str(valeur)


def _valeurs(liste: list) -> str:
    """Une énumération, repliée quand elle est longue."""
    rendus = [f"`{v}`" for v in liste]
    if len(rendus) <= VALEURS_INLINE_MAX:
        return ", ".join(rendus)
    # ⚠️ Tout sur **une seule ligne**, sans ligne vide : ces énumérations vivent
    # dans une cellule de tableau, et une ligne vide y interromprait le tableau
    # — le reste des colonnes serait rendu en texte brut par GitHub.
    return (
        f"<details><summary>{len(rendus)} valeurs</summary>"
        + ", ".join(rendus)
        + "</details>"
    )


def _ancre(nom: str) -> str:
    """L'ancre GitHub du titre d'une fiche : `### RAW.ORDER_ITEMS` -> `raworder_items`.

    GitHub met en minuscules et retire la ponctuation, **mais conserve les
    underscores**. Les retirer aussi produirait des liens de sommaire qui ne
    pointent nulle part — cassés en silence, puisqu'une ancre morte ne fait
    qu'ignorer le clic.
    """
    return nom.lower().replace(".", "")


def _clauses(regles: dict) -> str:
    """Les clauses d'une colonne, en une cellule de tableau."""
    morceaux = []
    if regles.get("unique"):
        morceaux.append("🔑 `unique`")
    if regles.get("not_null"):
        morceaux.append("`not_null`")
    if regles.get("between"):
        bas, haut = regles["between"]
        morceaux.append(f"`between` [{_nombre(bas)} … {_nombre(haut)}]")
    if regles.get("no_semantic_collisions"):
        morceaux.append("`no_semantic_collisions`")
    if regles.get("accepted_values"):
        morceaux.append(f"`accepted_values` : {_valeurs(regles['accepted_values'])}")
    return " · ".join(morceaux) or "—"


def _role_principal(contrat: dict, declaree) -> str:
    """La phrase de rôle : couche déclarée + grain + composition.

    Déduite, jamais écrite à la main — sinon elle vaudrait pour Olist seulement,
    et il faudrait la réécrire pour chaque dataset branché.
    """
    couche = COUCHES.get(
        getattr(declaree, "layer", ""), "Couche non déclarée au registre."
    )

    cles = [c for c, r in contrat["columns"].items() if r.get("unique")]
    if len(cles) == 1:
        grain = f"Grain : une ligne par `{cles[0]}`."
    elif cles:
        grain = "Grain : " + ", ".join(f"`{c}`" for c in cles) + " (plusieurs clés)."
    else:
        grain = "Grain : aucune colonne ne s'est révélée unique sur la référence."

    comptes = {}
    for regles in contrat["columns"].values():
        brut = regles.get("role")
        comptes[brut] = comptes.get(brut, 0) + 1
    composition = ", ".join(
        f"{n} {_role_fr(role, n)}"
        for role, n in sorted(comptes.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return f"{couche}\n\n{grain} Composition : {composition}."


def _fiche(contrat: dict, declaree, chemin: Path) -> str:
    colonnes = contrat["columns"]
    cles = [c for c, r in colonnes.items() if r.get("unique")]
    avertissements = contrat.get("warnings") or []

    lot = getattr(declaree, "batch_column", None)
    perimetre = (
        "table entière (le cycle Découverte cherche ce qui est *normal* : un "
        "contrat bâti sur une seule journée serait absurdement étroit)"
        if contrat["source"].get("batch_id") is None
        else f"lot `{contrat['source']['batch_id']}`"
    )

    lignes = [
        f"### {contrat['table']}",
        "",
        f"`{chemin.name}` · version {contrat['version']} · "
        f"{STATUTS.get(contrat['status'], contrat['status'])}",
        "",
        "**1 · Rôle principal**",
        "",
        _role_principal(contrat, declaree),
        "",
        "**2 · Volume de référence**",
        "",
        f"- **{len(colonnes)} colonnes** · **{_nombre(contrat['source']['row_count'])} "
        f"lignes** observées",
        f"- Colonne de lot : {f'`{lot}`' if lot else '*aucune* (agrégat)'}",
        f"- Périmètre du profil : {perimetre}",
        "",
        "**3 · Clés primaires identifiées**",
        "",
    ]

    if cles:
        lignes += [
            "".join(f"- 🔑 `{c}` — `unique: true` + `not_null: true`\n" for c in cles)
        ]
    else:
        lignes += [
            "*Aucune.* Une clause d'unicité n'est proposée que si la colonne "
            "s'est révélée quasi unique **et** sans nul sur la fenêtre de "
            "référence.\n"
        ]

    lignes += [
        "**4 · Règles appliquées**",
        "",
        "| Colonne | Rôle | Clauses |",
        "|---|---|---|",
    ]
    for nom, regles in colonnes.items():
        lignes.append(
            f"| `{nom}` | {_role_fr(regles.get('role'))} | {_clauses(regles)} |"
        )
    lignes.append("")

    lignes += ["**5 · Avertissements et limites**", ""]
    if avertissements:
        for a in avertissements:
            lignes.append(f"- ⚠️ **`{a['column']}`** — {a['detail']} *({a['kind']})*")
        lignes.append(
            "\n> Une clause `accepted_values` a été **retirée** sur ces colonnes : "
            "les valeurs relevées ne couvrent pas toutes les lignes, donc les "
            "valeurs légitimes absentes de la liste deviendraient des violations "
            "dès le lendemain. *Un avertissement se survole ; une clause absente "
            "ne peut pas être approuvée par distraction.*"
        )
    else:
        lignes.append(
            "*Aucun.* Toutes les clauses proposées reposent sur une preuve complète."
        )
    lignes.append("")
    return "\n".join(lignes)


def construire(dataset: str) -> str:
    registre = charger_registre(dataset)
    inventaire = loader.lister(dataset)
    if not inventaire:
        raise SystemExit(
            f"Aucun contrat pour {dataset!r}. Lancer d'abord :\n"
            f"  uv run python -m scripts.discover {dataset}"
        )

    # La dernière version de chaque table : c'est elle qui fait foi.
    derniers = {}
    for entree in inventaire:
        derniers[entree["table"]] = entree

    # `_lire` plutôt que `charger()` : ce dernier ne rend **que du validé** (la
    # garantie de 4.2.4), or une documentation doit précisément pouvoir décrire
    # ce qui attend une signature. On passe quand même par le module du format,
    # jamais par un `yaml.safe_load` local : le contrôle nom-de-fichier ↔ contenu
    # vit là et ne doit pas être contourné. À promouvoir en API publique quand
    # l'écran « Contrats » de la phase 6 en aura besoin lui aussi.
    contrats = {t: loader._lire(e["path"]) for t, e in derniers.items()}

    total_avert = sum(len(c.get("warnings") or []) for c in contrats.values())
    total_col = sum(len(c["columns"]) for c in contrats.values())

    out = [
        f"# Contrats de données — dataset `{dataset}`",
        "",
        "> ⚠️ **Fichier généré — ne pas éditer à la main.**",
        "> `uv run python -m scripts.export_contracts_doc"
        + (f" {dataset}" if dataset != "olist" else "")
        + "`",
        f"> Sources : `contracts/{dataset}/*.yaml` + `datasets/{dataset}.yaml`",
        "",
        "## À quoi sert un contrat",
        "",
        "Le contrat est le **3ᵉ pilier de détection**, à côté du z-score "
        "statistique et des tests dbt. Il dit ce qui *devrait* être vrai d'une "
        "table ; `detect` (phase 4.3) confronte chaque lot à ses clauses.",
        "",
        "Il est produit par le **cycle Découverte** — qui profile, classe chaque "
        "colonne par rôle inféré, propose des clauses **et critique sa propre "
        "proposition** — puis validé par un humain. Deux garanties structurelles :",
        "",
        "- `charger()` **ne rend jamais un contrat non signé** : tant qu'une fiche "
        "est ⏸, aucune de ses clauses ne s'applique ;",
        "- écrire n'écrase jamais une décision humaine : un amendement passe par "
        "une version suivante, jamais par une réécriture.",
        "",
        "### Les cinq clauses",
        "",
        "| Clause | Sens |",
        "|---|---|",
        "| `unique` | la colonne identifie une ligne |",
        "| `not_null` | aucune valeur manquante n'est tolérée |",
        "| `between` | la valeur reste dans les bornes observées sur la référence |",
        "| `accepted_values` | la valeur appartient à une liste close |",
        "| `no_semantic_collisions` | deux écritures d'une même valeur ne coexistent pas "
        "(`sao paulo` / `são paulo`) |",
        "",
        "### Vue d'ensemble",
        "",
        "| Table | Couche | Col. | Lignes de réf. | Clés | Clauses | ⚠️ | Statut |",
        "|---|:-:|--:|--:|:-:|--:|:-:|:-:|",
    ]

    for declaree in registre.tables:
        contrat = contrats.get(declaree.name)
        if contrat is None:
            out.append(
                f"| `{declaree.name}` | {declaree.layer} | — | — | — | — | — | "
                f"❌ aucun contrat |"
            )
            continue
        colonnes = contrat["columns"]
        n_cles = sum(1 for r in colonnes.values() if r.get("unique"))
        n_clauses = sum(
            1 for r in colonnes.values() for c in CLAUSES_FR if r.get(c) is not None
        )
        n_avert = len(contrat.get("warnings") or [])
        out.append(
            f"| [`{declaree.name}`](#{_ancre(declaree.name)}) | {declaree.layer} | "
            f"{len(colonnes)} | {_nombre(contrat['source']['row_count'])} | "
            f"{n_cles or '—'} | {n_clauses} | {n_avert or '—'} | "
            f"{STATUTS.get(contrat['status'], contrat['status'])} |"
        )

    out += [
        "",
        f"**Total** : {len(contrats)} contrats · {total_col} colonnes · "
        f"{total_avert} avertissements.",
        "",
        "---",
        "",
        "## Fiches par table",
        "",
    ]

    for declaree in registre.tables:
        contrat = contrats.get(declaree.name)
        if contrat is not None:
            out.append(_fiche(contrat, declaree, derniers[declaree.name]["path"]))
            out.append("---\n")

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    dataset = (argv or sys.argv[1:] or ["olist"])[0]
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(construire(dataset), encoding="utf-8")
    print(f"✅ {DESTINATION.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
