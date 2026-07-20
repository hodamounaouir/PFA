# Design — mécanismes et arbitrages

> **Ce document explique *pourquoi* le système est fait ainsi**, et comment fonctionnent les mécanismes
> non triviaux.
>
> - La **structure** (composants, flux) : [`ARCHITECTURE.md`](ARCHITECTURE.md)
> - Le **contrat fonctionnel** : [`CAHIER_DES_CHARGES.md`](../CAHIER_DES_CHARGES.md) (v4)
> - Les **décisions ponctuelles et datées** : [`adr/`](adr/)

Ce document est le lieu du **recul critique**. Il doit dire lui-même où le projet est faible — un jury
attaque toujours les points faibles ; autant les avoir déjà nommés.

---

## 1. Pourquoi un agent, alors qu'on a dbt test ?

**La question la plus légitime du projet.** Elle sera posée en soutenance. Réponse ici, une fois pour toutes.

### 1.1 Ce ne sont pas deux options concurrentes

dbt test est un **capteur** : il vérifie une règle que quelqu'un a déjà écrite.
L'agent est le **cerveau** : il décide quelles règles doivent exister, pourquoi une a cassé, et quoi faire.

Ils sont **chaînés, pas opposés** : l'agent **produit** des dbt tests (`generate_dq_rule`), dbt les
**exécute**. Retirer l'agent ne donne pas « la même chose en plus simple » — ça donne un pipeline où un
humain écrit chaque test à la main, pour toujours, et seulement pour les problèmes qu'il avait déjà
imaginés.

### 1.2 Les quatre limites structurelles d'un test statique

**a) Il ne peut pas trouver l'imprévu.**
Un dbt test répond à *« la règle X est-elle violée ? »*. Il ne peut pas répondre à *« qu'est-ce qui cloche
ici ? »*. Le cas `sao paulo` / `são paulo` le montre : `not_null` passe, `unique` passe, le typage passe.
**Aucun test ne casse, et les ventes par ville sont fausses.** Pour qu'un test l'attrape, il faudrait qu'un
humain ait déjà su que le problème existe — auquel cas il l'aurait corrigé plutôt que testé.

**b) Il ne dit pas *pourquoi*.**
Même si un `accepted_values` finit par échouer, il annonce « 47 lignes en échec ». Il ne dit pas que la
cause est une normalisation manquante dans un modèle Silver, ni que 8 tables Gold en dépendent. C'est le
travail de cause racine de `Diagnose` (via le lineage) — et c'est précisément l'étape qui consomme le plus
de temps d'un data engineer. D'où la métrique **MTTR**.

**c) Il ne s'adapte pas.**
Une source ajoute une colonne : dbt n'a aucune règle dessus, donc **dbt est vert**. Un pipeline vert sur
des données non testées est pire que rouge — il est *faussement rassurant*. L'agent profile, détecte la
dérive et génère la règle manquante.

**d) Il n'apprend pas et ne propose rien.**
Un test échoue à l'identique la 100ᵉ fois. Et surtout : dbt test **ne propose rien**, donc il n'a besoin
d'aucun garde-fou. Toute la couche HITL n'existe que parce que quelque chose *propose des actions*.

### 1.3 Le point d'honnêteté (qui renforce la défense)

**Pour la grande majorité des cas, dbt test suffit — et est meilleur.** Déterministe, gratuit, instantané,
versionné, lisible. C'est la décision **HG6** du cahier : *« dbt couvre la baseline »*. Et c'est le
principe de mitigation du §12 du cahier : *« LLM seulement quand une anomalie est détectée »*.

L'agent ne se justifie que là où les règles statiques s'arrêtent : le **sémantique**, l'**imprévu**, le
**diagnostic**. Dire ça rend le projet **plus** crédible, pas moins : c'est la preuve qu'on n'a pas mis de
l'IA partout par effet de mode.

C'est aussi pourquoi le benchmark est construit ainsi : **la baseline, ce sont les dbt tests**. L'agent
n'est pas comparé au néant. Si l'agent n'apportait rien, le benchmark du projet le dirait lui-même.

> **La formule** : *dbt test vérifie les règles que je connais déjà. L'agent trouve celles que je ne
> connais pas encore, m'explique pourquoi elles ont cassé, et propose la correction — que j'approuve ou
> refuse. L'agent écrit les tests, dbt les exécute.*

