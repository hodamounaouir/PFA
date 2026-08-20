# Le fil rouge, à la souris

> **Objectif (§6.2)** : rejouer le scénario complet — casser → détecter →
> proposer → approuver → corriger → vérifier → journal — **sans ouvrir un
> terminal** une fois la démo lancée.

Ce document est le **runbook** de la démonstration. Il est écrit avant d'avoir
été joué : les commandes de préparation viennent de séquences déjà exécutées
(§4.5, phase 2.3), les écrans de la phase 6.1 sont testés sans navigateur, mais
**l'enchaînement complet reste à éprouver** sur le PC avec Snowflake actif.
Ce qui n'a pas été fait est dit comme tel — voir « Ce qui reste à vérifier ».

---

## Ce que la démo doit montrer

Une seule anomalie suffit à parcourir les huit objectifs du cahier. Le fil rouge
est le **fan-out São Paulo** parce qu'il a une propriété qu'aucune autre n'a :

| | |
|---|---|
| `not_null` | ✅ passe |
| `unique` | ✅ passe |
| le typage | ✅ passe |
| **le pipeline est vert** | ✅ |
| **et le total par ville est faux** | ❌ |

C'est ce que la baseline ne peut pas voir, et ce que l'agent voit sans référence
extérieure — le lot se contredit lui-même.

---

## 0. Préparation (terminal, avant la démo)

```bash
uv run python scripts/check_access.py           # tout vert avant de commencer
uv run python -m data.replay   --day 2018-05-14 # le lot du jour
uv run python -m data.inject   --day 2018-05-14 --if-scheduled
uv run python -m ingestion.load --day 2018-05-14
make dbt-run
```

Puis l'agent sur la couche où le fan-out se voit :

```bash
uv run python -m scripts.check_layer olist gold --day 2018-05-14
```

La tâche se termine en **succès** même si l'agent a trouvé : une proposition en
attente est le fonctionnement normal. Elle affiche le fil à reprendre.

```bash
uv run streamlit run streamlit/app.py
```

---

## 1 → 6 : la démonstration (souris uniquement)

| # | Écran | Ce qu'on montre | Ce qu'on dit |
|:-:|---|---|---|
| 1 | 📊 **Dashboard BI** | `fct_geolocation_by_city` : `sao paulo` et `são paulo` sur **deux lignes** | « Le pipeline est vert, et ce total est faux. » |
| 2 | ✅ **Validation** | l'impact en tête : *n lignes sur N (x %)* | « Sans ce chiffre, on n'approuve pas — on signe. » |
| 3 | ✅ **Validation** | les **gestes autorisés**, dépliés | « L'agent peut isoler, vider, normaliser. Jamais deviner. » |
| 4 | ✅ **Validation** | saisir son nom, cliquer **Approuver** | « La décision est tracée : sans nom, le bouton reste gris. » |
| 5 | 📋 **Incidents** | la ligne du run, parcours complet | « Une ligne par run, quel que soit le chemin. » |
| 6 | 🔍 **Décision** | l'incident déplié : faits, diagnostic, décision | « Le code constate, le modèle suppose, l'humain tranche. » |

Puis **retour à l'écran 1** : le mart est recalculé, São Paulo tient sur une
ligne. C'est le moment de la démo.

---

## Les deux écrans qui distinguent ce projet

Ils ne servent pas le fil rouge mais répondent aux deux questions qu'un jury pose.

### 🔇 Signatures en silence — *« et si l'humain approuve sans lire ? »*

Refuser une proposition fait **taire** l'agent sur cette signature. Cet écran
liste tout ce qu'il ne dit plus, **avec qui l'a refusé et quand**.

Sans lui, un agent devient progressivement muet sans que personne s'en aperçoive
— et c'est invisible **parce qu'**il ne dit plus rien. Un système de surveillance
silencieux ressemble en tout point à un système qui n'a rien à signaler.

À montrer : la colonne **ordre de grandeur**. Un refus sur 30 % de nulls ne fait
pas taire l'agent à 85 % — il reparle de lui-même quand l'ampleur change
d'échelle.

### 📜 Contrats — *« l'agent décide-t-il tout seul ? »*

Un contrat `proposed` n'est **pas** appliqué : tant qu'il attend une signature,
aucune de ses clauses ne gouverne la surveillance. À montrer sur
`RAW.CUSTOMERS` : `CUSTOMER_CITY` porte `no_semantic_collisions` mais **pas**
`accepted_values` — la couverture n'était que de 43 %, donc la preuve manquait,
donc la clause a été **retirée** plutôt qu'assortie d'un avertissement.

*Un avertissement se survole ; une clause absente ne peut pas être approuvée par
distraction.*

---

## Variante : le refus (30 secondes)

Utile si le temps le permet, parce qu'elle montre la moitié qu'on oublie.

1. Sur une autre proposition : cliquer **❌ Refuser**.
2. 📋 **Incidents** — la ligne existe : *un faux positif est une donnée de
   mesure*, c'est sur elle que se calcule la précision au benchmark.
3. 🔇 **Signatures en silence** — la signature y apparaît, avec son auteur.

---

## Ce qui reste à vérifier sur le PC

Rien de ce qui suit n'a encore été joué de bout en bout :

- [ ] l'enchaînement complet des six écrans avec Snowflake actif ;
- [ ] le **recalcul du mart** après approbation — l'écran 1 doit changer, et
      c'est le moment le plus visible de la démo ;
- [ ] le temps réel de la séquence, à mesurer avant de la caler dans un horaire ;
- [ ] la **répéter au moins trois fois** et enregistrer une vidéo de secours
      (§9.2). Une démo live qui n'a jamais été répétée échoue le jour où elle
      compte.

> ⚠️ Le trial Snowflake expire vers le **2026-09-16**. La répétition doit tenir
> dans cette fenêtre, ou être rejouée sur un trial suivant — tout est scripté
> pour ça (ADR 001).
