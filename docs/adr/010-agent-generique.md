# ADR 010 — Un agent générique : deux cycles, contrats versionnés, 8 nœuds

**Date** : 2026-07-28 (décisions) · 2026-08-03 (rédaction, en fin de phase 3) · **Statut** : accepté
**Complète** : [ADR 008](008-hitl-pur-vs-scoring.md) (HITL pur) · **Impacte** : phases 3 à 6, 8 et 9

## Contexte

Fin de phase 2 : le pipeline Medallion tourne, la baseline dbt est figée, l'agent va être écrit.
En relisant la spécification, un problème apparaît — tel que décrit, l'agent aurait été **cousu main
pour Olist** : noms de tables en dur, règle de normalisation écrite pour `geolocation_city`, seuils
choisis en regardant les données.

Or un agent qualité qui ne fonctionne que sur un dataset n'est pas un agent qualité, c'est un script.
La question posée par un jury serait immédiate : *« et si je vous donne une autre base ? »*

Olist doit redevenir un **cas de test**, pas le sujet.

Cinq décisions en découlent. Elles ne remplacent rien de la v4 : elles s'y ajoutent.

---

## Décision 1 — Deux cycles au lieu d'un

### Options envisagées

- **(a) Un seul cycle.** Le graphe fait tout à chaque batch : introspection, profilage, détection.
  Simple, mais il faudrait ré-introspecter la base à chaque exécution, et surtout l'agent n'aurait
  **aucune référence** de ce qui est normal — il ne saurait comparer qu'à l'historique statistique.
- **(b) Deux cycles.** Un cycle *Découverte*, hors DAG, exécuté une fois par table : il introspecte,
  profile une fenêtre de référence, classe les colonnes et propose un **contrat**. Un cycle
  *Surveillance* — le graphe — à chaque batch.

### Décision

**Option (b).** `scripts/discover.py <dataset>` produit un contrat validé par l'humain ; le graphe le
charge au runtime.

### Pourquoi

Ce que « normal » veut dire ne se déduit pas d'un seul lot. Il faut une période d'observation, et
surtout un moment où **un humain regarde et valide** — c'est là que le métier entre dans le système.

---

## Décision 2 — Zéro nom de table ou de colonne en dur

### Décision

Aucun nom de table ni de colonne n'apparaît dans `agent/`, **pas même en exemple dans un commentaire**.
Tout vient d'`INFORMATION_SCHEMA` et du contrat. Les noms de datasets vivent dans `datasets/*.yaml`,
les noms de colonnes dans les tests et les contrats.

La détection s'appuie sur des **rôles de colonne inférés** (identifiant, clé étrangère, catégoriel,
numérique, temporel, texte libre), chacun appelant ses propres contrôles.

### Conséquence sur le fil rouge

`sao paulo` / `são paulo` n'est **pas** attrapé par une règle écrite pour cette ville, mais par la
détection de collisions sémantiques appliquée à *toute* colonne classée catégorielle. C'est ce qui
transforme une astuce en méthode.

### Comment on l'a rendu vérifiable

Un test de portabilité (`test_agent_nodes.py`) branche deux datasets volontairement étrangers l'un à
l'autre — des commandes et des salaires — sur les mêmes nœuds. S'il devient rouge parce qu'un nom de
colonne s'est glissé dans `agent/`, l'agent a cessé d'être portable.

### Ce qui reste déclaré, et qu'on assume

Trois choses ne sont pas inférables et doivent être écrites par un humain :

- la **colonne de batch** de chaque table ;
- la **liste des tables** à surveiller ;
- les **règles métier**, injectées à la validation du contrat.

Le prétendre autrement serait malhonnête.

---

## Décision 3 — Le contrat versionné, 3ᵉ pilier de détection

### Options envisagées

- **(a) Deux piliers** : dérive statistique (historique) + dbt tests. C'est la v4.
- **(b) Trois piliers** : ajout d'un **contrat YAML** décrivant ce qui *devrait* être vrai.

### Décision

**Option (b)**, avec deux exigences qui ne sont pas négociables.

**Le contrat est construit sur une période de référence propre.** Chez Olist : J1→J44, c'est-à-dire
*avant* la première anomalie injectée (J45). Sinon il apprendrait les anomalies comme normales.

**Le contrat est versionné, jamais figé.** D'où le nœud `Amend` (décision 4).

### Le piège identifié : descriptif ↔ normatif

Un contrat auto-généré naïvement enregistre ce qu'il observe. Sur `geolocation_city`, il graverait
`sao paulo` **et** `são paulo` comme deux valeurs légitimes — et le cas d'école du projet serait perdu
avant même d'avoir commencé.