→ ADR `007-agent-vs-dbt-tests.md`

---

## 2. Pourquoi une machine à états, et pas un agent ReAct ?

L'alternative naturelle : donner les tools à un LLM et le laisser boucler (function calling / ReAct).
Rejeté.

| Critère | Agent ReAct autonome | Machine à états (LangGraph) |
|---------|---------------------|----------------------------|
| Flux d'exécution | Décidé par le LLM à chaque tour | **Décidé par le code** |
| Reproductibilité | Faible — deux runs, deux chemins | Élevée — le chemin est le graphe |
| Testabilité | Il faut mocker un dialogue entier | Un node = une fonction = un test |
| Audit | « le LLM a choisi d'appeler X » | Chemin explicite, journalisé |
| Garde-fous | Dans le prompt (« s'il te plaît, demande avant d'écrire ») | **Dans la topologie** (`Apply` est inatteignable sans approbation) |
| Coût | N appels LLM par run | **≤ 1 appel LLM par run** |

Le point décisif est le garde-fou. Un garde-fou écrit dans un prompt est une **supplication** ;
un garde-fou écrit dans la structure du graphe est une **garantie**. Sur un sujet où la promesse est
« l'agent propose, l'humain décide », c'est structurant.

**D'où P1** : *le graphe contrôle le flux, le LLM ne fait que raisonner*. Un seul node appelle le LLM
(`Diagnose`). Les six autres sont du code déterministe, testables sans mock.

**Le prix payé** — à assumer : l'agent est **moins souple**. Il ne saura pas gérer une classe d'anomalies
pour laquelle aucun chemin n'existe dans le graphe. C'est un choix : on échange de la généralité contre
de la gouvernabilité. Pour un système qui touche à la donnée, c'est le bon sens de l'échange.

→ ADR `004-langgraph-vs-function-calling.md`

---

## 3. Pourquoi le LLM ne voit-il jamais les données brutes ?

Trois raisons, dans l'ordre d'importance :

1. **Confidentialité.** Des données d'entreprise ne partent pas chez un fournisseur tiers. C'est
   rédhibitoire chez Tython, pas une préférence.
2. **Coût et contexte.** 100k lignes ne tiennent pas dans une fenêtre de contexte, et n'ont aucune raison
   d'y tenir.
3. **Qualité du raisonnement.** Un LLM raisonne *mieux* sur `{"ville": {"cardinalité": 812, "top": [["sao paulo", 1240], ["são paulo", 890]]}}`
   que sur 100k lignes brutes. L'agrégat *est* le signal ; le reste est du bruit.

**Conséquence de design** : le node `Profile` n'est pas un préliminaire, c'est le **traducteur** entre le
monde des données et le monde du LLM. La qualité du profiling plafonne la qualité du diagnostic.

**L'échappatoire, encadrée** : `run_sql` en lecture seule permet d'aller chercher un échantillon si le
diagnostic l'exige — journalisé, masquable, jamais par défaut.

**L'option zéro-fuite** : Snowflake Cortex. Les données ne quittent jamais Snowflake. C'est la réponse si
l'entreprise refuse tout appel externe — et une des raisons du choix Snowflake vs DuckDB (HG12/HG14).

---

## 4. Comment détecter une anomalie *sémantique* ?

Le cœur technique du projet, et **son morceau le plus délicat**.

### 4.1 Le problème

`sao paulo`, `são paulo`, `sao paulo - sp` sont trois valeurs distinctes pour une base, et une seule pour un humain.
Aucune règle de format n'est violée. Le symptôme n'apparaît qu'**en aval** : un `GROUP BY city` en Gold
produit trois lignes là où il en faut une → **fan-out**, agrégats faux.

### 4.2 L'approche

Sur les colonnes catégorielles, à partir du profil :

1. **Normaliser** les valeurs (casse, accents, espaces, ponctuation).
2. **Regrouper** les valeurs dont la forme normalisée collide, ou dont la distance d'édition est faible.
3. **Signaler** un cluster de cardinalité > 1 comme anomalie sémantique candidate.
4. **Faire raisonner le LLM** sur le cluster (pas sur les lignes) pour qualifier : vraie anomalie, ou
   distinction métier légitime ?

