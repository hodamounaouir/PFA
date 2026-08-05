"""Contrôle du classement par rôle (phase 4.2) — le moteur de généricité.

Aucun de ces tests ne touche à une base : le classement ne lit que des agrégats
déjà calculés. C'est d'ailleurs sa propriété centrale — décider ne coûte aucune
requête, puisque c'est la décision qui engage les requêtes coûteuses.

⚠️ Les colonnes nommées ici viennent d'Olist **et** d'un dataset RH imaginaire :
les deux, exprès. Un classement qui ne marcherait que sur Olist ne serait pas un
moteur de généricité, ce serait une table de correspondance.
"""

import datetime

import pytest

from agent.characterize import (
    CATEGORIEL,
    IDENTIFIANT,
    INDETERMINE,
    NUMERIQUE,
    TEMPOREL,
    TEXTE_LIBRE,
    classer,
    classer_fiche,
    lisible_comme_date,
    lisible_comme_nombre,
)


def colonne(distinct, mini=None, maxi=None, nulls=0):
    return {"distinct": distinct, "min": mini, "max": maxi, "null_count": nulls}


# ---------------------------------------------------------------------------
# Les six rôles, sur 1 000 lignes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cas,stats,attendu",
    [
        # --- Olist, en Bronze : tout est VARCHAR, et le classement tient quand même
        ("order_id", colonne(1000, "0000a", "fffff"), IDENTIFIANT),
        ("order_status", colonne(8, "approved", "shipped"), CATEGORIEL),
        ("customer_city", colonne(300, "abadia", "zortea"), CATEGORIEL),
        ("payment_value", colonne(800, "0.00", "9999.99"), NUMERIQUE),
        (
            "order_purchase_timestamp",
            colonne(990, "2018-01-02 10:56:33", "2018-04-29 23:12:01"),
            TEMPOREL,
        ),
        ("review_comment", colonne(940, "adorei", "otimo"), TEXTE_LIBRE),
        # --- un dataset RH étranger à Olist : mêmes règles, aucun nom en dur
        ("matricule", colonne(1000, "A-0001", "A-1000"), IDENTIFIANT),
        ("contrat", colonne(3, "CDD", "STAGE"), CATEGORIEL),
        ("salaire_brut", colonne(420, 18000, 91000), NUMERIQUE),
        (
            "date_embauche",
            colonne(600, datetime.date(2015, 1, 5), datetime.date(2024, 9, 1)),
            TEMPOREL,
        ),
        # --- les cas limites
        ("colonne entièrement nulle", colonne(0, None, None, nulls=1000), INDETERMINE),
        ("presque unique mais troué", colonne(1000, "a", "z", nulls=3), TEXTE_LIBRE),
        # --- ⚠️ LES DEUX bornes, jamais une seule
        #
        # Une seule borne suffirait sur une colonne Bronze salie par un `N/A` :
        # elle serait déclarée quantitative (ou temporelle) sur la foi d'un seul
        # côté de l'intervalle, et sa médiane porterait sur les 3 % de valeurs
        # lisibles. Ces quatre cas ont été écrits après que deux sabotages
        # (`and` → `or`) soient passés inaperçus — ils existaient en 4.1.5 et
        # mon propre refactor les a supprimés en déplaçant le critère.
        ("montant sali en fin d'ordre", colonne(60, "0.00", "N/A"), CATEGORIEL),
        ("montant sali en début d'ordre", colonne(60, "inconnu", "99.99"), CATEGORIEL),
        ("date salie en fin d'ordre", colonne(60, "2018-01-02", "N/A"), CATEGORIEL),
        ("date salie en début d'ordre", colonne(60, "N/A", "2018-04-29"), CATEGORIEL),
    ],
)
def test_les_roles(cas, stats, attendu):
    assert classer(stats, 1000) == attendu, cas


def test_un_horodatage_presque_unique_reste_temporel():
    """L'ordre des tests **est** la décision, pas un détail d'implémentation.

    `order_purchase_timestamp` est unique à 99 % et sans nul : il satisfait la
    signature d'un identifiant. Le classer ainsi ferait perdre la fraîcheur, les
    dates futures, les trous et la monotonie — pour ne gagner qu'un contrôle
    d'unicité sur une colonne qui n'identifie rien.
    """
    horodatage = colonne(1000, "2018-01-02 10:56:33", "2018-04-29 23:12:01")
    assert classer(horodatage, 1000) == TEMPOREL