La découverte doit donc **critiquer** ce qu'elle trouve, pas seulement l'enregistrer : elle fait
tourner la détection de collisions *pendant* la découverte. Clause attendue :
`cardinalité_normalisée == cardinalité_brute`.

C'est aussi pourquoi la validation humaine est indispensable : les bornes proposées sont *descriptives*
(« observé entre 1 et 100 »), l'humain les rend *normatives* (« oui, 100 est une vraie borne métier »).

### Option écartée

**« Découverte une seule fois, puis contrat figé »** — rejetée pour deux raisons : le contrat
deviendrait obsolète à la première évolution du métier, et le piège descriptif ↔ normatif ne serait
jamais corrigé.

---

## Décision 4 — Le graphe passe à 8 nœuds, `Propose` a 3 issues

### Contexte

Avec un contrat, une situation nouvelle apparaît : **la donnée est juste, c'est la règle qui a
vieilli**. Un nouveau moyen de paiement, une borne métier qui bouge. Avec deux issues seulement, il
faudrait répondre « refusé » — et l'agent recrierait au batch suivant.

### Décision

Ajout du nœud **`Amend`**. `Propose` a trois issues :

| Décision | Ce que ça veut dire | Effet |
|---|---|---|
| `approved` | la donnée est fausse | `Apply` écrit dans les **données** |
| `amend_contract` | la règle a vieilli | `Amend` écrit dans le **contrat** (v1 → v2), **rien** dans les données |
| `rejected` | cas isolé, rien à changer | `Log` seul ; la signature est mise en silence |

`Amend` est le miroir d'`Apply`, et le **mécanisme anti-obsolescence** du contrat : sans lui, un contrat
figé crie à chaque évolution normale du métier, l'équipe s'habitue à ignorer les alertes, et l'agent
meurt de son bruit.

### Garantie conservée

**`Amend` ne mène jamais à `Apply`.** Amender une règle ne donne aucun droit d'écriture sur les
données. C'est vérifié topologiquement (une seule arête entre dans `Apply`, étiquetée `approved`) et
à l'exécution (test P3, `tests/test_agent_graph.py`).

### Garde-fou anti-cécité

Une signature mise en silence n'est pas effacée : tout reste en base, la liste est requêtable et sera
affichée dans Streamlit (phase 6), **réactivable d'un clic**. Sans cet écran, l'agent deviendrait
progressivement muet sans que personne ne s'en aperçoive.

---

## Décision 5 — L'agent n'invente jamais une valeur

### Contexte

Face à `8000` dans une colonne dont les valeurs vont de 1 à 100, l'agent **ne peut pas savoir** s'il
s'agit de 80,00 € saisis en centimes, d'une faute de frappe, ou d'une vraie grosse commande.

Proposer « remplacer 8000 par 80 », c'est **fabriquer de la donnée qui n'a jamais existé**.

### Décision

Ce garde-fou est placé **au même rang que le HITL** — c'est l'invariant P6 de l'architecture.

| Correction | Autorisée |
|---|---|
| isoler en quarantaine | ✅ |
| mettre à NULL + marquer | ✅ |
| exclure d'un agrégat Gold (la valeur brute reste intacte en Bronze) | ✅ |
| **substituer une valeur devinée** | ❌ rejetée par `Apply` **même après approbation humaine** |

Proposition par défaut sur une valeur aberrante : *isoler + exclure de l'agrégat*, jamais *remplacer*.

### La nuance assumée

Cette règle contraint l'**agent**, pas l'humain. L'agent ne peut pas savoir si `8000` valait `80` ;
l'humain, lui, peut avoir appelé le fournisseur. Il a l'autorité pour affirmer une valeur — via le
champ `fix_override`, qui trace que la correction appliquée n'était pas celle proposée.

Les autres garde-fous d'`Apply` (table unique, mots-clés destructeurs) restent actifs dans les deux
cas : ils protègent contre l'accident, pas contre le jugement.

---

## Décisions prises pendant la réalisation (phase 3)

Trois choix se sont imposés en écrivant le code. Consignés ici tant qu'ils sont frais.

### Les contrats vivent dans git, pas dans Snowflake

`contracts/<table>.vN.yaml`, versionnés dans le dépôt. Git donne gratuitement l'historique, le diff, le
retour arrière et la relecture — il faudrait tout réinventer dans une table. C'est aussi le choix du
métier : dbt, Great Expectations et Soda mettent tous leurs règles dans des fichiers versionnés.

**Limite connue, non résolue à ce jour.** Ces outils ont des règles écrites *par des humains* dans un
flux de pull request. Ici, `Amend` écrit un fichier *pendant une exécution* — dans un conteneur Docker,
sur une machine qui n'est pas celle du dépôt. **Qui fait le commit ?** Deux mesures :

