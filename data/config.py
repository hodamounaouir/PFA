"""Configuration figée du rejeu Olist (phase 1, ADR 009).

Ne pas modifier après le lancement de l'agent : la fenêtre et le seed font
partie du contrat de vérité (ground_truth.yaml s'y réfère).
"""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
OLIST_DIR = DATA_DIR / "olist"
INCOMING_DIR = DATA_DIR / "incoming"

# Fenêtre de rejeu : plateau stable du dataset (~230 commandes/jour),
# choisie en phase 1.1 (docs/dataset.md).
WINDOW_START = "2018-03-01"
WINDOW_END = "2018-05-31"  # inclus → 92 jours, J1 = 2018-03-01

# Fin de la fenêtre de RÉFÉRENCE (décision du 2026-08-04) : J1→J43 doit rester
# entièrement propre — aucune anomalie injectée, aucune collision naturelle
# (cf. section `preparation` de ground_truth.yaml). C'est sur cette fenêtre que
# l'agent construira son contrat en phase 4.2 ; s'il apprend sur des données
# sales, il grave le désordre comme la norme. Un test l'asserte.
REFERENCE_END_DAY = 43

# Déterminisme des choix aléatoires (injection d'anomalies).
SEED = 42

# Tables transactionnelles : rejouées chaque jour.
DAILY_TABLES = ("orders", "order_items", "order_payments", "customers")

# Référentiels : livrés en entier au jour 1 uniquement.
REFERENCE_TABLES = ("products", "geolocation")

CSV_BY_TABLE = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
}