def test_une_cle_presque_unique_reste_un_identifiant():
    """Quelques doublons ne font pas d'une clé primaire une catégorie.

    C'est justement l'écart que le contrat (4.2) fera constater comme une
    **violation d'unicité**. Reclasser la colonne, ce serait se taire : l'agent
    expliquerait l'anomalie au lieu de la signaler.
    """
    assert classer(colonne(995, "a", "z"), 1000) == IDENTIFIANT


def test_un_identifiant_troue_n_en_est_plus_un():
    """Unique **et** jamais nul : les deux. Une clé primaire nulle n'existe pas,
    et un identifiant troué est plus probablement autre chose."""
    assert classer(colonne(1000, "a", "z", nulls=1), 1000) != IDENTIFIANT


def test_une_table_vide_ne_donne_aucun_role():
    """0 ligne : aucun rôle ne peut être déduit, et en inventer un serait pire
    que se taire — le contrat le graverait ensuite comme une vérité."""
    assert classer(colonne(5, "a", "z"), 0) == INDETERMINE


# ---------------------------------------------------------------------------
# Ce qui sépare une date d'un nombre, et un nombre d'un mot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valeur",
    [
        "2018-04-29",
        "2018-04-29 10:56:33",
        "2018-04-29T10:56:33.000",
        "2018-04-29T10:56:33Z",
    ],
)
def test_les_formes_de_date_rendues_par_snowflake(valeur):
    """En Bronze ces dates sont du texte, en Silver elles sont typées — et
    `_json_sur` les rend en chaîne dans les deux cas. Une seule forme à lire."""
    assert lisible_comme_date(valeur)


def test_une_date_compacte_n_est_pas_une_quantite():
    """`20180429` se lit aussi comme un nombre : d'où le test temporel **avant**
    le test numérique. Une médiane d'horodatages n'aurait aucun sens."""
    assert classer(colonne(90, "20180101", "20180429"), 1000) == NUMERIQUE
    # …et la forme ISO, elle, est bien reconnue comme temporelle
    assert classer(colonne(90, "2018-01-01", "2018-04-29"), 1000) == TEMPOREL


@pytest.mark.parametrize("valeur", ["nan", "inf", "1_000", "", "  ", "12abc"])
def test_ce_qui_n_est_pas_un_nombre(valeur):
    """`float("nan")` et `float("inf")` réussissent — d'où une regex, pas un cast."""
    assert not lisible_comme_nombre(valeur)


@pytest.mark.parametrize("valeur", ["-12.5e3", "0.00", "42", ".5", 42, 42.0])
def test_ce_qui_en_est_un(valeur):
    assert lisible_comme_nombre(valeur)


def test_un_booleen_n_est_ni_un_nombre_ni_une_date():
    """`isinstance(True, int)` vaut `True` en Python : sans garde explicite, une
    colonne booléenne passerait pour numérique."""
    assert not lisible_comme_nombre(True)
    assert not lisible_comme_date(False)


# ---------------------------------------------------------------------------
# Le classement d'une fiche entière
# ---------------------------------------------------------------------------


def test_classer_une_fiche_entiere():
    fiche = {
        "ORDER_ID": colonne(1000, "a", "z"),
        "STATUS": colonne(4, "approved", "shipped"),
        "AMOUNT": colonne(700, "0.00", "9999.99"),
    }
    assert classer_fiche(fiche, 1000) == {
        "ORDER_ID": IDENTIFIANT,
        "STATUS": CATEGORIEL,
        "AMOUNT": NUMERIQUE,
    }


def test_aucun_nom_de_colonne_n_intervient():
    """LE test de généricité du module : deux colonnes aux noms opposés et aux
    mêmes statistiques reçoivent le même rôle.

    S'il devenait rouge, c'est qu'une heuristique de nommage se serait glissée
    dans le classement — et le moteur de généricité aurait cessé d'en être un.
    """
    stats = colonne(6, "alpha", "omega")
    assert classer(stats, 1000) == classer(dict(stats), 1000)
    fiche = classer_fiche({"customer_city": stats, "zzz_9": dict(stats)}, 1000)
    assert len(set(fiche.values())) == 1


def test_aucun_type_sql_n_intervient():
    """Le classement ignore `type`, même quand la fiche le porte.

    En Bronze tout est VARCHAR (phase 2.1) : un classement fondé sur le type
    déclaré y verrait six colonnes de texte libre et rien d'autre — donc aucun
    contrôle, sur la couche où les anomalies sont injectées.
    """
    montant = {**colonne(700, "0.00", "9999.99"), "type": "TEXT"}
    montant_type = {**colonne(700, 0.0, 9999.99), "type": "NUMBER"}
    assert classer(montant, 1000) == classer(montant_type, 1000) == NUMERIQUE