1. `Amend` journalise aussi le diff de clause dans `OPS.INCIDENTS` — si le fichier se perd, la décision
   n'est pas perdue et le contrat est reconstructible ;
2. le commit reste **manuel**, ce qui est cohérent avec l'esprit du projet : un contrat amendé est une
   décision importante, la relire avant de la graver n'est pas une corvée.

À réexaminer en phase 5.3, quand `Amend` deviendra réel.

### Groq plutôt que Snowflake Cortex

Groq est gratuit, validé en phase 0, et la règle R2 fait que le modèle ne reçoit que des agrégats.
Cortex — l'option « les données ne quittent jamais Snowflake » — reste identifié comme alternative.

`agent/llm.py` isole la totalité de la frontière réseau : le mot `groq` n'apparaît que dans deux lignes
de code de tout le projet. La bascule coûterait une trentaine de lignes dans un seul fichier, sans
toucher aux nœuds, au graphe ni aux tests.

**Point de bascule identifié** : en phase 4, la détection de collisions sémantiques enverra les **top-K
valeurs** des colonnes catégorielles — donc de vraies valeurs de la base, et non plus des chiffres
abstraits. C'est là que la question se reposera sérieusement. Elle se reposera aussi si une contrainte
de confidentialité réelle apparaît (entreprise, données sensibles).

> **Le point de bascule a été atteint le 2026-08-04**, avec le tool `top_values` (étape 4.1.2) — voir
> la **décision 9b** plus bas. Groq est maintenu, mais l'argument « il n'y a rien à fuiter » ne tient
> plus : il est remplacé par un raisonnement sur la nature des colonnes interrogées.

### Mode JSON natif plutôt que `PydanticOutputParser`

Le plan prévoyait `PydanticOutputParser` (LangChain). Retenu à la place : le mode JSON natif de Groq
(`response_format={"type": "json_object"}`) **plus** la validation Pydantic.

Le parser injecte des consignes de format dans le prompt puis parse la réponse ; le mode JSON
**empêche le format invalide d'exister**. Les deux barrières sont conservées et couvrent des risques
différents — l'API garantit un JSON *valide*, Pydantic garantit que c'est le *bon* JSON (un modèle peut
renvoyer `cause` au lieu de `root_cause`, ou omettre un champ).

---

## Décision 6 — Pouvoir discuter avant de décider (2026-08-03)

### Contexte

Trois issues, trois boutons. Le `DESIGN.md` anticipe déjà la question de jury qui va avec : *« et si
l'humain approuve sans lire ? »*. Un validateur à qui on ne laisse que trois boutons approuve vite, et
le HITL devient un tampon plutôt qu'un contrôle.

### Options envisagées

- **(a) Décision en texte libre.** L'humain écrit ce qu'il veut, l'agent interprète. Écarté : `route_after_propose`
  devrait *deviner* ce qui a été voulu dire — exactement ce que le projet s'interdit partout ailleurs.
  Et `INCIDENTS` ne pourrait plus servir à calculer la précision au benchmark.
- **(b) `propose` répond lui-même aux questions.** Écarté : `propose` appellerait le LLM, et la règle R1
  (« le LLM n'est appelé que dans `Diagnose` ») tomberait. Deux nœuds en contact avec le modèle, c'est
  deux endroits à auditer, à simuler en test et à surveiller.
- **(c) Une 4ᵉ issue `question` qui renvoie à `Diagnose`.**

### Décision

**Option (c).** `Propose` gagne une quatrième réponse qui **n'est pas une décision** : elle ne clôt
rien, elle diffère. La question repart à `Diagnose`, la réponse revient, la proposition attend de
nouveau. C'est la seule branche du graphe qui **remonte**.

La décision finale reste l'un des trois mots : c'est elle qui route le graphe, qui est enregistrée, et
qui sert au benchmark.

### Ce que ça préserve

**P3 est intact.** `Apply` garde son unique arête entrante, étiquetée `approved`. Discuter ne rapproche
pas de l'écriture — un test le vérifie après cinq questions, et la topologie le garantit pour toute
exécution.

**R1 est intacte.** Un seul nœud parle au modèle. `agent/llm.py` gagne une seconde fonction
(`repondre`), mais elle est appelée depuis `diagnose`, comme la première.

### Garde-fous

- **Plafond de 10 échanges.** Sans lui, la boucle `propose → diagnose → propose` peut tourner sans fin —
  notamment si le modèle est en panne et répond « je ne peux pas » à chaque tour. Au-delà, le run se
  clôt **sans décision** : rien n'écrit, tout est journalisé, l'humain relance un run.
- **Une question vide n'en est pas une** — sinon `human_decision` resterait à `question` et le graphe
  boucherait sans que personne n'ait parlé.
- **Le diagnostic n'est pas retouché** pendant le dialogue. Si le modèle le réécrivait à chaque échange,
  la proposition changerait sous les yeux de l'humain pendant qu'il réfléchit. Réviser un diagnostic sur
  objection est une autre fonctionnalité, à traiter en phase 5 si elle s'avère utile.

### Ce que ça apporte au projet

Le dialogue est conservé dans l'état, donc dans le journal, donc dans `INCIDENTS`. On pourra montrer non
pas « l'humain a approuvé », mais « l'humain a posé deux questions, obtenu ces réponses, **puis**
approuvé ». C'est une meilleure réponse à *« et s'il approuve sans lire ? »* qu'un taux d'approbation.

## Décision 7 — La couture plutôt que la classe abstraite (2026-08-03)

### Contexte

L'étape 4.0 prévoyait `agent/connectors/base.py` : une interface abstraite (`list_tables`,
`get_schema`, `profile`) dont Snowflake serait la première implémentation, « les autres » suivant plus
tard. En l'écrivant, deux vérifications ont fait tomber la prémisse :

