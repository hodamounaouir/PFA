# Contrats de données — dataset `olist`

> ⚠️ **Fichier généré — ne pas éditer à la main.**
> `uv run python -m scripts.export_contracts_doc`
> Sources : `contracts/olist/*.yaml` + `datasets/olist.yaml`

## À quoi sert un contrat

Le contrat est le **3ᵉ pilier de détection**, à côté du z-score statistique et des tests dbt. Il dit ce qui *devrait* être vrai d'une table ; `detect` (phase 4.3) confronte chaque lot à ses clauses.

Il est produit par le **cycle Découverte** — qui profile, classe chaque colonne par rôle inféré, propose des clauses **et critique sa propre proposition** — puis validé par un humain. Deux garanties structurelles :

- `charger()` **ne rend jamais un contrat non signé** : tant qu'une fiche est ⏸, aucune de ses clauses ne s'applique ;
- écrire n'écrase jamais une décision humaine : un amendement passe par une version suivante, jamais par une réécriture.

### Les cinq clauses

| Clause | Sens |
|---|---|
| `unique` | la colonne identifie une ligne |
| `not_null` | aucune valeur manquante n'est tolérée |
| `between` | la valeur reste dans les bornes observées sur la référence |
| `accepted_values` | la valeur appartient à une liste close |
| `no_semantic_collisions` | deux écritures d'une même valeur ne coexistent pas (`sao paulo` / `são paulo`) |

### Vue d'ensemble

