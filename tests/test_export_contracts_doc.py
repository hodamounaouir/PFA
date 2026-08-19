"""Contrôle du générateur de `docs/CONTRATS.md` (phase 4.2).

Aucun de ces tests ne touche à une base ni à un contrat réel : le générateur
transforme des dictionnaires en Markdown, et c'est cette transformation qu'on
éprouve. Les fiches réelles, elles, sont vérifiables à l'œil dans le fichier
produit.

Le test qui compte est `test_une_enumeration_longue_tient_sur_une_seule_ligne` :
il fige un bug déjà commis. Écrit d'abord avec des lignes vides autour du
`<details>`, le générateur produisait un Markdown où **la ligne vide
interrompait le tableau** — GitHub rendait les colonnes suivantes en texte brut.
Invisible dans la sortie du script, visible seulement une fois le fichier lu.
"""

import importlib

import pytest

doc = importlib.import_module("scripts.export_contracts_doc")


# ---------------------------------------------------------------------------
# Les ancres du sommaire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table,attendu",
    [
        ("RAW.ORDERS", "raworders"),
        ("RAW.ORDER_ITEMS", "raworder_items"),
        ("STAGING.STG_ORDER_PAYMENTS", "stagingstg_order_payments"),
        ("MARTS.FCT_GEOLOCATION_BY_CITY", "martsfct_geolocation_by_city"),
    ],
)
def test_l_ancre_garde_les_underscores(table, attendu):
    """GitHub retire la ponctuation mais **conserve** les underscores.

    Les retirer aussi produirait des liens de sommaire morts — cassés en
    silence, puisqu'une ancre qui ne pointe nulle part ne fait qu'ignorer le
    clic. Onze des dix-sept tables portent un underscore.
    """
    assert doc._ancre(table) == attendu


# ---------------------------------------------------------------------------
# Les énumérations dans une cellule de tableau
# ---------------------------------------------------------------------------


def test_une_enumeration_courte_reste_en_clair():
    rendu = doc._valeurs(["approved", "shipped", "delivered"])
    assert rendu == "`approved`, `shipped`, `delivered`"
    assert "<details>" not in rendu


def test_une_enumeration_longue_tient_sur_une_seule_ligne():
    """Le bug figé : une ligne vide dans une cellule **interrompt le tableau**.

    Le rendu doit donc être strictement mono-ligne, `<details>` compris — sans
    quoi les colonnes suivantes de la fiche partent en texte brut chez le
    lecteur, alors que le script, lui, annonce un succès.
    """
    rendu = doc._valeurs([f"v{i}" for i in range(doc.VALEURS_INLINE_MAX + 1)])

    assert "\n" not in rendu, "une énumération repliée doit rester sur une ligne"
    assert rendu.startswith("<details>") and rendu.endswith("</details>")
    assert f"{doc.VALEURS_INLINE_MAX + 1} valeurs" in rendu


def test_la_bascule_se_fait_au_bon_seuil():
    """Les deux côtés de la frontière : sans ça, un `<` mis pour un `<=`
    passerait inaperçu."""
    assert "<details>" not in doc._valeurs(["x"] * doc.VALEURS_INLINE_MAX)
    assert "<details>" in doc._valeurs(["x"] * (doc.VALEURS_INLINE_MAX + 1))


# ---------------------------------------------------------------------------
# Lisibilité : accord et séparateurs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,nombre,attendu",
    [
        ("categorical", 1, "catégorielle"),
        ("categorical", 3, "catégorielles"),
        ("temporal", 2, "temporelles"),
        ("free_text", 2, "textes libres"),
        ("identifier", 1, "identifiant"),
    ],
)
def test_le_role_s_accorde(role, nombre, attendu):
    """« 3 catégoriel » se lit comme une sortie de machine, pas comme une fiche
    qu'un humain relit avant de signer."""
    assert doc._role_fr(role, nombre) == attendu


def test_un_role_inconnu_est_rendu_tel_quel():
    """Ne jamais masquer un rôle qu'on ne connaît pas : le lecteur doit le voir
    plutôt que de lire une case vide."""
    assert doc._role_fr("cinquieme_element") == "cinquieme_element"


@pytest.mark.parametrize(
    "valeur,attendu",
    [(1000163, "1 000 163"), (43, "43"), (99955.0, "99 955"), (24000.21, "24000.21")],
)
def test_les_grands_nombres_sont_lisibles(valeur, attendu):
    """`1 000 163` plutôt que `1000163`. Un flottant entier perd son `.0` — la
    borne d'un code postal n'est pas `99955.0` pour un lecteur humain."""
    assert doc._nombre(valeur) == attendu


# ---------------------------------------------------------------------------
# Une fiche complète
# ---------------------------------------------------------------------------


class DeclareeJouet:
    name = "RH.EMPLOYES"
    layer = "bronze"
    batch_column = "_batch_id"


CONTRAT_JOUET = {
    "table": "RH.EMPLOYES",
    "version": 1,
    "status": "proposed",
    "source": {"batch_id": None, "row_count": 1200},
    "columns": {
        "MATRICULE": {"role": "identifier", "unique": True, "not_null": True},
        "CONTRAT": {
            "role": "categorical",
            "not_null": True,
            "accepted_values": ["CDD", "CDI", "STAGE"],
        },
        "SALAIRE": {"role": "numeric", "not_null": True, "between": [18000, 91000]},
        "VILLE": {"role": "categorical", "no_semantic_collisions": True},
    },
    "warnings": [
        {"column": "VILLE", "kind": "partial_evidence", "detail": "couverture 40%"}
    ],
}


@pytest.fixture
def fiche(tmp_path):
    return doc._fiche(CONTRAT_JOUET, DeclareeJouet(), tmp_path / "RH.EMPLOYES.v1.yaml")


def test_la_fiche_porte_les_cinq_sections(fiche):
    for section in (
        "**1 · Rôle principal**",
        "**2 · Volume de référence**",
        "**3 · Clés primaires identifiées**",
        "**4 · Règles appliquées**",
        "**5 · Avertissements et limites**",
    ):
        assert section in fiche, section


def test_la_fiche_dit_le_grain_et_la_cle(fiche):
    assert "Grain : une ligne par `MATRICULE`." in fiche
    assert "🔑 `MATRICULE`" in fiche


def test_la_fiche_rend_les_clauses(fiche):
    assert "`between` [18 000 … 91 000]" in fiche
    assert "`accepted_values` : `CDD`, `CDI`, `STAGE`" in fiche
    assert "`no_semantic_collisions`" in fiche


def test_la_fiche_conserve_l_avertissement(fiche):
    """Un avertissement retiré de la documentation serait un contrat qui paraît
    plus solide qu'il n'est — exactement ce que la critique de 4.2.2 refuse."""
    assert "VILLE" in fiche and "couverture 40%" in fiche
    assert "partial_evidence" in fiche


def test_une_fiche_sans_cle_le_dit(tmp_path):
    """« aucune clé » et « clé non affichée » sont deux choses différentes."""
    sans_cle = dict(CONTRAT_JOUET)
    sans_cle["columns"] = {"VILLE": CONTRAT_JOUET["columns"]["VILLE"]}
    rendu = doc._fiche(sans_cle, DeclareeJouet(), tmp_path / "x.v1.yaml")
    assert "*Aucune.*" in rendu