- **Postgres** ne viendra pas : l'[ADR 009](009-source-hybride-olist.md) l'a explicitement écarté ;
- **l'API REST/FastAPI de l'objectif O1 n'est pas un connecteur d'agent** — c'est une source
  d'*ingestion*, consommée par `ingestion/`, qui alimente Bronze. L'agent ne lira jamais cet endpoint :
  il lit ce qui a atterri dans `RAW`. Confusion de catégorie, corrigée dans `PROGRESS.md`.

Le projet n'a donc, dans son périmètre réel, **qu'un seul backend : Snowflake**. Écrire une classe
abstraite pour une implémentation unique, c'est de la généralisation spéculative : payer aujourd'hui
une souplesse dont on ne connaît pas encore la forme, et deviner probablement de travers.

### Options envisagées

- **(a) L'interface abstraite tout de suite.** Conforme au plan, mais une seule implémentation : la
  forme de l'abstraction serait devinée, pas constatée.
- **(b) La couture seule.** Tout le SQL vit sous `agent/connectors/`, un test échoue s'il en apparaît
  ailleurs. Pas d'héritage, pas de classe de base.
- **(c) L'interface + un second connecteur réel (CSV/pandas).** L'abstraction serait *validée* par deux
  implémentations au lieu d'être supposée. Coût : ~1 jour.

### Décision

**Option (b).** `agent/connectors/__init__.py` tient une fabrique (nom → connecteur) et documente le
contrat des trois méthodes ; `agent/connectors/snowflake.py` est le seul fichier de `agent/` où du SQL
a le droit d'exister.

### Pourquoi

Ce qui protège la propriété « l'agent ne connaît pas sa base », ce n'est pas l'héritage — une classe de
base n'empêche personne d'ouvrir une connexion à côté. C'est le test
`test_aucun_sql_hors_des_connecteurs`, qui relit tout `agent/` à chaque exécution de la suite. La
discipline qu'aurait imposée l'abstraction est imposée par un test, et un test ne se contourne pas par
distraction.

Détail qui compte : `profile()` reçoit `(batch_column, batch_id)` et **jamais un fragment de SQL**. Si
l'appelant passait `"_batch_id = '2018-04-29'"`, du SQL existerait au-dessus de la couture — soit
exactement ce que le socle sert à empêcher.

### Ce que ça coûte, et qu'on assume

La promesse de généricité change de portée. Ce qui est **démontré** aujourd'hui : l'agent est portable
d'un *schéma* à l'autre — le test de généricité branche un dataset RH étranger à Olist via un connecteur
en mémoire, sans qu'une ligne de `agent/` change. Ce qui reste **argumenté et non démontré** : la
portabilité d'un *backend* à l'autre.

L'option (c) reste ouverte et bon marché. C'est le seul endroit de la phase 4 où un jour de travail
achète une réponse de soutenance en direct plutôt qu'une explication.

### Ce qu'il faudra surveiller

Le jour où un second backend arrive, extraire l'interface est un refactor mécanique d'un seul fichier,
parce que la couture est déjà là. Si le refactor s'avère douloureux, c'est que du SQL avait fui — et le
test l'aura dit avant.

## Décision 8 — La mémoire de l'agent n'est pas derrière le connecteur (2026-08-03)

### Contexte

Deux bases jouent deux rôles différents, et les confondre était facile : le **système observé** (ce que
le connecteur lit) et la **mémoire de l'agent** (`OPS._SCHEMA_HISTORY`, `OPS._PROFILES`,
`OPS.INCIDENTS`).

### Décision

`OPS` ne passe pas par le connecteur, et `list_tables()` l'exclut explicitement.

