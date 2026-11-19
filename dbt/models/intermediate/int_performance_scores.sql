-- Outcomes z-scored within sampled tier x role x patch (PREREGISTRATION.md 4.2), over outcome-eligible
-- games only: not a remake, not AFK, reached the minute mark, has a lane opponent.
with eligible as (
    select match_id, player_key, sampled_tier, role, patch, gold_diff_14, cs_diff_14, xp_diff_14, deaths_before_14
    from {{ ref('int_player_games') }}
    where not is_remake and not is_afk and has_minute_mark and has_lane_opponent
),

{% set outcomes = ['gold_diff_14', 'cs_diff_14', 'xp_diff_14', 'deaths_before_14'] %}
scored as (
    select
        match_id,
        player_key,
        {% for o in outcomes %}
        ({{ o }} - avg({{ o }}) over g) / nullif(stddev_samp({{ o }}) over g, 0) as {{ o }}_z{{ ',' if not loop.last }}
        {% endfor %}
    from eligible
    window g as (partition by sampled_tier, role, patch)
)

select
    *,
    (gold_diff_14_z + cs_diff_14_z + xp_diff_14_z - deaths_before_14_z) / 4 as perf_index
from scored
