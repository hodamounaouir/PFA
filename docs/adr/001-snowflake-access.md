# ADR 001 — Accès Snowflake : trial personnel

**Date** : 2026-07-21 · **Statut** : accepté

## Contexte

Le pipeline Bronze/Silver/Gold du projet repose sur Snowflake (choix confirmé : stack
entreprise standard, valeur CV — voir CAHIER_DES_CHARGES §stack). Il fallait décider
*quel compte* Snowflake utiliser, sachant qu'un trial est limité dans le temps
(30 jours, ~400 $ de crédits).

Trois options étaient sur la table (ROADMAP, préambule phase 0) :

- **(a)** Demander un compte via Tython (dépendance à un tiers, délais incertains) ;
- **(b)** Différer l'ouverture du trial jusqu'à la phase 2 pour ne pas consommer les
  30 jours pendant les phases 0–1 (qui n'ont presque pas besoin de Snowflake) ;
- **(c)** Trial personnel immédiat, avec second trial de secours si besoin.

## Décision

**Trial personnel de Hoda, déjà ouvert.** On l'utilise dès la phase 0 pour créer la
base et les schémas, et valider `scripts/check_access.py`.

## Conséquences et parades

1. **Le compte à rebours des 30 jours court déjà.** Les phases 0–1 consomment très peu
   de Snowflake (création de schémas + tests de connexion) ; l'essentiel du besoin
   arrive en phase 2 (pipeline Medallion). Il faut donc avancer sans traîner sur la
   phase 1.
2. **Plan B assumé : second trial.** Si le trial expire en cours de route, on rouvre un
   trial avec une autre adresse email et on rejoue l'infrastructure. Pour que ce soit
   indolore, **tout ce qui touche Snowflake doit être scripté et rejouable** :
   création de la base, des schémas (`RAW`, `STAGING`, `MARTS`, `OPS`), des tables
   techniques → scripts SQL versionnés dans le repo (`scripts/` ou `dbt/`),
   jamais de clic manuel non documenté dans la console.
3. **Crédits** : ~400 $ largement suffisants pour le projet si le warehouse reste en
   `X-SMALL` avec auto-suspend court (60 s). À configurer dès la création.
4. Les identifiants restent dans `.env` (jamais commités) ; `.env.example` liste les
   clés attendues.