### Pourquoi

Deux conséquences, l'une immédiate, l'autre structurelle :

- **immédiate** — sans exclusion, la famille *inventaire* (4.3) verrait `INCIDENTS` et `_PROFILES`
  comme des « tables nouvelles non déclarées » à chaque run : l'agent se découvrirait lui-même,
  indéfiniment ;
- **structurelle** — si la mémoire suivait le connecteur, surveiller une base Postgres voudrait dire y
  écrire ses incidents. La mémoire se fragmenterait en autant de bases que de datasets, et l'objectif
  O7 (« l'agent se souvient ») n'aurait plus de lieu où s'exercer.

Le connecteur lit ce qu'on surveille ; la mémoire reste là où l'agent vit.

## Décision 9 — Le top-K entre au contrat, et R2 y change de nature (2026-08-04)

### Contexte

L'étape 4.1.2 ajoute `top_values` : les *K* valeurs les plus fréquentes d'une colonne. Ce n'est pas un
tool de plus — c'est celui **sans lequel aucune détection sémantique n'existe**. Le profil sait déjà
qu'une colonne porte 8 000 villes distinctes ; il ne sait pas *lesquelles*. Or `sao paulo` et
`são paulo` sont, pour un compteur, deux unités parfaitement indiscernables.

Deux questions se posaient en même temps, et elles n'ont pas la même nature.

### Décision 9a — une 4ᵉ méthode plutôt qu'un enrichissement de `profile`

Le contrat des connecteurs passe de trois méthodes à quatre :
`top_values(table, column, k, batch_column, batch_id)`.

L'alternative était de faire remonter le top-K depuis `profile`, en une passe. Elle a été écartée sur
un argument de **coût**, pas de style : `profile` fait *un* passage sur la table et rend la même chose
pour toutes les colonnes ; un top-K coûte un `GROUP BY` **par colonne**. L'imposer à toutes
multiplierait le coût du profilage par le nombre de colonnes — pour un résultat sans le moindre
intérêt sur un identifiant (K valeurs de fréquence 1) ou sur du texte libre. Deux opérations qui ne se
paient pas au même prix ne se demandent pas ensemble.

Conséquence assumée : quelles colonnes méritent un top-K devient une **décision d'appelant**. Le
critère provisoire (« texte, faible cardinalité ») est celui de 4.1 ; le vrai viendra de la
caractérisation par rôle en 4.2.

### Décision 9b — R2 tient, mais plus pour la même raison

C'était le point de bascule annoncé plus haut dans cet ADR, à propos de Groq et de Cortex. Jusqu'ici,
tout ce qui remontait de la base était un **chiffre** : comptes, cardinalités, bornes. R2 (« le LLM ne
reçoit jamais de lignes brutes ») était vraie *structurellement* — il n'y avait rien à fuiter.
`top_values` rend de **vraies valeurs**.

R2 n'est pas enfreinte : une valeur accompagnée de sa fréquence est une **distribution**, pas une
ligne. On ne recompose pas un client à partir de `{"sao paulo": 8 412}`. Mais la garantie a changé de
nature — elle était structurelle, elle devient **conditionnelle** : elle ne tient que tant qu'on
interroge des colonnes *catégorielles*. Le top-K d'un nom, d'une adresse ou d'un e-mail serait une
fuite, et rien dans le type de la colonne ne l'annonce.

Trois mesures, du plus fort au plus faible :

1. **une seule colonne nue dans la projection**, et elle est groupée. Une seconde colonne au `SELECT`
   rendrait les lignes recomposables : ce ne serait plus une distribution, ce serait un extrait de
   table. Un test le vérifie sur le SQL émis (`test_top_values_ne_projette_que_la_colonne_demandee`),
   comme le test anti-fuite SQL de 4.0 ;
2. **`coverage` est rendu avec la réponse** — la part des lignes que le top-K couvre. Proche de 1,
   quelques valeurs décrivent la colonne : elle est catégorielle. Proche de 0, c'est une longue traîne,
   donc du texte libre ou un identifiant, et ses valeurs n'ont rien à faire dans un prompt ;
3. **le tool ne se censure pas lui-même**. Il constate `coverage` et rend ce qu'il a lu ; c'est la
   caractérisation (4.2) qui choisit les colonnes à interroger, et `detect` qui décide de ce qui monte
   vers `diagnose`. Un tool qui déciderait tout seul de se taire cacherait un fait à `detect`.

### Ce qu'il faudra surveiller

- **Le moment Cortex.** La question « les données ne quittent jamais Snowflake » ne se posait pas tant
  que le modèle ne voyait que des chiffres. Elle se pose maintenant pour de bon. Elle reste tranchée
  en faveur de Groq — les colonnes visées sont des villes, des statuts, des catégories de produits —
  mais l'argument « il n'y a rien à fuiter » n'est plus disponible, et il ne faut pas continuer à
  l'invoquer.
- **La mesure 2 est un signal, pas une barrière.** Rien n'empêche aujourd'hui un appelant de demander
  le top-K d'une colonne à `coverage` de 0,02 et de l'envoyer au modèle. C'est 4.2 qui doit rendre ce
  chemin impossible en ne classant jamais une telle colonne comme catégorielle. Tant que 4.2 n'est pas
  écrite, la garantie repose sur l'appelant — et c'est à dire, pas à masquer.

### Décision 9c — `close()` reste hors du contrat

`top_values` est le premier tool à ouvrir un connecteur, donc le premier à devoir le refermer. Exiger
`close()` de tout connecteur obligerait chaque implémentation en mémoire à écrire une méthode vide,
pour un besoin qui ne concerne que celles qui tiennent une session. Les appelants passent donc par
`connectors.fermer(connecteur)`, qui ferme si le connecteur sait le faire. La règle vit à un seul
endroit au lieu d'être re-décidée dans chaque tool.

## Décision 10 — Le contrat se lit en deux familles, et la mesure ne se corrige pas (2026-08-04)

### Contexte

L'étape 4.1.3 ajoute `robust_stats` (médiane + MAD). C'est la **deuxième** méthode ajoutée au contrat
des connecteurs en deux étapes, et 4.1.4 (fraîcheur) en ajoutera une troisième. Défendre chaque ajout
au cas par cas finirait par ne plus rien défendre du tout : il fallait une ligne, pas une suite
d'exceptions.

### Décision 10a — méthodes de table, méthodes de colonne

Le contrat se lit désormais en deux familles, et ce qui les sépare est le **coût** :

| Famille | Méthodes | Coût |
|---|---|---|
| **de table** | `list_tables`, `get_schema`, `profile` | un balayage, tout ce qu'on en tire d'un coup |
| **de colonne** | `top_values`, `robust_stats` | une requête **par colonne**, donc à la demande |

C'est la généralisation de la décision 9a, et elle répond d'avance à la question « jusqu'où le contrat
va-t-il grossir ? » : une méthode de colonne s'ajoute quand une mesure coûte un passage dédié *et* n'a
de sens que sur certaines colonnes. Un top-K coûte un `GROUP BY` par colonne ; une médiane coûte un
tri. Les imposer à toutes multiplierait le coût du profilage par le nombre de colonnes, pour un
résultat sans intérêt (le top-K d'un identifiant) ou impossible (la médiane d'un texte libre).

Conséquence, déjà assumée en 9a et qui vaut pour toute la famille : **quelles colonnes méritent quelle
mesure est une décision d'appelant**, et le vrai critère viendra de la caractérisation par rôle (4.2).

### Décision 10b — la mesure constate, elle ne se corrige pas

Une colonne constante sur un lot a un MAD nul. En 4.3, comparer le jour à l'historique en divisant par
le MAD produira une division par zéro — et la roadmap prévoit depuis le début un **plancher** pour ce
cas.

Ce plancher n'est **pas** appliqué dans la mesure. `robust_stats` rend `mad: 0.0`, parce que c'est ce
qui a été observé. Le plancher est un réglage de *détection* : il appartient à `detect`, avec les
seuils, et il rejoindra `agent/config.py`.

La règle générale, qui vaut aussi pour `coverage` en 9b et pour le `k` de `top_values` :

> **Une mesure qui se corrige elle-même ment sur ce qu'elle a vu.** Un lecteur du profil ne peut plus
> distinguer « la colonne est constante » de « la colonne varie très peu », et l'information est perdue
> pour toujours — y compris pour les usages qu'on n'a pas prévus.

### Ce que ça coûte, et qu'on assume

`detect` devra penser au plancher, et rien ne l'y oblige aujourd'hui. C'est un report volontaire, pas
un oubli : la roadmap 4.3 le porte déjà noir sur blanc, et le premier calcul d'écart le rencontrera.
La garantie est faible tant que 4.3 n'est pas écrite — c'est à dire, pas à masquer.

### Trois pièges techniques rencontrés, consignés parce qu'ils se reproduiront

1. **`TRY_CAST` de Snowflake n'accepte qu'une source texte.** L'appliquer à une colonne déjà `NUMBER`
   lève. Le type est lu dans `INFORMATION_SCHEMA` — qu'on interroge de toute façon pour résoudre la
   casse — et le cast n'est posé que sur du texte. Un connecteur Postgres devra faire l'inverse
   (`::numeric` échoue là où Snowflake tolère), donc la logique reste sous la couture.
2. **Le MAD a besoin de la médiane avant de pouvoir se soustraire.** `MEDIAN(...) OVER ()` la répète
   sur chaque ligne en un seul balayage, au lieu d'une seconde requête pour aller la chercher.
3. **`SUM` sur zéro ligne rend `NULL`, pas `0`.** Sur un lot vide, `int(None)` tuerait le run — celui-là
   même qui devrait signaler que le lot est vide.

### Un effet de bord utile : le VARCHAR de Bronze devient un signal

Bronze est en texte par construction (phase 2.1), donc les nombres y sont *écrits*. `TRY_CAST` rend
`NULL` sur ce qui n'est pas lisible plutôt que d'échouer — et compter ces `NULL` donne `numeric_rate`,
la part des valeurs renseignées qui se laissent lire comme un nombre. Il vaut 1,0 sur une colonne
saine ; s'il tombe à 0,7, un tiers des valeurs a cessé d'être numérique. C'est une **dérive de
format**, détectable pour rien puisqu'il fallait compter de toute façon.

Cette mesure n'était pas au plan. Elle est apparue en traitant une contrainte (« `AVG` échouerait sur
Bronze ») au lieu de la contourner.

