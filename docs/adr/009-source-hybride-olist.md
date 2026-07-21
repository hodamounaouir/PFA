# ADR 009 — Source de données : Olist réel rejoué + anomalies injectées (montage hybride)

**Date** : 2026-07-21 · **Statut** : accepté · **Remplace** : le générateur de données synthétiques (Faker) des versions v1–v3

## Contexte

Le benchmark du projet (phase 8) mesure précision/rappel de l'agent : il exige une
**vérité terrain** — savoir exactement quelles anomalies sont présentes, où et quand.
Il fallait choisir d'où viennent les données du pipeline.

## Options envisagées

- **(a) Données 100 % générées (Faker)** : contrôle total, mais données irréalistes
  (« trop propres », distributions artificielles) ; l'utilisateur refuse ce montage —
  un projet de qualité de données sur des données fausses perd sa crédibilité.
- **(b) Données réelles telles quelles** : réalisme maximal, mais aucune vérité
  terrain (les anomalies réelles sont inconnues) → benchmark incalculable.
- **(c) Hybride** : dataset réel **Olist** (e-commerce brésilien, Kaggle, ~100k
  commandes, 9 tables CSV) **rejoué jour par jour** + **injection contrôlée**
  d'anomalies à des dates choisies, documentées dans `data/ground_truth.yaml`.

## Décision

**Montage hybride (option c).**

- **Rejeu** (`data/replay.py`) : découpage par `order_purchase_timestamp`,
  1 jour = 1 batch, fenêtre ~90 jours, déterministe (`--seed 42`).
- **Injection** (`data/inject.py`) : dérive de schéma (J45), nulls anormaux
  (J60, **réinjectés à J85** pour mesurer le gain mémoire T1 vs T2), doublons (J75),
  fichier tronqué (J80). Chaque anomalie est consignée dans `ground_truth.yaml`
  (jour, table, colonne, type, ampleur, dimension DAMA).
- **Fil rouge sémantique = cas réel, pas injecté** : les variantes de casse de la
  ville de São Paulo existent nativement dans Olist. Mesuré le 2026-07-21 sur
  `geolocation_city` : **135 800 lignes `sao paulo` vs 24 918 `são paulo`**
  (+ 2 `sãopaulo`), soit un éclatement 85/15 de tout agrégat par ville. Le plan B
  (injection de variantes) est donc inutile.
- **Acquisition** : téléchargement manuel du zip Kaggle → CSV dans `data/olist/`
  (gitignoré). Pas d'API Kaggle : aucun gain pour un dataset statique.

## Règle d'honnêteté du benchmark

`ground_truth.yaml` est écrit en phase 1 et **n'est plus jamais modifié après que
l'agent tourne**. L'adapter aux résultats de l'agent invaliderait le benchmark.

## Les 2 sources d'ingestion de l'objectif O1 (figées ici)

O1 exige de démontrer l'ingestion multi-sources. Les deux sources sont :

1. **Fichiers plats** : les batchs CSV quotidiens produits par le rejeu dans
   `data/incoming/` (chemin nominal du pipeline).
2. **API REST locale** (FastAPI) : une table de référence Olist (ex. `products`)
   exposée en HTTP, consommée par un connecteur d'ingestion dédié.

PostgreSQL a été écarté pour la source 2 : un système de plus à installer et
opérer, sans diversité supplémentaire de connecteur par rapport à une API REST
(qui, elle, ne coûte qu'une dépendance Python déjà utile pour Streamlit).

## Conséquences

- Benchmark calculable (précision/rappel vs `ground_truth.yaml`) **et** réalisme
  des données (volumes, nulls naturels, encodages, vraies distributions).
- Le dataset n'est pas versionné (~120 Mo) : un tiers doit le télécharger
  manuellement — une ligne de documentation dans le README (phase 1).
- La fenêtre de rejeu et le seed sont figés en config : deux exécutions produisent
  exactement les mêmes batchs (reproductibilité des expériences).
