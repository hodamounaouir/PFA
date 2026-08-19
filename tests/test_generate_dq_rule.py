"""Contrôle du générateur de règles dbt (phase 4.1.8).

Le tool transforme un écart constaté en test dbt : c'est ce qui fait que l'agent
**durcit le pipeline** au lieu de seulement réparer la donnée. Une anomalie
attrapée une fois devient une règle vérifiée à chaque run, sans LLM et sans
humain.

Aucun de ces tests ne touche à dbt ni à une base : le générateur est une
fonction pure de l'écart vers du YAML. Le SQL du test générique maison, lui, vit
dans `dbt/tests/generic/` et se valide en exécutant dbt (4.5).
"""

import yaml

from agent.detect import ecart
from agent.tools.generate_dq_rule import TAG, regle_pour, rendre_yaml


def ec(**kw):
    base = dict(
        famille="contrat",
        table="STAGING.STG_CUSTOMERS",
        type="nulls_interdits",
        dama="completude",
        colonne="CUSTOMER_ID",
        ampleur=0.30,
    )
    base.update(kw)
    return ecart(**base)


def document(*ecarts):
    regles = [r for r in (regle_pour(e) for e in ecarts) if r]
    return yaml.safe_load(rendre_yaml(regles)) if regles else None


# ---------------------------------------------------------------------------
# Quel écart donne quel test
# ---------------------------------------------------------------------------


def test_des_nulls_donnent_not_null():
    assert regle_pour(ec())["test"] == "not_null"


def test_des_doublons_donnent_unique():
    assert regle_pour(ec(type="doublons", dama="unicite"))["test"] == "unique"


def test_une_valeur_hors_liste_donne_accepted_values():
    regle = regle_pour(ec(type="valeur_non_admise", reference=["a", "b"]))
    assert regle["test"] == "accepted_values"
    assert regle["arguments"] == {"values": ["a", "b"]}


def test_la_liste_admise_vient_du_CONTRAT_pas_des_valeurs_vues():
    """⭐ La subtilité qui compte.

    L'écart porte dans `observe` les valeurs **intruses** et dans `reference` la
    liste signée. Générer le test depuis `observe` graverait l'anomalie comme
    règle : le pipeline validerait désormais ce qu'il aurait dû refuser.
    """
    regle = regle_pour(
        ec(type="valeur_non_admise", observe=["?", "INTRUS"], reference=["ok", "ko"])
    )
    assert regle["arguments"]["values"] == ["ok", "ko"]
    assert "INTRUS" not in str(regle)


def test_une_collision_semantique_donne_le_test_maison():
    """La seule règle du projet qu'aucun test dbt standard ne sait exprimer."""
    regle = regle_pour(
        ec(famille="semantique", type="collision_semantique", dama="coherence")
    )
    assert regle["test"] == "no_semantic_collisions"
    assert regle["dama"] == "coherence"


def test_une_derive_de_nulls_donne_aussi_not_null():
    """La table est indexée sur ce que l'écart **signifie**, pas sur la famille
    qui l'a trouvé : des nulls constatés par le contrat et des nulls constatés
    par la dérive statistique appellent le même test."""
    regle = regle_pour(
        ec(famille="statistique", type="derive_statistique", metrique="null_rate")
    )
    assert regle["test"] == "not_null"


# ---------------------------------------------------------------------------
# Ce qui ne donne aucune règle — et pourquoi c'est correct
# ---------------------------------------------------------------------------


def test_une_derive_de_volume_ne_donne_aucune_regle():
    """⭐ dbt ne sait pas dire « il y a moins de lignes que d'habitude » : c'est
    une comparaison à un historique, pas une propriété du lot. Générer une règle
    bancale plutôt que rien produirait un test qui échoue sans rien dire — et on
    apprendrait à l'ignorer."""
    assert (
        regle_pour(
            ec(
                famille="statistique",
                type="derive_statistique",
                colonne=None,
                metrique="row_count",
            )
        )
        is None
    )


def test_une_table_absente_ne_donne_aucune_regle():
    assert (
        regle_pour(ec(famille="inventaire", type="table_absente", colonne=None)) is None
    )


def test_un_ecart_sans_colonne_ne_donne_aucune_regle():
    """Un test dbt générique s'attache à une colonne : sans elle, il n'y a rien
    à écrire."""
    assert regle_pour(ec(colonne=None)) is None


def test_aucun_ecart_traduisible_rend_un_document_vide():
    assert (
        document(ec(famille="inventaire", type="table_absente", colonne=None)) is None
    )