| Table | Couche | Col. | Lignes de réf. | Clés | Clauses | ⚠️ | Statut |
|---|:-:|--:|--:|:-:|--:|:-:|:-:|
| [`RAW.ORDERS`](#raworders) | bronze | 11 | 9 991 | 2 | 14 | — | ⏸ en attente de signature |
| [`RAW.ORDER_ITEMS`](#raworder_items) | bronze | 10 | 11 378 | — | 17 | 2 | ⏸ en attente de signature |
| [`RAW.ORDER_PAYMENTS`](#raworder_payments) | bronze | 8 | 10 388 | — | 15 | — | ⏸ en attente de signature |
| [`RAW.CUSTOMERS`](#rawcustomers) | bronze | 8 | 9 991 | 1 | 15 | 1 | ⏸ en attente de signature |
| [`RAW.PRODUCTS`](#rawproducts) | bronze | 12 | 32 951 | 1 | 16 | — | ⏸ en attente de signature |
| [`RAW.GEOLOCATION`](#rawgeolocation) | bronze | 8 | 1 000 163 | — | 16 | 1 | ⏸ en attente de signature |
| [`STAGING.STG_ORDERS`](#stagingstg_orders) | silver | 11 | 9 991 | 2 | 12 | — | ⏸ en attente de signature |
| [`STAGING.STG_ORDER_ITEMS`](#stagingstg_order_items) | silver | 10 | 11 378 | 1 | 16 | 2 | ⏸ en attente de signature |
| [`STAGING.STG_ORDER_PAYMENTS`](#stagingstg_order_payments) | silver | 7 | 10 388 | — | 12 | — | ⏸ en attente de signature |
| [`STAGING.STG_CUSTOMERS`](#stagingstg_customers) | silver | 7 | 9 991 | 1 | 12 | 1 | ⏸ en attente de signature |
| [`STAGING.STG_PRODUCTS`](#stagingstg_products) | silver | 11 | 32 951 | 1 | 13 | — | ⏸ en attente de signature |
| [`STAGING.STG_GEOLOCATION`](#stagingstg_geolocation) | silver | 7 | 1 000 163 | — | 13 | 1 | ⏸ en attente de signature |
| [`MARTS.FCT_DAILY_SALES`](#martsfct_daily_sales) | gold | 3 | 43 | — | 5 | — | ⏸ en attente de signature |
| [`MARTS.FCT_AVG_ORDER_VALUE`](#martsfct_avg_order_value) | gold | 3 | 43 | — | 5 | — | ⏸ en attente de signature |
| [`MARTS.FCT_DELIVERY_DELAYS`](#martsfct_delivery_delays) | gold | 4 | 9 720 | 1 | 7 | — | ⏸ en attente de signature |
| [`MARTS.FCT_SALES_BY_CITY_STATE`](#martsfct_sales_by_city_state) | gold | 4 | 1 569 | — | 8 | — | ⏸ en attente de signature |
| [`MARTS.FCT_GEOLOCATION_BY_CITY`](#martsfct_geolocation_by_city) | gold | 4 | 6 326 | — | 8 | — | ⏸ en attente de signature |

**Total** : 17 contrats · 128 colonnes · 8 avertissements.

---

## Fiches par table

### RAW.ORDERS

`RAW.ORDERS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Bronze** — données brutes ingérées telles quelles. Tout y est `VARCHAR` par construction : les bornes `min`/`max` du profil y sont lexicographiques, pas numériques.

Grain : `ORDER_ID`, `CUSTOMER_ID` (plusieurs clés). Composition : 7 temporelles, 2 catégorielles, 2 identifiants.

**2 · Volume de référence**

- **11 colonnes** · **9 991 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `ORDER_ID` — `unique: true` + `not_null: true`
- 🔑 `CUSTOMER_ID` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `_BATCH_ID` | temporelle | `not_null` |
| `_SOURCE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `orders.csv` |
| `_INGESTED_AT` | temporelle | `not_null` |
| `ORDER_ID` | identifiant | 🔑 `unique` · `not_null` |
| `CUSTOMER_ID` | identifiant | 🔑 `unique` · `not_null` |
| `ORDER_STATUS` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `canceled`, `delivered`, `invoiced`, `processing`, `shipped`, `unavailable` |
| `ORDER_PURCHASE_TIMESTAMP` | temporelle | `not_null` |
| `ORDER_APPROVED_AT` | temporelle | — |
| `ORDER_DELIVERED_CARRIER_DATE` | temporelle | — |
| `ORDER_DELIVERED_CUSTOMER_DATE` | temporelle | — |
| `ORDER_ESTIMATED_DELIVERY_DATE` | temporelle | `not_null` |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### RAW.ORDER_ITEMS

`RAW.ORDER_ITEMS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Bronze** — données brutes ingérées telles quelles. Tout y est `VARCHAR` par construction : les bornes `min`/`max` du profil y sont lexicographiques, pas numériques.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 3 catégorielles, 3 numériques, 3 temporelles, 1 texte libre.

**2 · Volume de référence**

- **10 colonnes** · **11 378 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `_BATCH_ID` | temporelle | `not_null` |
| `_SOURCE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `order_items.csv` |
| `_INGESTED_AT` | temporelle | `not_null` |
| `ORDER_ID` | texte libre | `not_null` |
| `ORDER_ITEM_ID` | numérique | `not_null` · `between` [1 … 13] |
| `PRODUCT_ID` | catégorielle | `not_null` · `no_semantic_collisions` |
| `SELLER_ID` | catégorielle | `not_null` · `no_semantic_collisions` |
| `SHIPPING_LIMIT_DATE` | temporelle | `not_null` |
| `PRICE` | numérique | `not_null` · `between` [4.99 … 4099.99] |
| `FREIGHT_VALUE` | numérique | `not_null` · `between` [0.02 … 338.3] |

**5 · Avertissements et limites**

- ⚠️ **`PRODUCT_ID`** — les valeurs relevées ne couvrent que 7% des lignes *(partial_evidence)*
- ⚠️ **`SELLER_ID`** — les valeurs relevées ne couvrent que 24% des lignes *(partial_evidence)*

> Une clause `accepted_values` a été **retirée** sur ces colonnes : les valeurs relevées ne couvrent pas toutes les lignes, donc les valeurs légitimes absentes de la liste deviendraient des violations dès le lendemain. *Un avertissement se survole ; une clause absente ne peut pas être approuvée par distraction.*

---

### RAW.ORDER_PAYMENTS

`RAW.ORDER_PAYMENTS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Bronze** — données brutes ingérées telles quelles. Tout y est `VARCHAR` par construction : les bornes `min`/`max` du profil y sont lexicographiques, pas numériques.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 3 numériques, 2 catégorielles, 2 temporelles, 1 texte libre.

**2 · Volume de référence**

- **8 colonnes** · **10 388 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `_BATCH_ID` | temporelle | `not_null` |
| `_SOURCE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `order_payments.csv` |
| `_INGESTED_AT` | temporelle | `not_null` |
| `ORDER_ID` | texte libre | `not_null` |
| `PAYMENT_SEQUENTIAL` | numérique | `not_null` · `between` [1 … 15] |
| `PAYMENT_TYPE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `boleto`, `credit_card`, `debit_card`, `voucher` |
| `PAYMENT_INSTALLMENTS` | numérique | `not_null` · `between` [1 … 20] |
| `PAYMENT_VALUE` | numérique | `not_null` · `between` [0.14 … 4175.26] |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### RAW.CUSTOMERS

`RAW.CUSTOMERS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Bronze** — données brutes ingérées telles quelles. Tout y est `VARCHAR` par construction : les bornes `min`/`max` du profil y sont lexicographiques, pas numériques.

Grain : une ligne par `CUSTOMER_ID`. Composition : 3 catégorielles, 2 temporelles, 1 texte libre, 1 identifiant, 1 numérique.

**2 · Volume de référence**

- **8 colonnes** · **9 991 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `CUSTOMER_ID` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `_BATCH_ID` | temporelle | `not_null` |
| `_SOURCE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `customers.csv` |
| `_INGESTED_AT` | temporelle | `not_null` |
| `CUSTOMER_ID` | identifiant | 🔑 `unique` · `not_null` |
| `CUSTOMER_UNIQUE_ID` | texte libre | `not_null` |
| `CUSTOMER_ZIP_CODE_PREFIX` | numérique | `not_null` · `between` [1 005 … 99 955] |
| `CUSTOMER_CITY` | catégorielle | `not_null` · `no_semantic_collisions` |
| `CUSTOMER_STATE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : <details><summary>27 valeurs</summary>`AC`, `AL`, `AM`, `AP`, `BA`, `CE`, `DF`, `ES`, `GO`, `MA`, `MG`, `MS`, `MT`, `PA`, `PB`, `PE`, `PI`, `PR`, `RJ`, `RN`, `RO`, `RR`, `RS`, `SC`, `SE`, `SP`, `TO`</details> |

**5 · Avertissements et limites**

- ⚠️ **`CUSTOMER_CITY`** — les valeurs relevées ne couvrent que 43% des lignes *(partial_evidence)*

> Une clause `accepted_values` a été **retirée** sur ces colonnes : les valeurs relevées ne couvrent pas toutes les lignes, donc les valeurs légitimes absentes de la liste deviendraient des violations dès le lendemain. *Un avertissement se survole ; une clause absente ne peut pas être approuvée par distraction.*

---

### RAW.PRODUCTS

`RAW.PRODUCTS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Bronze** — données brutes ingérées telles quelles. Tout y est `VARCHAR` par construction : les bornes `min`/`max` du profil y sont lexicographiques, pas numériques.

Grain : une ligne par `PRODUCT_ID`. Composition : 7 numériques, 2 catégorielles, 2 temporelles, 1 identifiant.

**2 · Volume de référence**

- **12 colonnes** · **32 951 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `PRODUCT_ID` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `_BATCH_ID` | temporelle | `not_null` |
| `_SOURCE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `products.csv` |
| `_INGESTED_AT` | temporelle | `not_null` |
| `PRODUCT_ID` | identifiant | 🔑 `unique` · `not_null` |
| `PRODUCT_CATEGORY_NAME` | catégorielle | `no_semantic_collisions` · `accepted_values` : <details><summary>73 valeurs</summary>`agro_industria_e_comercio`, `alimentos`, `alimentos_bebidas`, `artes`, `artes_e_artesanato`, `artigos_de_festas`, `artigos_de_natal`, `audio`, `automotivo`, `bebes`, `bebidas`, `beleza_saude`, `brinquedos`, `cama_mesa_banho`, `casa_conforto`, `casa_conforto_2`, `casa_construcao`, `cds_dvds_musicais`, `cine_foto`, `climatizacao`, `consoles_games`, `construcao_ferramentas_construcao`, `construcao_ferramentas_ferramentas`, `construcao_ferramentas_iluminacao`, `construcao_ferramentas_jardim`, `construcao_ferramentas_seguranca`, `cool_stuff`, `dvds_blu_ray`, `eletrodomesticos`, `eletrodomesticos_2`, `eletronicos`, `eletroportateis`, `esporte_lazer`, `fashion_bolsas_e_acessorios`, `fashion_calcados`, `fashion_esporte`, `fashion_roupa_feminina`, `fashion_roupa_infanto_juvenil`, `fashion_roupa_masculina`, `fashion_underwear_e_moda_praia`, `ferramentas_jardim`, `flores`, `fraldas_higiene`, `industria_comercio_e_negocios`, `informatica_acessorios`, `instrumentos_musicais`, `la_cuisine`, `livros_importados`, `livros_interesse_geral`, `livros_tecnicos`, `malas_acessorios`, `market_place`, `moveis_colchao_e_estofado`, `moveis_cozinha_area_de_servico_jantar_e_jardim`, `moveis_decoracao`, `moveis_escritorio`, `moveis_quarto`, `moveis_sala`, `musica`, `papelaria`, `pc_gamer`, `pcs`, `perfumaria`, `pet_shop`, `portateis_casa_forno_e_cafe`, `portateis_cozinha_e_preparadores_de_alimentos`, `relogios_presentes`, `seguros_e_servicos`, `sinalizacao_e_seguranca`, `tablets_impressao_imagem`, `telefonia`, `telefonia_fixa`, `utilidades_domesticas`</details> |
| `PRODUCT_NAME_LENGHT` | numérique | `between` [5 … 76] |
| `PRODUCT_DESCRIPTION_LENGHT` | numérique | `between` [4 … 3 992] |
| `PRODUCT_PHOTOS_QTY` | numérique | `between` [1 … 20] |
| `PRODUCT_WEIGHT_G` | numérique | `between` [0 … 40 425] |
| `PRODUCT_LENGTH_CM` | numérique | `between` [7 … 105] |
| `PRODUCT_HEIGHT_CM` | numérique | `between` [2 … 105] |
| `PRODUCT_WIDTH_CM` | numérique | `between` [6 … 118] |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### RAW.GEOLOCATION

`RAW.GEOLOCATION.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Bronze** — données brutes ingérées telles quelles. Tout y est `VARCHAR` par construction : les bornes `min`/`max` du profil y sont lexicographiques, pas numériques.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 3 catégorielles, 3 numériques, 2 temporelles.

**2 · Volume de référence**

- **8 colonnes** · **1 000 163 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `_BATCH_ID` | temporelle | `not_null` |
| `_SOURCE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `geolocation.csv` |
| `_INGESTED_AT` | temporelle | `not_null` |
| `GEOLOCATION_ZIP_CODE_PREFIX` | numérique | `not_null` · `between` [1 001 … 99 990] |
| `GEOLOCATION_LAT` | numérique | `not_null` · `between` [-36.6053744107061 … 45.06593318269697] |
| `GEOLOCATION_LNG` | numérique | `not_null` · `between` [-101.46676644931476 … 121.10539381057764] |
| `GEOLOCATION_CITY` | catégorielle | `not_null` · `no_semantic_collisions` |
| `GEOLOCATION_STATE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : <details><summary>27 valeurs</summary>`AC`, `AL`, `AM`, `AP`, `BA`, `CE`, `DF`, `ES`, `GO`, `MA`, `MG`, `MS`, `MT`, `PA`, `PB`, `PE`, `PI`, `PR`, `RJ`, `RN`, `RO`, `RR`, `RS`, `SC`, `SE`, `SP`, `TO`</details> |

**5 · Avertissements et limites**

- ⚠️ **`GEOLOCATION_CITY`** — les valeurs relevées ne couvrent que 39% des lignes *(partial_evidence)*

> Une clause `accepted_values` a été **retirée** sur ces colonnes : les valeurs relevées ne couvrent pas toutes les lignes, donc les valeurs légitimes absentes de la liste deviendraient des violations dès le lendemain. *Un avertissement se survole ; une clause absente ne peut pas être approuvée par distraction.*

---

### STAGING.STG_ORDERS

`STAGING.STG_ORDERS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Silver** — typé et nettoyé par dbt. Les doublons y survivent volontairement, pour que les tests baseline puissent les constater.

Grain : `ORDER_ID`, `CUSTOMER_ID` (plusieurs clés). Composition : 8 temporelles, 2 identifiants, 1 catégorielle.

**2 · Volume de référence**

- **11 colonnes** · **9 991 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `ORDER_ID` — `unique: true` + `not_null: true`
- 🔑 `CUSTOMER_ID` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `ORDER_ID` | identifiant | 🔑 `unique` · `not_null` |
| `CUSTOMER_ID` | identifiant | 🔑 `unique` · `not_null` |
| `ORDER_STATUS` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `canceled`, `delivered`, `invoiced`, `processing`, `shipped`, `unavailable` |
| `ORDER_PURCHASE_TS` | temporelle | `not_null` |
| `ORDER_PURCHASE_DATE` | temporelle | `not_null` |
| `ORDER_APPROVED_TS` | temporelle | — |
| `ORDER_DELIVERED_CARRIER_TS` | temporelle | — |
| `ORDER_DELIVERED_CUSTOMER_TS` | temporelle | — |
| `ORDER_ESTIMATED_DELIVERY_TS` | temporelle | `not_null` |
| `_BATCH_ID` | temporelle | `not_null` |
| `_INGESTED_AT` | temporelle | `not_null` |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### STAGING.STG_ORDER_ITEMS

`STAGING.STG_ORDER_ITEMS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Silver** — typé et nettoyé par dbt. Les doublons y survivent volontairement, pour que les tests baseline puissent les constater.

Grain : une ligne par `ORDER_ITEM_SK`. Composition : 3 numériques, 3 temporelles, 2 catégorielles, 1 texte libre, 1 identifiant.

**2 · Volume de référence**

- **10 colonnes** · **11 378 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `ORDER_ITEM_SK` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `ORDER_ITEM_SK` | identifiant | 🔑 `unique` · `not_null` |
| `ORDER_ID` | texte libre | `not_null` |
| `ORDER_ITEM_ID` | numérique | `not_null` · `between` [1 … 13] |
| `PRODUCT_ID` | catégorielle | `not_null` · `no_semantic_collisions` |
| `SELLER_ID` | catégorielle | `not_null` · `no_semantic_collisions` |
| `SHIPPING_LIMIT_TS` | temporelle | `not_null` |
| `PRICE` | numérique | `not_null` · `between` [4.99 … 4099.99] |
| `FREIGHT_VALUE` | numérique | `not_null` · `between` [0.02 … 338.3] |
| `_BATCH_ID` | temporelle | `not_null` |
| `_INGESTED_AT` | temporelle | `not_null` |

**5 · Avertissements et limites**

- ⚠️ **`PRODUCT_ID`** — les valeurs relevées ne couvrent que 7% des lignes *(partial_evidence)*
- ⚠️ **`SELLER_ID`** — les valeurs relevées ne couvrent que 24% des lignes *(partial_evidence)*

> Une clause `accepted_values` a été **retirée** sur ces colonnes : les valeurs relevées ne couvrent pas toutes les lignes, donc les valeurs légitimes absentes de la liste deviendraient des violations dès le lendemain. *Un avertissement se survole ; une clause absente ne peut pas être approuvée par distraction.*

---

### STAGING.STG_ORDER_PAYMENTS

`STAGING.STG_ORDER_PAYMENTS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Silver** — typé et nettoyé par dbt. Les doublons y survivent volontairement, pour que les tests baseline puissent les constater.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 3 numériques, 2 temporelles, 1 catégorielle, 1 texte libre.

**2 · Volume de référence**

- **7 colonnes** · **10 388 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `ORDER_ID` | texte libre | `not_null` |
| `PAYMENT_SEQUENTIAL` | numérique | `not_null` · `between` [1 … 15] |
| `PAYMENT_TYPE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : `boleto`, `credit_card`, `debit_card`, `voucher` |
| `PAYMENT_INSTALLMENTS` | numérique | `not_null` · `between` [1 … 20] |
| `PAYMENT_AMOUNT` | numérique | `not_null` · `between` [0.14 … 4175.26] |
| `_BATCH_ID` | temporelle | `not_null` |
| `_INGESTED_AT` | temporelle | `not_null` |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### STAGING.STG_CUSTOMERS

`STAGING.STG_CUSTOMERS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Silver** — typé et nettoyé par dbt. Les doublons y survivent volontairement, pour que les tests baseline puissent les constater.

Grain : une ligne par `CUSTOMER_ID`. Composition : 2 catégorielles, 2 temporelles, 1 texte libre, 1 identifiant, 1 numérique.

**2 · Volume de référence**

- **7 colonnes** · **9 991 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `CUSTOMER_ID` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `CUSTOMER_ID` | identifiant | 🔑 `unique` · `not_null` |
| `CUSTOMER_UNIQUE_ID` | texte libre | `not_null` |
| `CUSTOMER_ZIP_CODE_PREFIX` | numérique | `not_null` · `between` [1 005 … 99 955] |
| `CUSTOMER_CITY` | catégorielle | `not_null` · `no_semantic_collisions` |
| `CUSTOMER_STATE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : <details><summary>27 valeurs</summary>`AC`, `AL`, `AM`, `AP`, `BA`, `CE`, `DF`, `ES`, `GO`, `MA`, `MG`, `MS`, `MT`, `PA`, `PB`, `PE`, `PI`, `PR`, `RJ`, `RN`, `RO`, `RR`, `RS`, `SC`, `SE`, `SP`, `TO`</details> |
| `_BATCH_ID` | temporelle | `not_null` |
| `_INGESTED_AT` | temporelle | `not_null` |

**5 · Avertissements et limites**

- ⚠️ **`CUSTOMER_CITY`** — les valeurs relevées ne couvrent que 43% des lignes *(partial_evidence)*

> Une clause `accepted_values` a été **retirée** sur ces colonnes : les valeurs relevées ne couvrent pas toutes les lignes, donc les valeurs légitimes absentes de la liste deviendraient des violations dès le lendemain. *Un avertissement se survole ; une clause absente ne peut pas être approuvée par distraction.*

---

### STAGING.STG_PRODUCTS

`STAGING.STG_PRODUCTS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Silver** — typé et nettoyé par dbt. Les doublons y survivent volontairement, pour que les tests baseline puissent les constater.

Grain : une ligne par `PRODUCT_ID`. Composition : 7 numériques, 2 temporelles, 1 catégorielle, 1 identifiant.

**2 · Volume de référence**

- **11 colonnes** · **32 951 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `PRODUCT_ID` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `PRODUCT_ID` | identifiant | 🔑 `unique` · `not_null` |
| `PRODUCT_CATEGORY_NAME` | catégorielle | `no_semantic_collisions` · `accepted_values` : <details><summary>73 valeurs</summary>`agro_industria_e_comercio`, `alimentos`, `alimentos_bebidas`, `artes`, `artes_e_artesanato`, `artigos_de_festas`, `artigos_de_natal`, `audio`, `automotivo`, `bebes`, `bebidas`, `beleza_saude`, `brinquedos`, `cama_mesa_banho`, `casa_conforto`, `casa_conforto_2`, `casa_construcao`, `cds_dvds_musicais`, `cine_foto`, `climatizacao`, `consoles_games`, `construcao_ferramentas_construcao`, `construcao_ferramentas_ferramentas`, `construcao_ferramentas_iluminacao`, `construcao_ferramentas_jardim`, `construcao_ferramentas_seguranca`, `cool_stuff`, `dvds_blu_ray`, `eletrodomesticos`, `eletrodomesticos_2`, `eletronicos`, `eletroportateis`, `esporte_lazer`, `fashion_bolsas_e_acessorios`, `fashion_calcados`, `fashion_esporte`, `fashion_roupa_feminina`, `fashion_roupa_infanto_juvenil`, `fashion_roupa_masculina`, `fashion_underwear_e_moda_praia`, `ferramentas_jardim`, `flores`, `fraldas_higiene`, `industria_comercio_e_negocios`, `informatica_acessorios`, `instrumentos_musicais`, `la_cuisine`, `livros_importados`, `livros_interesse_geral`, `livros_tecnicos`, `malas_acessorios`, `market_place`, `moveis_colchao_e_estofado`, `moveis_cozinha_area_de_servico_jantar_e_jardim`, `moveis_decoracao`, `moveis_escritorio`, `moveis_quarto`, `moveis_sala`, `musica`, `papelaria`, `pc_gamer`, `pcs`, `perfumaria`, `pet_shop`, `portateis_casa_forno_e_cafe`, `portateis_cozinha_e_preparadores_de_alimentos`, `relogios_presentes`, `seguros_e_servicos`, `sinalizacao_e_seguranca`, `tablets_impressao_imagem`, `telefonia`, `telefonia_fixa`, `utilidades_domesticas`</details> |
| `PRODUCT_NAME_LENGTH` | numérique | `between` [5 … 76] |
| `PRODUCT_DESCRIPTION_LENGTH` | numérique | `between` [4 … 3 992] |
| `PRODUCT_PHOTOS_QTY` | numérique | `between` [1 … 20] |
| `PRODUCT_WEIGHT_G` | numérique | `between` [0 … 40 425] |
| `PRODUCT_LENGTH_CM` | numérique | `between` [7 … 105] |
| `PRODUCT_HEIGHT_CM` | numérique | `between` [2 … 105] |
| `PRODUCT_WIDTH_CM` | numérique | `between` [6 … 118] |
| `_BATCH_ID` | temporelle | `not_null` |
| `_INGESTED_AT` | temporelle | `not_null` |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### STAGING.STG_GEOLOCATION

`STAGING.STG_GEOLOCATION.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Silver** — typé et nettoyé par dbt. Les doublons y survivent volontairement, pour que les tests baseline puissent les constater.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 3 numériques, 2 catégorielles, 2 temporelles.

**2 · Volume de référence**

- **7 colonnes** · **1 000 163 lignes** observées
- Colonne de lot : `_batch_id`
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `GEOLOCATION_ZIP_CODE_PREFIX` | numérique | `not_null` · `between` [1 001 … 99 990] |
| `GEOLOCATION_LAT` | numérique | `not_null` · `between` [-36.6053744107061 … 45.06593318269697] |
| `GEOLOCATION_LNG` | numérique | `not_null` · `between` [-101.46676644931476 … 121.10539381057764] |
| `GEOLOCATION_CITY` | catégorielle | `not_null` · `no_semantic_collisions` |
| `GEOLOCATION_STATE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : <details><summary>27 valeurs</summary>`AC`, `AL`, `AM`, `AP`, `BA`, `CE`, `DF`, `ES`, `GO`, `MA`, `MG`, `MS`, `MT`, `PA`, `PB`, `PE`, `PI`, `PR`, `RJ`, `RN`, `RO`, `RR`, `RS`, `SC`, `SE`, `SP`, `TO`</details> |
| `_BATCH_ID` | temporelle | `not_null` |
| `_INGESTED_AT` | temporelle | `not_null` |

**5 · Avertissements et limites**

- ⚠️ **`GEOLOCATION_CITY`** — les valeurs relevées ne couvrent que 39% des lignes *(partial_evidence)*

> Une clause `accepted_values` a été **retirée** sur ces colonnes : les valeurs relevées ne couvrent pas toutes les lignes, donc les valeurs légitimes absentes de la liste deviendraient des violations dès le lendemain. *Un avertissement se survole ; une clause absente ne peut pas être approuvée par distraction.*

---

### MARTS.FCT_DAILY_SALES

`MARTS.FCT_DAILY_SALES.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Gold** — agrégat métier, reconstruit en entier à chaque run. Pas de notion de lot : le profilage porte sur toute la table.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 2 numériques, 1 temporelle.

**2 · Volume de référence**

- **3 colonnes** · **43 lignes** observées
- Colonne de lot : *aucune* (agrégat)
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `SALES_DATE` | temporelle | `not_null` |
| `N_ORDERS` | numérique | `not_null` · `between` [164 … 303] |
| `REVENUE` | numérique | `not_null` · `between` [24000.21 … 55782.82] |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### MARTS.FCT_AVG_ORDER_VALUE

`MARTS.FCT_AVG_ORDER_VALUE.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Gold** — agrégat métier, reconstruit en entier à chaque run. Pas de notion de lot : le profilage porte sur toute la table.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 2 numériques, 1 temporelle.

**2 · Volume de référence**

- **3 colonnes** · **43 lignes** observées
- Colonne de lot : *aucune* (agrégat)
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `SALES_DATE` | temporelle | `not_null` |
| `N_ORDERS` | numérique | `not_null` · `between` [164 … 303] |
| `AVG_ORDER_VALUE` | numérique | `not_null` · `between` [133.3345 … 220.48545455] |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### MARTS.FCT_DELIVERY_DELAYS

`MARTS.FCT_DELIVERY_DELAYS.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Gold** — agrégat métier, reconstruit en entier à chaque run. Pas de notion de lot : le profilage porte sur toute la table.

Grain : une ligne par `ORDER_ID`. Composition : 2 numériques, 1 identifiant, 1 temporelle.

**2 · Volume de référence**

- **4 colonnes** · **9 720 lignes** observées
- Colonne de lot : *aucune* (agrégat)
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

- 🔑 `ORDER_ID` — `unique: true` + `not_null: true`

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `ORDER_ID` | identifiant | 🔑 `unique` · `not_null` |
| `ORDER_PURCHASE_DATE` | temporelle | `not_null` |
| `DELIVERY_DAYS` | numérique | `not_null` · `between` [1 … 108] |
| `DELAY_VS_ESTIMATE` | numérique | `not_null` · `between` [-147 … 81] |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### MARTS.FCT_SALES_BY_CITY_STATE

`MARTS.FCT_SALES_BY_CITY_STATE.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Gold** — agrégat métier, reconstruit en entier à chaque run. Pas de notion de lot : le profilage porte sur toute la table.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 2 numériques, 1 catégorielle, 1 texte libre.

**2 · Volume de référence**

- **4 colonnes** · **1 569 lignes** observées
- Colonne de lot : *aucune* (agrégat)
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `CUSTOMER_STATE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : <details><summary>27 valeurs</summary>`AC`, `AL`, `AM`, `AP`, `BA`, `CE`, `DF`, `ES`, `GO`, `MA`, `MG`, `MS`, `MT`, `PA`, `PB`, `PE`, `PI`, `PR`, `RJ`, `RN`, `RO`, `RR`, `RS`, `SC`, `SE`, `SP`, `TO`</details> |
| `CUSTOMER_CITY` | texte libre | `not_null` |
| `N_ORDERS` | numérique | `not_null` · `between` [1 … 1 661] |
| `REVENUE` | numérique | `not_null` · `between` [17.61 … 251977.85] |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---

### MARTS.FCT_GEOLOCATION_BY_CITY

`MARTS.FCT_GEOLOCATION_BY_CITY.v1.yaml` · version 1 · ⏸ en attente de signature

**1 · Rôle principal**

**Gold** — agrégat métier, reconstruit en entier à chaque run. Pas de notion de lot : le profilage porte sur toute la table.

Grain : aucune colonne ne s'est révélée unique sur la référence. Composition : 2 numériques, 1 catégorielle, 1 texte libre.

**2 · Volume de référence**

- **4 colonnes** · **6 326 lignes** observées
- Colonne de lot : *aucune* (agrégat)
- Périmètre du profil : table entière (le cycle Découverte cherche ce qui est *normal* : un contrat bâti sur une seule journée serait absurdement étroit)

**3 · Clés primaires identifiées**

*Aucune.* Une clause d'unicité n'est proposée que si la colonne s'est révélée quasi unique **et** sans nul sur la fenêtre de référence.

**4 · Règles appliquées**

| Colonne | Rôle | Clauses |
|---|---|---|
| `GEOLOCATION_STATE` | catégorielle | `not_null` · `no_semantic_collisions` · `accepted_values` : <details><summary>27 valeurs</summary>`AC`, `AL`, `AM`, `AP`, `BA`, `CE`, `DF`, `ES`, `GO`, `MA`, `MG`, `MS`, `MT`, `PA`, `PB`, `PE`, `PI`, `PR`, `RJ`, `RN`, `RO`, `RR`, `RS`, `SC`, `SE`, `SP`, `TO`</details> |
| `GEOLOCATION_CITY` | texte libre | `not_null` |
| `N_POINTS` | numérique | `not_null` · `between` [1 … 160 719] |
| `N_ZIP_PREFIXES` | numérique | `not_null` · `between` [1 … 3 185] |

**5 · Avertissements et limites**

*Aucun.* Toutes les clauses proposées reposent sur une preuve complète.

---
