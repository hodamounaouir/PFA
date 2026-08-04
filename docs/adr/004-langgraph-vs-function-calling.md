# ADR 004 — LangGraph plutôt que function calling, et ce que « tool » veut dire ici

**Statut** : accepté
**Date** : 2026-08-03 (rédigé au moment où les tools sont écrits, phase 4.1)
**Complète** : [ADR 010](010-agent-generique.md) · **Formalise** : [`DESIGN.md` §2](../DESIGN.md)

## Contexte

Deux documents du projet se lisent comme s'ils se contredisaient, et l'écriture des tools (phase 4.1)
force à trancher :

- le [cahier des charges §5.6](../../CAHIER_DES_CHARGES.md) s'intitule **« Outils exposés (`@tool`) »**
  et met LangChain (`@tool`) dans la pile technique ;
- le [`DESIGN.md` §2](../DESIGN.md) rejette explicitement l'agent ReAct : *« donner les tools à un LLM
  et le laisser boucler (function calling / ReAct). **Rejeté.** »*

La contradiction est apparente. Le mot « tool » recouvre **deux choses distinctes**, et seule la seconde
est en cause :

| | Ce que c'est | Effet |
|---|---|---|
| le **décorateur** `@tool` | une fonction emballée en objet `BaseTool`, avec un schéma JSON dérivé de sa signature | aucun, tant que personne n'envoie ce schéma à un modèle |
| le **tool-calling** (`bind_tools`) | donner ces schémas au modèle pour qu'il choisisse quoi appeler | le flux d'exécution passe du code au modèle |

## Options envisagées

- **(a) Fonctions Python nues.** Le plus simple à tester, mais s'écarte du cahier §5.6 sans nécessité.
- **(b) `@tool` + `bind_tools`.** L'architecture ReAct canonique. Le modèle décide de l'ordre des
  observations. C'est ce que `DESIGN.md` §2 écarte, avec un tableau comparatif et un argument décisif :
  *« un garde-fou écrit dans un prompt est une supplication ; un garde-fou écrit dans la structure du
  graphe est une garantie »*.
- **(c) `@tool` sans `bind_tools`.** Le format demandé par le cahier, sans la délégation de flux
  refusée par le design.

## Décision

**Option (c).** Les tools de `agent/tools/` sont décorés `@tool`. **`bind_tools` n'apparaît nulle part
dans le projet**, et un test le vérifie (`test_aucun_bind_tools`, même principe que le test anti-fuite
SQL de la phase 4.0).

Ce sont les **nœuds** qui appellent les tools, dans l'ordre écrit dans `agent/graph.py`. Le modèle, lui,
n'est appelé qu'à un seul endroit (`diagnose`, règle R1) et ne reçoit que du texte : il raisonne sur des
mesures déjà prises, il n'en réclame pas de nouvelles.

## Pourquoi

Parce que c'est la seule lecture qui honore les deux documents, et parce que ce que le projet vend, ce
n'est pas l'autonomie de l'agent — c'est sa **gouvernabilité** :

- **reproductibilité** : deux runs sur le même batch observent exactement la même chose. La phase 8
  mesure précision et rappel ; un ordre d'observation choisi par le modèle ajouterait de la variance
  là où on cherche à en retirer.
- **testabilité** : un tool est une fonction, donc un test. Avec `bind_tools`, il faudrait simuler un
  dialogue entier pour éprouver une seule mesure.
- **R2 tient sans effort** : le modèle ne peut pas réclamer un échantillon de lignes puisqu'il ne peut
  rien réclamer du tout. Le garde-fou reste dans l'architecture, pas dans le prompt.

## Conséquences

### Sur la forme des tools

Un `@tool` dérive son schéma de sa signature : ses arguments doivent être des valeurs simples. On ne
lui passe donc pas un objet connecteur — il le résout lui-même depuis le registre :

```python
@tool
def profile_table(dataset: str, table: str, batch_id: str) -> dict: ...
```

Ça tombe juste : c'est exactement la forme dont Airflow aura besoin en 4.5, où la tâche transmet
`(dataset, layer, table, batch_id)` — quatre chaînes.

### Sur les tests

Un tool s'invoque par `.invoke({...})` et non par un appel direct. Friction mineure, assumée.

### Sur ce qu'on perd

L'agent ne saura pas improviser une observation qu'aucun nœud n'a prévue. C'est le prix déjà annoncé
par `DESIGN.md` §2 — *« on échange de la généralité contre de la gouvernabilité »* — et il est payé
ici en toute connaissance de cause.

### Ce qu'il faudra surveiller

Le jour où quelqu'un voudra que le modèle réclame lui-même un échantillon via `run_sql`, cette décision
devra être rouverte — et R2 réexaminée avec elle. Le test `test_aucun_bind_tools` deviendra rouge : il
est là pour rendre ce moment visible, pas pour l'interdire à jamais.

### Question de jury anticipée

*« Vous avez des tools LangChain, donc votre LLM boucle dessus ? »* → Non : le format sans la
délégation. Le graphe appelle les tools, le modèle ne les voit pas. Le test le prouve.