# ---------------------------------------------------------------------------
# La forme du YAML — Bronze n'est pas un modèle
# ---------------------------------------------------------------------------


def test_silver_et_gold_sont_des_modeles():
    doc = document(ec(table="STAGING.STG_CUSTOMERS"), ec(table="MARTS.FCT_DAILY_SALES"))
    assert {m["name"] for m in doc["models"]} == {"stg_customers", "fct_daily_sales"}
    assert "sources" not in doc


def test_bronze_est_une_source():
    """⚠️ `RAW.ORDERS` n'est pas un modèle dbt mais une table de la source `raw`.

    Se tromper produirait un fragment que dbt refuse d'analyser — et l'erreur ne
    ressemblerait pas à sa cause.
    """
    doc = document(ec(table="RAW.ORDERS", colonne="ORDER_ID"))
    assert doc["sources"][0]["name"] == "raw"
    assert doc["sources"][0]["tables"][0]["name"] == "orders"
    assert "models" not in doc


def test_les_noms_sont_en_minuscules():
    """dbt nomme ses modèles et colonnes en minuscules ; Snowflake les rend en
    majuscules. Recopier telles quelles produirait un fragment qui ne référence
    aucun modèle existant."""
    doc = document(ec(colonne="CUSTOMER_ID"))
    assert doc["models"][0]["columns"][0]["name"] == "customer_id"


def test_chaque_test_porte_ses_tags():
    """⭐ Sans le tag, le bras « baseline » de la phase 8 ne pourrait pas exclure
    le généré — et la baseline attraperait des anomalies grâce à l'agent, donc
    la comparaison mesurerait l'agent contre lui-même."""
    doc = document(ec())
    corps = doc["models"][0]["columns"][0]["data_tests"][0]["not_null"]
    assert TAG in corps["tags"]
    assert "dama:completude" in corps["tags"]


def test_les_regles_d_une_meme_table_sont_regroupees():
    doc = document(ec(colonne="A"), ec(colonne="B", type="doublons"))
    assert len(doc["models"]) == 1
    assert [c["name"] for c in doc["models"][0]["columns"]] == ["a", "b"]


def test_le_rendu_est_deterministe():
    """Deux exécutions sur les mêmes écarts doivent produire le **même texte** :
    sinon un `git diff` devient illisible et personne ne relit plus rien.

    ⚠️ **Plusieurs tables, et pas seulement plusieurs colonnes.** La première
    version de ce test n'en utilisait qu'une : le tri des colonnes le rendait
    vert, et le tri des *tables* n'était jamais éprouvé. Un sabotage l'a montré —
    retirer le `sorted()` externe laissait la suite verte.
    """
    ecarts = [
        ec(table="STAGING.STG_ORDERS", colonne="B", type="doublons"),
        ec(table="MARTS.FCT_DAILY_SALES", colonne="A"),
        ec(table="RAW.ORDERS", colonne="C"),
        ec(table="STAGING.STG_CUSTOMERS", colonne="D"),
    ]
    regles = [regle_pour(e) for e in ecarts]
    assert rendre_yaml(regles) == rendre_yaml(list(reversed(regles)))


def test_l_ordre_des_tables_est_stable():
    """Le tri externe, éprouvé pour lui-même : deux tables dans l'ordre inverse
    de celui attendu doivent ressortir dans le même ordre."""
    regles = [
        regle_pour(ec(table="STAGING.STG_ORDERS", colonne="A")),
        regle_pour(ec(table="MARTS.FCT_DAILY_SALES", colonne="A")),
    ]
    doc = yaml.safe_load(rendre_yaml(regles))
    assert [m["name"] for m in doc["models"]] == ["fct_daily_sales", "stg_orders"]


def test_l_unicode_reste_lisible():
    """Même leçon qu'en 4.2.4 : on ne relit pas ce qu'on ne peut pas lire, et
    c'est un humain qui doit valider ce fragment avant de le réintégrer."""
    brut = rendre_yaml(
        [regle_pour(ec(type="valeur_non_admise", reference=["são paulo"]))]
    )
    assert "são paulo" in brut


def test_la_provenance_accompagne_la_regle():
    """Un test généré sans provenance est un test que personne n'ose supprimer
    six mois plus tard, faute de savoir ce qu'il protège."""
    regle = regle_pour(ec())
    assert "contrat" in regle["origine"] and "nulls_interdits" in regle["origine"]
