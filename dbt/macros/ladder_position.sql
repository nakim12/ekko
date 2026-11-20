{# Continuous LP scale (PREREGISTRATION.md 4.4): Iron IV 0 LP = 0, +100 per division, +400 per
   tier, so Diamond I 100 LP = 2,800; Master, Grandmaster and Challenger share 2,800 + LP. #}
{% macro ladder_position(tier, division, lp) -%}
case
    when {{ tier }} is null then null
    when {{ tier }} in ('MASTER', 'GRANDMASTER', 'CHALLENGER') then 2800 + {{ lp }}
    else (list_position(['IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND'], {{ tier }}) - 1) * 400
        + (list_position(['IV', 'III', 'II', 'I'], {{ division }}) - 1) * 100
        + {{ lp }}
end
{%- endmacro %}
