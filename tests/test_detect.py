"""Contrôle des cinq familles de détection (phase 4.3), une par une.

Aucun de ces tests ne touche à une base : les familles sont des **fonctions
pures** sur l'état. C'est leur propriété centrale — le benchmark (phase 8) doit
pouvoir rejouer la détection à l'identique, ce qu'une famille qui interroge la
base pendant qu'elle raisonne rendrait impossible.

Les cas sont ceux du corrigé Olist (`data/ground_truth.yaml`) chaque fois que
c'est possible : ce sont eux que la phase 4.6 mesurera, et les éprouver ici
évite de découvrir en fin de parcours qu'un détecteur ne voyait pas ce pour quoi
il avait été écrit.
"""

import pytest

from agent import config
from agent.detect import contrat, inventaire, schema, semantique, statistique
from agent.state import new_state


def etat(**surcharges):
    state = new_state(
        dataset="olist", layer="bronze", table="RAW.ORDERS", batch_id="2018-04-29"
    )
    state.update(surcharges)
    return state


def profil(colonnes=None, lignes=351):
    return {"row_count": lignes, "columns": colonnes or {}}


# ===========================================================================
# Famille 1 — inventaire
# ===========================================================================


def test_une_table_declaree_absente_est_signalee():
    """L'incident le plus grave qui puisse arriver, et le plus facile à masquer.

    Sans cette famille, le connecteur lèverait et le run planterait : personne
    ne saurait *pourquoi*, et l'anomalie serait prise pour un bug.
    """
    ecarts = inventaire.detecter(
        etat(inventory={"present": ["RAW.CUSTOMERS"], "declared": ["RAW.ORDERS"]})
    )
    types = [e["type"] for e in ecarts]
    assert "table_absente" in types
    assert ecarts[0]["dama"] == "completude"


def test_un_inventaire_non_releve_ne_declare_pas_tout_disparu():
    """⭐ Le faux positif le plus spectaculaire qu'on puisse produire.

    `present` absent veut dire « on n'a pas regardé », pas « il n'y a rien ».
    Confondre les deux ferait signaler la disparition de toutes les tables au
    premier run monté à la main.
    """
    assert inventaire.detecter(etat(inventory={})) == []
    assert inventaire.detecter(etat()) == []


def test_une_table_presente_mais_non_declaree_est_signalee():
    """Elle n'est surveillée par personne, et personne ne le sait."""
    ecarts = inventaire.detecter(
        etat(
            inventory={
                "present": ["RAW.ORDERS", "RAW.SURPRISE"],
                "declared": ["RAW.ORDERS"],
            }
        )
    )
    assert [e["observe"] for e in ecarts if e["type"] == "table_non_declaree"] == [
        "RAW.SURPRISE"
    ]


def test_le_renommage_est_une_conjonction_de_faits_pas_une_conclusion():
    """« A absente, B nouvelle, mêmes colonnes » — `diagnose` suppose, pas nous."""
    ecarts = inventaire.detecter(
        etat(
            schema_history=[{"name": "ORDER_ID"}, {"name": "STATUT"}],
            inventory={
                "present": ["RAW.COMMANDES"],
                "declared": ["RAW.ORDERS"],
                "schemas": {"RAW.COMMANDES": ["ORDER_ID", "STATUT"]},
            },
        )
    )
    renommages = [e for e in ecarts if e["type"] == "renommage_probable"]
    assert len(renommages) == 1
    assert renommages[0]["observe"] == "RAW.COMMANDES"
    assert renommages[0]["reference"] == "RAW.ORDERS"
    # Aucun champ ne conclut : ni « renommage confirmé », ni score de confiance.
    assert "confiance" not in renommages[0]["details"]


def test_pas_de_renommage_quand_les_schemas_different():
    """Deux tables qui n'ont rien à voir ne doivent pas être rapprochées."""
    ecarts = inventaire.detecter(
        etat(
            schema_history=[{"name": "ORDER_ID"}],
            inventory={
                "present": ["RAW.AUTRE"],
                "declared": ["RAW.ORDERS"],
                "schemas": {"RAW.AUTRE": ["TOUT", "AUTRE", "CHOSE"]},
            },
        )
    )
    assert not [e for e in ecarts if e["type"] == "renommage_probable"]


