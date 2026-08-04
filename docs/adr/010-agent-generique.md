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