L'étape 4 est le point important. Les étapes 1–3 sont du code déterministe et produisent des
**candidats** ; le LLM **qualifie**. `Detect` ne l'appelle pas (P1) — il prépare le terrain, et
`Diagnose` tranche.

### 4.3 Les limites, assumées

- **Ça ne se généralise pas.** L'approche vise la classe d'anomalies du `ground_truth.yaml`. Elle ne
  détectera pas une incohérence sémantique d'un autre genre (ex. un montant en euros mélangé à des dollars
  sans colonne de devise).
- **Les faux positifs sont réels.** `Paris` (ville) et `paris` (paris sportifs) collident à la
  normalisation. C'est exactement pourquoi le LLM qualifie — et pourquoi, in fine, **c'est un humain qui
  tranche** : un faux positif coûte un clic « Refuser », pas une correction erronée.
- **La distance d'édition est naïve** sur les langues à forte flexion.

> **Un détecteur modeste et lucide vaut mieux qu'un détecteur ambitieux et faux.** Ces limites vont dans
> la section « limites connues » du rapport — pas dans un tiroir.

---

## 5. Pourquoi la validation humaine systématique (et pas un score d'autonomie) ?

### 5.1 L'alternative écartée

La v3 du projet prévoyait un routage à trois branches : action autonome si `confiance ≥ 0.85` et
`risque < 0.30` en DEV/TEST, validation humaine en zone grise, escalade sinon — avec les seuils dans un
`policy.yaml` (policy-as-code). C'était défendable, mais la v4 l'a **délibérément abandonné**. Trois
raisons :

**a) Le scoring était la partie la plus fragile à calibrer.** La confiance est auto-déclarée par le LLM
(juge et partie) ; le score de risque exigeait une formule pondérée (`impact × distance × breadth`) dont
les poids étaient, honnêtement, arbitraires. Beaucoup de complexité pour une frontière DEV/TEST où
l'autonomie n'a de toute façon presque aucune valeur.

**b) La garantie structurelle est plus forte que la garantie configurée.** Avec une policy, la réponse à
« quand l'agent agit-il seul ? » dépend d'un YAML qu'un commit peut changer. Sans branche autonome, la
réponse est **topologique** : le graphe ne contient aucun chemin `Diagnose → Apply`. Ce n'est pas une
règle qu'on applique, c'est un chemin qui n'existe pas.

**c) Le vrai gain de l'agent n'est pas d'agir — c'est de diagnostiquer.** Le temps est dans le
diagnostic (MTTR, §1.2b), pas dans l'exécution de la normalisation de `city`, qui prend trente secondes une fois la
cause connue et la correction écrite. Automatiser l'exécution optimisait la mauvaise étape.

### 5.2 Ce qu'on gagne, ce qu'on perd

| | HITL pur (v4) | Scoring d'autonomie (v3) |
|---|---|---|
| Garantie | Structurelle (topologie du graphe) | Configurée (policy.yaml) |
| Complexité | 7 nœuds, zéro seuil à calibrer | 13 nœuds, 2 scores, 5 lignes de matrice |
| Latence de correction | Attend un humain, toujours | Immédiate dans les cas sûrs (DEV/TEST) |
| Risque résiduel | Le « rubber-stamping » humain | Un score mal calibré qui auto-applique à tort |

Le prix payé est la latence : même une correction triviale attend un clic. Pour un POC de stage — et,
en vérité, pour la plupart des équipes data en production — c'est le bon échange. Et le risque de
« rubber-stamping » (approuver sans lire) est mitigé par le contenu de la proposition (cause + impact +
incidents passés) et **mesuré** par le taux d'approbation au benchmark.

### 5.3 La question du jury, anticipée

*« Votre agent n'est donc qu'un système de suggestion ? »* — Oui, et c'est revendiqué : suggestion
**diagnostiquée, outillée et tracée**. La détection trouve ce que les règles ratent, le diagnostic fait
gagner le MTTR, la mémoire accélère les récidives — et l'application, seule étape dangereuse, reste
humaine. Un système qui propose juste et vite vaut mieux qu'un système qui agit seul et se trompe
rarement mais irrattrapablement.

→ ADR `008-hitl-pur-vs-scoring.md`

---

## 6. Design de la mémoire