def test_sans_schema_connu_l_absence_reste_signalee():
    """L'hypothèse de renommage est un service rendu, pas la détection elle-même."""
    ecarts = inventaire.detecter(
        etat(
            inventory={
                "present": ["RAW.COMMANDES"],
                "declared": ["RAW.ORDERS"],
                "schemas": {"RAW.COMMANDES": ["ORDER_ID"]},
            }
        )
    )
    assert [e["type"] for e in ecarts].count("table_absente") == 1


# ===========================================================================
# Famille 2 — schéma  (corrigé : schema_drift_j45)
# ===========================================================================


def test_le_renommage_de_colonne_du_J45_est_vu():
    """`payment_value` → `amount` : une disparue, une nouvelle, aucun seuil."""
    ecarts = schema.detecter(
        etat(
            schema_history=[{"name": "ORDER_ID"}, {"name": "PAYMENT_VALUE"}],
            profile=profil({"ORDER_ID": {}, "AMOUNT": {}}),
        )
    )
    par_type = {e["type"]: e["colonne"] for e in ecarts}
    assert par_type == {
        "colonne_disparue": "PAYMENT_VALUE",
        "colonne_nouvelle": "AMOUNT",
    }


def test_la_famille_schema_ne_conclut_pas_au_renommage():
    """Deux faits séparés. Supposer est le travail du modèle, décider celui de
    l'humain — la même répartition que pour les tables."""
    ecarts = schema.detecter(
        etat(
            schema_history=[{"name": "A"}],
            profile=profil({"B": {}}),
        )
    )
    assert not [e for e in ecarts if "renommage" in e["type"]]


def test_l_historique_prime_sur_le_contrat():
    """L'historique dit ce qui a été **observé hier** ; le contrat ce qu'un
    humain a **signé** il y a peut-être des semaines. Comparer au second
    signalerait comme nouvelle toute colonne ajoutée depuis la signature."""
    ecarts = schema.detecter(
        etat(
            schema_history=[{"name": "A"}, {"name": "B"}],
            contract={"columns": {"A": {}}},
            profile=profil({"A": {}, "B": {}}),
        )
    )
    assert ecarts == []


def test_le_contrat_sert_de_repli_hors_bronze():
    """`_SCHEMA_HISTORY` n'est écrite que par l'ingestion : elle ne couvre que
    Bronze. Sans repli, la dérive de schéma serait aveugle sur Silver et Gold."""
    ecarts = schema.detecter(
        etat(
            contract={"columns": {"A": {}, "B": {}}},
            profile=profil({"A": {}}),
        )
    )
    assert [e["type"] for e in ecarts] == ["colonne_disparue"]
    assert ecarts[0]["reference"] == "contrat"


def test_sans_reference_le_premier_run_ne_crie_pas():
    """Tout serait « nouveau » : un premier run noyé sous des faux écarts
    apprend à ignorer l'agent dès le jour un."""
    assert schema.detecter(etat(profile=profil({"A": {}}))) == []


# ===========================================================================
# Famille 3 — contrat  (corrigé : nulls_j60, duplicates_j75)
# ===========================================================================


def test_les_nulls_du_J60_violent_la_clause_not_null():
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"CUSTOMER_ID": {"not_null": True}}},
            profile=profil({"CUSTOMER_ID": {"null_count": 51, "null_rate": 0.30}}),
        )
    )
    assert [e["type"] for e in ecarts] == ["nulls_interdits"]
    assert ecarts[0]["observe"] == 51
    assert ecarts[0]["dama"] == "completude"


def test_les_doublons_du_J75_violent_la_clause_unique():
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"ORDER_ITEM_SK": {"unique": True}}},
            profile=profil({"ORDER_ITEM_SK": {"distinct": 413, "null_count": 0}}, 475),
        )
    )
    assert [e["type"] for e in ecarts] == ["doublons"]
    assert ecarts[0]["details"]["doublons"] == 62


