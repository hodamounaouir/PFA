"""Les seuils de **détection** (phase 4.3).

Ce fichier ne contient que des réglages qui disent *à partir de quand l'agent
signale*. Il ne contient — et ne contiendra — aucune règle qui dise *quoi faire*
d'un écart : ça, c'est la décision humaine, et la garder hors du code est tout
l'objet du projet (ADR 008). La distinction est concrète : changer une valeur
ici rend l'agent plus ou moins bavard, jamais plus ou moins autonome.

Pourquoi un fichier séparé plutôt que des constantes dans chaque nœud : au
benchmark (phase 8), tout chiffre produit doit être rattachable au réglage qui
l'a produit. Des seuils dispersés dans cinq familles de détection donneraient
des mesures qu'on ne saurait pas reproduire six mois plus tard.
"""

# Combien de lots précédents servent de référence à la comparaison statistique.
#
# 30 : assez pour qu'une médiane soit stable sur des volumes qui varient déjà
# beaucoup d'un jour à l'autre (chez Olist, de 164 à 303 commandes), assez court
# pour qu'une évolution métier légitime — une croissance, une saisonnalité —
# finisse par entrer dans la référence au lieu d'être signalée indéfiniment.
#
# Ce sont des **lots** et non des jours calendaires : un jour sans livraison ne
# consomme pas de place dans la fenêtre, sinon une interruption du pipeline
# raccourcirait l'historique sans que personne le voie.
FENETRE_HISTORIQUE_LOTS = 30

# En dessous, aucune détection statistique — l'agent le dit au lieu de comparer.
#
# ⚠️ C'est un garde-fou contre le **démarrage à froid**, pas une optimisation.
# Une médiane sur trois jours est un chiffre, pas une référence : elle produirait
# des écarts spectaculaires sur des variations parfaitement normales, et on
# apprendrait en une semaine à ignorer les alertes de l'agent. Mieux vaut se
# taire en le disant que crier sans fondement.
#
# 15 est confortable chez Olist : la fenêtre de référence est propre jusqu'au
# J43 et la première anomalie injectée arrive au J45, donc l'historique est
# largement constitué quand il commence à servir.
HISTORIQUE_MIN_LOTS = 15

# --- Dérive statistique : à partir de quand un écart en est un ---------------

# Le seuil du **score z modifié** (médiane + MAD, pas moyenne + écart-type).
#
# 3,5 est la valeur usuelle d'Iglewicz & Hoaglin. Elle est ici *conservatrice* à
# dessein : mieux vaut manquer une dérive légère — que le contrat ou les tests
# dbt attraperont peut-être — que noyer l'humain sous des écarts qu'il
# apprendra à survoler. Le HITL ne survit pas à un agent bavard.
SEUIL_Z = 3.5

# Le score z modifié vaut `0,6745 × (x − médiane) / MAD`. La constante rend le
# MAD comparable à un écart-type sur une distribution normale — sans elle, le
# seuil de 3,5 ne voudrait pas dire la même chose que dans la littérature.
CONSTANTE_Z = 0.6745

# ⚠️ **Aucun plancher sur le MAD.** Le plan prévoyait d'en poser un pour éviter
# la division par zéro sur un historique parfaitement constant (0 % de nulls
# pendant 43 jours). On ne le fait pas, et c'est une décision :
#
# 1. les métriques n'ont pas la même échelle — `null_rate` vit dans [0, 1],
#    `row_count` dans [0, 10⁶] — donc un plancher absolu serait absurde sur
#    l'une et inopérant sur l'autre, et un plancher relatif vaudrait zéro
#    précisément quand la médiane vaut zéro, c'est-à-dire dans le cas visé ;
# 2. surtout, un MAD nul **n'est pas un problème à corriger, c'est une
#    information** : la métrique n'a jamais bougé. Si elle bouge aujourd'hui,
#    aucun score n'est nécessaire pour le dire. Inventer un MAD reviendrait à
#    fabriquer une variabilité qui n'a pas été observée — ce que la décision 10b
#    interdit déjà à la mesure.
#
# La famille statistique traite donc ce cas à part : historique constant +
# valeur différente = écart, rapporté par son écart brut plutôt que par un z.
