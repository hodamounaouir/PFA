{#
  Force le nom du schéma tel qu'indiqué par +schema (ex. STAGING, MARTS),
  sans le préfixe <target_schema>_ que dbt ajoute par défaut. On obtient donc
  exactement les schémas Medallion RAW / STAGING / MARTS / OPS.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