def test_les_nulls_ne_comptent_pas_comme_des_doublons():
    """⭐ Le faux positif permanent qu'il fallait éviter.

    `distinct` compte les valeurs **non nulles**. Sans la soustraction, toute
    colonne unique portant des nulls paraîtrait en doublon à chaque run — et
    l'humain apprendrait à ignorer la clause d'unicité.
    """
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"ID": {"unique": True}}},
            profile=profil({"ID": {"distinct": 340, "null_count": 11}}, 351),
        )
    )
    assert ecarts == []


def test_une_valeur_hors_bornes_est_vue():
    """Le cas « 8000 dans une colonne à [1–100] » — celui que le projet cite."""
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"PRIX": {"between": [1, 100]}}},
            profile=profil({"PRIX": {"numeric_min": 1.0, "numeric_max": 8000.0}}),
        )
    )
    assert [e["type"] for e in ecarts] == ["hors_bornes"]
    assert ecarts[0]["dama"] == "exactitude"


def test_les_bornes_comparees_sont_les_numeriques():
    """⚠️ Piège de 4.1.5 : sur Bronze `min`/`max` sont **lexicographiques**
    (`"8000" < "90"`). Les comparer à des bornes numériques rendrait un verdict
    différent selon la couche."""
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"PRIX": {"between": [1, 100]}}},
            # Les lexicographiques sont hors bornes, les numériques non.
            profile=profil({"PRIX": {"min": "1", "max": "90", "numeric_max": 90.0}}),
        )
    )
    assert ecarts == []


def test_une_valeur_hors_liste_est_vue():
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"STATUT": {"accepted_values": ["ok", "ko"]}}},
            profile=profil(
                {
                    "STATUT": {
                        "top": [
                            {"value": "ok", "count": 9},
                            {"value": "?", "count": 1},
                        ],
                        "coverage": 1.0,
                    }
                }
            ),
        )
    )
    assert [e["type"] for e in ecarts] == ["valeur_non_admise"]
    assert ecarts[0]["observe"] == ["?"]


def test_la_famille_contrat_ignore_les_collisions_semantiques():
    """⭐ Un même fait ne doit pas produire deux écarts.

    La clause `no_semantic_collisions` existe dans les contrats, mais c'est la
    famille *sémantique* qui la constate — et elle le fait même sans contrat,
    sinon la détection du fil rouge dépendrait d'une signature humaine.
    """
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"VILLE": {"no_semantic_collisions": True}}},
            profile=profil(
                {
                    "VILLE": {
                        "role": "categorical",
                        "top": [
                            {"value": "sao paulo", "count": 8},
                            {"value": "são paulo", "count": 2},
                        ],
                    }
                }
            ),
        )
    )
    assert ecarts == []


def test_sans_contrat_la_famille_se_tait():
    """`charger()` ne rend que du validé : sans signature, aucune clause ne
    s'applique. Ce silence est correct, ce n'est pas un « tout va bien »."""
    assert contrat.detecter(etat(profile=profil({"A": {"null_count": 9}}))) == []


def test_une_colonne_du_contrat_absente_du_lot_releve_du_schema():
    """La signaler ici la ferait compter deux fois, et sous une dimension DAMA
    qui n'est pas la sienne."""
    ecarts = contrat.detecter(
        etat(
            contract={"columns": {"DISPARUE": {"not_null": True}}},
            profile=profil({"AUTRE": {}}),
        )
    )
    assert ecarts == []


# ===========================================================================
# Famille 4 — statistique  (corrigé : truncate_j80, nulls_j60/j85)
# ===========================================================================


def historique(valeurs, cle=(None, "row_count")):
    return {cle: list(valeurs)}


def test_pas_de_detection_avant_l_historique_minimal():
    """Une médiane sur trois lots est un chiffre, pas une référence."""
    ecarts = statistique.detecter(
        etat(profile=profil(lignes=42), profile_history=historique([300] * 3))
    )
    assert ecarts == []


