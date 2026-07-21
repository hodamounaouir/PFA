# ADR 008 — Validation humaine systématique (HITL pur) plutôt que scoring d'autonomie

**Date** : 2026-07-21 · **Statut** : accepté · **Remplace** : le mécanisme de scoring des versions v1–v3 du cahier des charges (passage en v4 documenté au §0 du CAHIER_DES_CHARGES)

## Contexte

Dans les versions v1–v3, l'agent décidait *seul* d'appliquer ou non une correction,
via un score `confiance × risque × environnement` : au-dessus d'un seuil il agissait
en autonomie (branche **Act**), en dessous il escaladait à un humain (branche
**Escalate**). Deux problèmes sont apparus à la conception :

1. **Le scoring était la partie la plus difficile à calibrer** : aucun jeu de données
   pour apprendre les seuils, risque élevé de faux positifs (correction automatique
   erronée sur des données de production simulées) — pour un gain démonstratif faible.
2. La complexité (policy-as-code, seuils par environnement, deux branches à tester)
   pesait sur toutes les phases suivantes, dans un projet mené en solo avec un
   calendrier de stage.

## Options envisagées

- **(a) Scoring + autonomie partielle** (design v1–v3) : démontre l'autonomie, mais
  seuils arbitraires, difficile à défendre en soutenance (« pourquoi 0,7 ? »), et
  dangereux par principe (un agent qui modifie des données sans relecture).
- **(b) HITL pur** : toute correction proposée est soumise à un humain avant
  application. L'agent détecte, diagnostique et *propose* ; l'humain décide.
- **(c) HITL avec liste blanche** : autonomie sur les seules corrections « sans
  risque ». Rejeté comme premier pas : c'est un raffinement possible *après* (b),
  pas une alternative.

## Décision

**HITL pur (option b).** Le graphe LangGraph s'interrompt au nœud `Propose`
(mécanisme d'*interrupt* LangGraph) et attend la décision humaine dans Streamlit :

```
Profile ► Detect ► Diagnose ► Propose ⏸(humain) ► Apply ► Validate ► Log
                                      └─ refus ──────────────────────► Log
```

Aucun chemin ne mène de `Diagnose` à `Apply` sans passer par une approbation
humaine explicite.

## Conséquences

- **Sûreté et défendabilité** : aucune modification de données sans trace d'une
  décision humaine — argument fort en soutenance, aligné avec les pratiques
  réelles en production.
- **Simplicité** : plus de policy-as-code ni de seuils à calibrer ; l'effort se
  reporte sur la qualité du diagnostic et de la proposition (la vraie valeur du LLM).
- **Coût assumé** : l'humain est un goulot d'étranglement ; le projet ne démontre
  pas d'autonomie décisionnelle. Extension future possible (liste blanche, option c)
  sans casser l'architecture.
- La table `INCIDENTS` journalise la décision humaine (approuvé/refusé), ce qui
  nourrit la mémoire de l'agent (objectif O7).
