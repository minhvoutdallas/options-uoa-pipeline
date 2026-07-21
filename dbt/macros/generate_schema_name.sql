{#
  Use custom schema names verbatim (staging, marts) instead of dbt's default
  <target_schema>_<custom> prefixing — this is a single-target project, so the
  prefix would just be noise in the warehouse.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