def test_la_troncature_du_J80_est_vue():
    """139 lignes attendues, 42 livrées : le volume s'effondre."""
    ecarts = statistique.detecter(
        etat(
            profile=profil(lignes=42),
            profile_history=historique([300, 310, 290, 305] * 5),
        )
    )
    assert [e["type"] for e in ecarts] == ["derive_statistique"]
    assert ecarts[0]["observe"] == 42.0
    assert ecarts[0]["details"]["metrique"] == "row_count"
    assert abs(ecarts[0]["details"]["z"]) > config.SEUIL_Z


def test_une_variation_normale_ne_declenche_rien():
    ecarts = statistique.detecter(
        etat(
            profile=profil(lignes=302), profile_history=historique([300, 310, 290] * 7)
        )
    )
    assert ecarts == []


def test_la_rupture_d_une_constante_est_vue_sans_score():
    """⭐ Historique parfaitement constant : aucun plancher sur le MAD.

    43 jours à 0 % de nulls, puis 30 % au J60. Un MAD nul n'est pas un problème
    à corriger, c'est une information — la métrique n'a jamais bougé. Inventer
    une variabilité qui n'a pas été observée, c'est ce que la décision 10b
    interdit déjà à la mesure elle-même.
    """
    ecarts = statistique.detecter(
        etat(
            profile=profil({"CUSTOMER_ID": {"null_rate": 0.301}}),
            profile_history={("CUSTOMER_ID", "null_rate"): [0.0] * 20},
        )
    )
    assert [e["type"] for e in ecarts] == ["rupture_de_constante"]
    assert ecarts[0]["details"]["ecart_brut"] == pytest.approx(0.301)
    assert "z" not in ecarts[0]["details"], "aucun score sur une variabilité nulle"


def test_une_constante_qui_ne_bouge_pas_ne_declenche_rien():
    ecarts = statistique.detecter(
        etat(
            profile=profil({"C": {"null_rate": 0.0}}),
            profile_history={("C", "null_rate"): [0.0] * 20},
        )
    )
    assert ecarts == []


def test_la_recidive_du_J85_reste_aussi_grave_que_le_J60():
    """⭐⭐ LE test de la médiane robuste — l'objectif O7 en dépend.

    L'anomalie du J60 est entrée dans l'historique sans être corrigée. Avec une
    moyenne et un écart-type, elle gonflerait σ et la **récidive identique du
    J85 paraîtrait moins grave** : la référence se contaminerait elle-même et
    l'agent deviendrait aveugle à ce qu'il vient de signaler.

    On construit donc un historique **pollué** par l'anomalie précédente et on
    vérifie que la récidive est toujours vue.
    """
    pollue = [0.0] * 19 + [0.301]  # 19 jours propres + le J60 non corrigé
    ecarts = statistique.detecter(
        etat(
            profile=profil({"CUSTOMER_ID": {"null_rate": 0.301}}),
            profile_history={("CUSTOMER_ID", "null_rate"): pollue},
        )
    )
    assert ecarts, "la récidive a été masquée par l'anomalie précédente"


def test_l_ecart_porte_sa_dimension_dama():
    """Sans elle, la phase 8 dirait combien d'anomalies l'agent trouve, pas
    **quelle sorte** de qualité il améliore."""
    ecarts = statistique.detecter(
        etat(
            profile=profil({"C": {"numeric_rate": 0.7}}),
            profile_history={("C", "numeric_rate"): [1.0] * 20},
        )
    )
    assert ecarts[0]["dama"] == "validite"


def test_une_colonne_neuve_n_est_pas_jugee_sur_ses_debuts():
    """Le démarrage à froid se constate **par série**, pas globalement : une
    colonne apparue il y a trois jours n'a pas d'historique même si la table en
    a trente."""
    ecarts = statistique.detecter(
        etat(
            profile=profil({"NEUVE": {"null_rate": 0.9}}, lignes=300),
            profile_history={
                (None, "row_count"): [300] * 20,
                ("NEUVE", "null_rate"): [0.0, 0.0],
            },
        )
    )
    assert ecarts == []


