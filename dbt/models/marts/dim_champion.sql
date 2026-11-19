select champion_id as champion_key, any_value(champion_name) as champion_name
from {{ ref('stg_participants') }}
group by champion_id