### 6.1 L'idée (noyau)

La mémoire du noyau est **la table `INCIDENTS` elle-même** — pas un composant de plus. Au début de
`Diagnose`, l'agent requête les incidents passés **ayant reçu une décision humaine** sur la même table ou
le même type d'anomalie, et les injecte dans le contexte du LLM : *« cas similaire le J-12, cause X,
correction Y approuvée »*.

C'est volontairement du SQL simple : pas d'embeddings, pas de store vectoriel, zéro infrastructure. Le
rappel par similarité **sémantique** (une anomalie « qui ressemble » sans être identique) est
l'**extension E1** : vectorisation dans Chroma, tool `search_past_incidents`. Le noyau démontre le
concept ; l'extension le généralise.

### 6.2 La règle non négociable

> **`Diagnose` ne relit que les incidents ayant reçu une décision humaine.**

Un agent qui apprend de ses propres hallucinations est une **régression**, pas une amélioration : il se
renforce dans l'erreur. Les incidents refusés sont eux aussi informatifs (« cette correction a été
refusée, n'y reviens pas ») — mais un diagnostic jamais validé n'entre pas dans le contexte. C'est la
première question qu'un jury posera sur cette feature.

### 6.3 Ce qui compte comme preuve

Pas le fait que « la mémoire marche ». La preuve est **chiffrée** :

- Passage 1 sur l'anomalie : pas d'antécédent, diagnostic complet, durée **T1**.
- Passage 2 sur la **même** anomalie : l'antécédent est retrouvé, durée **T2 < T1**, et le diagnostic
  cite l'incident précédent.
- L'écart T1 → T2 est **reproductible**.

C'est pourquoi le jeu de données contient **deux livraisons** (J1, J2) dès la phase 1 : sans elles, le
gain mémoire n'est pas mesurable.

---

## 7. Design de la cause racine (lineage)

### 7.1 Pourquoi pas OpenMetadata

Parce que dbt **a déjà le graphe de dépendances**, dans `manifest.json`. Le parser donne le lineage
inter-modèles pour un coût quasi nul.

OpenMetadata apporterait un catalogue, une UI, du lineage cross-outils — dont le projet n'a pas besoin
pour O8. Déployer un catalogue pour lire un graphe qu'on possède déjà, c'est de l'outillage qui déplace
le projet loin de sa promesse. **E5 reste en perspective** (recentrage sur l'agent).

Limite assumée : le lineage s'arrête aux frontières de dbt. Une transformation faite dans l'ingestion
Python est invisible. Acceptable ici, puisque l'ingestion est volontairement **brute** (aucune
transformation en Bronze) — la contrainte d'architecture rend la limite inoffensive.

### 7.2 Ce que ça débloque

1. **O8** — sur une casse Gold, remonter à la transformation Silver responsable → **MTTR**.
2. **L'impact affiché dans la proposition** — « 8 tables Gold dépendent de cette colonne » : c'est ce qui
   rend la décision humaine éclairée, pas un acte de foi.

---

## 8. Ce qui a été délibérément écarté

Un design se juge autant à ce qu'il refuse qu'à ce qu'il contient.

| Écarté | Pourquoi |
|--------|----------|
| **Scoring confiance × risque + action autonome** | Voir §5 — complexité de calibration élevée, garantie plus faible que la garantie topologique, et le gain (latence en DEV/TEST) ne vaut pas le coût. Décision v4. |
| **Policy-as-code** (`policy.yaml`) | N'existait que pour router l'autonomie. Sans branche autonome, plus rien à configurer — la « policy » est le graphe lui-même. |
| **Boucle de retry sur échec de validation** | Re-diagnostiquer automatiquement après un échec, c'est réessayer sans information nouvelle fiable. L'échec est journalisé et rendu à l'humain. |
| **Great Expectations** | dbt tests couvrent la baseline. Deux frameworks de qualité = de l'outillage, pas de la valeur (HG6). |
| **Dagster** | Airflow est open source et plus demandé sur le marché — un stage sert aussi à ça (HG10). |
| **DuckDB** | Snowflake apporte Streamlit natif et Cortex (LLM zéro-fuite). Le zéro-fuite, à lui seul, justifie le choix (HG12/HG14). |
| **Claude / GPT payants** | Un POC ne doit pas dépendre d'un budget. Groq/Cortex sont gratuits et suffisants (HG11). |
| **Agent ReAct autonome** | Voir §2 — non gouvernable, non testable, non auditable. |
| **OpenMetadata** | Voir §7.1 — dbt `manifest.json` suffit à O8. |
| **Big Data** | POC démontrable ≠ système à l'échelle. Rien à prouver là-dessus. |

