"""Preuve du trou sémantique laissé par la baseline (phase 2.2).

La baseline (dbt tests) attrape les anomalies "faciles" mais NE détecte PAS le
fan-out de casse/accent sur les villes. Le cas est ancré sur geolocation_city
(ground_truth : semantic_sao_paulo) : dans MARTS.fct_geolocation_by_city,
'são paulo', 'sao paulo' et 'sãopaulo' apparaissent comme des villes distinctes.
Aucun test baseline ne couvre ce cas — c'est réservé à l'agent (phase 4, ⭐).

Usage : PYTHONPATH=. uv run python benchmarks/proof_semantic_gap.py
"""
from ingestion.load import connect


def main() -> None:
    conn = connect()
    cur = conn.cursor()

    print("=== Variantes de São Paulo dans le Gold géo (fct_geolocation_by_city) ===")
    cur.execute(
        """
        SELECT geolocation_state, geolocation_city, n_points, n_zip_prefixes
        FROM MARTS.fct_geolocation_by_city
        WHERE geolocation_state = 'SP'
          AND (LOWER(geolocation_city) IN ('são paulo', 'sao paulo', 'sãopaulo')
               OR REPLACE(LOWER(geolocation_city), 'ã', 'a') = 'sao paulo')
        ORDER BY n_points DESC
        """
    )
    rows = cur.fetchall()
    total = 0
    for state, city, n_points, n_zip in rows:
        print(f"  {state}  {city!r:<12} points={n_points:<8} zip_prefixes={n_zip}")
        total += n_points

    print(
        f"\n➡️  {len(rows)} lignes 'ville' distinctes pour UNE SEULE métropole "
        f"({total} points géo éclatés, ~85/15)."
    )
    print("   Aucun test baseline ne le signale : c'est le trou que l'agent comblera (⭐).")
    conn.close()


if __name__ == "__main__":
    main()