# ===========================================================================
# Famille 5 — sémantique  (corrigé : semantic_drift_j50) ⭐ le fil rouge
# ===========================================================================


def colonne_ville(valeurs, role="categorical", coverage=1.0):
    return profil(
        {
            "CUSTOMER_CITY": {
                "role": role,
                "coverage": coverage,
                "top": [{"value": v, "count": n} for v, n in valeurs],
            }
        }
    )


def test_sao_paulo_est_vu():
    """⭐ Le cas que le projet existe pour montrer, et que la baseline rate.

    `not_null` passe, `unique` passe, le typage passe, le pipeline est vert —
    et le total de São Paulo est faux.
    """
    ecarts = semantique.detecter(
        etat(profile=colonne_ville([("sao paulo", 135800), ("são paulo", 24918)]))
    )
    assert [e["type"] for e in ecarts] == ["collision_semantique"]
    assert ecarts[0]["observe"] == ["sao paulo", "são paulo"]
    assert ecarts[0]["reference"] == "sao paulo"
    assert ecarts[0]["dama"] == "coherence"


def test_l_ampleur_est_chiffree():
    """Une collision sur 3 lignes et une sur 160 000 ne sont pas le même
    incident — confondre les deux ferait taire l'agent sur la seconde après un
    refus sur la première (signature d'anomalie, 4.4)."""
    ecarts = semantique.detecter(
        etat(profile=colonne_ville([("sao paulo", 135800), ("são paulo", 24918)]))
    )
    assert ecarts[0]["details"]["lignes_concernees"] == 160718


def test_la_detection_est_generique():
    """Aucun nom de ville, aucun nom de colonne : brancher un dataset RH et la
    même famille trouve `CDI` / `cdi`."""
    profil_rh = profil(
        {
            "CONTRAT": {
                "role": "categorical",
                "coverage": 1.0,
                "top": [{"value": "CDI", "count": 40}, {"value": "cdi", "count": 3}],
            }
        }
    )
    ecarts = semantique.detecter(etat(table="HR.EMPLOYES", profile=profil_rh))
    assert ecarts[0]["colonne"] == "CONTRAT"


@pytest.mark.parametrize("role", ["identifier", "free_text", "numeric", "temporal"])
def test_seules_les_colonnes_categorielles_sont_examinees(role):
    """Replier des identifiants ou du texte libre n'aurait aucun sens — et sur
    du texte libre, ce serait une fuite de données au sens de R2."""
    ecarts = semantique.detecter(
        etat(profile=colonne_ville([("a", 1), ("A", 1)], role=role))
    )
    assert ecarts == []


def test_sans_top_k_on_ne_conclut_rien():
    """Ne pas avoir regardé n'est pas avoir constaté que tout va bien."""
    profil_muet = profil({"VILLE": {"role": "categorical"}})
    assert semantique.detecter(etat(profile=profil_muet)) == []


def test_la_couverture_accompagne_le_constat():
    """Le repli travaille sur le top-K : `coverage` dit sur quelle part du lot
    le constat porte. Sans lui, « 2 écritures » ne dit pas s'il s'agit de 3
    lignes ou de 160 000."""
    ecarts = semantique.detecter(
        etat(profile=colonne_ville([("sao paulo", 8), ("são paulo", 2)], coverage=0.4))
    )
    assert ecarts[0]["details"]["coverage"] == 0.4


def test_deux_communes_distinctes_ne_sont_pas_fusionnees():
    """Décision 13c : le repli ne supprime pas les espaces. `arco verde` et
    `arcoverde` sont **deux communes du Pernambouc** — perdre une variante rare
    coûte moins cher que déclarer identiques deux villes qui ne le sont pas."""
    ecarts = semantique.detecter(
        etat(profile=colonne_ville([("arco verde", 50), ("arcoverde", 40)]))
    )
    assert ecarts == []