## Décision 11 — L'assembleur porte le critère, et le critère ignore les types SQL (2026-08-04)

### Contexte

Les décisions 9a et 10a ont créé une famille de **méthodes de colonne** — une requête chacune, donc
demandées à la demande. Elles ont aussi créé une dette, formulée explicitement à chaque fois :
*« quelles colonnes méritent quelle mesure devient une décision d'appelant »*. `profile_table` (4.1.5)
est ce premier appelant. La dette arrive à échéance.

### Options envisagées

1. **L'appelant liste les colonnes.** `profile_table(dataset, table, batch_id, colonnes_top,
   colonnes_stats)`. Honnête — l'assembleur n'assemble que ce qu'on lui demande — mais il n'est plus
   appelable seul : quelqu'un doit déjà savoir. On repousse le problème d'un cran, et 4.3 devrait
   inventer sa propre règle dans un nœud, sans test dédié.
2. **L'assembleur porte un critère provisoire.** Il est autonome, testable seul, et 4.2 remplacera la
   règle. Au prix d'un critère qu'on sait faux par endroits, dans le code, pendant quelques semaines.

### Décision

Option 2, choisie explicitement par le porteur du projet. La règle vit dans **une seule fonction**,
`_mesure_pour()`, que la caractérisation par rôle de 4.2 remplacera — tout le reste de l'assembleur
est indifférent à la façon dont le choix est fait.

### Le point qui n'était pas dans la question : le critère ne lit aucun nom de type

Le critère « texte + faible cardinalité » présuppose de savoir ce qu'est « du texte ». La voie évidente
— lire `DATA_TYPE` depuis `INFORMATION_SCHEMA` — a été **écartée**, pour deux raisons qui pointent dans
le même sens.

La première est structurelle : `VARCHAR`, `NUMBER`, `TEXT` sont du vocabulaire Snowflake. Un tool qui
les interpréterait ferait entrer un dialecte de base dans une couche qui doit les ignorer (décision 2).
Le SQL est sous la couture ; les *noms de types* doivent l'être aussi.

La seconde est fatale, et c'est elle qui tranche : **en Bronze, tout est VARCHAR par construction**
(phase 2.1). Un critère fondé sur le type déclaré n'y trouverait *aucune* colonne numérique — donc
aucune statistique robuste sur la couche où les anomalies sont précisément injectées. L'étape 4.1.3
aurait été livrée inutilisable là où elle sert le plus.

Le critère ne lit donc que des **faits mesurés**, que n'importe quel backend produit :

| Ce qu'on observe | Ce qu'on en déduit | Mesure |
|---|---|---|
| aucune valeur distincte | colonne vide sur ce lot | aucune |
| `min` **et** `max` se lisent comme des nombres | la colonne porte des quantités | `robust_stats` |
| cardinalité ≤ 50 % des lignes | la colonne se répète, donc elle catégorise | `top_values` |
| le reste | identifiant ou texte libre | aucune |

Les bornes disent la vérité là où le type ment : `min="0.00"`, `max="99.99"` est une colonne de
montants, qu'elle soit déclarée `VARCHAR` ou `NUMBER`.

### Ce que ça coûte, et qu'on assume

- **Un code postal est « lisible comme un nombre ».** Il recevra une médiane, qui ne veut rien dire.
  Le critère confond *écrit comme un nombre* et *est une quantité* — soit exactement la distinction
  identifiant/numérique que le classement par rôle de 4.2 tranchera. Le coût est une requête inutile,
  pas un faux positif : `detect` ne compare pas encore ces médianes.
- **Une colonne de dates peu variée peut recevoir un top-K.** Sans intérêt, sans danger ; 4.2 lui
  donnera le rôle *temporel*.
- **Deux valeurs ne font pas une preuve.** `min` et `max` numériques ne garantissent pas que le reste
  l'est — mais `robust_stats` rend `numeric_rate`, qui mesure exactement à quel point la supposition
  était juste. On suppose à bas prix, on mesure honnêtement.
- **Le seuil penche du côté généreux** (50 %). Rater une colonne catégorielle, c'est rater une
  détection — dont le cas São Paulo. En mesurer une de trop coûte une requête, et `coverage` le dit
  immédiatement.

### Ce qu'il faudra surveiller

**Le coût en allers-retours de métadonnées.** Chaque méthode de colonne résout son propre schéma
(elle doit rester appelable seule, ADR 004). Profiler une table coûte donc une requête
`INFORMATION_SCHEMA` par colonne mesurée, en plus du balayage d'agrégats — sur une seule connexion,
mais pas gratuitement. Sur 17 tables, c'est mesurable.

Le remède est connu et local : mémoriser le schéma sur l'instance de connecteur, dont la durée de vie
est exactement un appel de tool. Il n'est **pas** implémenté — le mesurer sur le vrai Snowflake avant
d'optimiser vaut mieux que de deviner, et 4.5 (branchement Airflow) est le moment où le coût réel
apparaîtra.

**Ce qui a été évité, en revanche** : `profile_table` appelle les **méthodes du connecteur**, jamais
les autres tools. Passer par `top_values.invoke()` aurait rouvert une connexion Snowflake par colonne
— une à deux secondes chacune. Un test l'impose.

## Question ouverte — l'amendement du registre (soulevée le 2026-08-03)

Le registre `datasets/<dataset>.yaml` déclare les tables à surveiller. Il peut donc, lui aussi,
**cesser de décrire la réalité** : une table renommée, supprimée, ou ajoutée sans être déclarée.

Conséquence immédiate, traitée : une cinquième famille de détection — *inventaire* — est ajoutée à
l'étape 4.3. Elle confronte les tables déclarées à celles réellement présentes. C'est la seule famille
qui s'exerce **avant** de profiler, et la seule qui puisse constater qu'il n'y a rien à profiler. Sans
elle, une table disparue ferait lever le connecteur : l'incident le plus grave possible serait masqué
par ce qui ressemblerait à un bug.

Conséquence non tranchée : **quelle issue de `Propose` pour « le registre a vieilli » ?** Ce n'est ni
une donnée fausse (`approved`), ni un contrat périmé (`amend_contract`), ni un cas isolé (`rejected`).

Deux options :

- **élargir `amend_contract`** — c'est la même idée (« ce que j'ai déclaré est faux, pas la donnée »),
  au prix d'une issue qui recouvre deux fichiers différents ;
- **ajouter une 4ᵉ issue** — plus explicite, au prix d'un nœud de plus et d'une décision de plus à
  expliquer à l'humain.

À trancher **avant** d'écrire `detect` (4.3), et à consigner ici.

Note de méthode : cette lacune a été trouvée en expliquant le plan, pas en l'écrivant. C'est un
argument pour continuer à faire relire les phases avant de les commencer.

## Conséquences

### Sur le calendrier

La phase 4 passe de 2 à ~3 semaines : elle gagne le socle interchangeable (connecteurs + registre) et
le cycle Découverte (caractérisation + contrats). Découpage conseillé : **4a** = le socle, testable sur
Olist *et* sur un dataset jouet ; **4b** = la détection et la mémoire.

### Sur ce qui devient démontrable

La preuve la plus forte pour un jury devient possible : **brancher un dataset inconnu en direct**, avec
un nouveau `datasets/*.yaml` et une découverte, sans modifier une ligne de code (phase 9.1).

### Sur ce qui reste spécifique à Olist

Seulement `ground_truth.yaml` — c'est le **benchmark**, pas l'agent. Changer de dataset = écrire un
nouveau registre et refaire le benchmark.

### Sur la documentation

`README.md`, `ROADMAP.md`, `CAHIER_DES_CHARGES.md` (§0bis, 5.2, 5.3, 5.4), `docs/ARCHITECTURE.md`
(invariant P6), `CONTRIBUTING.md` (règle R7) et `docs/DESIGN.md` ont été mis en cohérence en
phase 3.0 — ils décrivaient encore un graphe à 7 nœuds et 2 issues.

Leçon tirée au passage : le schéma du graphe est désormais **généré depuis le code**
(`scripts/export_graph.py`) et non plus dessiné à la main. Un schéma écrit à la main dérive ; c'est
précisément ce qui s'était produit.