---

## 9. Design du benchmark

### 9.1 Le seul design qui rend le benchmark honnête

Le `ground_truth.yaml` est écrit **en phase 1**, avant que l'agent existe.

Ce n'est pas un détail de planning, c'est une **précaution méthodologique**. Écrire la vérité terrain
après avoir vu ce que l'agent trouve, c'est l'adapter inconsciemment à ses résultats — et le benchmark ne
vaut alors plus rien. Précision et rappel n'ont aucun sens sans vérité terrain indépendante.

Même logique pour la baseline : les dbt tests statiques sont **figés et versionnés en phase 2**, avant
l'arrivée de l'agent. On ne rejoue pas la baseline après coup.

### 9.2 Le non-déterminisme

Un LLM ne donne pas deux fois la même réponse. Un run unique ne mesure rien.

**Chaque mesure est répétée ≥ 3 fois** → moyenne + écart-type. Un écart-type large est un résultat en soi :
il dit que l'agent est instable, ce qui est une information utile, pas un échec à masquer.

### 9.3 Les faiblesses, écrites par nous

- Échantillon modeste (~100k lignes, un domaine).
- Anomalies injectées **synthétiques** — plus propres et mieux séparées que le réel (le cas sémantique du fil rouge, lui, est réel — Olist).
- Non-déterminisme du LLM, atténué mais pas éliminé.
- Le MTTR « manuel » est estimé, pas mesuré sur une population de data engineers.
- Le **taux d'approbation** est mesuré avec un seul validateur (l'auteur) — biais évident, à nommer.
- La détection sémantique est ajustée à la classe d'anomalies du `ground_truth.yaml` — il y a un risque
  de sur-ajustement, à nommer.

> Un jury attaque toujours le benchmark. Le rapport doit dire lui-même où il est faible — sinon quelqu'un
> d'autre le dira, et ça coûte beaucoup plus cher.

---

## 10. Les hypothèses fragiles

Ce sur quoi le projet peut se casser. Nommé maintenant plutôt que découvert en phase 7.

| Hypothèse | Si elle est fausse | Mitigation |
|-----------|-------------------|------------|
| La détection sémantique par normalisation + distance attrape le cas cible | Le projet perd sa démonstration centrale | Le cas `sao paulo`/`são paulo` est vérifié **dès la phase 2** (la baseline doit le rater) et attaqué en phase 4, tôt |
| Le LLM produit une sortie parsable de façon fiable | `Diagnose` échoue en série | `PydanticOutputParser` + incident « à traiter manuellement » sur échec de parsing (jamais d'action sur un diagnostic incertain) |
| Le trial Snowflake couvre le projet | Perte d'une semaine en plein milieu | Tranché en phase 0 → ADR `001` |
| `manifest.json` suffit au lineage | O8 s'effondre | Lineage minimal validé tôt ; O8 est 🌟, coupable |
| L'`interrupt` + checkpointer LangGraph tient la pause sur des heures | Le HITL devient une démo fragile | Testé tôt (phase 3, stub) ; c'est un mécanisme documenté et standard de LangGraph |
| Les gains sont mesurables sur le montage hybride (réel + injecté) | Le benchmark ne montre rien | Anomalies **conçues** pour être discriminantes ; limite documentée |

---

## 11. La ligne à ne pas franchir

S'il ne fallait retenir qu'une chose de ce document :

> **Tout ce qui décide est soit du code testable, soit un humain. Le LLM ne fait que raisonner, une
> fois, sur des agrégats — et rien ne s'applique sans un clic humain.**

Chaque fois qu'une décision de design s'est présentée, c'est ce principe qui a tranché : un seul node LLM,
une pause de validation inscrite dans la topologie du graphe, des garde-fous dans le code plutôt que dans
le prompt, un journal append-only.

C'est ce qui permet de dire *« l'agent propose, l'humain décide, tout est tracé »* sans que ce soit un
slogan.
